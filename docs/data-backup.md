# Data Backup / 数据备份

TeXada data export and import uses JSON files. The Settings -> Data panel
supports full backups, history-only export/import, and history clearing.

TeXada 的数据导入导出使用 JSON 文件。设置 -> 数据 面板支持完整备份、仅历史
记录导入导出，以及清空历史记录。

## Full Backup / 完整备份

A full backup contains metadata, non-sensitive settings, user-defined presets,
and conversion history.

完整备份包含元数据、非敏感设置、用户自定义预设和转换历史。

```json
{
  "_meta": {
    "app": "TeXada",
    "schema_version": 1,
    "version": "0.2.5",
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
  ]
}
```

## History-Only Export / 仅历史记录导出

History export keeps the same metadata envelope but includes only the `history`
array.

历史记录导出保留相同的元数据外壳，但只包含 `history` 数组。

```json
{
  "_meta": {
    "app": "TeXada",
    "schema_version": 1,
    "version": "0.2.5",
    "exported_at": "2026-07-20T15:00:00.000000+00:00"
  },
  "history": [
    {
      "id": 1,
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
- Full backup import may import non-sensitive settings.
- `openai_api_key` is never exported and is ignored during import.
- Clearing history is irreversible and requires confirmation in the UI.

- UI 中的导入使用 `merge` 模式，并会跳过完全重复的历史记录。
- 历史记录按 `input_text`、`input_type`、`latex`、`created_at` 判断重复。
- 完整备份导入会合并用户自定义预设，并跳过内置预设 key。
- 完整备份导入可以导入非敏感设置。
- `openai_api_key` 永远不会被导出，导入时即使存在也会被忽略。
- 清空历史不可撤销，UI 会要求二次确认。
