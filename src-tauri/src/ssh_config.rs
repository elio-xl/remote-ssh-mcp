use serde::{Deserialize, Serialize};
use std::{
    env,
    fs,
    io,
    net::{SocketAddr, TcpStream, ToSocketAddrs},
    path::{Path, PathBuf},
    process::Command,
    time::Duration,
};

#[derive(Clone, Debug)]
struct HostBlock {
    host: String,
    lines: Vec<String>,
    start: usize,
    end: usize,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SshConfigEntry {
    pub host: String,
    pub hostname: String,
    pub user: String,
    pub port: u16,
    #[serde(rename = "type")]
    pub auth_type: String,
    #[serde(rename = "IdentityFile")]
    pub identity_file: String,
    pub password: String,
    pub workdir: String,
    pub remarks: String,
}

#[derive(Clone, Debug, Serialize)]
pub struct ApiResponse {
    pub success: bool,
    pub message: String,
}

fn app_support_dir() -> Result<PathBuf, String> {
    let home = env::var_os("HOME").ok_or_else(|| "无法读取 HOME 环境变量".to_string())?;
    Ok(PathBuf::from(home)
        .join("Library")
        .join("Application Support")
        .join("Remote SSH MCP"))
}

fn config_path() -> Result<PathBuf, String> {
    Ok(app_support_dir()?.join("ssh_config"))
}

#[tauri::command]
pub fn get_ssh_config_path() -> Result<String, String> {
    Ok(config_path()?.display().to_string())
}

fn ensure_file(path: &Path) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|err| format!("创建配置目录失败: {err}"))?;
    }
    if !path.exists() {
        fs::write(path, "").map_err(|err| format!("创建 ssh_config 失败: {err}"))?;
    }
    Ok(())
}

fn read_lines() -> Result<Vec<String>, String> {
    let path = config_path()?;
    ensure_file(&path)?;
    let content = fs::read_to_string(&path).map_err(|err| format!("读取 ssh_config 失败: {err}"))?;
    Ok(content.lines().map(str::to_string).collect())
}

fn write_lines(lines: &[String]) -> Result<(), String> {
    let path = config_path()?;
    ensure_file(&path)?;
    if path.exists() {
        fs::copy(&path, path.with_file_name("ssh_config.bak"))
            .map_err(|err| format!("备份 ssh_config 失败: {err}"))?;
    }

    let content = lines.join("\n");
    let content = content.trim_end();
    let final_content = if content.is_empty() {
        String::new()
    } else {
        format!("{content}\n")
    };
    fs::write(&path, final_content).map_err(|err| format!("写入 ssh_config 失败: {err}"))
}

fn parse_blocks(lines: &[String]) -> Vec<HostBlock> {
    let mut blocks = Vec::new();
    let mut current_start: Option<usize> = None;
    let mut current_host = String::new();

    for (idx, line) in lines.iter().enumerate() {
        let stripped = line.trim();
        let mut parts = stripped.splitn(2, char::is_whitespace);
        let key = parts.next().unwrap_or_default();
        if key.eq_ignore_ascii_case("host") {
            if let Some(start) = current_start {
                blocks.push(HostBlock {
                    host: current_host.clone(),
                    lines: lines[start..idx].to_vec(),
                    start,
                    end: idx,
                });
            }
            current_start = Some(idx);
            current_host = parts.next().unwrap_or_default().trim().to_string();
        }
    }

    if let Some(start) = current_start {
        blocks.push(HostBlock {
            host: current_host,
            lines: lines[start..].to_vec(),
            start,
            end: lines.len(),
        });
    }

    blocks
}

