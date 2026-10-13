"""Bounded local reviews holding the original FormulaState, never imported ledgers."""

from __future__ import annotations

import hashlib
import io
import re
import threading
import time
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from PIL import Image

from texada.runtime import CommitBarrierError, FormulaState, StaleRevisionError
from texada.semantic.katex import shared_katex_parser
from texada.types import RenderResult


def input_source_hash(source_text: str, source_image: bytes | None = None) -> str:
    """Hash the source bytes when present, otherwise the exact original text."""
    return hashlib.sha256(
        source_image if source_image is not None else source_text.encode()
    ).hexdigest()


class ReviewError(RuntimeError):
    def __init__(self, detail: str, status_code: int = 409):
        self.status_code = status_code
        super().__init__(detail)


@dataclass(frozen=True)
class ReviewBinding:
    input_hash: str
    parent_revision: int | None
    candidate_hash: str
    current_revision: int

    def to_dict(self) -> dict[str, Any]:
        return dict(
            input_hash=self.input_hash,
            parent_revision=self.parent_revision,
            candidate_hash=self.candidate_hash,
            current_revision=self.current_revision,
        )


@dataclass
class PendingReview:
    id: str
    state: FormulaState
    binding: ReviewBinding
    source_text: str
    source_image: bytes | None
    source_mime: str
    source_image_digest: str | None
    source_text_digest: str
    render: RenderResult
    reasons: list[str]
    expires_monotonic: float
    expires_at: str
    status: str = "pending"
    metadata: dict[str, Any] = field(default_factory=dict)


def _position(parent_latex: str, path: str) -> dict[str, Any]:
    missing = {"status": "unavailable", "source": "parent_latex", "offset_units": "utf16"}
    # Only report direct, exact raw-role locations. Flattened wrappers or
    # changed tree shape cannot silently be assigned an approximate offset.
    match = re.fullmatch(
        r"root\[(\d+)\]\.(numerator|denominator|lower_bound|upper_bound|subscript|superscript|base|radicand|index)(?:\[\d+\])?(?:\.value)?",
        path,
    )
    if not match:
        return missing
    try:
        parsed = shared_katex_parser().parse(parent_latex)
        if not parsed.ok:
            return missing
        node = parsed.ast[int(match[1])]
        role = match[2]
        fields = {
            "genfrac": {"numerator": "numer", "denominator": "denom"},
            "supsub": {
                "lower_bound": "sub",
                "upper_bound": "sup",
                "subscript": "sub",
                "superscript": "sup",
                "base": "base",
            },
            "sqrt": {"radicand": "body", "index": "index"},
        }
        key = fields.get(node.get("type"), {}).get(role)
        if not key or not isinstance(node.get(key), dict):
            return missing
        loc = node[key].get("loc", {})
        start, end = loc.get("start"), loc.get("end")
        utf16_length = len(parent_latex.encode("utf-16-le")) // 2
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or not 0 <= start <= end <= utf16_length
        ):
            return missing
        return dict(
            status="available", source="parent_latex", start=start, end=end, offset_units="utf16"
        )
    except Exception:
        return missing


