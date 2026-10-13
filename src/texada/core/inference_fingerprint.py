"""Request-bound inference identity and secret-free provider attempt telemetry."""

from __future__ import annotations

import copy
import hashlib
import json
import platform
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from importlib.metadata import PackageNotFoundError, version
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_serializer,
    model_validator,
)

from texada import __version__
from texada.config import TeXadaConfig

Digest = str


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sanitized_endpoint(value: str) -> str:
    """Retain routing identity without URL credentials, query, or fragment."""
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if not host or parsed.scheme not in {"http", "https"}:
            return ""
        if ":" in host:
            host = f"[{host}]"
        authority = host if parsed.port is None else f"{host}:{parsed.port}"
        return urlunsplit((parsed.scheme, authority, parsed.path.rstrip("/"), "", ""))
    except ValueError:
        return ""


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IdentityEvidence(_Contract):
    status: Literal["CONFIGURED", "OBSERVED", "REPORTED", "NOT_CHECKED"]
    value: str | None = Field(default=None, max_length=300)
    reason: str = Field(default="", max_length=300)

    @model_validator(mode="after")
    def unknown_has_no_value(self):
        if self.status == "NOT_CHECKED" and self.value is not None:
            raise ValueError("NOT_CHECKED identity must not contain an asserted value")
        return self


class ConfiguredModels(_Contract):
    text: str = Field(max_length=300)
    vision: str = Field(max_length=300)


class InferenceConfiguration(_Contract):
    temperature: float
    max_tokens: int
    inference_timeout_seconds: float
    api_request_timeout_seconds: float
    agent_max_steps: int
    tool_timeout_seconds: float
    nl_candidate_first: bool
    ocr_preprocessing: Literal["raw", "binary"]


class ArtifactIdentities(_Contract):
    weights_sha256: IdentityEvidence
    weights_revision: IdentityEvidence
    quantization: IdentityEvidence
    mmproj_sha256: IdentityEvidence
    runtime_build: IdentityEvidence
    chat_template_revision: IdentityEvidence


class ClientRuntime(_Contract):
    python: str
    openai: str | None
    httpx: str | None
    opencv: str | None


class DatasetIdentity(_Contract):
    version: IdentityEvidence
    sha256: IdentityEvidence


class PlannerControls(_Contract):
    failure_context_projection: bool
    surface: Literal["full", "minimal"]


class InferenceIdentity(_Contract):
    application_version: str = Field(max_length=100)
    application_build: IdentityEvidence
    backend: Literal["ollama", "openai_compatible"]
    endpoint: str = Field(max_length=500)
    configured_models: ConfiguredModels
    configuration: InferenceConfiguration
    client_runtime: ClientRuntime
    prompt_manifest_sha256: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    tool_schema_sha256: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    artifacts: ArtifactIdentities
    dataset: DatasetIdentity
    planner_controls: PlannerControls | None = None

    @model_serializer(mode="wrap")
    def preserve_legacy_identity_bytes(self, handler):
        data = handler(self)
        if self.planner_controls is None:
            data.pop("planner_controls", None)
        return data

    @field_validator("endpoint")
    @classmethod
    def endpoint_contains_no_url_secrets(cls, value):
        if value != sanitized_endpoint(value):
            raise ValueError("fingerprint endpoint must not contain URL credentials or query")
        return value


class StructuredToolChoice(_Contract):
    type: Literal["function", "custom", "allowed_tools"]
    name: str | None = Field(default=None, max_length=300)
    mode: Literal["auto", "required"] | None = None
    tools_sha256: Digest | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class TimeoutConfiguration(_Contract):
    connect: float | None
    read: float | None
    write: float | None
    pool: float | None


class CaptureFailure(_Contract):
    stage: Literal["begin_call", "finish_call"]
    error_type: str = Field(max_length=100)


class RequestOptions(_Contract):
    temperature: float | None = None
    max_tokens: int | None = None
    tool_choice: Annotated[str, Field(max_length=80)] | StructuredToolChoice | None = None
    reasoning_effort: str | None = Field(default=None, max_length=80)
    enable_thinking: bool | None = None


