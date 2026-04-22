// 阻止 Windows release 构建弹出附带的控制台窗口
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    rosetta_desktop_lib::run();
}
