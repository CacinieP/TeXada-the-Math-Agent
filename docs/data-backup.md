# Data Backup / 数据备份

TeXada data export and import uses JSON files. The Settings -> Data panel
supports full backups plus independent history, run-log, and custom-preset
export/import.

TeXada 的数据导入导出使用 JSON 文件。设置 -> 数据 面板支持完整备份，也支持
历史、运行日志、自定义预设三类数据的独立导入导出。

## Full Backup / 完整备份

A full backup contains metadata, non-sensitive settings, user-defined presets,
conversion history, and request-level run logs.

完整备份包含元数据、非敏感设置、用户自定义预设、转换历史和请求级运行日志。

```json
{
  "_meta": {
    "app": "TeXada",
    "schema_version": 2,
    "version": "0.3.0",
    "exported_at": "2026-07-20T15:00:00.000000+00:00"
  },
  "settings": {
    "backend": "ollama",
    "ollama_host": "http://localhost:11434",
    "model_name": "hf.co/openbmb/MiniCPM5-1B-GGUF:Q4_K_M",
    "vision_model_name": "openbmb/minicpm-v4.6:latest",
    "openai_base_url": "",
    "openai_model_name": "",
    "openai_vision_model_name": "",
    "temperature": 0.1,
    "max_tokens": 2048,
    "default_render_mode": "katex",
    "delimiter": "$$",
    "ui_language": "zh",
    "ui_zoom": 1.0,
    "inference_timeout_seconds": 45.0,
    "api_request_timeout_seconds": 120.0
  },
  "shorthands": {
    "my-formula": "\\frac{a}{b}"
  },
  "history": [
    {
      "id": 1,
      "run_id": "99bb7ea04f0b4b2ca2a9670cdf317768",
      "input_text": "integral of x squared",
      "input_type": "nl",
      "latex": "\\int x^2\\,dx",
      "intent": "integral",
      "source": "model",
      "render_mode": "katex",
      "valid": true,
      "latency_ms": 123.4,
      "tokens_used": 0,
      "starred": false,
      "created_at": "2026-07-20 22:30:00"
    }
  ],
  "run_logs": [
    {
      "run_id": "99bb7ea04f0b4b2ca2a9670cdf317768",
      "operation": "agent",
      "input_type": "nl",
      "input_text": "integral of x squared",
      "input_bytes": 0,
      "input_mime": "",
      "model_role": "planner",
      "model_name": "hf.co/openbmb/MiniCPM5-1B-GGUF:Q4_K_M",
      "backend": "ollama",
      "status": "success",
      "status_code": 200,
      "output_latex": "\\int x^2\\,dx",
      "valid": true,
      "latency_ms": 123.4,
      "tokens_used": 64,
      "stop_reason": "planner_final",
      "tool_call_count": 2,
      "tool_names": ["parse_tex", "render_math"],
      "trace": [{"step": 1, "tool_calls": [], "observations": []}],
      "error_message": "",
      "created_at": "2026-07-20 22:30:00"
    }
  ]
}
```

`run_id` links a successful result in `history` to its execution record in
`run_logs`. Failed executions have a run-log row but no result-history row.

`run_id` 将 `history` 中的成功结果与 `run_logs` 中的执行详情关联起来。失败
执行只记录运行日志，不会伪造一条结果历史。

## History-Only Export / 仅历史记录导出

History export keeps the same metadata envelope but includes only the `history`
array.

历史记录导出保留相同的元数据外壳，但只包含 `history` 数组。

```json
{
  "_meta": {
    "app": "TeXada",
    "schema_version": 2,
    "version": "0.3.0",
    "exported_at": "2026-07-20T15:00:00.000000+00:00"
  },
  "history": [
    {
      "id": 1,
      "run_id": "",
      "input_text": "sum from i equals 1 to n",
      "input_type": "nl",
      "latex": "\\sum_{i=1}^{n}",
      "intent": "summation",
      "source": "model",
      "render_mode": "katex",
      "valid": true,
      "latency_ms": 90.2,
      "tokens_used": 0,
      "starred": false,
      "created_at": "2026-07-20 22:31:00"
    }
  ]
}
```

## Run Logs / 运行日志

The run ledger is stored separately in `~/.texada/runs.db`. It records both
success and failure for `agent`, `convert`, `ocr`, `completion`, and
`validate`. The UI loads summary rows in pages and fetches the full Agent trace
only when a row is expanded. It can filter by operation or status and displays
request success separately from formula validity.

