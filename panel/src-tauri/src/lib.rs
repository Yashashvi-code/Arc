
#[tauri::command]
fn toggle_pin(window: tauri::Window) -> Result<bool, String> {
    let current = window.is_always_on_top().map_err(|e| e.to_string())?;
    let target = !current;
    window.set_always_on_top(target).map_err(|e| e.to_string())?;
    Ok(target)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    #[cfg(target_os = "linux")]
    {
        // Force XWayland backend on Linux GNOME to support stays-on-bottom and positioning hints
        std::env::set_var("GDK_BACKEND", "x11");
        // Prevent blank webview rendering issues on hybrid Intel/Nvidia drivers
        std::env::set_var("WEBKIT_DISABLE_DMABUF_RENDERER", "1");
    }

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![toggle_pin])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
