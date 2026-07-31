"""FastAPI backend — HTTP API for the shell UI."""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from texada.agent.runtime import TeXadaAgentRuntime
from texada.config import (
    TeXadaConfig,
    load_config,
    save_config_updates,
    validate_config_updates,
)
from texada.core.backend import BackendManager
from texada.core.router import InputRouter
from texada.render.engine import RenderEngine
from texada.semantic.katex import shared_katex_parser
from texada.store.history import HistoryStore
from texada.store.run_log import RunLogStore
from texada.store.shorthand import DEFAULT_SHORTHANDS
from texada.types import ConvertResult, HistoryEntry, RenderMode, RunLogEntry

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
    "agent_max_steps",
    "run_log_max_days",
    "run_log_max_items",
})

# ── Request / Response models ──

class ConvertRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    context: str = Field(default="", max_length=8000)
    intent_override: str | None = Field(default=None, max_length=80)
    render_mode: str = Field(default="katex", pattern="^(katex|latex)$")

class LaTeXResponse(BaseModel):
    run_id: str
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


class AgentResponse(LaTeXResponse):
    semantic_document: dict = Field(default_factory=dict)
    semantic_diff: dict = Field(default_factory=dict)
    agent_trace: list[dict] = Field(default_factory=list)
    stop_reason: str = "completed"

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
    inference_timeout_seconds: float
    api_request_timeout_seconds: float

class BackendSettingsUpdate(BaseModel):
    backend: str | None = Field(default=None, pattern="^(ollama|openai_compatible)$")
    ollama_host: str | None = Field(default=None, max_length=500)
    model_name: str | None = Field(default=None, max_length=300)
    vision_model_name: str | None = Field(default=None, max_length=300)
    openai_base_url: str | None = Field(default=None, max_length=500)
    openai_model_name: str | None = Field(default=None, max_length=300)
    openai_vision_model_name: str | None = Field(default=None, max_length=300)
    openai_api_key: str | None = Field(default=None, max_length=4000)
    inference_timeout_seconds: float | None = Field(default=None, ge=10.0, le=600.0)
    api_request_timeout_seconds: float | None = Field(default=None, ge=30.0, le=900.0)


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
    run_id: str = Field(default="", max_length=80)
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
    history: list[HistoryImportEntry] = Field(default_factory=list)


class RunLogImportEntry(BaseModel):
    run_id: str = Field(min_length=1, max_length=80)
    operation: str = Field(default="", max_length=40)
    input_type: str = Field(default="", max_length=40)
    input_text: str = Field(default="", max_length=4000)
    input_bytes: int = Field(default=0, ge=0)
    input_mime: str = Field(default="", max_length=120)
    model_role: str = Field(default="", max_length=40)
    model_name: str = Field(default="", max_length=300)
    backend: str = Field(default="", max_length=80)
    status: str = Field(default="success", pattern="^(success|error)$")
    status_code: int = Field(default=200, ge=100, le=599)
    output_latex: str = Field(default="", max_length=4000)
    intent: str = Field(default="", max_length=120)
    source: str = Field(default="", max_length=40)
    render_mode: str = Field(default="", max_length=20)
    valid: bool | None = None
    latency_ms: float = Field(default=0.0, ge=0)
    tokens_used: int = Field(default=0, ge=0)
    stop_reason: str = Field(default="", max_length=160)
    tool_call_count: int = Field(default=0, ge=0)
    tool_names: list[str] = Field(default_factory=list, max_length=200)
    trace: list[dict] = Field(default_factory=list, max_length=100)
    error_message: str = Field(default="", max_length=8000)
    created_at: str = Field(default="", max_length=80)


class RunLogImportRequest(BaseModel):
    mode: str = Field(default="merge", pattern="^(merge|replace)$")
    run_logs: list[RunLogImportEntry] = Field(default_factory=list)


class PresetImportRequest(BaseModel):
    mode: str = Field(default="merge", pattern="^(merge|replace)$")
    presets: dict[str, str] = Field(default_factory=dict)


