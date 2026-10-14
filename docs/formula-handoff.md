# Single-formula handoff v1

TeXada Studio uses its server-configured Math endpoint to POST `/api/handoff/formula`.
The Math service must already use `MiniCPM-V-4.7-1B` for both configured roles;
checkpoint mismatch returns 409. Credentials stay in server configuration.
Enable the Studio experiment with `TEXADA_MATH_HANDOFF_ENABLED=1`; it is off by default.

The strict envelope contains a canonical UUID transfer id, full-document SHA256,
original formula SHA256, Unicode-codepoint source range (math body without dollar
delimiters), host formula id, Studio source revision, original LaTeX, checkpoint,
requested action/scope, bounded budget, `requires_review: true`, and empty evidence.
`repair` pairs with `syntax_repair`; `complete` with `completion_prefix`. Untrusted
URLs, paths, endpoint overrides, credentials, and nonempty evidence refs are rejected.
The Math service receives only the formula text and a claimed document hash. Studio
must recheck the whole document; the claimed hash is not independently observed.

Requested step/time/output-per-call budgets clamp existing configuration and are
recorded in the actual inference identity. Deterministic repair uses local tools
and records zero provider calls. Completion uses the same checkpoint, without a
fallback model. The deadline also covers identity setup, review registration and logging.
Registration is checked before and after its synchronous held-state write; an
abandoned pending review is invalidated and cannot be adopted. Cancellation
cannot interrupt already started synchronous CPU work, which is checked afterward.
The overall async deadline cannot undo an already sent HTTP request;
provider timeout is also bounded, and a late provider reply cannot register a review
or commit after cancellation. Token limits apply to each provider response.

The response returns the bound candidate, semantic diff, scope/CAS transition
evidence, actual inference fingerprint, and native pending ReviewDTO. Parent revision
may be null for an unchanged seed. Math revisions and Studio source revision are
independent. `review.transfer_context` displays actual effective budget and the
CONFIGURED whole-document evidence boundary. No automatic commit occurs.

Only explicit human adoption POSTs `/api/reviews/{id}/decision` with `accept` or
`reject` and the exact nested binding: `input_hash`, `parent_revision`,
`candidate_hash`, `current_revision`. Decisions use the held runtime FormulaState;
the client cannot manufacture a successful ledger. Native states are lowercase
`pending`, `accepted`, `rejected`. Invalid compilation/rendering remains a barrier
even after acceptance. Accepted history is written once; pending/rejected entries
are not silently adopted. Studio separately checks the source before and after
asynchronous proposal/decision calls and changes only the candidate buffer.

Canonical-envelope identity makes duplicate transfer ids execute once per Math
process. Conflicting ids return 409, cached final failures need a new explicit id,
completed records expire after 15 minutes, capacity is bounded to 128, and live
reviews have their own bounded TTL/store. This is a local single-worker protocol,
not a distributed durable queue: restarting Math discards pending reviews, so a
cached Studio transfer then fails closed and needs a new transfer. Studio persists
its proposal/decision intent and refuses endpoint changes and HTTP redirects.

`tests/test_formula_handoff.py` exercises actual local compile/render/review HTTP
flows, concurrency, mutation/candidate binding, cancellation and the real SDK with
a mocked transport. These synthetic tests establish integration behavior; they do
not certify model accuracy, Q4 performance, or packaged desktop interaction.
