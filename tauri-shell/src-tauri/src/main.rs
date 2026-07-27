// TeXada Tauri Shell — Floating input method style UI
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::env;
use std::net::IpAddr;
use std::process::Command;
use std::sync::Mutex;
use std::time::Duration;

use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder},
    Manager, RunEvent,
};
use tauri_plugin_clipboard_manager::ClipboardExt;
use tauri_plugin_global_shortcut::ShortcutState;
use tauri_plugin_shell::{
    process::{CommandChild, CommandEvent},
    ShellExt,
};

#[cfg(target_os = "macos")]
const SHORTCUT: &str = "Option+Command+T";
#[cfg(not(target_os = "macos"))]
const SHORTCUT: &str = "Ctrl+Alt+T";

const DEFAULT_REQUEST_TIMEOUT_SECS: u64 = 120;
const BACKEND_STARTUP_PROBE_MS: u64 = 900;
const BUNDLED_BACKEND_NAME: &str = "texada-backend";

#[derive(Default)]
struct BackendSidecarState(Mutex<Option<CommandChild>>);

fn normalize_api_base(value: String) -> String {
    value.trim().trim_end_matches('/').to_string()
}

fn configured_api_base() -> String {
    if let Ok(base) = env::var("TEXADA_API_BASE") {
        let normalized = normalize_api_base(base);
        if !normalized.is_empty() {
            return normalized;
        }
    }

    let host = env::var("TEXADA_API_HOST")
        .unwrap_or_else(|_| "127.0.0.1".to_string())
        .trim()
        .to_string();
    let port = env::var("TEXADA_API_PORT")
        .ok()
        .and_then(|value| value.parse::<u16>().ok())
        .unwrap_or(18732);

    format!("http://{}:{}", host, port)
}

fn api_url(path: &str) -> Result<String, String> {
    let trimmed = path.trim();
    if !trimmed.starts_with("/api/") || trimmed.starts_with("//") || trimmed.contains("://") {
        return Err("Invalid API path".to_string());
    }
    Ok(format!("{}{}", configured_api_base(), trimmed))
}

fn request_timeout() -> Duration {
    let secs = env::var("TEXADA_API_TIMEOUT_SECS")
        .ok()
        .and_then(|value| value.parse::<u64>().ok())
        .filter(|value| *value > 0)
        .unwrap_or(DEFAULT_REQUEST_TIMEOUT_SECS);
    Duration::from_secs(secs)
}

fn http_client() -> Result<reqwest::Client, String> {
    reqwest::Client::builder()
        .timeout(request_timeout())
        .build()
        .map_err(|e| format!("HTTP client setup failed: {}", e))
}

fn startup_probe_client() -> Result<reqwest::Client, String> {
    reqwest::Client::builder()
        .timeout(Duration::from_millis(BACKEND_STARTUP_PROBE_MS))
        .build()
        .map_err(|e| format!("HTTP client setup failed: {}", e))
}

fn env_flag_enabled(name: &str) -> bool {
    env::var(name)
        .map(|value| {
            matches!(
                value.trim().to_ascii_lowercase().as_str(),
                "1" | "true" | "yes" | "on"
            )
        })
        .unwrap_or(false)
}

fn is_local_api_host(host: &str) -> bool {
    if host.eq_ignore_ascii_case("localhost") {
        return true;
    }
    host.parse::<IpAddr>()
        .map(|addr| addr.is_loopback() || addr.is_unspecified())
        .unwrap_or(false)
}

fn explicit_api_base_is_remote() -> bool {
    let Ok(value) = env::var("TEXADA_API_BASE") else {
        return false;
    };
    let normalized = normalize_api_base(value);
    if normalized.is_empty() {
        return false;
    }
    let Ok(url) = reqwest::Url::parse(&normalized) else {
        return true;
    };
    url.host_str()
        .map(|host| !is_local_api_host(host))
        .unwrap_or(true)
}

fn should_start_bundled_backend() -> bool {
    !env_flag_enabled("TEXADA_DISABLE_BUNDLED_BACKEND") && !explicit_api_base_is_remote()
}

