"""SDK wiring for the actual desktop insert and window restoration commands."""

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
SOURCE = (ROOT / "tauri-shell/src-tauri/src/main.rs").read_text(encoding="utf-8")
INSERT = SOURCE.split("async fn insert_text_at_cursor(", 1)[1].split(
    "\n#[tauri::command]", 1,
)[0]
RESTORE = SOURCE.split("fn show_focused_window(", 1)[1].split(
    "\n#[tauri::command]", 1,
)[0]
SHOW_COMMAND = SOURCE.split("fn show_window(", 1)[1].split("fn show_focused_window(", 1)[0]
TOGGLE = SOURCE.split("fn toggle_window(", 1)[1].split("fn position_window_near_cursor(", 1)[0]


def test_insert_command_hides_window_then_macos_application_before_paste():
    operations = [
        ".write_text(text)", "window.hide()", "app.hide()",
        "tokio::time::sleep(Duration::from_millis(160)).await", "trigger_system_paste()",
    ]
    positions = [INSERT.index(operation) for operation in operations]
    assert positions == sorted(positions)
    assert re.search(r'#\[cfg\(target_os = "macos"\)\]\s*\{\s*app.hide\(\)', INSERT)


def test_both_hide_failures_are_propagated_before_paste_is_attempted():
    for operation, stage in (
        (r"window\.hide\(\)", "window_hide"),
        (r"app\.hide\(\)", "application_hide"),
    ):
        assert re.search(
            operation + rf'\.map_err\(\|error\| \{{.*?stage={stage}.*?\}}\)\?;',
            INSERT, re.S,
        )
    assert "let _ = window.hide()" not in INSERT
    assert "let _ = app.hide()" not in INSERT


def test_restore_shows_macos_application_then_window_and_focuses_it():
    compact = re.sub(r"\s+", "", RESTORE)
    operations = ["_app.show()", "window.show()", "window.set_focus()"]
    positions = [compact.index(operation) for operation in operations]
    assert positions == sorted(positions)
    assert '#[cfg(target_os="macos")]_app.show()' in compact
    assert compact.count("map_err(") == 3


def test_command_and_tray_shortcut_toggle_use_the_shared_restore_path():
    assert "show_focused_window(&app, &window)" in SHOW_COMMAND
    assert "-> Result<(), String>" in SHOW_COMMAND
    assert "show_focused_window(app, &window)" in TOGGLE
    assert "window.is_visible()" in TOGGLE
    assert "window.show()" not in TOGGLE
    assert "window.set_focus()" not in TOGGLE
    assert SOURCE.count("toggle_window(app);") == 3


def test_insert_diagnostics_only_record_stages_and_booleans():
    logs = [re.sub(r"\s+", " ", call.strip())
            for call in re.findall(r"eprintln!\((.*?)\);", INSERT, re.S)]
    assert logs == [
        '"lifecycle insert_started has_text={}", !text.is_empty()',
        '"lifecycle insert_failed stage=clipboard_write"',
        '"lifecycle insert_clipboard_written"',
        '"lifecycle insert_failed stage=window_hide"',
        '"lifecycle insert_window_hidden"',
        '"lifecycle insert_failed stage=application_hide"',
        '"lifecycle insert_application_hidden"',
        '"lifecycle insert_paste_requested"',
        '"lifecycle insert_paste_finished success={}", result.is_ok()',
    ]


def test_actual_paste_command_result_reaches_the_command_caller():
    assert re.search(
        r"let result = trigger_system_paste\(\);.*?result.is_ok\(\)\);\s*result\s*\}",
        INSERT, re.S,
    )
    assert re.search(r"tauri::generate_handler!\[.*?insert_text_at_cursor,.*?show_window,",
                     SOURCE, re.S)
