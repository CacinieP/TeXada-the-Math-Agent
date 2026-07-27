"""Static frontend contracts that catch broken IDs and missing data controls."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "tauri-shell" / "src" / "index.html").read_text(encoding="utf-8")
JAVASCRIPT = (ROOT / "tauri-shell" / "src" / "main.js").read_text(encoding="utf-8")


def test_every_javascript_element_id_exists_once_in_html():
    html_ids = re.findall(r'\bid="([^"]+)"', HTML)
    referenced_ids = set(re.findall(r"getElementById\('([^']+)'\)", JAVASCRIPT))

    assert len(html_ids) == len(set(html_ids)), "index.html contains duplicate IDs"
    assert referenced_ids <= set(html_ids)


def test_history_run_log_and_data_portability_controls_are_wired():
    required_ids = {
        "history-view-switch",
        "history-results-panel",
        "run-logs-panel",
        "run-log-list",
        "run-log-search",
        "run-log-operation",
        "run-log-status",
        "btn-load-more-runs",
        "btn-export-backup",
        "btn-import-backup",
        "btn-export-history",
        "btn-import-history",
        "btn-clear-history",
        "btn-export-runs",
        "btn-import-runs",
        "btn-clear-runs",
        "btn-export-presets",
        "btn-import-presets",
        "data-import-input",
    }
    html_ids = set(re.findall(r'\bid="([^"]+)"', HTML))

    assert required_ids <= html_ids
    for endpoint in (
        "/api/export",
        "/api/import",
        "/api/history/export",
        "/api/history/import",
        "/api/runs/export",
        "/api/runs/import",
        "/api/shorthands/export",
        "/api/shorthands/import",
    ):
        assert endpoint in JAVASCRIPT

    assert "loadRunLogs({ append: true })" in JAVASCRIPT
    assert "apiRunLogDetail(run.run_id)" in JAVASCRIPT
    assert "typeof run.valid === 'boolean'" in JAVASCRIPT


def test_frontend_uses_the_same_placeholder_macro_as_backend_katex():
    assert "'\\\\placeholder': '\\\\square'" in JAVASCRIPT
    assert "macros: KATEX_MACROS" in JAVASCRIPT


def test_agent_trace_count_includes_runtime_guard_tool_observations():
    assert "stepToolNames(step)" in JAVASCRIPT
    assert "name !== 'operator_drift_guard'" in JAVASCRIPT


def test_ocr_and_completion_render_their_agent_traces():
    assert "function inlineAgentTrace(res)" in JAVASCRIPT
    assert JAVASCRIPT.count("${inlineAgentTrace(res)}") == 2
    assert 'intent: res.intent' in JAVASCRIPT
