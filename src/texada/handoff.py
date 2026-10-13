"""Bounded, idempotent single-formula transfers to the configured MiniCPM runtime."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import math
import time
from collections.abc import Awaitable, Callable
from contextlib import ExitStack
from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from texada.agent.runtime import TeXadaAgentRuntime
from texada.config import TeXadaConfig
from texada.core.inference_fingerprint import (
    build_inference_identity,
    canonical_sha256,
    collect_inference,
    unavailable_inference_fingerprint,
    without_inference_collection,
)
from texada.core.model import MiniCPMModel
from texada.types import RenderMode

CHECKPOINT = "MiniCPM-V-4.7-1B"
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceRange(_Contract):
    start: int = Field(ge=0, strict=True)
    end: int = Field(ge=1, strict=True)
    encoding: Literal["unicode-codepoints"]


class TransferBudget(_Contract):
    max_steps: int = Field(ge=1, le=8, strict=True)
    max_seconds: float = Field(gt=0, le=900)
    max_tokens: int = Field(ge=64, le=32768, strict=True)

    @model_validator(mode="after")
    def finite_seconds(self):
        if not math.isfinite(self.max_seconds):
            raise ValueError("max_seconds must be finite")
        return self


class FormulaTransfer(_Contract):
    schema_version: Literal[1]
    transfer_id: str = Field(min_length=36, max_length=36)
    document_sha256: Digest
    input_sha256: Digest
    source_range: SourceRange
    formula_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9:_-]+$")
    expected_revision: int = Field(ge=0, strict=True)
    original_latex: str = Field(min_length=1, max_length=32768)
    requested_action: Literal["repair", "complete"]
    allowed_scope: Literal["syntax_repair", "completion_prefix"]
    checkpoint: Literal["MiniCPM-V-4.7-1B"]
    budget: TransferBudget
    requires_review: Literal[True]
    evidence: list[dict] = Field(max_length=0)

    @model_validator(mode="after")
    def source_and_scope_binding(self):
        if str(UUID(self.transfer_id)) != self.transfer_id:
            raise ValueError("transfer_id must be a canonical UUID")
        if self.input_sha256 != text_digest(self.original_latex):
            raise ValueError("original formula hash mismatch")
        if self.source_range.end - self.source_range.start != len(self.original_latex):
            raise ValueError("source range does not match formula codepoints")
        expected = "syntax_repair" if self.requested_action == "repair" else "completion_prefix"
        if self.allowed_scope != expected:
            raise ValueError("action and scope do not match")
        return self


class HandoffError(RuntimeError):
    def __init__(self, code: str, *, status_code=503):
        super().__init__(code)
        self.code, self.status_code = code, status_code


@dataclass
class _TransferRecord:
    digest: str
    expires_at: float
    done: asyncio.Event
    result: dict | None = None
    error: HandoffError | None = None


class TransferRegistry:
    """Process-local bounded cache: identical concurrent IDs execute exactly once."""

    def __init__(self, *, max_items=128, ttl_seconds=900.0, clock=time.monotonic):
        self.max_items, self.ttl_seconds, self.clock = max_items, ttl_seconds, clock
        self._records: dict[str, _TransferRecord] = {}
        self._lock = asyncio.Lock()

    async def execute(self, transfer: FormulaTransfer, execute: Callable[[], Awaitable[dict]]) -> dict:
        digest = canonical_sha256(transfer.model_dump(mode="json"))
        async with self._lock:
            now = self.clock()
            for key, record in list(self._records.items()):
                if record.done.is_set() and record.expires_at <= now:
                    del self._records[key]
            record = self._records.get(transfer.transfer_id)
            owner = record is None
            if record is not None and record.digest != digest:
                raise HandoffError("TRANSFER_ID_CONFLICT", status_code=409)
            if owner:
                if len(self._records) >= self.max_items:
                    raise HandoffError("TRANSFER_CAPACITY", status_code=429)
                record = _TransferRecord(digest, now+self.ttl_seconds, asyncio.Event())
                self._records[transfer.transfer_id] = record
        assert record is not None
        if owner:
            try:
                record.result = copy.deepcopy(await execute())
            except HandoffError as exc:
                record.error = HandoffError(exc.code, status_code=exc.status_code)
            except asyncio.CancelledError:
                record.error = HandoffError("TRANSFER_CANCELLED")
                raise
            except Exception:
                record.error = HandoffError("TRANSFER_EXECUTION_FAILED")
            finally:
                record.expires_at = self.clock()+self.ttl_seconds
                record.done.set()
        else:
            try:
                await asyncio.wait_for(record.done.wait(), timeout=transfer.budget.max_seconds+1)
            except TimeoutError as exc:
                raise HandoffError("TRANSFER_PENDING", status_code=504) from exc
        if record.error is not None:
            raise HandoffError(record.error.code, status_code=record.error.status_code)
        if record.result is None:
            raise HandoffError("TRANSFER_RESULT_UNAVAILABLE")
        return copy.deepcopy(record.result)


def bounded_configuration(config: TeXadaConfig, transfer: FormulaTransfer) -> TeXadaConfig:
    if (config.active_model_name != CHECKPOINT or config.active_vision_model_name != CHECKPOINT):
        raise HandoffError("CHECKPOINT_MISMATCH", status_code=409)
    seconds = min(config.api_request_timeout_seconds, transfer.budget.max_seconds)
    return config.model_copy(update={
        "agent_max_steps": min(config.agent_max_steps, transfer.budget.max_steps),
        "max_tokens": min(config.max_tokens, transfer.budget.max_tokens),
        "api_request_timeout_seconds": seconds,
        "inference_timeout_seconds": min(config.inference_timeout_seconds, seconds),
        "tool_timeout_seconds": min(config.tool_timeout_seconds, seconds),
    })


async def produce_formula_transfer(
    transfer: FormulaTransfer, config: TeXadaConfig, register_review: Callable,
    *, model_factory=None, runtime_factory=None,
    record_result: Callable | None = None,
) -> dict:
    """Only original formula text is transferred to inference; whole-document hash is a claim."""
    bounded = bounded_configuration(config, transfer)
    model_factory = model_factory or MiniCPMModel
    runtime_factory = runtime_factory or TeXadaAgentRuntime
    model = model_factory(bounded)
    runtime = runtime_factory(bounded, model=model)
    collector, fallback = None, None
    started = time.monotonic()
    try:
        with ExitStack() as collection:
            try:
                identity = build_inference_identity(bounded, tool_schemas=runtime.tools.schemas)
                collector = collection.enter_context(collect_inference(identity))
            except Exception as exc:
                fallback = unavailable_inference_fingerprint(exc)
                collection.enter_context(without_inference_collection())

            async def run():
                candidate = transfer.original_latex
                tokens = 0
                task = "repair"
                if transfer.requested_action == "complete":
                    task = "completion"
                    candidate = await model.complete_latex(transfer.original_latex)
                    tokens = model.consume_tokens_used()
                return await runtime.run_candidate(
                    task, transfer.original_latex, candidate, render_mode=RenderMode.KATEX,
                    initial_tokens_used=tokens, requires_review=True,
                    input_source_hash=transfer.input_sha256,
                )

            try:
                result = await asyncio.wait_for(run(), timeout=bounded.api_request_timeout_seconds)
            except TimeoutError as exc:
                raise HandoffError("TRANSFER_TIMEOUT", status_code=504) from exc
            if result.committed:
                # An automatic commit violates the transfer's trusted review requirement.
                raise HandoffError("UNCONFIRMED_TRANSFER_COMMIT")
            if not result.latex or result.revision is None:
                raise HandoffError("TRANSFER_CANDIDATE_UNAVAILABLE")
            fingerprint = collector.snapshot() if collector is not None else fallback
            review = register_review(
                result, source_text=transfer.original_latex, input_hash=transfer.input_sha256,
                metadata={"transfer_id": transfer.transfer_id,
                          "document_sha256": transfer.document_sha256,
                          "source_range": transfer.source_range.model_dump(),
                          "consumer_revision": transfer.expected_revision,
                          "inference_fingerprint": fingerprint},
            )
            if inspect.isawaitable(review):
                review = await review
            if not review or review.get("status") != "pending":
                raise HandoffError("TRANSFER_REVIEW_UNAVAILABLE")
            binding = review.get("binding") or {name: review[name] for name in (
                "input_hash", "parent_revision", "candidate_hash", "current_revision",
            )}
            if (binding["input_hash"] != transfer.input_sha256
                    or binding["candidate_hash"] != text_digest(result.latex)
                    or binding["current_revision"] != result.revision):
                raise HandoffError("TRANSFER_REVIEW_BINDING_MISMATCH")
            review = {**review, "binding": binding, "transfer_context": {
                "effective_budget": {
                    "max_steps": bounded.agent_max_steps,
                    "max_seconds": bounded.api_request_timeout_seconds,
                    "max_tokens": bounded.max_tokens,
                    "max_tokens_scope": "output per provider call",
                },
                "document_evidence": {"status": "CONFIGURED",
                                      "reason": "consumer must recheck source document"},
            }}
            scope = next((step["mutation_scope"] for step in reversed(result.trace)
                          if "mutation_scope" in step), {"status": "NOT_CHECKED"})
            cas = next((step["cas_transition"] for step in reversed(result.trace)
                        if "cas_transition" in step), {"status": "NOT_CHECKED"})
            response = {
                **transfer.model_dump(mode="json"),
                "status": "review_required", "candidate": result.latex,
                "candidate_sha256": text_digest(result.latex),
                "parent_revision": binding["parent_revision"],
                "candidate_revision": result.revision,
                "diff": result.semantic_diff,
                "evidence": {"mutation_scope": scope, "cas_transition": cas},
                "inference_fingerprint": fingerprint, "review": review,
            }
            if record_result is not None:
                recorded = record_result(result, response, (time.monotonic()-started)*1000)
                if inspect.isawaitable(recorded):
                    await recorded
            return response
    finally:
        client = getattr(model, "_client", None)
        if client is not None:
            client.close()