async fn api_runtime_reachable() -> bool {
    let Ok(client) = startup_probe_client() else {
        return false;
    };
    let Ok(url) = api_url("/api/runtime") else {
        return false;
    };
    client
        .get(url)
        .send()
        .await
        .map(|response| response.status().is_success())
        .unwrap_or(false)
}

fn http_error(status: reqwest::StatusCode, body: &str) -> String {
    if let Ok(json) = serde_json::from_str::<serde_json::Value>(body) {
        if let Some(detail) = json.get("detail").and_then(|value| value.as_str()) {
            return format!("API error {}: {}", status, detail);
        }
    }
    format!("API error {}", status)
}

#[derive(serde::Serialize)]
struct ConvertPayload {
    text: String,
    render_mode: String,
}

#[derive(serde::Deserialize, serde::Serialize)]
struct ConvertResponse {
    run_id: String,
    latex: String,
    katex_html: Option<String>,
    copy_text: String,
    valid: bool,
    source: String,
    intent: String,
    confidence: f64,
    latency_ms: f64,
    tokens_used: usize,
    agent_trace: Option<Vec<serde_json::Value>>,
    semantic_document: Option<serde_json::Value>,
    semantic_diff: Option<serde_json::Value>,
    stop_reason: Option<String>,
}

#[tauri::command]
fn get_api_base() -> String {
    configured_api_base()
}

#[tauri::command]
async fn api_json(
    method: String,
    path: String,
    body: Option<serde_json::Value>,
) -> Result<serde_json::Value, String> {
    let url = api_url(&path)?;
    let client = http_client()?;
    let request = match method.to_uppercase().as_str() {
        "GET" => client.get(url),
        "POST" => client.post(url),
        "DELETE" => client.delete(url),
        _ => return Err("Unsupported API method".to_string()),
    };
    let request = match body {
        Some(payload) => request.json(&payload),
        None => request,
    };
    let res = request
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;
    let status = res.status();
    let text = res
        .text()
        .await
        .map_err(|e| format!("Response read error: {}", e))?;
    if !status.is_success() {
        return Err(http_error(status, &text));
    }
    if text.trim().is_empty() {
        return Ok(serde_json::json!({}));
    }
    serde_json::from_str::<serde_json::Value>(&text).map_err(|e| format!("Parse error: {}", e))
}

async fn post_text(
    endpoint: &str,
    text: String,
    render_mode: Option<String>,
) -> Result<ConvertResponse, String> {
    let client = http_client()?;
    let payload = ConvertPayload {
        text,
        render_mode: render_mode.unwrap_or_else(|| "katex".to_string()),
    };
    let res = client
        .post(api_url(endpoint)?)
        .json(&payload)
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;

    if !res.status().is_success() {
        let status = res.status();
        let body = res.text().await.unwrap_or_default();
        return Err(http_error(status, &body));
    }

    res.json::<ConvertResponse>()
        .await
        .map_err(|e| format!("Parse error: {}", e))
}

#[tauri::command]
async fn convert_text(
    text: String,
    render_mode: Option<String>,
) -> Result<ConvertResponse, String> {
    post_text("/api/agent", text, render_mode).await
}

#[tauri::command]
async fn complete_latex(
    text: String,
    render_mode: Option<String>,
) -> Result<ConvertResponse, String> {
    post_text("/api/complete", text, render_mode).await
}

#[tauri::command]
async fn convert_image(
    image: Vec<u8>,
    render_mode: Option<String>,
) -> Result<ConvertResponse, String> {
    let render_mode = match render_mode.as_deref() {
        Some("latex") => "latex",
        _ => "katex",
    };
    let client = http_client()?;
    let part = reqwest::multipart::Part::bytes(image)
        .file_name("upload.png")
        .mime_str("image/png")
        .map_err(|e| format!("Image payload error: {}", e))?;
    let form = reqwest::multipart::Form::new().part("image", part);

    let res = client
        .post(api_url(&format!("/api/ocr?render_mode={}", render_mode))?)
        .multipart(form)
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;

    if !res.status().is_success() {
        let status = res.status();
        let body = res.text().await.unwrap_or_default();
        return Err(http_error(status, &body));
    }

    res.json::<ConvertResponse>()
        .await
        .map_err(|e| format!("Parse error: {}", e))
}

