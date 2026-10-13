"""Runtime-issued, revision-bound mutation scopes; no model-issued permissions."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from texada.runtime import FormulaState
from texada.semantic import SemanticDiffer
from texada.semantic.structure import UnsupportedStructure, canonical_structure


class MutationVerdict(StrEnum):
    ALLOWED = "allowed"
    OUT_OF_SCOPE = "out_of_scope"
    REVIEW_REQUIRED = "review_required"


class TransitionKind(StrEnum):
    CANDIDATE_SYNTHESIS = "candidate_synthesis"
    SYNTAX_REPAIR = "syntax_repair"
    COMPLETION_PREFIX = "completion_prefix"
    OCR_ROLES = "ocr_roles"
    PRESERVE_STRUCTURE = "preserve_structure"


@dataclass(frozen=True)
class MutationGrant:
    """Issued by the runtime, never deserialized from tool arguments."""

    kind: TransitionKind
    source_prefix: str = ""
    uncertain_role_paths: tuple[str, ...] = ()


@dataclass
class MutationEvidence:
    verdict: MutationVerdict
    transition: TransitionKind
    parent_revision: int | None
    child_revision: int
    basis: str
    footprint: list[dict[str, Any]] = field(default_factory=list)
    authorized_role_paths: list[str] = field(default_factory=list)
    parser_backend: str | None = None
    reason: str = ""
    intent_status: str = "NOT_CHECKED"
    semantics_preserving_declared: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _tokens(latex: str) -> list[str]:
    # Keep braces, scripts, operator rank, all literal tokens and delimiters.
    # Commands and numeric literals remain indivisible: a prefix ending in 1 cannot
    # authorize extending that numeric token to 12 or 1.2. This is conservative even
    # for TeX's unbraced arguments. Prefix bytes separately preserve whitespace
    # because it can be meaningful inside text, operator names or verbatim spans.
    return re.findall(r"\\[A-Za-z]+|\\.|[0-9]+(?:\.[0-9]+)?|\.[0-9]+|[^\s]", latex)


def _role_at(path: str) -> str:
    roles = re.findall(
        r"\.(numerator|denominator|radicand|index|base|lower_bound|upper_bound|subscript|superscript|argument|row_\d+|column_\d+)(?=[.\[]|$)",
        path,
    )
    return roles[-1] if roles else "root"


def _footprint(before: Any, after: Any, path: str = "root") -> list[dict[str, Any]]:
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        if before.keys() != after.keys():
            return [{"path": path, "operation": "replace", "role": _role_at(path)}]
        changes = []
        for key in before:
            if key == "children":
                changes.extend(_footprint(before[key], after[key], path))
            else:
                changes.extend(_footprint(before[key], after[key], f"{path}.{key}"))
        return changes
    if isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            return [
                {
                    "path": path,
                    "operation": "replace_children",
                    "role": _role_at(path),
                    "before_count": len(before),
                    "after_count": len(after),
                }
            ]
        changes = []
        for index, (left, right) in enumerate(zip(before, after, strict=True)):
            role = left.get("role") if isinstance(left, dict) else None
            matched_role = role and isinstance(right, dict) and role == right.get("role")
            child_path = f"{path}.{role}" if matched_role else f"{path}[{index}]"
            changes.extend(_footprint(left, right, child_path))
        return changes
    change = {"path": path, "operation": "update", "role": _role_at(path)}
    if not isinstance(before, (dict, list)) and not isinstance(after, (dict, list)):
        change.update(before=before, after=after)
    return [change]


def _in_role(path: str, authorized: str) -> bool:
    return (
        path == authorized or path.startswith(authorized + ".") or path.startswith(authorized + "[")
    )


class MutationScopeGuard:
    """Conservative scopes for one run; uncertain OCR role paths are trusted input.

    The public OCR endpoint supplies no uncertainty labels, so its default grant
    is empty. A trusted detector may supply complete canonical role paths through
    the internal runtime seam. A planner's extra arguments never become grants.
    """

    def __init__(
        self, *, task: str = "nl", prefix: str = "", uncertain_roles: tuple[str, ...] = ()
    ):
        self.task = task
        self.prefix = prefix
        if any(
            not isinstance(path, str)
            or not re.fullmatch(
                r"root(?:\[\d+\]|\.(?:numerator|denominator|radicand|index|base|lower_bound|upper_bound|subscript|superscript|argument|row_\d+|column_\d+))+",
                path,
            )
            or "." not in path
            for path in uncertain_roles
        ):
            raise ValueError("OCR uncertainty grants require complete mathematical role paths")
        self.uncertain_roles = tuple(uncertain_roles)

    def grant(self, origin: str) -> MutationGrant:
        if origin == "tool:repair_tex":
            return MutationGrant(TransitionKind.SYNTAX_REPAIR, source_prefix=self.prefix)
        if self.task == "completion":
            return MutationGrant(TransitionKind.COMPLETION_PREFIX, source_prefix=self.prefix)
        if self.task == "ocr":
            return MutationGrant(
                TransitionKind.OCR_ROLES, uncertain_role_paths=self.uncertain_roles
            )
        return MutationGrant(TransitionKind.CANDIDATE_SYNTHESIS)

    def assess(
        self,
        before: str,
        after: str,
        *,
        origin: str,
        parent_revision: int | None,
        child_revision: int,
    ) -> MutationEvidence:
        grant = self.grant(origin)
        result = MutationEvidence(
            MutationVerdict.ALLOWED,
            grant.kind,
            parent_revision,
            child_revision,
            "unchanged",
            authorized_role_paths=list(grant.uncertain_role_paths),
            semantics_preserving_declared=grant.kind
            in {
                TransitionKind.SYNTAX_REPAIR,
                TransitionKind.PRESERVE_STRUCTURE,
            },
        )
        prefix_tokens = _tokens(grant.source_prefix)
        if grant.source_prefix and (
            not after.startswith(grant.source_prefix)
            or _tokens(after)[: len(prefix_tokens)] != prefix_tokens
        ):
            result.verdict = MutationVerdict.OUT_OF_SCOPE
            result.basis = "completion_prefix_tokens"
            result.footprint = [{"path": "source_prefix", "operation": "update", "role": "prefix"}]
            result.reason = "existing completion prefix was changed"
            return result
        if before == after:
            return result
        if not before:
            result.basis = "initial_candidate"
            return result
        if grant.kind == TransitionKind.CANDIDATE_SYNTHESIS:
            # NL candidates are provisional translations of a user request,
            # rather than edits to a supplied formula. This broad grant makes
            # no claim that the request was translated correctly.
            result.basis = "provisional_nl_synthesis"
            try:
                left, result.parser_backend = canonical_structure(before)
                right, _ = canonical_structure(after)
                result.footprint = _footprint(left, right)
            except Exception:
                result.footprint = [{"path": "root", "operation": "replace", "role": "unresolved"}]
            return result
        try:
            left, backend = canonical_structure(before)
            right, _ = canonical_structure(after)
            if not left or not right:
                raise UnsupportedStructure("empty_structure")
            result.parser_backend = backend
            result.footprint = _footprint(left, right)
            # A degraded role alignment cannot authorize a local edit even when
            # the independent raw AST scan produces a footprint.
            if SemanticDiffer().diff(before, after).degraded:
                raise UnsupportedStructure("semantic_diff_degraded")
        except (UnsupportedStructure, MemoryError, RecursionError):
            # The only malformed-parent exception is deterministic trailing
            # closing-brace insertion, which cannot edit any existing token.
            suffix = after[len(before) :] if after.startswith(before) else ""
            if grant.kind == TransitionKind.SYNTAX_REPAIR and suffix and set(suffix) == {"}"}:
                try:
                    child, result.parser_backend = canonical_structure(after)
                    if not child:
                        raise UnsupportedStructure("empty_structure")
                except Exception:
                    pass
                else:
                    result.basis = "deterministic_trailing_closing_braces"
                    result.footprint = [
                        {"path": "syntax.trailing_braces", "operation": "add", "role": "syntax"}
                    ]
                    return result
            result.verdict = MutationVerdict.REVIEW_REQUIRED
            result.basis = "unreliable_parse_or_diff"
            result.reason = "mutation cannot be authorized by reliable structure evidence"
            return result
        except Exception:
            result.verdict = MutationVerdict.REVIEW_REQUIRED
            result.basis = "parser_unavailable"
            result.reason = "structure parser is unavailable"
            return result
        result.basis = "pinned_raw_ast_roles"
        if not result.footprint:
            return result
        if grant.kind == TransitionKind.COMPLETION_PREFIX:
            # The existing prefix has exact byte and token contracts. The generated
            # suffix is provisional and may be changed by completion review.
            result.basis = "completion_prefix_tokens"
            return result
        if grant.kind == TransitionKind.OCR_ROLES and all(
            any(_in_role(change["path"], role) for role in grant.uncertain_role_paths)
            for change in result.footprint
        ):
            return result
        result.verdict = MutationVerdict.OUT_OF_SCOPE
        result.reason = "changed mathematical roles exceed the runtime grant"
        return result

    @staticmethod
    def commit_blockers(state: FormulaState) -> list[dict[str, Any]]:
        """All accepted transitions remain auditable; later revisions cannot erase a violation."""
        return [
            item.to_dict()
            for item in state.ledger.evidence
            if item.kind == "mutation_scope" and not item.ok
        ]