class ProviderAttempt(_Contract):
    purpose: Literal["planner", "nl_generation", "completion", "ocr", "unspecified"]
    requested_model: str = Field(max_length=300)
    options: RequestOptions
    system_prompt_sha256: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    fixed_few_shot_sha256: Digest | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    tool_schema_sha256: Digest | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    effective_timeout_seconds: float | None = None
    effective_timeout: TimeoutConfiguration | None = None
    outcome: Literal["pending", "success", "error"] = "pending"
    error_type: str | None = Field(default=None, max_length=100)
    response_model: IdentityEvidence
    provider_system_fingerprint: IdentityEvidence


class InferenceFingerprint(_Contract):
    schema_version: Literal[1] = 1
    status: Literal["RECORDED", "NOT_CHECKED"]
    reason: str = Field(default="", max_length=300)
    identity: InferenceIdentity | None = None
    identity_sha256: Digest | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    calls: list[ProviderAttempt] = Field(default_factory=list, max_length=100)
    capture_status: Literal["COMPLETE", "PARTIAL", "NOT_CHECKED"] = "NOT_CHECKED"
    capture_errors: list[CaptureFailure] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def identity_digest_matches(self):
        if self.capture_errors and self.capture_status != "PARTIAL":
            raise ValueError("capture failures must be marked PARTIAL")
        if self.capture_status == "PARTIAL" and not self.capture_errors:
            raise ValueError("PARTIAL capture requires a capture failure record")
        if self.status == "RECORDED":
            if self.identity is None:
                raise ValueError("RECORDED fingerprint requires identity")
            if self.identity_sha256 != canonical_sha256(self.identity.model_dump()):
                raise ValueError("fingerprint identity_sha256 does not match identity")
        elif (
            self.identity is not None or self.identity_sha256 is not None or self.calls
            or self.capture_status != "NOT_CHECKED" or self.capture_errors
        ):
            raise ValueError("NOT_CHECKED fingerprint must not reconstruct an execution")
        return self


def legacy_inference_fingerprint() -> dict:
    return {
        "schema_version": 1, "status": "NOT_CHECKED", "reason": "legacy_record",
        "identity": None, "identity_sha256": None, "calls": [],
    }


def unavailable_inference_fingerprint(error: Exception) -> dict:
    fingerprint = legacy_inference_fingerprint()
    error_type = type(error).__name__[:100]
    fingerprint["reason"] = f"capture_initialization_failed:{error_type}"
    return fingerprint


def validate_inference_fingerprint(value: Any) -> dict:
    validated = InferenceFingerprint.model_validate(value).model_dump()
    if validated["status"] == "NOT_CHECKED":
        # Keep the legacy wire shape unchanged; its status already says that
        # no historical execution was captured.
        validated.pop("capture_status")
        validated.pop("capture_errors")
    return validated


def _not_checked(reason: str) -> dict:
    return {"status": "NOT_CHECKED", "value": None, "reason": reason}


def _configured(value: str | None, reason: str) -> dict:
    return (
        {"status": "CONFIGURED", "value": value, "reason": ""}
        if value is not None else _not_checked(reason)
    )


def _package_version(package: str) -> str | None:
    try:
        return version(package)
    except PackageNotFoundError:
        return None


def default_prompt_manifest() -> dict:
    # Lazy imports avoid model/runtime initialization cycles. These are fixed
    # application instructions and examples, never request content.
    from texada.agent.actions import ACTION_BINDING_INSTRUCTION, SURFACE_INSTRUCTIONS
    from texada.agent.failure_context import FAILURE_CONTEXT_INSTRUCTION
    from texada.agent.runtime import (
        COMPLETION_AGENT_PROMPT,
        NL_AGENT_PROMPT,
        OCR_AGENT_PROMPT,
        PLANNER_SYSTEM_PROMPT,
    )
    from texada.core.model import (
        NL_RETRY_INSTRUCTION,
        OCR_RETRY_INSTRUCTION,
        OCR_USER_INSTRUCTION,
        OPERATOR_CONSTRAINT_TEMPLATE,
    )
    from texada.core.prompts import (
        COMPLETION_PROMPT,
        FEW_SHOT_BY_INTENT,
        OCR_SYSTEM_PROMPT,
        SYSTEM_PROMPT,
    )

    return {
        "planner": PLANNER_SYSTEM_PROMPT, "nl_review": NL_AGENT_PROMPT,
        "ocr_review": OCR_AGENT_PROMPT, "completion_review": COMPLETION_AGENT_PROMPT,
        "nl_generation": SYSTEM_PROMPT, "completion": COMPLETION_PROMPT,
        "ocr": OCR_SYSTEM_PROMPT, "few_shot": FEW_SHOT_BY_INTENT,
        "nl_retry": NL_RETRY_INSTRUCTION, "ocr_retry": OCR_RETRY_INSTRUCTION,
        "ocr_user_instruction": OCR_USER_INSTRUCTION,
        "operator_constraint_template": OPERATOR_CONSTRAINT_TEMPLATE,
        "failure_context_instruction": FAILURE_CONTEXT_INSTRUCTION,
        "planner_action_binding": ACTION_BINDING_INSTRUCTION,
        "planner_surface_instructions": SURFACE_INSTRUCTIONS,
    }


