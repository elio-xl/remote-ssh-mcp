mod ssh_config;

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            ssh_config::get_ssh_config_path,
            ssh_config::list_ssh_configs,
            ssh_config::get_ssh_config,
            ssh_config::create_ssh_config,
            ssh_config::update_ssh_config,
            ssh_config::delete_ssh_config,
            ssh_config::test_ssh_connection,
        ])
        .run(tauri::generate_context!())
        .expect("error while running Remote SSH MCP");
}