运行账本独立保存在 `~/.texada/runs.db`。`agent`、`convert`、`ocr`、
`completion`、`validate` 的成功和失败都会记录。界面分页加载摘要，只有展开
某一条记录时才读取完整 Agent 轨迹；可按运行类型与状态筛选，并分别显示请求
是否成功与公式是否有效。

- OCR logs store filename, MIME type, and byte count, not original image bytes.
- API keys are never stored in run logs or exported backups.
- Agent traces can contain user input, generated LaTeX, and tool observations;
  exported log files should therefore be treated as user documents.
- Retention is unlimited by default. Set `TEXADA_RUN_LOG_MAX_DAYS` and/or
  `TEXADA_RUN_LOG_MAX_ITEMS` to positive integers to enable automatic cleanup.

- OCR 日志只保存文件名、MIME 和字节数，不保存图片原始字节。
- API Key 不会写入运行日志，也不会进入备份。
- Agent trace 可能包含用户输入、生成的 LaTeX 与工具 Observation；导出的日志
  文件应按用户文档保护。
- 默认不限天数、不限条数，完整保留每次运行。可将
  `TEXADA_RUN_LOG_MAX_DAYS` 和/或 `TEXADA_RUN_LOG_MAX_ITEMS` 配置为正整数，
  启用自动清理。

Run-log export uses `{ "_meta": ..., "run_logs": [...] }`. Import deduplicates
by the globally unique `run_id`. `replace` mode clears the existing ledger
before importing; the desktop UI defaults to safer `merge`.

运行日志导出格式为 `{ "_meta": ..., "run_logs": [...] }`，导入按全局唯一
`run_id` 去重。`replace` 会先清空现有日志；桌面 UI 默认使用更安全的 `merge`。

## Presets / 预设

Custom preset export uses `{ "_meta": ..., "presets": { ... } }`. Import also
accepts the legacy `shorthands` key. Built-in presets are never exported,
overwritten, or removed. `replace` replaces only user-owned presets.

自定义预设导出格式为 `{ "_meta": ..., "presets": { ... } }`，导入也兼容旧
`shorthands` 字段。内置预设不会被导出、覆盖或删除；`replace` 只替换用户预设。

## Minimal History Import / 最小历史导入

History import also accepts a plain JSON array. `input_text` and `latex` are the
only required fields; other fields use safe defaults.

历史导入也接受普通 JSON 数组。`input_text` 和 `latex` 是必填字段，其他字段会
使用默认值。

```json
[
  {
    "input_text": "integral",
    "input_type": "nl",
    "latex": "\\int x\\,dx"
  }
]
```

Default values:

默认值：

| Field | Default |
|-------|---------|
| `run_id` | empty string for legacy history |
| `input_type` | `nl` |
| `intent` | empty string |
| `source` | `model` |
| `render_mode` | `katex` |
| `valid` | `true` |
| `latency_ms` | `0.0` |
| `tokens_used` | `0` |
| `starred` | `false` |
| `created_at` | current SQLite timestamp |

## Import Rules / 导入规则

- Imports use `merge` mode from the UI and skip exact duplicate history records.
- History duplicates are detected by `input_text`, `input_type`, `latex`, and
  `created_at`.
- Full backup import merges user-defined presets and skips built-in preset keys.
- Run logs are deduplicated by `run_id`; history and logs can be imported independently.
- Schema v1 backups remain importable; missing `run_logs` is treated as an empty list.
- Full backup import may import non-sensitive settings.
- `openai_api_key` is never exported and is ignored during import.
- Clearing history is irreversible and requires confirmation in the UI.

- UI 中的导入使用 `merge` 模式，并会跳过完全重复的历史记录。
- 历史记录按 `input_text`、`input_type`、`latex`、`created_at` 判断重复。
- 完整备份导入会合并用户自定义预设，并跳过内置预设 key。
- 运行日志按 `run_id` 去重；历史与日志可以独立导入。
- schema v1 备份仍可导入；没有 `run_logs` 时按空列表处理。
- 完整备份导入可以导入非敏感设置。
- `openai_api_key` 永远不会被导出，导入时即使存在也会被忽略。
- 清空历史不可撤销，UI 会要求二次确认。
