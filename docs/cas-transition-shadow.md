# Revision-bound CAS shadow evidence

Finalized runtime revisions now receive `cas_transition` evidence. Each record
contains the exact parent/child revision, hashes of both LaTeX values, the
runtime's semantics-preserving declaration and mutation verdict, applicability,
typed verdict, basis, witness, CAS evidence grade and policy versions. It is also
saved in the existing API/run-log trace as `cas_transition`.

The mode is always `shadow`, and `blocks_commit` is always false. CAS cannot grant
mutation permission, override the scope guard, or approve a review. Enabling a
CAS commit gate requires separate evaluation and revision/scope binding.

Initial candidates have no parent and are `NOT_CHECKED`. NL synthesis, OCR
correction and completion are not declared semantic identities, so they are not
compared. A runtime-issued syntax repair is declared preserving, but an invalid
parent normally cannot be reliably translated and is explicitly `UNSUPPORTED`.
This distinction prevents a repaired expression from falsely claiming a proof
against an unparseable parent.

The first comparison subset is deliberately conservative: rational-coefficient
polynomials and polynomial equations, with ordinary parentheses, positive
single-digit integer powers and positive single-digit constant denominators.
The existing semantic translator treats ambiguous `e`/`i`, subscripts and other
unsupported symbols separately. A raw AST check additionally excludes binomials,
operator/integral rank, roots, absolute-value or other delimiters, fonts, text,
matrices, nonconstant denominators and adjacent digits. Those fields can be lost
or interpreted incorrectly by the current SemanticUnit-to-CAS path. For example,
this version does not certify rational cancellation across a removed singularity
or interpret a two-digit number as a product of digits.

Eligible pairs use the existing isolated `AlgebraChecker`. Exact normalization
and exact finite counterexamples remain distinct from heuristic observations.
`UNKNOWN`, `UNSUPPORTED`, `TIMEOUT` and optional-dependency `UNAVAILABLE` retain
their types; none becomes mathematical equivalence or a false counterexample.
The witness is the CAS's actual exact witness, and no fabricated proof text is
attached.

The runtime uses the lesser of the remaining request deadline and one tool's
budget. A bounded background comparison returns an evidence list and never
mutates formula state. A timed-out result cannot attach later to another
revision. Worker startup/comparison use the remaining budget and reserve time
for cleanup; an exhausted budget returns typed timeout evidence immediately.
The shadow source limit is 2,048 characters per expression to bound translation
work before the isolated comparison. Background failures become typed unknown
evidence instead of aborting the ordinary runtime pipeline.

`eval/cas_transition_pairs.json` contains twelve authored pairs: six exact
identities and six drifts. The corpus declares synthetic authorship and agent
review rather than independent human validation. Tests also cover unsupported
notation/domain cases, all nonproof statuses, optional dependencies, idempotent
revision recording, actual runtime repair drift, and request/tool timeouts.