fn block_to_entry(block: &HostBlock) -> SshConfigEntry {
    let mut hostname = String::new();
    let mut user = String::from("root");
    let mut port = 22;
    let mut identity_file = String::new();
    let mut workdir = String::new();
    let mut remarks = String::new();
    let mut comment_lines = Vec::new();

    for line in block.lines.iter().skip(1) {
        let stripped = line.trim();
        if stripped.is_empty() {
            continue;
        }
        if let Some(comment) = stripped.strip_prefix('#') {
            let comment = comment.trim();
            if let Some(value) = comment
                .strip_prefix("Workdir:")
                .or_else(|| comment.strip_prefix("workdir:"))
            {
                workdir = value.trim().to_string();
            } else if let Some(value) = comment
                .strip_prefix("Remarks:")
                .or_else(|| comment.strip_prefix("remarks:"))
            {
                remarks = value.trim().to_string();
            } else {
                comment_lines.push(comment.to_string());
            }
            continue;
        }

        let mut parts = stripped.splitn(2, char::is_whitespace);
        let key = parts.next().unwrap_or_default();
        let value = parts.next().unwrap_or_default().trim();
        if key.eq_ignore_ascii_case("hostname") {
            hostname = value.to_string();
        } else if key.eq_ignore_ascii_case("user") {
            user = value.to_string();
        } else if key.eq_ignore_ascii_case("port") {
            port = value.parse::<u16>().unwrap_or(22);
        } else if key.eq_ignore_ascii_case("identityfile") {
            identity_file = value.to_string();
        }
    }

    if remarks.is_empty() && !comment_lines.is_empty() {
        remarks = comment_lines.join(" ");
    }

    SshConfigEntry {
        host: block.host.clone(),
        hostname,
        user,
        port,
        auth_type: if identity_file.is_empty() {
            "password".to_string()
        } else {
            "key".to_string()
        },
        identity_file,
        password: String::new(),
        workdir,
        remarks,
    }
}

fn validate_payload(payload: &SshConfigEntry, require_auth_secret: bool) -> Result<(), String> {
    if payload.host.trim().is_empty() {
        return Err("Host 为必填项".to_string());
    }
    if payload.hostname.trim().is_empty() {
        return Err("HostName 为必填项".to_string());
    }
    if payload.user.trim().is_empty() {
        return Err("User 为必填项".to_string());
    }
    if payload.port == 0 {
        return Err("Port 必须是 1-65535 之间的整数".to_string());
    }
    if payload.auth_type != "password" && payload.auth_type != "key" {
        return Err("请选择连接类型".to_string());
    }
    if payload.auth_type == "key" && payload.identity_file.trim().is_empty() {
        return Err("密钥连接必须填写 IdentityFile".to_string());
    }
    if require_auth_secret && payload.auth_type == "password" && payload.password.trim().is_empty() {
        return Err("密码连接必须填写 Password".to_string());
    }
    Ok(())
}

fn payload_to_block(payload: &SshConfigEntry) -> Vec<String> {
    let mut lines = vec![
        format!("Host {}", payload.host.trim()),
        format!("    HostName {}", payload.hostname.trim()),
        format!("    User {}", payload.user.trim()),
        format!("    Port {}", payload.port),
    ];

    if payload.auth_type == "key" && !payload.identity_file.trim().is_empty() {
        lines.push(format!("    IdentityFile {}", payload.identity_file.trim()));
    }
    if !payload.workdir.trim().is_empty() {
        lines.push(format!("    # Workdir: {}", payload.workdir.trim()));
    }
    if !payload.remarks.trim().is_empty() {
        lines.push(format!("    # Remarks: {}", payload.remarks.trim()));
    }

    lines
}

fn find_entry(host: &str) -> Result<Option<SshConfigEntry>, String> {
    Ok(parse_blocks(&read_lines()?)
        .into_iter()
        .find(|block| block.host == host)
        .map(|block| block_to_entry(&block)))
}

#[tauri::command]
pub fn list_ssh_configs() -> Result<Vec<SshConfigEntry>, String> {
    Ok(parse_blocks(&read_lines()?)
        .iter()
        .map(block_to_entry)
        .collect())
}

#[tauri::command]
pub fn get_ssh_config(host: String) -> Result<Option<SshConfigEntry>, String> {
    find_entry(&host)
}

#[tauri::command]
pub fn create_ssh_config(payload: SshConfigEntry) -> Result<SshConfigEntry, String> {
    validate_payload(&payload, false)?;
    if find_entry(&payload.host)?.is_some() {
        return Err(format!("Host '{}' 已存在", payload.host));
    }

    let mut lines = read_lines()?;
    if lines.last().is_some_and(|line| !line.trim().is_empty()) {
        lines.push(String::new());
    }
    lines.extend(payload_to_block(&payload));
    write_lines(&lines)?;
    find_entry(&payload.host)?.ok_or_else(|| "创建后读取 SSH 配置失败".to_string())
}