#[tauri::command]
async fn get_status() -> Result<serde_json::Value, String> {
    let client = http_client()?;
    let res = client
        .get(api_url("/api/status")?)
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;

    res.json::<serde_json::Value>()
        .await
        .map_err(|e| format!("Parse error: {}", e))
}

#[tauri::command]
fn read_clipboard(app: tauri::AppHandle) -> Result<String, String> {
    app.clipboard()
        .read_text()
        .map_err(|e| format!("Clipboard read failed: {}", e))
}

#[tauri::command]
fn write_clipboard(app: tauri::AppHandle, text: String) -> Result<(), String> {
    app.clipboard()
        .write_text(text)
        .map_err(|e| format!("Clipboard write failed: {}", e))
}

#[cfg(target_os = "macos")]
fn trigger_system_paste() -> Result<(), String> {
    let status = Command::new("osascript")
        .arg("-e")
        .arg("tell application \"System Events\" to keystroke \"v\" using command down")
        .status()
        .map_err(|e| format!("Paste automation failed: {}", e))?;
    if status.success() {
        Ok(())
    } else {
        Err("Paste automation failed; grant TeXada Accessibility permission".to_string())
    }
}

#[cfg(target_os = "windows")]
fn trigger_system_paste() -> Result<(), String> {
    let status = Command::new("powershell")
        .args([
            "-NoProfile",
            "-STA",
            "-WindowStyle",
            "Hidden",
            "-Command",
            "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait('^v')",
        ])
        .status()
        .map_err(|e| format!("Paste automation failed: {}", e))?;
    if status.success() {
        Ok(())
    } else {
        Err("Paste automation failed".to_string())
    }
}

#[cfg(not(any(target_os = "macos", target_os = "windows")))]
fn trigger_system_paste() -> Result<(), String> {
    Err("Insert-at-cursor is only implemented for macOS and Windows".to_string())
}

#[tauri::command]
async fn insert_text_at_cursor(
    app: tauri::AppHandle,
    window: tauri::WebviewWindow,
    text: String,
) -> Result<(), String> {
    app.clipboard()
        .write_text(text)
        .map_err(|e| format!("Clipboard write failed: {}", e))?;
    let _ = window.hide();
    tokio::time::sleep(Duration::from_millis(160)).await;
    trigger_system_paste()
}

#[tauri::command]
fn hide_window(window: tauri::WebviewWindow) {
    let _ = window.hide();
}

#[tauri::command]
fn show_window(window: tauri::WebviewWindow) {
    let _ = window.show();
    let _ = window.set_focus();
}

#[tauri::command]
fn start_dragging(window: tauri::WebviewWindow) -> Result<(), String> {
    window
        .start_dragging()
        .map_err(|e| format!("Start dragging failed: {}", e))
}

fn start_bundled_backend(app: &tauri::AppHandle) {
    if !should_start_bundled_backend() {
        return;
    }

    let handle = app.clone();
    tauri::async_runtime::spawn(async move {
        if api_runtime_reachable().await {
            return;
        }

        let command = match handle.shell().sidecar(BUNDLED_BACKEND_NAME) {
            Ok(command) => command,
            Err(e) => {
                eprintln!("Bundled backend is unavailable: {}", e);
                return;
            }
        };

        let (mut rx, child) = match command.spawn() {
            Ok(spawned) => spawned,
            Err(e) => {
                eprintln!("Failed to start bundled backend: {}", e);
                return;
            }
        };

        let pid = child.pid();
        {
            let state = handle.state::<BackendSidecarState>();
            let mut slot = state.0.lock().unwrap();
            *slot = Some(child);
        }
        eprintln!("Started bundled TeXada backend sidecar pid={}", pid);

        tauri::async_runtime::spawn(async move {
            while let Some(event) = rx.recv().await {
                match event {
                    CommandEvent::Stderr(bytes) => {
                        if let Ok(text) = String::from_utf8(bytes) {
                            let trimmed = text.trim();
                            if !trimmed.is_empty() {
                                eprintln!("texada-backend: {}", trimmed);
                            }
                        }
                    }
                    CommandEvent::Error(error) => {
                        eprintln!("texada-backend error: {}", error);
                    }
                    CommandEvent::Terminated(payload) => {
                        eprintln!("texada-backend exited: {:?}", payload);
                        break;
                    }
                    _ => {}
                }
            }
        });
    });
}

