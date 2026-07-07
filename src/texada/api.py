"""FastAPI backend — HTTP API for the shell UI."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from importlib.metadata import PackageNotFoundError, version

from fastapi import FastAPI, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from texada.config import TeXadaConfig, load_config, save_config_updates
from texada.core.backend import BackendManager
from texada.core.router import InputRouter
from texada.render.engine import RenderEngine
from texada.store.history import HistoryStore
from texada.types import ConvertResult, HistoryEntry, RenderMode, Route

# ── Request / Response models ──

class ConvertRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    context: str = Field(default="", max_length=8000)
    intent_override: str | None = Field(default=None, max_length=80)
    render_mode: str = Field(default="katex", pattern="^(katex|latex)$")

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
    latex: str = Field(min_length=1, max_length=4000)

class ValidateResponse(BaseModel):
    valid: bool
    errors: list[dict] = []

class ShorthandAddRequest(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=4000)

class ShorthandResponse(BaseModel):
    key: str
    value: str

class StatusResponse(BaseModel):
    status: str
    backend: str
    model: str | None = None
    message: str | None = None
    render_mode: str
    delimiter: str

class BackendSettingsResponse(BaseModel):
    backend: str
    ollama_host: str
    model_name: str
    vision_model_name: str
    openai_base_url: str
    openai_model_name: str
    openai_vision_model_name: str
    openai_api_key_set: bool

class BackendSettingsUpdate(BaseModel):
    backend: str | None = Field(default=None, pattern="^(ollama|openai_compatible)$")
    ollama_host: str | None = Field(default=None, max_length=500)
    model_name: str | None = Field(default=None, max_length=300)
    vision_model_name: str | None = Field(default=None, max_length=300)
    openai_base_url: str | None = Field(default=None, max_length=500)
    openai_model_name: str | None = Field(default=None, max_length=300)
    openai_vision_model_name: str | None = Field(default=None, max_length=300)
    openai_api_key: str | None = Field(default=None, max_length=4000)


class RuntimeConfigResponse(BaseModel):
    version: str
    api_base_url: str
    api_host: str
    api_port: int
    max_ocr_bytes: int
    allowed_image_mime_types: list[str]


# ── App factory ──

def _app_version() -> str:
    try:
        return version("texada")
    except PackageNotFoundError:
        return "0.3.0"


def _settings_response(config: TeXadaConfig) -> BackendSettingsResponse:
    return BackendSettingsResponse(
        backend=config.backend,
        ollama_host=config.ollama_host,
        model_name=config.model_name,
        vision_model_name=config.vision_model_name,
        openai_base_url=config.openai_base_url,
        openai_model_name=config.openai_model_name,
        openai_vision_model_name=config.openai_vision_model_name,
        openai_api_key_set=bool(config.openai_api_key),
    )

def _parse_render_mode(mode: str) -> RenderMode:
    try:
        return RenderMode(mode)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid render mode: {mode}. Use 'katex' or 'latex'.",
        ) from None


def _assert_image_upload(config: TeXadaConfig, image: UploadFile, data: bytes) -> None:
    if len(data) > config.max_ocr_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Image too large. Max upload size is {config.max_ocr_bytes} bytes.",
        )

    if image.content_type not in config.allowed_image_mime_types:
        allowed = ", ".join(config.allowed_image_mime_types)
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported image type: {image.content_type}. Allowed: {allowed}.",
        )


def create_app(config: TeXadaConfig | None = None) -> FastAPI:
    config = config or load_config()
    config.ensure_dirs()
    app_version = _app_version()

    router = InputRouter(config)
    shorthand = router.shorthand_store  # share router's store so /convert sees /api/shorthands adds
    history = HistoryStore(config)
    render_engine = RenderEngine(config)
    backend_mgr = BackendManager(config)

    app = FastAPI(title="TeXada", version=app_version)
    allowed_origins = set(config.api_allowed_origins)

    # CORS — only the local shell UI and Tauri app should call the API from a browser.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["content-type"],
    )

    @app.middleware("http")
    async def enforce_browser_origin(
        request: Request,
        call_next: Callable[[Request], Awaitable],
    ):
        origin = request.headers.get("origin")
        if origin and origin not in allowed_origins:
            return JSONResponse(status_code=403, content={"detail": "Forbidden origin"})
        return await call_next(request)

    @app.get("/api/status", response_model=StatusResponse)
    async def get_status():
        info = await backend_mgr.aget_status()
        return StatusResponse(
            status=info["status"],
            backend=info.get("backend", config.backend),
            model=info.get("model"),
            message=info.get("message"),
            render_mode=render_engine.mode.value,
            delimiter=render_engine.delimiter,
        )

    @app.get("/api/settings/backend", response_model=BackendSettingsResponse)
    async def get_backend_settings():
        return _settings_response(config)

    @app.get("/api/runtime", response_model=RuntimeConfigResponse)
    async def get_runtime_config():
        return RuntimeConfigResponse(
            version=app_version,
            api_base_url=config.api_base_url,
            api_host=config.api_host,
            api_port=config.api_port,
            max_ocr_bytes=config.max_ocr_bytes,
            allowed_image_mime_types=config.allowed_image_mime_types,
        )

    @app.post("/api/settings/backend", response_model=BackendSettingsResponse)
    async def update_backend_settings(req: BackendSettingsUpdate):
        nonlocal config, router, shorthand, history, render_engine, backend_mgr
        updates = req.model_dump(exclude_none=True)
        if updates.get("openai_api_key") == "":
            updates.pop("openai_api_key")
        config = save_config_updates(updates, data_dir=config.data_dir)
        router = InputRouter(config)
        shorthand = router.shorthand_store
        history = HistoryStore(config)
        render_engine = RenderEngine(config)
        backend_mgr = BackendManager(config)
        return _settings_response(config)

    @app.post("/api/convert", response_model=LaTeXResponse)
    async def convert_text(req: ConvertRequest):
        req_mode = _parse_render_mode(req.render_mode)
        try:
            result: ConvertResult = await router.process_text(
                req.text,
                intent_override=req.intent_override,
                context=req.context,
                render_mode=req_mode,
            )
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
        try:
            await history.add(HistoryEntry(
                input_text=req.text, input_type="nl", latex=result.latex,
                intent=result.intent, source=result.source.value,
                render_mode=req_mode.value, valid=result.valid,
                latency_ms=result.latency_ms, tokens_used=result.tokens_used,
            ))
        except Exception:
            pass  # history is best-effort; never fail the conversion
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
        ocr_mode = _parse_render_mode(render_mode)
        data = await image.read(config.max_ocr_bytes + 1)
        _assert_image_upload(config, image, data)
        try:
            result: ConvertResult = await router.process_image(data, render_mode=ocr_mode)
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
        try:
            await history.add(HistoryEntry(
                input_text=image.filename or "[image]", input_type="ocr",
                latex=result.latex, intent=result.intent, source=result.source.value,
                render_mode=ocr_mode.value, valid=result.valid,
                latency_ms=result.latency_ms, tokens_used=result.tokens_used,
            ))
        except Exception:
            pass  # history is best-effort; never fail the conversion
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
        comp_mode = _parse_render_mode(req.render_mode)
        try:
            result: ConvertResult = await router.process_text(
                req.text, route_override=Route.COMPLETION,
                render_mode=comp_mode,
            )
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
        try:
            await history.add(HistoryEntry(
                input_text=req.text, input_type="completion", latex=result.latex,
                intent=result.intent, source=result.source.value,
                render_mode=comp_mode.value, valid=result.valid,
                latency_ms=result.latency_ms, tokens_used=result.tokens_used,
            ))
        except Exception:
            pass  # history is best-effort; never fail the conversion
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
        _parse_render_mode(mode)
        render_engine.switch_mode(mode)
        return {"mode": render_engine.mode.value}

    @app.get("/api/shorthands")
    async def list_shorthands(q: str = Query(default="", max_length=200)):
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
    async def list_history(
        q: str = Query(default="", max_length=200),
        limit: int = Query(default=50, ge=1, le=100),
    ):
        entries = await history.list_recent(q, limit)
        return [e.__dict__ for e in entries]

    return app