#[tauri::command]
pub fn update_ssh_config(host: String, payload: SshConfigEntry) -> Result<SshConfigEntry, String> {
    validate_payload(&payload, false)?;
    let lines = read_lines()?;
    let blocks = parse_blocks(&lines);
    let target = blocks
        .iter()
        .find(|block| block.host == host)
        .ok_or_else(|| format!("Host '{host}' 未找到"))?;

    if payload.host != host && find_entry(&payload.host)?.is_some() {
        return Err(format!("Host '{}' 已存在", payload.host));
    }

    let mut updated = Vec::new();
    updated.extend_from_slice(&lines[..target.start]);
    updated.extend(payload_to_block(&payload));
    updated.extend_from_slice(&lines[target.end..]);
    write_lines(&updated)?;
    find_entry(&payload.host)?.ok_or_else(|| "更新后读取 SSH 配置失败".to_string())
}

#[tauri::command]
pub fn delete_ssh_config(host: String) -> Result<bool, String> {
    let lines = read_lines()?;
    let blocks = parse_blocks(&lines);
    let target = blocks
        .iter()
        .find(|block| block.host == host)
        .ok_or_else(|| format!("Host '{host}' 未找到"))?;

    let mut updated = Vec::new();
    updated.extend_from_slice(&lines[..target.start]);
    updated.extend_from_slice(&lines[target.end..]);
    while updated.first().is_some_and(|line| line.trim().is_empty()) {
        updated.remove(0);
    }
    write_lines(&updated)?;
    Ok(true)
}

fn first_socket_addr(hostname: &str, port: u16) -> Result<SocketAddr, String> {
    (hostname, port)
        .to_socket_addrs()
        .map_err(|err| format!("解析地址失败: {err}"))?
        .next()
        .ok_or_else(|| format!("无法解析地址 {hostname}:{port}"))
}

fn check_tcp_reachable(hostname: &str, port: u16, timeout: Duration) -> Result<(), String> {
    let addr = first_socket_addr(hostname, port)?;
    TcpStream::connect_timeout(&addr, timeout).map(drop).map_err(|err| {
        if err.kind() == io::ErrorKind::TimedOut {
            format!("连接超时: 无法在 {} 秒内连接到 {hostname}:{port}", timeout.as_secs())
        } else {
            format!("TCP 连接失败: {hostname}:{port}, {err}")
        }
    })
}

#[tauri::command]
pub fn test_ssh_connection(payload: SshConfigEntry) -> Result<ApiResponse, String> {
    validate_payload(&payload, true)?;
    let timeout = Duration::from_secs(8);
    check_tcp_reachable(&payload.hostname, payload.port, timeout)?;

    if payload.auth_type == "password" {
        return Ok(ApiResponse {
            success: true,
            message: "TCP 连接可达；密码认证不会写入磁盘，后续将接入交互式认证测试".to_string(),
        });
    }

    let destination = format!("{}@{}", payload.user.trim(), payload.hostname.trim());
    let output = Command::new("ssh")
        .arg("-o")
        .arg("BatchMode=yes")
        .arg("-o")
        .arg("ConnectTimeout=8")
        .arg("-o")
        .arg("StrictHostKeyChecking=no")
        .arg("-o")
        .arg("UserKnownHostsFile=/dev/null")
        .arg("-i")
        .arg(payload.identity_file.trim())
        .arg("-p")
        .arg(payload.port.to_string())
        .arg(destination)
        .arg("true")
        .output()
        .map_err(|err| format!("执行系统 ssh 失败: {err}"))?;

    if output.status.success() {
        return Ok(ApiResponse {
            success: true,
            message: "连接测试成功".to_string(),
        });
    }

    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
    Err(if stderr.is_empty() {
        format!("连接测试失败，退出码: {}", output.status)
    } else {
        stderr
    })
}
