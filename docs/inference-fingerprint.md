# Inference Fingerprints

This implements the production logging portion of
[issue #8](https://github.com/CacinieP/TeXada-the-Math-Agent/issues/8).
Every newly recorded conversion, Agent, OCR, completion, and validation run
contains an `inference_fingerprint`. The same envelope appears in run summaries,
details, run exports, and full backups. It is retained through imports.

## Stable identity and observed attempts

`schema_version` is `1`. New records have `status: RECORDED` and two separate
parts:

- `identity` captures the configuration at request entry: application version,
  installed client-library versions, backend, sanitized endpoint, configured
  text/vision roles, generation settings, request/tool budgets, candidate-first
  selection, and OCR preprocessing. It includes hashes of the fixed prompt
  manifest and canonical tool definitions. A supplied evaluation dataset version
  and content hash are explicitly configured values.
- `calls` records each attempted provider invocation, including failed attempts
  and retries. Each item records its purpose, requested model, effective decoding
  options, hashes of the actual system instructions, selected fixed few-shot
  examples and supplied tools, effective call timeout, outcome, and exception
  type. A compatibility retry that removes tools has a separate attempt with
  `tool_schema_sha256: null`.

`identity_sha256` hashes canonical JSON of `identity` only. Dynamic remaining
timeouts, outcomes, and provider response metadata stay in `calls`; they cannot
make identical configured experiments acquire random stable identities.
Per-call hashes show the actual surface when retries or task-specific prompts
differ from the fixed manifest.

A deterministic candidate shortcut or validation run has `calls: []`. Configured
model names still describe the selected environment; they do not claim that a
model was invoked. Failed provider attempts remain recorded even when no model
response exists. An in-flight attempt is marked `pending` if its response has
not yet been observed when a snapshot is taken.

## Evidence boundaries

Provider response `model` and `system_fingerprint` are `REPORTED`, never verified
weight identities. Missing response fields are `NOT_CHECKED` with a reason.
The configured gateway endpoint identifies the route selected by TeXada; it
does not establish the underlying model provider.

The application currently cannot inspect the actual served weight hash,
checkpoint revision, quantization, multimodal projector hash, server runtime
build, or chat-template revision. Each has a distinct `NOT_CHECKED` field.
This applies to both cloud APIs and externally managed local Q4 servers.
A Q4-looking alias, loopback endpoint, or provider fingerprint does not establish
those facts. Future integration with controlled download/process evidence must
add its own evidence contract rather than accepting user-entered hashes as
verified. The application build revision is likewise `NOT_CHECKED` until a build
identity is embedded; the application version and client-package versions remain
observable.

Interactive API runs have no dataset identity and explicitly record that limit.
Evaluation callers may supply a dataset version and a SHA256 of fixture file
bytes. Those values are `CONFIGURED` and are separate from observed model
artifacts.

## Collection and privacy

At request entry, the API freezes references to the configuration, router, shared
model, runtime, history store, and run-log store. A settings update or backup
import during inference affects subsequent requests, not the identity or model
used by an already-running request.
Route matching uses the ASGI path relative to its root path, so mounted apps and
proxy prefixes receive the same collection context as an unmounted server.

A request-local `ContextVar` holds a collector. `asyncio.to_thread` copies that
context, and the copied context references the same collector object. A lock
protects attempts and snapshots. Concurrent requests using one model instance
therefore retain separate collectors. Collection wraps the real SDK call, not
only a result schema or a generated config snapshot.

Fingerprint serialization uses explicit fields. It does not include API keys,
authorization headers, raw SDK kwargs, user messages, image bytes, provider
response bodies, or exception messages. Endpoint userinfo, query, and fragment
are discarded before storage and hashing. System instructions and fixed examples
are stored as hashes, not prompt text. Existing run-log input and diagnostic
fields keep their existing behavior; this change does not remove that data.

## Persistence and compatibility

SQLite initialization idempotently adds `inference_fingerprint_json` to existing
run databases. Old rows are not backfilled from today's configuration. Missing,
empty, malformed, or non-object stored fingerprint JSON produces an explicit
`NOT_CHECKED` envelope with `reason: legacy_record`. Old backups without the new
field import with the same legacy envelope.

New fingerprint imports validate the versioned contract, reject extra fields,
reject endpoint credentials/query strings, and verify the identity digest.
Run-list responses retain fingerprints while omitting the execution trace.
The outer backup format stays at schema version 2; the optional fingerprint
envelope carries its own version.

All fourteen existing run-log construction paths use one collection hook:
conversion, Agent and completion success/RuntimeError/other-error branches;
OCR additionally records upload rejection; validation records its result.
Request-schema validation, forbidden origins, and invalid render-mode errors
that previously did not create a RunLog remain outside this logging boundary.

## Evaluation usage

Create one collector per evaluated input, including all candidate, Planner,
vision, retry, and fallback calls for that input:

```python
from texada.core.inference_fingerprint import build_inference_identity, collect_inference

identity = build_inference_identity(
    config,
    tool_schemas=runtime.tools.schemas,
    dataset_version="golden-v1",
    dataset_sha256=fixture_bytes_sha256,
)
with collect_inference(identity) as collector:
    result = await runtime.run(user_input)
fingerprint = collector.snapshot()
```

No provider request is issued by identity construction or collection setup.
Focused tests use fake HTTP transports and verify stable identity, all logged
API branches, real SDK attempts, tool-removal retries, failed attempts,
deterministic paths, concurrent/thread contexts, settings-update races,
SQLite migration, and import/export compatibility.