class BackupImportRequest(BaseModel):
    mode: str = Field(default="merge", pattern="^(merge|replace)$")
    history: list[HistoryImportEntry] = Field(default_factory=list)
    shorthands: dict[str, str] = Field(default_factory=dict)
    run_logs: list[RunLogImportEntry] = Field(default_factory=list)
    settings: dict = Field(default_factory=dict)


# ── App factory ──

def _app_version() -> str:
    try:
        return version("texada")
    except PackageNotFoundError:
        return "0.3.3"


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
        inference_timeout_seconds=config.inference_timeout_seconds,
        api_request_timeout_seconds=config.api_request_timeout_seconds,
    )


def _history_entry_response(entry: HistoryEntry) -> dict:
    return {
        "id": entry.id,
        "run_id": entry.run_id,
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
        run_id=entry.run_id,
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
        "schema_version": 2,
        "version": app_version,
        "exported_at": datetime.now(UTC).isoformat(),
    }


def _run_log_response(
    entry: RunLogEntry,
    *,
    include_trace: bool = True,
) -> dict:
    response = {
        "run_id": entry.run_id,
        "operation": entry.operation,
        "input_type": entry.input_type,
        "input_text": entry.input_text,
        "input_bytes": entry.input_bytes,
        "input_mime": entry.input_mime,
        "model_role": entry.model_role,
        "model_name": entry.model_name,
        "backend": entry.backend,
        "status": entry.status,
        "status_code": entry.status_code,
        "output_latex": entry.output_latex,
        "intent": entry.intent,
        "source": entry.source,
        "render_mode": entry.render_mode,
        "valid": entry.valid,
        "latency_ms": entry.latency_ms,
        "tokens_used": entry.tokens_used,
        "stop_reason": entry.stop_reason,
        "tool_call_count": entry.tool_call_count,
        "tool_names": entry.tool_names,
        "trace_available": entry.trace_available or bool(entry.trace),
        "error_message": entry.error_message,
        "created_at": entry.created_at,
    }
    if include_trace:
        response["trace"] = entry.trace
    return response


def _run_log_import_entry(entry: RunLogImportEntry) -> RunLogEntry:
    return RunLogEntry(**entry.model_dump())


