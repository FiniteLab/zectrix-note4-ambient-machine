use std::{
    fs,
    path::PathBuf,
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tokio::sync::mpsc::UnboundedSender;
use zectrix_sdk::DeviceStatus;

#[derive(Clone)]
pub struct SyncRequest {
    pub id: u64,
    pub audio: String,
    pub preset: usize,
    pub seed: u32,
    pub seconds: u32,
    pub overrides: Vec<(u32, i32)>,
    pub interrupt: bool,
}

pub enum SyncCommand {
    Push(SyncRequest),
    Disable,
    Volume(u8),
}

fn number<T: std::str::FromStr>(value: &str) -> Result<T, String> {
    value.parse().map_err(|_| "同步请求数值无效".into())
}

fn valid_audio(name: &str, preset: usize) -> bool {
    if preset >= 8 {
        return name == format!("{}.mp3", crate::session::PRESETS[preset]);
    }
    let bytes = name.as_bytes();
    bytes.len() == 26
        && (bytes.starts_with(b"e-") || bytes.starts_with(b"r-"))
        && bytes[2..22].iter().all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
        && bytes.ends_with(b".wav")
}

impl SyncRequest {
    fn parse(text: &str) -> Result<Self, String> {
        let mut id = None;
        let mut audio = None;
        let mut preset = None;
        let mut seed = None;
        let mut seconds = None;
        let mut interrupt = false;
        let mut overrides = Vec::new();
        for line in text.lines() {
            let Some((key, value)) = line.split_once('=') else { return Err("同步请求格式无效".into()) };
            match key {
                "v" if value == "1" => {}
                "id" => id = Some(number(value)?),
                "audio" => audio = Some(value.to_string()),
                "preset" => preset = Some(number(value)?),
                "seed" => seed = Some(number(value)?),
                "seconds" => seconds = Some(number(value)?),
                "interrupt" => interrupt = match value { "1" => true, "0" => false, _ => return Err("同步切换标记无效".into()) },
                "set" => {
                    let Some((id, value)) = value.split_once('=') else { return Err("同步配方无效".into()) };
                    overrides.push((number(id)?, number(value)?));
                }
                _ => return Err("同步请求包含未知字段".into()),
            }
        }
        let request = Self {
            id: id.ok_or("同步请求缺少 ID")?,
            audio: audio.ok_or("同步请求缺少音频")?,
            preset: preset.ok_or("同步请求缺少预设")?,
            seed: seed.ok_or("同步请求缺少种子")?,
            seconds: seconds.ok_or("同步请求缺少时长")?,
            overrides,
            interrupt,
        };
        if request.id == 0
            || request.preset >= crate::session::PRESETS.len()
            || !valid_audio(&request.audio, request.preset)
            || request.seed > 65535
            || (request.preset < 8 && !(15..=300).contains(&request.seconds))
            || (request.preset >= 8 && request.seconds != crate::session::FIELD_SECONDS[request.preset - 8])
            || request.overrides.len() > 32
            || (request.preset >= 8 && !request.overrides.is_empty())
            || request.overrides.iter().any(|(id, value)| *id > 22 || !(-1000..=1000).contains(value))
        {
            return Err("同步请求超出允许范围".into());
        }
        Ok(request)
    }
}

fn spool() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("spool")
}

pub async fn watch(sender: UnboundedSender<SyncCommand>) {
    let directory = spool();
    if fs::create_dir_all(&directory).is_err() {
        eprintln!("无法创建本地同步目录");
        return;
    }
    let _ = fs::set_permissions(&directory, std::os::unix::fs::PermissionsExt::from_mode(0o700));
    let mut interval = tokio::time::interval(Duration::from_millis(250));
    loop {
        interval.tick().await;
        let Ok(entries) = fs::read_dir(&directory) else { continue };
        let mut paths = entries.flatten().map(|entry| entry.path()).filter(|path| path.extension().and_then(|value| value.to_str()) == Some("cmd")).collect::<Vec<_>>();
        paths.sort();
        for path in paths {
            let text = match fs::read_to_string(&path) {
                Ok(text) => text,
                Err(_) => continue,
            };
            let _ = fs::remove_file(path);
            let command = if text.trim() == "disable" {
                Ok(SyncCommand::Disable)
            } else if let Some(value) = text.trim().strip_prefix("volume=") {
                match value.parse::<u8>() {
                    Ok(level) if [10, 25, 50, 75, 100].contains(&level) => Ok(SyncCommand::Volume(level)),
                    _ => Err("网页音量档位无效".into()),
                }
            } else {
                SyncRequest::parse(&text).map(SyncCommand::Push)
            };
            match command {
                Ok(command) => {
                    if sender.send(command).is_err() {
                        return;
                    }
                }
                Err(error) => eprintln!("已忽略无效同步请求：{error}"),
            }
        }
    }
}

pub struct Report {
    path: PathBuf,
    pub connected: bool,
    pub phase: &'static str,
    pub preset: usize,
    pub seed: u32,
    pub seconds: u32,
    pub volume: u8,
    pub device: DeviceStatus,
    pub sync_id: Option<u64>,
    pub sync_state: &'static str,
    pub frame_key: Option<String>,
}

impl Report {
    pub fn new() -> Self {
        Self {
            path: PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("out/status.json"),
            connected: false,
            phase: "offline",
            preset: 0,
            seed: 0,
            seconds: 300,
            volume: 45,
            device: DeviceStatus::default(),
            sync_id: None,
            sync_state: "off",
            frame_key: None,
        }
    }

    pub fn write(&self) {
        let updated = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_secs();
        fn optional<T: ToString>(value: Option<T>) -> String {
            value.map(|value| value.to_string()).unwrap_or_else(|| "null".into())
        }
        let json = format!(
            concat!(
                "{{\"version\":1,\"pid\":{},\"updated\":{},\"connected\":{},\"phase\":\"{}\",",
                "\"preset\":{},\"seed\":{},\"seconds\":{},\"volume\":{},\"battery\":{},\"charging\":{},",
                "\"wifi\":{},\"syncId\":{},\"syncState\":\"{}\"}}"
            ),
            std::process::id(),
            updated,
            self.connected,
            self.phase,
            self.preset,
            self.seed,
            self.seconds,
            self.volume,
            optional(self.device.battery_percent),
            optional(self.device.charging),
            optional(self.device.wifi_rssi_dbm),
            optional(self.sync_id),
            self.sync_state,
        );
        let temporary = self.path.with_extension("tmp");
        if fs::write(&temporary, json).and_then(|_| fs::rename(temporary, &self.path)).is_err() {
            eprintln!("无法写入 NOTE4 本地状态");
        }
    }
}
