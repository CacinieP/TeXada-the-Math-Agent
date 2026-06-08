"""FastAPI backend — HTTP API for the shell UI."""
from __future__ import annotations

from fastapi import FastAPI, UploadFile, HTTPException
from pydantic import BaseModel

from texada.config import TeXadaConfig, load_config
from texada.core.router import InputRouter
from texada.core.ollama_manager import OllamaManager
from texada.render.engine import RenderEngine
from texada.store.shorthand import ShorthandStore
from texada.store.history import HistoryStore
from texada.types import ConvertResult, HistoryEntry, RenderMode


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
    ollama_mgr = OllamaManager(config)

    app = FastAPI(title="TeXada", version="0.2.0")

    @app.get("/api/status", response_model=StatusResponse)
    async def get_status():
        info = ollama_mgr.get_status()
        return StatusResponse(
            status=info["status"],
            model=info.get("model"),
            message=info.get("message"),
            render_mode=render_engine.mode.value,
            delimiter=render_engine.delimiter,
        )

    @app.post("/api/convert", response_model=LaTeXResponse)
    async def convert_text(req: ConvertRequest):
        render_engine.mode = RenderMode(req.render_mode)
        result: ConvertResult = await router.process_text(req.text)
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
        render_engine.mode = RenderMode(render_mode)
        data = await image.read()
        result: ConvertResult = await router.process_image(data)
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
        render_engine.mode = RenderMode(req.render_mode)
        result: ConvertResult = await router.process_text(req.text)
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
        render_engine.switch_mode(mode)
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