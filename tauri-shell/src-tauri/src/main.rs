// TeXada Tauri Shell — Floating input method style UI
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::env;
use std::net::IpAddr;
use std::path::PathBuf;
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

const DEFAULT_REQUEST_TIMEOUT_SECS: u64 = 240;
const BACKEND_STARTUP_PROBE_MS: u64 = 900;
const BUNDLED_BACKEND_NAME: &str = "texada-backend";
#[cfg(target_os = "macos")]
const WINDOW_CORNER_RADIUS: f64 = 14.0;

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
        .or_else(saved_request_timeout_secs)
        .unwrap_or(DEFAULT_REQUEST_TIMEOUT_SECS);
    Duration::from_secs(secs)
}

fn saved_request_timeout_secs() -> Option<u64> {
    let home = env::var_os("HOME")?;
    let path = PathBuf::from(home).join(".texada").join("config.json");
    let contents = std::fs::read_to_string(path).ok()?;
    let settings: serde_json::Value = serde_json::from_str(&contents).ok()?;
    let seconds = settings.get("api_request_timeout_seconds")?.as_f64()?;
    if seconds.is_finite() && seconds > 0.0 && seconds <= 900.0 {
        Some(seconds.ceil() as u64)
    } else {
        None
    }
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
    let host = host
        .strip_prefix('[')
        .and_then(|value| value.strip_suffix(']'))
        .unwrap_or(host);
    if host.eq_ignore_ascii_case("localhost") {
        return true;
    }
    host.parse::<IpAddr>()
        .map(|addr| addr.is_loopback() || addr.is_unspecified())
        .unwrap_or(false)
}

fn is_local_api_base(value: &str) -> bool {
    let Ok(url) = reqwest::Url::parse(value.trim()) else {
        return false;
    };
    url.host_str().map(is_local_api_host).unwrap_or(false)
}

fn api_client_for_base(timeout: Duration, api_base: &str) -> Result<reqwest::Client, String> {
    let mut builder = reqwest::Client::builder().timeout(timeout);
    if is_local_api_base(api_base) {
        // The desktop bridge only calls this API base. Loopback traffic must
        // never pass through a macOS or Windows system proxy.
        builder = builder.no_proxy();
    }
    builder
        .build()
        .map_err(|e| format!("HTTP client setup failed: {}", e))
}

fn api_client(timeout: Duration) -> Result<reqwest::Client, String> {
    api_client_for_base(timeout, &configured_api_base())
}

fn http_client() -> Result<reqwest::Client, String> {
    api_client(request_timeout())
}

fn startup_probe_client() -> Result<reqwest::Client, String> {
    api_client(Duration::from_millis(BACKEND_STARTUP_PROBE_MS))
}

fn is_startup_probe_request(method: &str, path: &str) -> bool {
    method.eq_ignore_ascii_case("GET")
        && matches!(path, "/api/status" | "/api/runtime" | "/api/settings/ui")
}

fn api_client_for_request(method: &str, path: &str) -> Result<reqwest::Client, String> {
    if is_startup_probe_request(method, path) {
        startup_probe_client()
    } else {
        http_client()
    }
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
    let client = api_client_for_request(&method, &path)?;
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
    let client = startup_probe_client()?;
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

#[cfg(target_os = "macos")]
fn configure_rounded_macos_window(
    window: &tauri::WebviewWindow,
) -> Result<(), Box<dyn std::error::Error>> {
    window.with_webview(|webview| unsafe {
        use objc2_app_kit::{NSColor, NSWindow};

        let native_window: &NSWindow = &*webview.ns_window().cast();
        let clear_color = NSColor::clearColor();
        native_window.setOpaque(false);
        native_window.setHasShadow(false);
        native_window.setBackgroundColor(Some(&clear_color));

        if let Some(content_view) = native_window.contentView() {
            content_view.setWantsLayer(true);
            if let Some(layer) = content_view.layer() {
                layer.setCornerRadius(WINDOW_CORNER_RADIUS);
                layer.setMasksToBounds(true);
            }
        }
    })?;
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
                let main_window = app
                    .get_webview_window("main")
                    .ok_or("main webview window is unavailable")?;
                configure_rounded_macos_window(&main_window)?;
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

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use super::{api_client_for_base, is_local_api_base, is_startup_probe_request};
    use tokio::io::{AsyncReadExt, AsyncWriteExt};

    #[test]
    fn local_api_base_detection_covers_loopback_variants() {
        assert!(is_local_api_base("http://127.0.0.1:18732"));
        assert!(is_local_api_base("http://localhost:18732/"));
        assert!(is_local_api_base("http://[::1]:18732"));
        assert!(is_local_api_base("http://0.0.0.0:18732"));
        assert!(is_local_api_base("http://[::]:18732"));
    }

    #[test]
    fn local_api_base_detection_preserves_proxy_support_for_remote_hosts() {
        assert!(!is_local_api_base("https://api.example.com/v1"));
        assert!(!is_local_api_base("http://192.168.1.10:18732"));
        assert!(!is_local_api_base("not a URL"));
    }

    #[test]
    fn only_startup_reads_use_the_short_startup_timeout() {
        assert!(is_startup_probe_request("GET", "/api/status"));
        assert!(is_startup_probe_request("GET", "/api/runtime"));
        assert!(is_startup_probe_request("GET", "/api/settings/ui"));
        assert!(!is_startup_probe_request("POST", "/api/settings/ui"));
        assert!(!is_startup_probe_request("GET", "/api/agent"));
        assert!(!is_startup_probe_request("GET", "/api/settings/backend"));
    }

    #[tokio::test]
    async fn local_api_client_reaches_loopback_directly() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .expect("bind loopback test server");
        let address = listener.local_addr().expect("read loopback address");
        let server = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.expect("accept local request");
            let mut request = [0_u8; 1024];
            let bytes_read = stream.read(&mut request).await.expect("read local request");
            assert!(bytes_read > 0, "local request must not be empty");
            stream
                .write_all(
                    b"HTTP/1.1 200 OK\r\nContent-Length: 6\r\nConnection: close\r\n\r\ndirect",
                )
                .await
                .expect("write local response");
        });

        let api_base = format!("http://{address}");
        let client = api_client_for_base(Duration::from_secs(2), &api_base)
            .expect("build direct local client");
        let response = client
            .get(format!("{api_base}/api/status"))
            .send()
            .await
            .expect("request local API without a proxy");

        assert!(response.status().is_success());
        assert_eq!(
            response.text().await.expect("read local response"),
            "direct"
        );
        server.await.expect("join loopback test server");
    }
}
