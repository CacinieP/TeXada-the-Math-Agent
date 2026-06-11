"""FastAPI backend — HTTP API for the shell UI."""
from __future__ import annotations

from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from texada.config import TeXadaConfig, load_config
from texada.core.router import InputRouter
from texada.core.llama_manager import LlamaCppManager
from texada.render.engine import RenderEngine
from texada.store.shorthand import ShorthandStore
from texada.store.history import HistoryStore
from texada.types import ConvertResult, HistoryEntry, RenderMode, Route


# ── Request / Response models ──

class ConvertRequest(BaseModel):
    text: str
    context: str = ""
    intent_override: str | None = None
    render_mode: str = "katex"

class LaTeXResponse(BaseModel):
    latex: str
    katex_html: str | None = None
    latex_highlighted: str | None = None
    copy_text: str
    valid: bool
    source: str
    intent: str
    confidence: float
    latency_ms: float
    tokens_used: int = 0

class ValidateRequest(BaseModel):
    latex: str

class ValidateResponse(BaseModel):
    valid: bool
    errors: list[dict] = []

class ShorthandAddRequest(BaseModel):
    key: str
    value: str

class ShorthandResponse(BaseModel):
    key: str
    value: str

class StatusResponse(BaseModel):
    status: str
    model: str | None = None
    message: str | None = None
    render_mode: str
    delimiter: str


# ── App factory ──

def create_app(config: TeXadaConfig | None = None) -> FastAPI:
    config = config or load_config()
    config.ensure_dirs()

    router = InputRouter(config)
    shorthand = ShorthandStore(config)
    history = HistoryStore(config)
    render_engine = RenderEngine(config)
    llama_mgr = LlamaCppManager(config)

    app = FastAPI(title="TeXada", version="0.2.0")

    # CORS — allow the shell UI (likely on a different port) to call the API
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/status", response_model=StatusResponse)
    async def get_status():
        info = llama_mgr.get_status()
        return StatusResponse(
            status=info["status"],
            model=info.get("model"),
            message=info.get("message"),
            render_mode=render_engine.mode.value,
            delimiter=render_engine.delimiter,
        )

    @app.post("/api/convert", response_model=LaTeXResponse)
    async def convert_text(req: ConvertRequest):
        req_mode = RenderMode(req.render_mode)
        try:
            result: ConvertResult = await router.process_text(
                req.text,
                intent_override=req.intent_override,
                context=req.context,
                render_mode=req_mode,
            )
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))
        return LaTeXResponse(
            latex=result.latex,
            katex_html=result.render.katex_html,
            latex_highlighted=result.render.latex_highlighted,
            copy_text=result.render.copy_text,
            valid=result.valid,
            source=result.source.value,
            intent=result.intent,
            confidence=result.confidence,
            latency_ms=result.latency_ms,
            tokens_used=result.tokens_used,
        )

    @app.post("/api/ocr", response_model=LaTeXResponse)
    async def convert_image(image: UploadFile, render_mode: str = "katex"):
        ocr_mode = RenderMode(render_mode)
        data = await image.read()
        try:
            result: ConvertResult = await router.process_image(data, render_mode=ocr_mode)
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))
        return LaTeXResponse(
            latex=result.latex,
            katex_html=result.render.katex_html,
            latex_highlighted=result.render.latex_highlighted,
            copy_text=result.render.copy_text,
            valid=result.valid,
            source=result.source.value,
            intent=result.intent,
            confidence=result.confidence,
            latency_ms=result.latency_ms,
            tokens_used=result.tokens_used,
        )

    @app.post("/api/complete", response_model=LaTeXResponse)
    async def complete_latex(req: ConvertRequest):
        comp_mode = RenderMode(req.render_mode)
        try:
            result: ConvertResult = await router.process_text(
                req.text, route_override=Route.COMPLETION,
                render_mode=comp_mode,
            )
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))
        return LaTeXResponse(
            latex=result.latex,
            katex_html=result.render.katex_html,
            latex_highlighted=result.render.latex_highlighted,
            copy_text=result.render.copy_text,
            valid=result.valid,
            source=result.source.value,
            intent=result.intent,
            confidence=result.confidence,
            latency_ms=result.latency_ms,
            tokens_used=result.tokens_used,
        )

    @app.post("/api/validate", response_model=ValidateResponse)
    async def validate_latex(req: ValidateRequest):
        from texada.core.validator import LaTeXValidator
        validator = LaTeXValidator()
        result = validator.validate(req.latex)
        return ValidateResponse(
            valid=result.valid,
            errors=[{"type": e.type, "detail": e.detail, "error": e.error} for e in result.errors],
        )

    @app.post("/api/render-mode")
    async def set_render_mode(mode: str):
        try:
            render_engine.switch_mode(mode)
        except ValueError:
            raise HTTPException(400, f"Invalid render mode: {mode}. Use 'katex' or 'latex'.")
        return {"mode": render_engine.mode.value}

    @app.get("/api/shorthands")
    async def list_shorthands(q: str = ""):
        items = shorthand.list_all(q)
        return [{"key": k, "value": v} for k, v in items]

    @app.post("/api/shorthands", response_model=ShorthandResponse)
    async def add_shorthand(req: ShorthandAddRequest):
        shorthand.add(req.key, req.value)
        return ShorthandResponse(key=req.key, value=req.value)

    @app.delete("/api/shorthands/{key}")
    async def delete_shorthand(key: str):
        if shorthand.delete(key):
            return {"deleted": key}
        raise HTTPException(404, f"Shorthand '{key}' not found or is built-in")

    @app.get("/api/history")
    async def list_history(q: str = "", limit: int = 50):
        entries = await history.list_recent(q, limit)
        return [e.__dict__ for e in entries]

    return app