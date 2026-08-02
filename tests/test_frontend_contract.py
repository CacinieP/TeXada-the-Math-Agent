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
        "btn-refresh-history",
        "btn-refresh-runs",
        "ocr-status",
        "inference-timeout-input",
        "api-timeout-input",
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


def test_primary_tabs_and_async_results_are_accessible():
    assert 'id="tab-bar" role="tablist"' in HTML
    assert HTML.count('role="tab"') == 6
    assert HTML.count('role="tabpanel"') == 6
    assert 'id="ocr-status" role="status" aria-live="polite"' in HTML
    assert 'id="history-list" role="status" aria-live="polite"' in HTML
    assert 'id="run-log-list" role="status" aria-live="polite"' in HTML
    assert "item.setAttribute('aria-selected', String(selected))" in JAVASCRIPT
    assert "panel.setAttribute('aria-hidden', String(!selected))" in JAVASCRIPT
    assert "if (e.key === 'ArrowRight')" in JAVASCRIPT


def test_slow_operations_show_progress_and_recoverable_load_errors():
    for message_key in (
        "ocr.processing",
        "ocr.failed",
        "history.loading",
        "history.loadError",
        "runs.loading",
        "runs.loadError",
    ):
        assert f"'{message_key}'" in JAVASCRIPT

    assert "ocrElapsedTimer = setInterval(update, 1000)" in JAVASCRIPT
    assert "els.historyList.setAttribute('aria-busy', 'true')" in JAVASCRIPT
    assert "els.runLogList.setAttribute('aria-busy', 'true')" in JAVASCRIPT
    assert "if (!ready && isDesktop) waitForBackendStartup()" in JAVASCRIPT


def test_bundled_backend_startup_wait_covers_slow_frozen_imports():
    assert "let backendStartupPromise = null" in JAVASCRIPT
    assert "if (backendStartupPromise) return backendStartupPromise" in JAVASCRIPT
    assert "attempt < 80" in JAVASCRIPT
    assert "window.location.protocol === 'tauri:'" in JAVASCRIPT
    assert "if (!ready && isDesktop) waitForBackendStartup()" in JAVASCRIPT
    assert "'status.starting': 'API 启动中…'" in JAVASCRIPT
    assert "checkBackend({ starting: true })" in JAVASCRIPT
    assert "setStatus(false, t('status.noApi'))" in JAVASCRIPT


def test_natural_language_input_is_never_prefilled_from_clipboard():
    assert "pasteFromClipboard()" not in JAVASCRIPT
    assert "navigator.clipboard.readText()" not in JAVASCRIPT
    assert "invoke('read_clipboard')" not in JAVASCRIPT
    assert "clip.length > 0 && clip.length < 500" not in JAVASCRIPT


def test_frozen_sidecar_collects_the_native_katex_runtime():
    build_script = (
        ROOT / "scripts" / "build-backend-sidecar.py"
    ).read_text(encoding="utf-8")

    assert '"--collect-all"' in build_script
    assert '"py_mini_racer"' in build_script


def test_signed_macos_sidecar_allows_the_v8_jit_runtime():
    build_script = (
        ROOT / "scripts" / "build-backend-sidecar.py"
    ).read_text(encoding="utf-8")
    entitlements = (
        ROOT / "scripts" / "macos-sidecar-entitlements.plist"
    ).read_text(encoding="utf-8")
    release_workflow = (
        ROOT / ".github" / "workflows" / "release-desktop.yml"
    ).read_text(encoding="utf-8")

    assert "MACOS_SIDECAR_ENTITLEMENTS" in build_script
    assert "candidate == path / \"texada-backend\"" in build_script
    assert "com.apple.security.cs.allow-jit" in entitlements
    assert "com.apple.security.cs.allow-unsigned-executable-memory" in entitlements
    assert "Verify macOS sidecar JIT entitlements" in release_workflow
    assert "com.apple.security.cs.allow-jit" in release_workflow
    assert "com.apple.security.cs.allow-unsigned-executable-memory" in release_workflow
    assert "Smoke test signed macOS KaTeX sidecar" in release_workflow
    assert '"parser_backend"] == "katex-0.17.0-v8"' in release_workflow


def test_frontend_uses_the_same_placeholder_macro_as_backend_katex():
    assert "'\\\\placeholder': '\\\\square'" in JAVASCRIPT
    assert "macros: KATEX_MACROS" in JAVASCRIPT


def test_shorthand_grid_keeps_katex_previews_inside_the_window():
    stylesheet = (ROOT / "tauri-shell" / "src" / "style.css").read_text(
        encoding="utf-8"
    )

    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in stylesheet
    assert re.search(r"\.shorthand-card\s*\{[^}]*min-width:\s*0;", stylesheet, re.S)
    assert re.search(
        r"\.shorthand-render\s*\{[^}]*overflow-x:\s*auto;", stylesheet, re.S
    )
    assert re.search(
        r"\.shorthand-render \.katex\s*\{[^}]*margin-inline:\s*auto;",
        stylesheet,
        re.S,
    )


def test_agent_trace_count_includes_runtime_guard_tool_observations():
    assert "stepToolNames(step)" in JAVASCRIPT
    assert "name !== 'operator_drift_guard'" in JAVASCRIPT


def test_ocr_and_completion_render_their_agent_traces():
    assert "function inlineAgentTrace(res)" in JAVASCRIPT
    assert JAVASCRIPT.count("${inlineAgentTrace(res)}") == 2
    assert 'intent: res.intent' in JAVASCRIPT


def test_agent_trace_origin_cannot_overlap_tool_badges():
    stylesheet = (ROOT / "tauri-shell" / "src" / "style.css").read_text(
        encoding="utf-8"
    )

    assert ".agent-step-origin" in stylesheet
    assert "text-overflow: ellipsis" in stylesheet
    assert '"index origin status"' in stylesheet
    assert '". tools ."' in stylesheet
    assert 'class="agent-step-origin" title=' in JAVASCRIPT