def _trace_tool_names(trace: list[dict]) -> list[str]:
    names: list[str] = []
    for step in trace:
        step_names: list[str] = []
        for call in step.get("tool_calls", []):
            name = str(call.get("name") or call.get("function", {}).get("name") or "").strip()
            if name:
                step_names.append(name)
        if step_names:
            names.extend(step_names)
        else:
            for observation in step.get("observations", []):
                name = str(observation.get("tool") or "").strip()
                if name and name != "operator_drift_guard":
                    names.append(name)
    return names


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
        "agent_max_steps": config.agent_max_steps,
        "run_log_max_days": config.run_log_max_days,
        "run_log_max_items": config.run_log_max_items,
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
    agent_runtime = TeXadaAgentRuntime(
        config,
        model=router.model,
        backend=router.backend,
    )
    shorthand = router.shorthand_store  # share router's store so /convert sees /api/shorthands adds
    history = HistoryStore(config)
    run_logs = RunLogStore(config)
    render_engine = RenderEngine(config)
    backend_mgr = BackendManager(config)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            shared_katex_parser().close()

    app = FastAPI(title="TeXada", version=app_version, lifespan=lifespan)
    allowed_origins = set(config.api_allowed_origins)
    # CORS — only the local shell UI and Tauri app should call the API from a browser.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["content-type"],
    )

    async def record_run(entry: RunLogEntry) -> None:
        """Run logging is best-effort and must never break a user request."""
        try:
            await run_logs.add(entry)
        except Exception:
            pass

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
        nonlocal config, router, agent_runtime, shorthand, history, run_logs
        nonlocal render_engine, backend_mgr
        updates = req.model_dump(exclude_none=True)
        if updates.get("openai_api_key") == "":
            updates.pop("openai_api_key")
        config = save_config_updates(updates, data_dir=config.data_dir)
        router = InputRouter(config)
        agent_runtime = TeXadaAgentRuntime(
            config,
            model=router.model,
            backend=router.backend,
        )
        shorthand = router.shorthand_store
        history = HistoryStore(config)
        run_logs = RunLogStore(config)
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
        run_id = uuid4().hex
        started = time.monotonic()
        req_mode = _parse_render_mode(req.render_mode)
        try:
            result: ConvertResult = await router.process_text(
                req.text,
                intent_override=req.intent_override,
                context=req.context,
                render_mode=req_mode,
            )
        except RuntimeError as e:
            await record_run(RunLogEntry(
                run_id=run_id, operation="convert", input_type="nl",
                input_text=req.text, model_role="text",
                model_name=config.active_model_name, backend=config.backend,
                status="error", status_code=503, render_mode=req_mode.value,
                latency_ms=(time.monotonic() - started) * 1000,
                error_message=str(e),
            ))
            raise HTTPException(status_code=503, detail=str(e)) from e
        except Exception as e:
            await record_run(RunLogEntry(
                run_id=run_id, operation="convert", input_type="nl",
                input_text=req.text, model_role="text",
                model_name=config.active_model_name, backend=config.backend,
                status="error", status_code=500, render_mode=req_mode.value,
                latency_ms=(time.monotonic() - started) * 1000,
                error_message=str(e),
            ))
            raise
        try:
            await history.add(HistoryEntry(
                run_id=run_id, input_text=req.text, input_type="nl", latex=result.latex,
                intent=result.intent, source=result.source.value,
                render_mode=req_mode.value, valid=result.valid,
                latency_ms=result.latency_ms, tokens_used=result.tokens_used,
            ))
        except Exception:
            pass  # history is best-effort; never fail the conversion
        await record_run(RunLogEntry(
            run_id=run_id, operation="convert", input_type="nl",
            input_text=req.text, model_role="text",
            model_name=config.active_model_name, backend=config.backend,
            status="success", status_code=200, output_latex=result.latex,
            intent=result.intent, source=result.source.value,
            render_mode=req_mode.value, valid=result.valid,
            latency_ms=result.latency_ms, tokens_used=result.tokens_used,
        ))
        return LaTeXResponse(
            run_id=run_id,
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

    @app.post("/api/agent", response_model=AgentResponse)
    async def run_agent(req: ConvertRequest):
        """Primary NL path: MiniCPM5 planner → tools → observations."""
        run_id = uuid4().hex
        started = time.monotonic()
        req_mode = _parse_render_mode(req.render_mode)
        try:
            result = await agent_runtime.run(
                req.text,
                context=req.context,
                render_mode=req_mode,
            )
        except RuntimeError as e:
            await record_run(RunLogEntry(
                run_id=run_id, operation="agent", input_type="nl",
                input_text=req.text, model_role="planner",
                model_name=config.active_model_name, backend=config.backend,
                status="error", status_code=503, render_mode=req_mode.value,
                latency_ms=(time.monotonic() - started) * 1000,
                error_message=str(e),
            ))
            raise HTTPException(status_code=503, detail=str(e)) from e
        except Exception as e:
            await record_run(RunLogEntry(
                run_id=run_id, operation="agent", input_type="nl",
                input_text=req.text, model_role="planner",
                model_name=config.active_model_name, backend=config.backend,
                status="error", status_code=500, render_mode=req_mode.value,
                latency_ms=(time.monotonic() - started) * 1000,
                error_message=str(e),
            ))
            raise
        try:
            await history.add(HistoryEntry(
                run_id=run_id,
                input_text=req.text,
                input_type="nl",
                latex=result.latex,
                intent="agent",
                source="agent",
                render_mode=req_mode.value,
                valid=result.valid,
                latency_ms=result.latency_ms,
                tokens_used=result.tokens_used,
            ))
        except Exception:
            pass
        tool_names = _trace_tool_names(result.trace)
        await record_run(RunLogEntry(
            run_id=run_id, operation="agent", input_type="nl",
            input_text=req.text, model_role="planner",
            model_name=config.active_model_name, backend=config.backend,
            status="success", status_code=200, output_latex=result.latex,
            intent="agent", source="agent", render_mode=req_mode.value,
            valid=result.valid, latency_ms=result.latency_ms,
            tokens_used=result.tokens_used, stop_reason=result.stop_reason,
            tool_call_count=len(tool_names), tool_names=tool_names,
            trace=result.trace,
        ))
        return AgentResponse(
            run_id=run_id,
            latex=result.latex,
            katex_html=result.render.katex_html,
            latex_highlighted=result.render.latex_highlighted,
            copy_text=result.render.copy_text,
            valid=result.valid,
            source="agent",
            intent="agent",
            confidence=1.0 if result.valid else 0.5,
            latency_ms=result.latency_ms,
            tokens_used=result.tokens_used,
            semantic_document=result.semantic_document,
            semantic_diff=result.semantic_diff,
            agent_trace=result.trace,
            stop_reason=result.stop_reason,
        )

    @app.post("/api/ocr", response_model=AgentResponse)
    async def convert_image(image: UploadFile, render_mode: str = "katex"):
        run_id = uuid4().hex
        started = time.monotonic()
        ocr_mode = _parse_render_mode(render_mode)
        model_chain = (
            f"{config.active_vision_model_name} -> {config.active_model_name}"
        )
        data = await image.read(config.max_ocr_bytes + 1)
        try:
            _assert_image_upload(config, image, data)
        except HTTPException as e:
            await record_run(RunLogEntry(
                run_id=run_id, operation="ocr", input_type="ocr",
                input_text=image.filename or "[image]", input_bytes=len(data),
                input_mime=image.content_type or "", model_role="planner",
                model_name=model_chain, backend=config.backend,
                status="error", status_code=e.status_code, render_mode=ocr_mode.value,
                latency_ms=(time.monotonic() - started) * 1000,
                error_message=str(e.detail),
            ))
            raise
        try:
            candidate, vision_tokens = await router.create_ocr_candidate(data)
            result = await agent_runtime.run_candidate(
                "ocr",
                image.filename or "[image]",
                candidate,
                render_mode=ocr_mode,
                initial_tokens_used=vision_tokens,
            )
        except RuntimeError as e:
            await record_run(RunLogEntry(
                run_id=run_id, operation="ocr", input_type="ocr",
                input_text=image.filename or "[image]", input_bytes=len(data),
                input_mime=image.content_type or "", model_role="planner",
                model_name=model_chain, backend=config.backend,
                status="error", status_code=503, render_mode=ocr_mode.value,
                latency_ms=(time.monotonic() - started) * 1000,
                error_message=str(e),
            ))
            raise HTTPException(status_code=503, detail=str(e)) from e
        except Exception as e:
            await record_run(RunLogEntry(
                run_id=run_id, operation="ocr", input_type="ocr",
                input_text=image.filename or "[image]", input_bytes=len(data),
                input_mime=image.content_type or "", model_role="planner",
                model_name=model_chain, backend=config.backend,
                status="error", status_code=500, render_mode=ocr_mode.value,
                latency_ms=(time.monotonic() - started) * 1000,
                error_message=str(e),
            ))
            raise
        try:
            await history.add(HistoryEntry(
                run_id=run_id, input_text=image.filename or "[image]", input_type="ocr",
                latex=result.latex, intent="ocr_agent", source="agent",
                render_mode=ocr_mode.value, valid=result.valid,
                latency_ms=result.latency_ms, tokens_used=result.tokens_used,
            ))
        except Exception:
            pass  # history is best-effort; never fail the conversion
        tool_names = _trace_tool_names(result.trace)
        await record_run(RunLogEntry(
            run_id=run_id, operation="ocr", input_type="ocr",
            input_text=image.filename or "[image]", input_bytes=len(data),
            input_mime=image.content_type or "", model_role="planner",
            model_name=model_chain, backend=config.backend,
            status="success", status_code=200, output_latex=result.latex,
            intent="ocr_agent", source="agent",
            render_mode=ocr_mode.value, valid=result.valid,
            latency_ms=result.latency_ms, tokens_used=result.tokens_used,
            stop_reason=result.stop_reason,
            tool_call_count=len(tool_names), tool_names=tool_names,
            trace=result.trace,
        ))
        return AgentResponse(
            run_id=run_id,
            latex=result.latex,
            katex_html=result.render.katex_html,
            latex_highlighted=result.render.latex_highlighted,
            copy_text=result.render.copy_text,
            valid=result.valid,
            source="agent",
            intent="ocr_agent",
            confidence=1.0 if result.valid else 0.5,
            latency_ms=result.latency_ms,
            tokens_used=result.tokens_used,
            semantic_document=result.semantic_document,
            semantic_diff=result.semantic_diff,
            agent_trace=result.trace,
            stop_reason=result.stop_reason,
        )

    @app.post("/api/complete", response_model=AgentResponse)
    async def complete_latex(req: ConvertRequest):
        run_id = uuid4().hex
        started = time.monotonic()
        comp_mode = _parse_render_mode(req.render_mode)
        try:
            candidate, candidate_tokens = await router.create_completion_candidate(
                req.text,
                context=req.context,
            )
            result = await agent_runtime.run_candidate(
                "completion",
                req.text,
                candidate,
                context=req.context,
                render_mode=comp_mode,
                initial_tokens_used=candidate_tokens,
            )
        except RuntimeError as e:
            await record_run(RunLogEntry(
                run_id=run_id, operation="completion", input_type="completion",
                input_text=req.text, model_role="planner",
                model_name=config.active_model_name, backend=config.backend,
                status="error", status_code=503, render_mode=comp_mode.value,
                latency_ms=(time.monotonic() - started) * 1000,
                error_message=str(e),
            ))
            raise HTTPException(status_code=503, detail=str(e)) from e
        except Exception as e:
            await record_run(RunLogEntry(
                run_id=run_id, operation="completion", input_type="completion",
                input_text=req.text, model_role="planner",
                model_name=config.active_model_name, backend=config.backend,
                status="error", status_code=500, render_mode=comp_mode.value,
                latency_ms=(time.monotonic() - started) * 1000,
                error_message=str(e),
            ))
            raise
        try:
            await history.add(HistoryEntry(
                run_id=run_id, input_text=req.text, input_type="completion",
                latex=result.latex,
                intent="completion_agent", source="agent",
                render_mode=comp_mode.value, valid=result.valid,
                latency_ms=result.latency_ms, tokens_used=result.tokens_used,
            ))
        except Exception:
            pass  # history is best-effort; never fail the conversion
        tool_names = _trace_tool_names(result.trace)
        await record_run(RunLogEntry(
            run_id=run_id, operation="completion", input_type="completion",
            input_text=req.text, model_role="planner",
            model_name=config.active_model_name, backend=config.backend,
            status="success", status_code=200, output_latex=result.latex,
            intent="completion_agent", source="agent",
            render_mode=comp_mode.value, valid=result.valid,
            latency_ms=result.latency_ms, tokens_used=result.tokens_used,
            stop_reason=result.stop_reason,
            tool_call_count=len(tool_names), tool_names=tool_names,
            trace=result.trace,
        ))
        return AgentResponse(
            run_id=run_id,
            latex=result.latex,
            katex_html=result.render.katex_html,
            latex_highlighted=result.render.latex_highlighted,
            copy_text=result.render.copy_text,
            valid=result.valid,
            source="agent",
            intent="completion_agent",
            confidence=1.0 if result.valid else 0.5,
            latency_ms=result.latency_ms,
            tokens_used=result.tokens_used,
            semantic_document=result.semantic_document,
            semantic_diff=result.semantic_diff,
            agent_trace=result.trace,
            stop_reason=result.stop_reason,
        )

    @app.post("/api/validate", response_model=ValidateResponse)
    async def validate_latex(req: ValidateRequest):
        run_id = uuid4().hex
        started = time.monotonic()
        from texada.core.validator import LaTeXValidator
        validator = LaTeXValidator()
        result = validator.validate(req.latex)
        await record_run(RunLogEntry(
            run_id=run_id, operation="validate", input_type="latex",
            input_text=req.latex, model_role="none", backend="local",
            status="success", status_code=200, output_latex=req.latex,
            source="validator", valid=result.valid,
            latency_ms=(time.monotonic() - started) * 1000,
        ))
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
        try:
            shorthand.add(req.key, req.value)
        except ValueError as exc:
            status = 409 if req.key.strip() in DEFAULT_SHORTHANDS else 422
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        return ShorthandResponse(key=req.key, value=req.value)

    @app.get("/api/shorthands/export")
    async def export_shorthands():
        return {
            "_meta": _backup_meta(app_version),
            "presets": shorthand.list_user_defined(),
        }

    @app.post("/api/shorthands/import")
    async def import_shorthands(req: PresetImportRequest):
        return shorthand.import_many(req.presets, mode=req.mode)

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

    @app.get("/api/runs")
    async def list_run_logs(
        q: str = Query(default="", max_length=200),
        operation: str = Query(default="", max_length=40),
        status: str = Query(default="", pattern="^(|all|success|error)$"),
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
        entries = await run_logs.list_recent(
            q,
            operation=operation,
            status=status,
            limit=limit,
            offset=offset,
            include_trace=False,
        )
        return [
            _run_log_response(entry, include_trace=False)
            for entry in entries
        ]

    @app.get("/api/runs/export")
    async def export_run_logs():
        entries = await run_logs.export_all()
        return {
            "_meta": _backup_meta(app_version),
            "run_logs": [_run_log_response(entry) for entry in entries],
        }

    @app.post("/api/runs/import")
    async def import_run_logs(req: RunLogImportRequest):
        entries = [_run_log_import_entry(entry) for entry in req.run_logs]
        return await run_logs.import_entries(entries, mode=req.mode)

    @app.delete("/api/runs")
    async def clear_run_logs():
        return {"deleted": await run_logs.clear()}

    @app.get("/api/runs/{run_id}")
    async def get_run_log(run_id: str):
        entry = await run_logs.get(run_id)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
        return _run_log_response(entry)

    @app.get("/api/export")
    async def export_backup():
        entries = await history.export_all()
        runs = await run_logs.export_all()
        return {
            "_meta": _backup_meta(app_version),
            "settings": _exportable_settings(config),
            "shorthands": shorthand.list_user_defined(),
            "history": [_history_entry_response(entry) for entry in entries],
            "run_logs": [_run_log_response(entry) for entry in runs],
        }

    @app.post("/api/import")
    async def import_backup(req: BackupImportRequest):
        nonlocal config, router, agent_runtime, shorthand, history, run_logs
        nonlocal render_engine, backend_mgr
        settings_updates = _importable_settings(req.settings)
        if settings_updates:
            try:
                validate_config_updates(settings_updates, data_dir=config.data_dir)
            except (TypeError, ValueError, ValidationError) as exc:
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid backup settings: {exc}",
                ) from exc

        history_result = await history.import_entries(
            [_history_import_entry(entry) for entry in req.history],
            mode=req.mode,
        )
        run_log_result = await run_logs.import_entries(
            [_run_log_import_entry(entry) for entry in req.run_logs],
            mode=req.mode,
        )
        shorthand_result = shorthand.import_many(req.shorthands, mode=req.mode)
        settings_imported = 0
        if settings_updates:
            config = save_config_updates(settings_updates, data_dir=config.data_dir)
            router = InputRouter(config)
            agent_runtime = TeXadaAgentRuntime(
                config,
                model=router.model,
                backend=router.backend,
            )
            shorthand = router.shorthand_store
            history = HistoryStore(config)
            run_logs = RunLogStore(config)
            render_engine = RenderEngine(config)
            backend_mgr = BackendManager(config)
            settings_imported = len(settings_updates)
        return {
            "history": history_result,
            "shorthands": shorthand_result,
            "run_logs": run_log_result,
            "settings": {"imported": settings_imported},
        }

    return app
