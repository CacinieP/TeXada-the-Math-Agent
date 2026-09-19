# Baseline report — 2026-09-19

- Mode: **live**
- Model: `hf.co/openbmb/MiniCPM5-2B-GGUF:Q4_K_M`
- Golden entries exercised: 100

## Golden set

- Structural pass rate (anchor layer): 28/95 (29.5%)
- Entries with descriptive (non-machine-checkable) anchors: 3
- Compile layer: 65/100
- Render layer: 98/100
- Trace layer: 98/100

## Repair dataset (deterministic, brace-balance scope)

- Repair pass rate: 53/53 (100.0%)
- Latency p50 / p95: 5457 ms / 9361 ms

> Development-regression scope; not a general benchmark. See eval/known-gaps.md for measured boundaries.

## Errors

- 051: InternalServerError: Error code: 500 - {'error': {'message': 'llama-server returned invalid tool call arguments for "parse_tex": unexpected end of JSON input', 'type': 'api_error', 'param': None, 'code': None}}
- 053: InternalServerError: Error code: 500 - {'error': {'message': 'llama-server returned invalid tool call arguments for "parse_tex": unexpected end of JSON input', 'type': 'api_error', 'param': None, 'code': None}}
