// TeXada Tauri Shell — Floating input method style UI
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::{
    menu::{Menu, MenuItem},
    tray::{TrayIconBuilder, MouseButton, MouseButtonState},
    Manager, WebviewUrl, WebviewWindowBuilder,
};
use tauri_plugin_clipboard_manager::ClipboardExt;
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};

const API_BASE: &str = "http://127.0.0.1:18732";
const SHORTCUT: &str = "Option+Command+T";

#[derive(serde::Serialize)]
struct ConvertPayload {
    text: String,
    render_mode: String,
}

#[derive(serde::Deserialize)]
struct ConvertResponse {
    latex: String,
    katex_html: Option<String>,
    copy_text: String,
    valid: bool,
    source: String,
    intent: String,
    confidence: f64,
    latency_ms: f64,
}

#[tauri::command]
async fn convert_text(text: String) -> Result<ConvertResponse, String> {
    let client = reqwest::Client::new();
    let payload = ConvertPayload {
        text,
        render_mode: "katex".to_string(),
    };
    let res = client
        .post(format!("{}/api/convert", API_BASE))
        .json(&payload)
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;

    if !res.status().is_success() {
        return Err(format!("API error: {}", res.status()));
    }

    res.json::<ConvertResponse>()
        .await
        .map_err(|e| format!("Parse error: {}", e))
}

#[tauri::command]
async fn get_status() -> Result<serde_json::Value, String> {
    let client = reqwest::Client::new();
    let res = client
        .get(format!("{}/api/status", API_BASE))
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

#[tauri::command]
fn hide_window(window: tauri::WebviewWindow) {
    let _ = window.hide();
}

#[tauri::command]
fn show_window(window: tauri::WebviewWindow) {
    let _ = window.show();
    let _ = window.set_focus();
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

#[cfg(target_os = "macos")]
fn position_window_near_cursor(window: &tauri::WebviewWindow) {
    use cocoa::appkit::NSScreen;
    use cocoa::base::nil;
    use cocoa::foundation::{NSArray, NSString};
    use objc::runtime::Object;
    use objc::{msg_send, sel, sel_impl};
    use tauri::PhysicalPosition;

    unsafe {
        let ns_window: *mut Object = window.ns_window().unwrap_or(nil) as *mut Object;
        if ns_window.is_null() {
            return;
        }

        // Get mouse location in screen coordinates (bottom-left origin)
        let mouse_location: cocoa::foundation::NSPoint = msg_send![class!(NSEvent), mouseLocation];

        // Get screen containing mouse
        let screens: *mut Object = NSScreen::screens(nil);
        let count: usize = msg_send![screens, count];
        let mut target_screen: *mut Object = nil;
        for i in 0..count {
            let screen: *mut Object = msg_send![screens, objectAtIndex:i];
            let frame: cocoa::foundation::NSRect = msg_send![screen, frame];
            if cocoa::foundation::NSPointInRect(mouse_location, frame) {
                target_screen = screen;
                break;
            }
        }

        if target_screen.is_null() {
            target_screen = msg_send![screens, objectAtIndex:0];
        }

        let screen_frame: cocoa::foundation::NSRect = msg_send![target_screen, frame];
        let window_frame: cocoa::foundation::NSRect = msg_send![ns_window, frame];

        // Convert to top-left origin
        let screen_height = screen_frame.size.height;
        let mut x = mouse_location.x - window_frame.size.width / 2.0;
        let mut y = screen_height - mouse_location.y + 16.0; // 16px above cursor

        // Clamp to screen bounds
        if x < screen_frame.origin.x {
            x = screen_frame.origin.x + 8.0;
        }
        if x + window_frame.size.width > screen_frame.origin.x + screen_frame.size.width {
            x = screen_frame.origin.x + screen_frame.size.width - window_frame.size.width - 8.0;
        }
        if y + window_frame.size.height > screen_height {
            y = screen_height - mouse_location.y - window_frame.size.height - 8.0;
        }
        if y < 0.0 {
            y = 8.0;
        }

        let _ = window.set_position(PhysicalPosition::new(x as i32, y as i32));
    }
}

#[cfg(not(target_os = "macos"))]
fn position_window_near_cursor(_window: &tauri::WebviewWindow) {
    // TODO: implement for Windows/Linux
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
            .with_handler(|app, shortcut, event| {
                if event.state == ShortcutState::Pressed && shortcut.matches("Option+Command+T") {
                    toggle_window(app);
                }
            })
            .build(),
    )?;

    app.global_shortcut().register(SHORTCUT)?;
    Ok(())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_global_shortcut::init())
        .plugin(tauri_plugin_os::init())
        .invoke_handler(tauri::generate_handler![
            convert_text,
            get_status,
            read_clipboard,
            write_clipboard,
            hide_window,
            show_window,
        ])
        .setup(|app| {
            setup_tray(app)?;
            setup_shortcut(app)?;

            // Hide dock icon on macOS for popup-style app
            #[cfg(target_os = "macos")]
            {
                app.set_activation_policy(tauri::ActivationPolicy::Accessory);
            }

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
