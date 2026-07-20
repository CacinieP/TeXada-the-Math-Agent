"""FastAPI backend — HTTP API for the shell UI."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
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

EXPORTABLE_SETTINGS_FIELDS = frozenset({
    "backend",
    "ollama_host",
    "model_name",
    "vision_model_name",
    "openai_base_url",
    "openai_model_name",
    "openai_vision_model_name",
    "temperature",
    "max_tokens",
    "default_render_mode",
    "delimiter",
    "ui_language",
    "ui_zoom",
    "inference_timeout_seconds",
    "api_request_timeout_seconds",
})

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
    ready: bool = False
    backend: str
    endpoint: str | None = None
    model: str | None = None
    vision: str | None = None
    message: str | None = None
    missing_models: list[str] = Field(default_factory=list)
    text_model_installed: bool | None = None
    vision_model_installed: bool | None = None
    installed_model_count: int | None = None
    ollama_cli_available: bool | None = None
    next_action: str | None = None
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


class UiSettingsResponse(BaseModel):
    ui_language: str
    ui_zoom: float


class UiSettingsUpdate(BaseModel):
    ui_language: str | None = Field(default=None, pattern="^(zh|en)$")
    ui_zoom: float | None = Field(default=None, ge=0.8, le=1.4)


class RuntimeConfigResponse(BaseModel):
    version: str
    api_base_url: str
    api_host: str
    api_port: int
    request_timeout_ms: int
    max_ocr_bytes: int
    allowed_image_mime_types: list[str]


class HistoryImportEntry(BaseModel):
    input_text: str = Field(min_length=1, max_length=4000)
    input_type: str = Field(default="nl", max_length=40)
    latex: str = Field(min_length=1, max_length=4000)
    intent: str = Field(default="", max_length=120)
    source: str = Field(default="model", max_length=40)
    render_mode: str = Field(default="katex", pattern="^(katex|latex)$")
    valid: bool = True
    latency_ms: float = Field(default=0.0, ge=0)
    tokens_used: int = Field(default=0, ge=0)
    starred: bool = False
    created_at: str = Field(default="", max_length=80)


class HistoryImportRequest(BaseModel):
    mode: str = Field(default="merge", pattern="^(merge|replace)$")
    history: list[HistoryImportEntry] = Field(default_factory=list, max_length=10000)


class BackupImportRequest(BaseModel):
    mode: str = Field(default="merge", pattern="^(merge|replace)$")
    history: list[HistoryImportEntry] = Field(default_factory=list, max_length=10000)
    shorthands: dict[str, str] = Field(default_factory=dict)
    settings: dict = Field(default_factory=dict)


# ── App factory ──

def _app_version() -> str:
    try:
        return version("texada")
    except PackageNotFoundError:
        return "0.2.4"


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


def _history_entry_response(entry: HistoryEntry) -> dict:
    return {
        "id": entry.id,
        "input_text": entry.input_text,
        "input_type": entry.input_type,
        "latex": entry.latex,
        "intent": entry.intent,
        "source": entry.source,
        "render_mode": entry.render_mode,
        "valid": entry.valid,
        "latency_ms": entry.latency_ms,
        "tokens_used": entry.tokens_used,
        "starred": entry.starred,
        "created_at": entry.created_at,
    }


def _history_import_entry(entry: HistoryImportEntry) -> HistoryEntry:
    return HistoryEntry(
        input_text=entry.input_text,
        input_type=entry.input_type.strip().lower() or "nl",
        latex=entry.latex,
        intent=entry.intent,
        source=entry.source,
        render_mode=entry.render_mode,
        valid=entry.valid,
        latency_ms=entry.latency_ms,
        tokens_used=entry.tokens_used,
        starred=entry.starred,
        created_at=entry.created_at,
    )


def _backup_meta(app_version: str) -> dict:
    return {
        "app": "TeXada",
        "schema_version": 1,
        "version": app_version,
        "exported_at": datetime.now(UTC).isoformat(),
    }


def _exportable_settings(config: TeXadaConfig) -> dict:
    """Settings safe to include in data backups. API keys are intentionally excluded."""
    return {
        "backend": config.backend,
        "ollama_host": config.ollama_host,
        "model_name": config.model_name,
        "vision_model_name": config.vision_model_name,
        "openai_base_url": config.openai_base_url,
        "openai_model_name": config.openai_model_name,
        "openai_vision_model_name": config.openai_vision_model_name,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "default_render_mode": config.default_render_mode,
        "delimiter": config.delimiter,
        "ui_language": config.ui_language,
        "ui_zoom": config.ui_zoom,
        "inference_timeout_seconds": config.inference_timeout_seconds,
        "api_request_timeout_seconds": config.api_request_timeout_seconds,
    }


def _importable_settings(settings: dict) -> dict:
    return {
        key: value
        for key, value in settings.items()
        if key in EXPORTABLE_SETTINGS_FIELDS
    }


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
            ready=info.get("ready", info["status"] in {"ready", "ok"}),
            backend=info.get("backend", config.backend),
            endpoint=info.get("endpoint"),
            model=info.get("model"),
            vision=info.get("vision"),
            message=info.get("message"),
            missing_models=info.get("missing_models", []),
            text_model_installed=info.get("text_model_installed"),
            vision_model_installed=info.get("vision_model_installed"),
            installed_model_count=info.get("installed_model_count"),
            ollama_cli_available=info.get("ollama_cli_available"),
            next_action=info.get("next_action"),
            render_mode=render_engine.mode.value,
            delimiter=render_engine.delimiter,
        )

    @app.get("/api/settings/backend", response_model=BackendSettingsResponse)
    async def get_backend_settings():
        return _settings_response(config)

    @app.get("/api/settings/ui", response_model=UiSettingsResponse)
    async def get_ui_settings():
        return UiSettingsResponse(ui_language=config.ui_language, ui_zoom=config.ui_zoom)

    @app.get("/api/runtime", response_model=RuntimeConfigResponse)
    async def get_runtime_config():
        return RuntimeConfigResponse(
            version=app_version,
            api_base_url=config.api_base_url,
            api_host=config.api_host,
            api_port=config.api_port,
            request_timeout_ms=int(config.api_request_timeout_seconds * 1000),
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

    @app.post("/api/settings/ui", response_model=UiSettingsResponse)
    async def update_ui_settings(req: UiSettingsUpdate):
        nonlocal config
        updates = req.model_dump(exclude_none=True)
        if updates:
            config = save_config_updates(updates, data_dir=config.data_dir)
        return UiSettingsResponse(ui_language=config.ui_language, ui_zoom=config.ui_zoom)

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
        return [{"key": k, "value": v, "editable": shorthand.can_delete(k)} for k, v in items]

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
        input_type: str = Query(default="", alias="type", max_length=40),
        limit: int = Query(default=50, ge=1, le=100),
    ):
        entries = await history.list_recent(q, limit, input_type=input_type)
        return [e.__dict__ for e in entries]

    @app.get("/api/history/export")
    async def export_history(
        input_type: str = Query(default="", alias="type", max_length=40),
    ):
        entries = await history.export_all(input_type=input_type)
        return {
            "_meta": _backup_meta(app_version),
            "history": [_history_entry_response(entry) for entry in entries],
        }

    @app.post("/api/history/import")
    async def import_history(req: HistoryImportRequest):
        entries = [_history_import_entry(entry) for entry in req.history]
        return await history.import_entries(entries, mode=req.mode)

    @app.delete("/api/history")
    async def clear_history(
        input_type: str = Query(default="", alias="type", max_length=40),
    ):
        deleted = await history.clear(input_type=input_type)
        return {"deleted": deleted}

    @app.get("/api/export")
    async def export_backup():
        entries = await history.export_all()
        return {
            "_meta": _backup_meta(app_version),
            "settings": _exportable_settings(config),
            "shorthands": shorthand.list_user_defined(),
            "history": [_history_entry_response(entry) for entry in entries],
        }

    @app.post("/api/import")
    async def import_backup(req: BackupImportRequest):
        nonlocal config, router, shorthand, history, render_engine, backend_mgr
        history_result = await history.import_entries(
            [_history_import_entry(entry) for entry in req.history],
            mode=req.mode,
        )
        shorthand_result = shorthand.import_many(req.shorthands)
        settings_updates = _importable_settings(req.settings)
        settings_imported = 0
        if settings_updates:
            config = save_config_updates(settings_updates, data_dir=config.data_dir)
            router = InputRouter(config)
            shorthand = router.shorthand_store
            history = HistoryStore(config)
            render_engine = RenderEngine(config)
            backend_mgr = BackendManager(config)
            settings_imported = len(settings_updates)
        return {
            "history": history_result,
            "shorthands": shorthand_result,
            "settings": {"imported": settings_imported},
        }

    return app
