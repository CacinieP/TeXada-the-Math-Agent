# ADR-019 — Bounded Sum Transcription

| Field | Value |
|---|---|
| Status | Implemented, release pending |
| Date | 2026-11-06 |
| Layers | Input / Deterministic Tools / Semantic / Evidence |
| Baseline | Official v0.4.3 at `6adcba0ab1540f2efb1bf78156783842001bc72c` |

## Problem and evidence

The official v0.4.3 macOS arm64 replay recorded three compilable, committed
outputs that changed the requested terms or domains. The package, model,
configuration and export hashes are recorded in ADR-018. This decision uses
those same released-package observations. [Replay identity](018-parameterized-matrix-candidates.md#reproduction-identity-and-scope)

| Case | Released replay run ID | Observed failure |
|---|---|---|
| C05 | `06547e53bc814b419d13cde5876015ab` | The request to sum `b_n` acquired a second summation factor and invented bounds. |
| C09 | `a35e889115054bf3891d3c8ab63c72d9` | The region `omega_i` acquired an integral upper bound, and `Fi` lost its function subscript. |
| C14 | `b97282caf0634c31b341534cd354099e` | The integer domain became the interval from one to `n`. |

Focused tests retain the exact request/output pairs and their replay IDs.
They establish syntax validity separately from a `DIFFERENT` source-display
verdict. New regression results belong to the source implementation.

## Decision

1. Recognize complete, finite descriptions from the original input before
   symbol substitution. Support indexed single-letter terms, single-argument
   functions summed over a named single-letter set or the integers, and sums
   of indexed functions integrated over indexed `omega` or `Omega` regions.
   Plain, underscore and braced single-letter indices are accepted.
2. Preserve unspecified bounds using `\sum_{n} b_n`. Preserve a specified
   integer domain using `\sum_{x \in \mathbb{Z}} F(x)`. Preserve a region
   integral using `\sum_{i} \int_{\omega_i} F_i`, with the integration measure
   implicit. Record omitted bounds and measure in `unspecified_fields`.
3. A missing region index such as `omega_`, ambiguous joined names such as
   `ln` or `pi`, conflicting function/region
   indices, or conflicting argument/summation variables produces a visible
   clarification request. Return the original input and diagnostic through
   the run trace with `source_clarification_required`, an empty candidate
   and `committed=false`.
4. Check the actual candidate against the recognized display contract using
   the existing strict structural normalizer. Record checked coverage, parser
   identity, hashes, diagnostics and revision. `MATCH` concerns the finite
   display contract. Mathematical evaluation and general semantic equivalence
   have separate evidence requirements.
5. Require fresh `transcription_constraints` evidence alongside compilation
   and rendering at the Commit Barrier. A revision change triggers a new
   check. A mismatched or unsupported candidate retains its diagnostics and
   stays uncommitted.
6. Supplemental context sends recognized descriptions through the existing
   model/Planner route. Both candidate generation and planning receive that
   context, and the trace reports `NOT_CHECKED` for finite source constraints.
   Requests outside the grammar use the same bounded Planner fallback with
   explicit unchecked coverage for sum/integral descriptions.

## Tradeoffs and acceptance

This extends the deterministic candidate seam from ADR-017 and the
revision-bound constraint pattern from ADR-018. Recognition requires a whole
supported description so added conditions reach the Planner. The maintained
grammar covers a small vocabulary. Context-dependent requests continue to
require model fidelity review.

Tests cover the three released failures, named-set and fraction neighbors,
alias/case preservation, incomplete inputs, actual-candidate mismatch,
revision changes, context-aware fallback, stopped-model execution, the Agent
API, history, backup roundtrips and the visible clarification alert.
Release-package validation is tracked separately from these source checks.