def build_inference_identity(
    config: TeXadaConfig,
    *,
    app_version: str = __version__,
    prompt_manifest: dict | None = None,
    tool_schemas: list[dict] | None = None,
    dataset_version: str | None = None,
    dataset_sha256: str | None = None,
) -> dict:
    """Capture configured identity; hidden server artifacts stay NOT_CHECKED."""
    if tool_schemas is None:
        from texada.tools.registry import TeXToolset

        tool_schemas = [definition.to_openai() for definition in TeXToolset.DEFINITIONS]
    configuration = {
        name: getattr(config, name) for name in InferenceConfiguration.model_fields
    }
    hidden = {
        "weights_sha256": "actual serving weight bytes are not observable for hashing",
        "weights_revision": "serving checkpoint revision is not exposed by the endpoint",
        "quantization": "actual serving precision cannot be verified from a configured alias",
        "mmproj_sha256": "serving multimodal projector bytes are not observable for hashing",
        "runtime_build": "externally managed server runtime build is not observed",
        "chat_template_revision": "server chat-template revision is not exposed by the endpoint",
    }
    identity = InferenceIdentity(
        application_version=app_version,
        application_build=_not_checked("application build revision is not embedded"),
        backend=config.backend,
        endpoint=sanitized_endpoint(config.active_base_url),
        configured_models={
            "text": config.active_model_name, "vision": config.active_vision_model_name,
        },
        configuration=configuration,
        client_runtime={
            "python": platform.python_version(), "openai": _package_version("openai"),
            "httpx": _package_version("httpx"), "opencv": _package_version("opencv-python"),
        },
        prompt_manifest_sha256=canonical_sha256(
            default_prompt_manifest() if prompt_manifest is None else prompt_manifest,
        ),
        tool_schema_sha256=canonical_sha256(tool_schemas),
        artifacts={name: _not_checked(reason) for name, reason in hidden.items()},
        dataset={
            "version": _configured(dataset_version, "interactive request has no dataset identity"),
            "sha256": _configured(dataset_sha256, "dataset content hash was not supplied"),
        },
        planner_controls={
            "failure_context_projection": config.failure_context_projection,
            "surface": getattr(config, "planner_surface", "full"),
        },
    )
    return identity.model_dump()


