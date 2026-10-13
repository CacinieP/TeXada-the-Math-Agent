# Revision-bound human adoption

OCR candidates always require review. High-risk role changes, denied or uncertain
mutation scope, unreliable role differences and CAS counterexamples also block
automatic adoption. Low-risk NL generation retains its existing automatic path.
Trusted integrations may request review with `requires_review=True`; model tool
arguments cannot lower that requirement. The deterministic candidate shortcut
uses the same gate.

The desktop result presents the original source image or an explicit missing
image state, source text, parent formula, candidate LaTeX and render, role changes
and reliable source positions. Original text is written with `textContent`.
Position ranges refer to the exact parent revision, using KaTeX UTF-16 offsets;
unsupported mappings report `unavailable` instead of an estimated position.
Raw and canonical roots must align individually before a location is shown;
spacing and flattened groups cannot redirect a highlight to another fraction.
Compile, render, CAS, human adoption and unverified user intent have separate
states. Agent confidence is no longer set to 1 merely because syntax is valid.

`PendingReviewStore` holds the original in-memory `FormulaState`; it never
reconstructs authority from a client ledger or a backup. Default retention is ten
minutes, 64 review records and 32 MiB of source images. Sources are served only
through a random review ID, with no-cache/nosniff headers and a loopback image CSP.
Unsupported or invalid image bytes are not exposed as an image, and the missing
source remains explicit. Raw image bytes do not enter fingerprints or run logs.
The held state is excluded from dataclass and API serialization.

`GET /api/reviews/{id}` returns the current review. A decision is posted to
`/api/reviews/{id}/decision` with all four original binding fields:

```json
{
  "decision": "accept",
  "input_hash": "<original source SHA-256>",
  "parent_revision": 1,
  "candidate_hash": "<candidate LaTeX SHA-256>",
  "current_revision": 2
}
```

The response also contains the same four fields under `binding`. A decision may
use `{ "decision": "accept", "binding": { ... } }`; conflicting flat and nested
bindings are rejected with 422. A candidate whose source is still its first
math-runtime revision has `parent_revision: null`, independent of any consumer
document's version.

The server checks each field, then checks the actual held state and source again
under the decision lock. Expiration/eviction returns 410; a changed source,
revision, candidate, opposite prior decision or failed commit barrier returns
409. Repeated identical decisions are idempotent. An acceptance explicitly
authorizes scope risk while retaining the original scope verdict. It still
requires successful compile and render evidence for the exact candidate.
Rejection leaves the candidate uncommitted. Pending/rejected results do not
enter adopted history; acceptance adds history once.

Editing the NL/completion source or selecting another image disables the old
confirmation in the UI. New requests, language changes and zoom changes cannot
restore a stale binding or permit a late decision response to adopt a new result.
Tauri retains revision, committed and review metadata rather than dropping it.

Trusted handoff integration uses
`run_candidate('repair', original, original, requires_review=True,
input_source_hash=...)`. This grants structural preservation to candidate
proposals and syntax repair only to the actual deterministic tool result; it
does not grant broad NL synthesis permission. This repair route runs the shared
host compile/repair/recompile/render pipeline directly, starting from the source
formula rather than first applying model-output alias normalization. Common missing closing
braces are repaired without a planner or backend request; inference fingerprints
explicitly contain `calls: []`. Unrepairable input remains uncommitted rather
than invoking an additional model or widening the grant. It then calls
`app.state.register_review_result(result, source_text=original,
input_hash=...)`, and uses the same review endpoints. Consumer document revision
and math-runtime parent/current revisions are separate identities.

Validation covers source/candidate mismatch, TTL and capacity eviction,
concurrent identical/opposite decisions, stale revision during commit, missing
source, compile/render failure, mandatory OCR/forced deterministic review,
low-risk NL automatic adoption and actual runtime-to-HTTP accept/reject flows.
Node DOM tests cover source safety, controlled image URLs, bindings, positions,
editing locks, reconstructed panels, 409/410 and late responses. Local Rust tests
exercise legacy and review response serialization. Packaged desktop visual and
device acceptance remain separate from these checks.