class PendingReviewStore:
    """Short-lived local memory, one decision lock and bounded source image bytes."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 600,
        max_items: int = 64,
        max_source_bytes: int = 32 * 1024 * 1024,
        clock=time.monotonic,
    ):
        if ttl_seconds <= 0 or max_items <= 0 or max_source_bytes < 0:
            raise ValueError("review retention limits must be positive")
        self.ttl_seconds = ttl_seconds
        self.max_items = max_items
        self.max_source_bytes = max_source_bytes
        self.clock = clock
        self._items: OrderedDict[str, PendingReview] = OrderedDict()
        self._expired: OrderedDict[str, None] = OrderedDict()
        self._lock = threading.RLock()

    def _expire(self, review_id: str) -> None:
        self._items.pop(review_id, None)
        self._expired[review_id] = None
        while len(self._expired) > self.max_items * 2:
            self._expired.popitem(last=False)

    def _purge(self) -> None:
        now = self.clock()
        for review_id, review in tuple(self._items.items()):
            if review.expires_monotonic <= now:
                self._expire(review_id)

    def register(
        self,
        state: FormulaState,
        *,
        input_hash: str,
        source_text: str,
        render: RenderResult,
        reasons: list[str],
        source_image: bytes | None = None,
        source_mime: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Retain the actual state object issued by this run and its source binding."""
        if state.revision is None or state.committed:
            raise ReviewError("review requires an uncommitted candidate revision")
        if not re.fullmatch("[a-f0-9]{64}", input_hash):
            raise ReviewError("invalid input source hash")
        if input_source_hash(source_text, source_image) != input_hash:
            raise ReviewError("original source bytes do not match the input hash")
        held_hash = getattr(state, "review_input_hash", input_hash)
        if held_hash != input_hash:
            raise ReviewError("input source identity changed before review registration")
        state.review_input_hash = input_hash
        image = self._displayable_image(source_image, source_mime)
        image_bytes = len(image) if image else 0
        if image_bytes > self.max_source_bytes:
            raise ReviewError("source image exceeds review memory capacity", 413)
        with self._lock:
            self._purge()
            while self._items and (
                len(self._items) >= self.max_items
                or self._source_bytes() + image_bytes > self.max_source_bytes
            ):
                self._expire(next(iter(self._items)))
            current = state.ledger.current
            binding = ReviewBinding(
                input_hash, current.parent, input_source_hash(state.latex), state.revision
            )
            review = PendingReview(
                uuid4().hex,
                state,
                binding,
                source_text,
                image,
                source_mime if image else "",
                input_source_hash("", image) if image else None,
                input_source_hash(source_text),
                deepcopy(render),
                list(reasons),
                self.clock() + self.ttl_seconds,
                datetime.fromtimestamp(time.time() + self.ttl_seconds, UTC).isoformat(),
                metadata=deepcopy(metadata or {}),
            )
            self._items[review.id] = review
            return self._dto(review)

    @staticmethod
    def _displayable_image(data: bytes | None, mime: str) -> bytes | None:
        if not data or mime not in {"image/png", "image/jpeg", "image/webp", "image/bmp"}:
            return None
        try:
            with Image.open(io.BytesIO(data)) as image:
                if Image.MIME.get(image.format) != mime:
                    return None
                image.verify()
        except Exception:
            return None
        return bytes(data)

    def _source_bytes(self) -> int:
        return sum(len(item.source_image or b"") for item in self._items.values())

    def _require(self, review_id: str) -> PendingReview:
        self._purge()
        review = self._items.get(review_id)
        if review is None:
            raise ReviewError(
                "review expired or was evicted"
                if review_id in self._expired
                else "review not found",
                410 if review_id in self._expired else 404,
            )
        self._verify(review)
        return review

    @staticmethod
    def _verify(review: PendingReview) -> None:
        state, binding = review.state, review.binding
        current = state.ledger.current
        if (
            state.revision != binding.current_revision
            or current is None
            or current.parent != binding.parent_revision
            or input_source_hash(state.latex) != binding.candidate_hash
            or getattr(state, "review_input_hash", None) != binding.input_hash
            or input_source_hash(review.source_text) != review.source_text_digest
            or (review.source_image is None) != (review.source_image_digest is None)
            or (
                review.source_image is not None
                and input_source_hash("", review.source_image) != review.source_image_digest
            )
        ):
            raise ReviewError("review source or candidate revision changed")

    def get(self, review_id: str) -> dict[str, Any]:
        with self._lock:
            return self._dto(self._require(review_id))

    def source(self, review_id: str) -> tuple[bytes, str]:
        with self._lock:
            review = self._require(review_id)
            if review.source_image is None:
                raise ReviewError("source image is unavailable", 404)
            return review.source_image, review.source_mime

    def decide(self, review_id: str, *, decision: str, binding: ReviewBinding) -> dict[str, Any]:
        with self._lock:
            review = self._require(review_id)
            if review.binding != binding:
                raise ReviewError("review confirmation does not match the source and revision")
            target = {"accept": "accepted", "reject": "rejected"}.get(decision)
            if target is None:
                raise ReviewError("decision must be accept or reject", 422)
            if review.status != "pending":
                if review.status != target:
                    raise ReviewError("an opposite review decision was already recorded")
                return self._dto(review)
            if decision == "accept":
                try:
                    # Human authorization overrides only scope/review policy;
                    # compile and render for this exact revision remain mandatory.
                    review.state.commit(expected_revision=binding.current_revision)
                except (CommitBarrierError, StaleRevisionError) as exc:
                    raise ReviewError(f"cannot accept candidate: {exc}") from None
                self._verify(review)
            review.state.add_evidence(
                revision=binding.current_revision,
                kind="human_review",
                ok=decision == "accept",
                output={
                    **binding.to_dict(),
                    "review_id": review.id,
                    "decision": decision,
                    "source_image_available": review.source_image is not None,
                    "scope_risk_explicitly_authorized": decision == "accept",
                    "intent_status": "NOT_CHECKED",
                },
            )
            review.status = target
            return self._dto(review)

    def claim_accept_event(self, review_id: str) -> dict[str, Any] | None:
        """Claim best-effort history/log work once even with concurrent HTTP retries."""
        with self._lock:
            review = self._require(review_id)
            if review.status != "accepted" or review.metadata.get("accept_event_claimed"):
                return None
            review.metadata["accept_event_claimed"] = True
            return deepcopy(review.metadata)

    def _dto(self, review: PendingReview) -> dict[str, Any]:
        evidence = review.state.ledger.evidence
        current = review.binding.current_revision
        compile_items = [
            item for item in evidence if item.revision == current and item.kind == "compile_tex"
        ]
        render_items = [
            item for item in evidence if item.revision == current and item.kind == "render_math"
        ]
        compiled = compile_items[-1] if compile_items else None
        rendered = render_items[-1] if render_items else None
        role_diff = []
        for item in evidence:
            if item.kind != "mutation_scope" or item.output.get("parent_revision") is None:
                continue
            parent_revision = item.output["parent_revision"]
            parent_latex = review.state.latex_at(parent_revision)
            for change in item.output.get("footprint", []):
                role_diff.append(
                    {
                        **change,
                        "parent_revision": parent_revision,
                        "child_revision": item.revision,
                        "parent_latex": parent_latex,
                        "position": _position(parent_latex, change["path"]),
                    }
                )
        return {
            "id": review.id,
            "status": review.status,
            **review.binding.to_dict(),
            "binding": review.binding.to_dict(),
            "expires_at": review.expires_at,
            "committed": any(item.revision == current for item in review.state.ledger.commits),
            "latex": review.state.latex_at(current),
            "parent_latex": review.state.latex_at(review.binding.parent_revision)
            if review.binding.parent_revision
            else "",
            "source_text": review.source_text,
            "source_image_url": f"/api/reviews/{review.id}/source" if review.source_image else None,
            "render": {
                "katex_html": review.render.katex_html,
                "latex_highlighted": review.render.latex_highlighted,
                "copy_text": review.render.copy_text,
            },
            "reasons": list(review.reasons),
            "role_diff": role_diff,
            "checks": {
                "compile": {
                    "status": "not_checked"
                    if compiled is None
                    else "valid"
                    if compiled.ok and compiled.output.get("valid") is True
                    else "invalid"
                },
                "render": {
                    "status": "not_checked"
                    if rendered is None
                    else "rendered"
                    if rendered.ok
                    else "failed"
                },
                "cas": [item.output for item in evidence if item.kind == "cas_transition"],
                "human": {
                    "status": review.status,
                    "source_image_available": review.source_image is not None,
                },
                "intent": {"status": "not_checked"},
            },
        }

    def clear(self) -> None:
        with self._lock:
            for review_id in tuple(self._items):
                self._expire(review_id)