class InferenceCollector:
    """One mutable collector shared with this request's copied thread context."""

    def __init__(self, identity: dict):
        self.identity = InferenceIdentity.model_validate(identity).model_dump()
        self.identity_sha256 = canonical_sha256(self.identity)
        self.calls: list[dict] = []
        self.capture_errors: list[dict] = []
        self._lock = threading.Lock()

    @staticmethod
    def _tool_choice(value):
        if not isinstance(value, dict):
            return value
        kind = value.get("type")
        if kind in {"function", "custom"}:
            return {"type": kind, "name": value[kind]["name"]}
        if kind == "allowed_tools":
            allowed = value["allowed_tools"]
            return {
                "type": kind, "mode": allowed["mode"],
                "tools_sha256": canonical_sha256(allowed["tools"]),
            }
        raise ValueError("unrecognized structured tool choice")

    @staticmethod
    def _timeout(value) -> dict:
        phases = value.as_dict() if isinstance(value, httpx.Timeout) else {
            phase: value for phase in TimeoutConfiguration.model_fields
        }
        return TimeoutConfiguration.model_validate(phases).model_dump()

    def begin_call(
        self, purpose: str, kwargs: dict, *, fixed_few_shot: list[dict] | None,
        default_timeout: float,
    ) -> int:
        options = {name: kwargs.get(name) for name in ("temperature", "max_tokens", "tool_choice")}
        options["tool_choice"] = self._tool_choice(options["tool_choice"])
        extra = kwargs.get("extra_body") or {}
        options["reasoning_effort"] = kwargs.get("reasoning_effort", extra.get("reasoning_effort"))
        options["enable_thinking"] = (extra.get("chat_template_kwargs") or {}).get(
            "enable_thinking",
        )
        system_messages = [
            message.get("content") for message in kwargs.get("messages", [])
            if message.get("role") == "system"
        ]
        tools = kwargs.get("tools")
        timeout = self._timeout(kwargs.get("timeout", default_timeout))
        uniform_timeout = timeout["read"] if len(set(timeout.values())) == 1 else None
        call = ProviderAttempt(
            purpose=purpose, requested_model=kwargs.get("model", ""), options=options,
            system_prompt_sha256=canonical_sha256(system_messages),
            fixed_few_shot_sha256=(
                canonical_sha256(fixed_few_shot) if fixed_few_shot is not None else None
            ),
            tool_schema_sha256=canonical_sha256(tools) if tools is not None else None,
            effective_timeout_seconds=uniform_timeout, effective_timeout=timeout,
            response_model=_not_checked("no provider response was observed"),
            provider_system_fingerprint=_not_checked(
                "provider did not report a system fingerprint",
            ),
        ).model_dump()
        with self._lock:
            self.calls.append(call)
            return len(self.calls) - 1

    def capture_failure(
        self, stage: str, error: Exception, *, attempt: int | None = None,
        outcome: str | None = None, provider_error_type: str | None = None,
    ) -> None:
        # Never retain exception text, request kwargs, or response bodies.
        failure = {"stage": stage, "error_type": type(error).__name__[:100]}
        with self._lock:
            self.capture_errors.append(failure)
            if isinstance(attempt, int) and 0 <= attempt < len(self.calls):
                # The SDK outcome is known even if response metadata failed.
                call = self.calls[attempt]
                call["outcome"] = outcome
                call["error_type"] = provider_error_type
                for field in ("response_model", "provider_system_fingerprint"):
                    if call[field]["status"] == "NOT_CHECKED":
                        call[field] = _not_checked("provider response metadata capture failed")

    def finish_call(self, index: int, *, response=None, error=None, api_key: str = "") -> None:
        with self._lock:
            call = self.calls[index]
            call["outcome"] = "error" if error is not None else "success"
            call["error_type"] = type(error).__name__ if error is not None else None
            if response is not None:
                for field, attribute in (
                    ("response_model", "model"),
                    ("provider_system_fingerprint", "system_fingerprint"),
                ):
                    value = getattr(response, attribute, None)
                    if isinstance(value, str) and value:
                        if api_key:
                            value = value.replace(api_key, "[redacted]")
                        call[field] = {"status": "REPORTED", "value": value[:300], "reason": ""}

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "schema_version": 1, "status": "RECORDED", "reason": "",
                "identity": copy.deepcopy(self.identity), "identity_sha256": self.identity_sha256,
                "calls": copy.deepcopy(self.calls),
                "capture_status": "PARTIAL" if self.capture_errors else "COMPLETE",
                "capture_errors": copy.deepcopy(self.capture_errors),
            }


_collector: ContextVar[InferenceCollector | None] = ContextVar(
    "texada_inference_collector", default=None,
)


def current_inference_collector() -> InferenceCollector | None:
    return _collector.get()


@contextmanager
def without_inference_collection() -> Iterator[None]:
    """Do not inherit an outer collector when request collection failed."""
    token = _collector.set(None)
    try:
        yield
    finally:
        _collector.reset(token)


@contextmanager
def collect_inference(identity: dict) -> Iterator[InferenceCollector]:
    collector = InferenceCollector(identity)
    token = _collector.set(collector)
    try:
        yield collector
    finally:
        _collector.reset(token)
