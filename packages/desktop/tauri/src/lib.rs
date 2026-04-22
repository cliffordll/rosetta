//! Tauri 桌面外壳主逻辑。
//!
//! 职责
//! ----
//! - `setup` 钩子里 spawn `rosetta-server` sidecar,`--parent-pid` 传当前 Tauri
//!   进程 PID;server 的 watcher 会在 Tauri 退出后 5s 内自动 graceful_shutdown
//!   (DESIGN §6)。
//! - `get_server_url` command:读 `~/.rosetta/endpoint.json` 的 `url` 字段。
//!   prod 模式下 webview 无法通过相对路径走 vite proxy,前端首次启动 invoke
//!   一次拿 base URL 替换 fetch 基路径(7.2+ 前端再适配)。

use std::sync::Mutex;

use serde::Deserialize;
use tauri::{Manager, State};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

/// sidecar 进程句柄;保存在 Tauri state 里,窗口关闭时可供 7.2 做优雅关闭
struct SidecarState(Mutex<Option<CommandChild>>);

#[derive(Deserialize)]
struct Endpoint {
    url: String,
}

#[tauri::command]
fn get_server_url() -> Result<String, String> {
    let home = dirs::home_dir().ok_or_else(|| "无法解析用户 HOME 目录".to_string())?;
    let ep_path = home.join(".rosetta").join("endpoint.json");
    let raw = std::fs::read_to_string(&ep_path).map_err(|e| {
        format!(
            "读取 {} 失败:{}(server 可能还未启动)",
            ep_path.display(),
            e
        )
    })?;
    let ep: Endpoint = serde_json::from_str(&raw).map_err(|e| format!("endpoint.json 解析失败:{e}"))?;
    Ok(ep.url)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(SidecarState(Mutex::new(None)))
        .setup(|app| {
            let parent_pid = std::process::id().to_string();
            let sidecar = app
                .shell()
                .sidecar("rosetta-server")
                .map_err(|e| format!("找不到 rosetta-server sidecar:{e}"))?
                .args(["--parent-pid", &parent_pid]);

            let (_rx, child) = sidecar
                .spawn()
                .map_err(|e| format!("spawn rosetta-server 失败:{e}"))?;

            let state: State<SidecarState> = app.state();
            if let Ok(mut guard) = state.0.lock() {
                *guard = Some(child);
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![get_server_url])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