fn stop_bundled_backend(app: &tauri::AppHandle) {
    let state = app.state::<BackendSidecarState>();
    let child = {
        let mut slot = state.0.lock().unwrap();
        slot.take()
    };
    if let Some(child) = child {
        let _ = child.kill();
    }
}

fn toggle_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        if window.is_visible().unwrap_or(false) {
            let _ = window.hide();
        } else {
            position_window_near_cursor(&window);
            let _ = window.show();
            let _ = window.set_focus();
        }
    }
}

fn position_window_near_cursor(window: &tauri::WebviewWindow) {
    use tauri::PhysicalPosition;

    let Ok(cursor) = window.cursor_position() else {
        return;
    };
    let monitor = window
        .monitor_from_point(cursor.x, cursor.y)
        .ok()
        .flatten()
        .or_else(|| window.current_monitor().ok().flatten());
    let Some(monitor) = monitor else {
        return;
    };
    let Ok(window_size) = window.outer_size() else {
        return;
    };

    let work_area = monitor.work_area();
    let width = window_size.width as i32;
    let height = window_size.height as i32;
    let left = work_area.position.x;
    let top = work_area.position.y;
    let right = left + work_area.size.width as i32;
    let bottom = top + work_area.size.height as i32;

    let mut x = cursor.x.round() as i32 - width / 2;
    let mut y = cursor.y.round() as i32 + 16;
    if y + height > bottom - 8 {
        y = cursor.y.round() as i32 - height - 16;
    }
    x = x.clamp(left + 8, (right - width - 8).max(left + 8));
    y = y.clamp(top + 8, (bottom - height - 8).max(top + 8));

    let _ = window.set_position(PhysicalPosition::new(x, y));
}

fn setup_tray(app: &mut tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    let quit_i = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
    let toggle_i = MenuItem::with_id(app, "toggle", "Show/Hide", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&toggle_i, &quit_i])?;

    let _tray = TrayIconBuilder::new()
        .icon(app.default_window_icon().unwrap().clone())
        .menu(&menu)
        .show_menu_on_left_click(true)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "quit" => {
                app.exit(0);
            }
            "toggle" => {
                toggle_window(app);
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let tauri::tray::TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                let app = tray.app_handle();
                toggle_window(app);
            }
        })
        .build(app)?;

    Ok(())
}

fn setup_shortcut(app: &mut tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    app.handle().plugin(
        tauri_plugin_global_shortcut::Builder::new()
            .with_shortcut(SHORTCUT)?
            .with_handler(|app, shortcut, event| {
                let _ = shortcut;
                if event.state == ShortcutState::Pressed {
                    toggle_window(app);
                }
            })
            .build(),
    )?;
    Ok(())
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_os::init())
        .manage(BackendSidecarState::default())
        .invoke_handler(tauri::generate_handler![
            get_api_base,
            api_json,
            convert_text,
            complete_latex,
            convert_image,
            get_status,
            read_clipboard,
            write_clipboard,
            insert_text_at_cursor,
            hide_window,
            show_window,
            start_dragging,
        ])
        .setup(|app| {
            setup_tray(app)?;
            setup_shortcut(app)?;
            start_bundled_backend(app.handle());

            // Hide dock icon on macOS for popup-style app
            #[cfg(target_os = "macos")]
            {
                app.set_activation_policy(tauri::ActivationPolicy::Accessory);
            }

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app_handle, event| {
        if let RunEvent::Exit = event {
            stop_bundled_backend(app_handle);
        }
    });
}
