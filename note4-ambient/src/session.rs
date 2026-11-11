use crate::{config_path, configured_target, error_kind, save_target};
use std::{
    env, fs,
    io::{Read, Write},
    net::IpAddr,
    path::PathBuf,
    process,
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Arc,
    },
    time::Duration,
};
use tokio::{
    process::Command,
    sync::mpsc::{unbounded_channel, UnboundedReceiver, UnboundedSender},
    task::JoinHandle,
    time::Instant,
};
use zectrix_sdk::{
    AudioClip, ConnectionRequestListener, Device, Error, Event, ImageFormat, Key, KeyAction, PlaybackEnd,
};

pub(crate) const PRESETS: [&str; 12] = [
    "garden", "departures", "voices", "afternoon", "night-bus", "shoreline", "glass", "tides",
    "rain-street", "cafe", "city-voices", "midnight-road",
];
pub(crate) const FIELD_SECONDS: [u32; 4] = [1800, 1200, 300, 1590];
const FIELD_CHUNK_SAMPLES: usize = 300 * 16000;
static NEXT_FILE: AtomicU64 = AtomicU64::new(0);
static STOPPING: AtomicBool = AtomicBool::new(false);

fn project_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().into()
}

fn state_path() -> Result<PathBuf, String> {
    Ok(config_path()?.with_file_name("state"))
}

struct Settings {
    preset: usize,
    seed: u32,
    seconds: u32,
    volume: u8,
    overrides: Vec<(u32, i32)>,
}

impl Default for Settings {
    fn default() -> Self {
        Self { preset: 0, seed: 42, seconds: 300, volume: 45, overrides: Vec::new() }
    }
}

fn env_number(name: &str) -> Result<Option<u32>, String> {
    match env::var(name) {
        Ok(value) => value.parse::<u32>().map(Some).map_err(|_| format!("{name} 应为整数")),
        Err(_) => Ok(None),
    }
}

fn random_seed() -> Result<u32, String> {
    let mut bytes = [0_u8; 2];
    fs::File::open("/dev/urandom")
        .and_then(|mut file| file.read_exact(&mut bytes))
        .map_err(|_| "无法取得本机随机种子")?;
    Ok(u16::from_le_bytes(bytes) as u32)
}

fn next_volume(current: u8, delta: i16) -> u8 {
    const LEVELS: [u8; 5] = [10, 25, 50, 75, 100];
    if delta > 0 {
        LEVELS.iter().copied().find(|level| *level > current).unwrap_or(100)
    } else {
        LEVELS.iter().rev().copied().find(|level| *level < current).unwrap_or(10)
    }
}

impl Settings {
    fn load() -> Result<Self, String> {
        let mut settings = Self::default();
        match fs::read_to_string(state_path()?) {
            Ok(text) => {
                for line in text.lines() {
                    let Some((key, value)) = line.split_once('=') else { continue };
                    if key == "set" {
                        let Some((id, value)) = value.split_once('=') else { return Err("本机配方配置无效".into()) };
                        let id = id.parse::<u32>().map_err(|_| "本机配方编号无效")?;
                        let value = value.parse::<i32>().map_err(|_| "本机配方数值无效")?;
                        if id > 22 || !(-1000..=1000).contains(&value) || settings.overrides.len() >= 32 {
                            return Err("本机配方配置超出允许范围".into());
                        }
                        settings.overrides.push((id, value));
                        continue;
                    }
                    let number = value.parse::<u32>().map_err(|_| "本机状态配置无效")?;
                    match key {
                        "preset" => settings.preset = number as usize,
                        "seed" => settings.seed = number,
                        "volume" => {
                            if number > 100 {
                                return Err("音量配置超出允许范围".into());
                            }
                            settings.volume = number as u8;
                        }
                        _ => {}
                    }
                }
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(_) => return Err("无法读取本机状态配置".into()),
        }
        if let Some(value) = env_number("AMBIENT_PRESET")? {
            settings.preset = value as usize;
        }
        if let Some(value) = env_number("AMBIENT_SEED")? {
            settings.seed = value;
        }
        if let Some(value) = env_number("AMBIENT_SEGMENT_SECONDS")? {
            settings.seconds = value;
        }
        if let Some(value) = env_number("AMBIENT_VOLUME")? {
            if value > 100 {
                return Err("音量配置超出允许范围".into());
            }
            settings.volume = value as u8;
        }
        settings.volume = settings.volume.max(10);
        if settings.preset >= PRESETS.len() || settings.seed > 65535 || !(15..=300).contains(&settings.seconds) || settings.volume > 100 {
            return Err("氛围配置超出允许范围".into());
        }
        Ok(settings)
    }

    fn save(&self) -> Result<(), String> {
        use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};

        let path = state_path()?;
        let directory = path.parent().ok_or("状态路径无效")?;
        fs::create_dir_all(directory).map_err(|_| "无法创建状态目录")?;
        fs::set_permissions(directory, fs::Permissions::from_mode(0o700)).map_err(|_| "无法保护状态目录")?;
        let temporary = path.with_extension("tmp");
        let mut file = fs::OpenOptions::new()
            .create(true)
            .truncate(true)
            .write(true)
            .mode(0o600)
            .open(&temporary)
            .map_err(|_| "无法写入本机状态配置")?;
        write!(file, "preset={}\nseed={}\nvolume={}\n", self.preset, self.seed, self.volume)
            .map_err(|_| "无法保存本机状态配置")?;
        for (id, value) in &self.overrides {
            writeln!(file, "set={id}={value}").map_err(|_| "无法保存本机配方配置")?;
        }
        fs::rename(temporary, path).map_err(|_| "无法更新本机状态配置")?;
        Ok(())
    }
}

#[derive(Clone)]
struct Prepared {
    preset: usize,
    seed: u32,
    seconds: u32,
    clip: AudioClip,
    position: usize,
}

struct Scratch {
    wav: PathBuf,
    pcm: PathBuf,
}

impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.wav);
        let _ = fs::remove_file(&self.pcm);
    }
}

fn cleanup_cache(cache: &PathBuf) {
    let Ok(entries) = fs::read_dir(cache) else { return };
    let mut removed = 0;
    let mut errors = 0;
    for entry in entries.flatten() {
        let path = entry.path();
        let Some(name) = path.file_name().and_then(|name| name.to_str()) else { continue };
        if !name.starts_with("segment-") || !(name.ends_with(".wav") || name.ends_with(".pcm")) {
            continue;
        }
        let Ok(metadata) = entry.metadata() else { continue };
        if !metadata.is_file() {
            continue;
        }
        let stale = metadata.modified().ok().and_then(|time| time.elapsed().ok()).map(|age| age > Duration::from_secs(3600)).unwrap_or(false);
        if !stale {
            continue;
        }
        match fs::remove_file(path) {
            Ok(()) => removed += 1,
            Err(_) => errors += 1,
        }
    }
    if removed > 0 || errors > 0 {
        println!("NOTE4 临时音频清理：删除 {removed} 个，失败 {errors} 个");
    }
}

fn new_scratch(preset: usize, seed: u32) -> Result<Scratch, String> {
    use std::os::unix::fs::PermissionsExt;

    let cache = project_root().join("note4-ambient/cache");
    fs::create_dir_all(&cache).map_err(|_| "无法创建音频缓存目录")?;
    fs::set_permissions(&cache, fs::Permissions::from_mode(0o700)).map_err(|_| "无法保护音频缓存目录")?;
    cleanup_cache(&cache);
    let serial = NEXT_FILE.fetch_add(1, Ordering::Relaxed);
    let stem = format!("segment-{}-{preset}-{seed}-{serial}", process::id());
    Ok(Scratch { wav: cache.join(format!("{stem}.wav")), pcm: cache.join(format!("{stem}.pcm")) })
}

async fn decode_wav(scratch: &Scratch, seconds: u32) -> Result<AudioClip, String> {
    let converted = Command::new("ffmpeg")
        .args(["-hide_banner", "-loglevel", "error", "-y", "-i"])
        .arg(&scratch.wav)
        .args(["-af", "aformat=sample_fmts=s16:channel_layouts=mono,aresample=16000,apad"])
        .arg("-t")
        .arg(seconds.to_string())
        .args(["-f", "s16le"])
        .arg(&scratch.pcm)
        .kill_on_drop(true)
        .output()
        .await
        .map_err(|_| "无法启动音频格式转换")?;
    if !converted.status.success() {
        return Err("音频转换为 16 kHz 单声道 PCM16 失败".into());
    }
    let bytes = fs::read(&scratch.pcm).map_err(|_| "无法读取生成的 PCM")?;
    if bytes.len() != seconds as usize * 16000 * 2 {
        return Err("生成音频的帧数与分段时长不符".into());
    }
    Ok(AudioClip { samples: bytes.chunks_exact(2).map(|chunk| i16::from_le_bytes([chunk[0], chunk[1]])).collect() })
}

async fn prepare(preset: usize, seed: u32, seconds: u32, overrides: Vec<(u32, i32)>) -> Result<Prepared, String> {
    let started = Instant::now();
    println!("PREPARE_BEGIN：{} · 种子 {seed}", PRESETS[preset]);
    let scratch = new_scratch(preset, seed)?;
    let seconds = if preset >= 8 { FIELD_SECONDS[preset - 8] } else { seconds };
    if preset >= 8 {
        let source = project_root().join("field-recordings/audio").join(format!("{}.mp3", PRESETS[preset]));
        fs::copy(source, &scratch.wav).map_err(|_| "实地录音文件不可读")?;
        let clip = decode_wav(&scratch, seconds).await?;
        println!("实地录音已准备：{} · 完整 {seconds} 秒 · 准备耗时 {:.1} 秒", PRESETS[preset], started.elapsed().as_secs_f32());
        return Ok(Prepared { preset, seed: 0, seconds, clip, position: 0 });
    }
    let mut command = Command::new(project_root().join("ambient-synth/out/amb-render"));
    command.arg(preset.to_string()).arg(seconds.to_string()).arg(&scratch.wav).arg(seed.to_string());
    for (id, value) in overrides {
        command.arg("--set").arg(format!("{id}={value}"));
    }
    let renderer = command.kill_on_drop(true).output().await.map_err(|_| "无法启动 AMB 渲染器")?;
    if !renderer.status.success() {
        return Err("AMB 渲染失败，未自动重试".into());
    }
    println!("PREPARE_RENDERED：{} · 渲染耗时 {:.1} 秒", PRESETS[preset], started.elapsed().as_secs_f32());
    let clip = decode_wav(&scratch, seconds).await?;
    println!("已准备：{} · 种子 {seed} · {seconds} 秒 · 准备耗时 {:.1} 秒", PRESETS[preset], started.elapsed().as_secs_f32());
    Ok(Prepared { preset, seed, seconds, clip, position: 0 })
}

async fn prepare_sync(request: crate::sync::SyncRequest) -> Result<Prepared, String> {
    let source = if request.preset >= 8 {
        project_root().join("field-recordings/audio").join(&request.audio)
    } else {
        project_root().join("ambient-gui/out").join(&request.audio)
    };
    let scratch = new_scratch(request.preset, request.seed)?;
    fs::copy(source, &scratch.wav).map_err(|_| "网页同步音频已过期或不可读")?;
    let clip = decode_wav(&scratch, request.seconds).await?;
    println!("网页同步音频已准备：{} · 种子 {} · {} 秒", PRESETS[request.preset], request.seed, request.seconds);
    Ok(Prepared { preset: request.preset, seed: request.seed, seconds: request.seconds, clip, position: 0 })
}

#[derive(Clone, Copy)]
enum Screen {
    Startup,
    Loading(usize),
    Cover(usize),
}

async fn show_image(device: &Device, screen: Screen, status: &zectrix_sdk::DeviceStatus, volume: u8) -> Result<(), String> {
    let root = project_root();
    let path = match screen {
        Screen::Startup => root.join("note4-ambient/assets/startup.png"),
        Screen::Loading(index) => root.join("note4-ambient/assets").join(format!("loading-{}.png", PRESETS[index])),
        Screen::Cover(index) => root.join("ambient-gui/covers").join(format!("{}.png", PRESETS[index])),
    };
    let source = fs::read(path).map_err(|_| "启动图、加载图或风格封面尚未准备好")?;
    let png = crate::display::render(&source, status, volume)?;
    let format = if matches!(screen, Screen::Loading(6) | Screen::Cover(6)) { ImageFormat::Gray4 } else { ImageFormat::Gray16 };
    let label = match screen {
        Screen::Startup => "启动图",
        Screen::Loading(_) => "加载图",
        Screen::Cover(_) => "封面",
    };
    println!("IMAGE_BEGIN：{label}");
    device.show_with_format(&png, format).await.map_err(|error| format!("{label}推送失败：{}", error_kind(&error)))?;
    match screen {
        Screen::Startup => println!("STARTUP_DISPLAY_COMPLETED：启动图已显示"),
        Screen::Loading(index) => println!("LOADING_DISPLAY_COMPLETED：{}", PRESETS[index]),
        Screen::Cover(index) => println!("COVER_COMPLETED：{}；状态栏已提交", PRESETS[index]),
    }
    Ok(())
}

async fn present(device: &Device, screen: Screen, status: &zectrix_sdk::DeviceStatus, report: &mut crate::sync::Report) -> Result<(), String> {
    let (kind, index) = match screen {
        Screen::Startup => (0, 0),
        Screen::Loading(index) => (1, index),
        Screen::Cover(index) => (2, index),
    };
    let frame_key = format!("{kind}:{index}:{:?}:{:?}:{:?}:{}", status.battery_percent, status.charging, status.wifi_rssi_dbm, report.volume);
    if matches!(screen, Screen::Cover(_)) && report.frame_key.as_deref() == Some(frame_key.as_str()) {
        report.phase = "ready";
        report.write();
        println!("SLICE_SKIP_REFRESH：封面与设备状态均未变化");
        return Ok(());
    }
    report.phase = match screen {
        Screen::Startup => "startup_display",
        Screen::Loading(_) => "loading_display",
        Screen::Cover(_) => "cover_display",
    };
    if let Screen::Loading(index) | Screen::Cover(index) = screen {
        report.preset = index;
    }
    report.write();
    show_image(device, screen, status, report.volume).await?;
    report.frame_key = Some(frame_key);
    report.phase = match screen {
        Screen::Startup => "generating",
        Screen::Loading(_) => "generating",
        Screen::Cover(_) => "ready",
    };
    if let Screen::Loading(_) = screen {
        if report.sync_id.is_some() {
            report.sync_state = "loading";
        }
    }
    report.write();
    Ok(())
}

async fn present_optional(device: &Device, screen: Screen, status: &zectrix_sdk::DeviceStatus, report: &mut crate::sync::Report) -> Result<(), String> {
    match present(device, screen, status, report).await {
        Err(error) if error == "启动图、加载图或风格封面尚未准备好" => {
            println!("画面素材缺失；保持会话，继续生成或播放，不重试推图");
            report.phase = if matches!(screen, Screen::Loading(_)) { "generating" } else { "ready" };
            report.write();
            Ok(())
        }
        result => result,
    }
}

async fn refresh_status(device: &Device, status: &mut zectrix_sdk::DeviceStatus, updated: &mut Option<Instant>) {
    if let Some(at) = *updated {
        if at.elapsed() < Duration::from_secs(30) {
            return;
        }
    }
    match device.status().await {
        Ok(value) => *status = value,
        Err(error) => println!("设备状态未读取：{}；保留已有值或显示 --", error_kind(&error)),
    }
    *updated = Some(Instant::now());
}

enum Control {
    Next,
    Volume(i16),
    Stop,
    Fatal(String),
}

async fn consume_events(device: Arc<Device>, controls: UnboundedSender<Control>, closing: Arc<AtomicBool>) {
    loop {
        match device.next_event().await {
            Ok(Some(Event::Key { key, action })) => {
                let control = match (key, action) {
                    (Key::Confirm, KeyAction::Short) => Control::Next,
                    (Key::Up, KeyAction::Short) => Control::Volume(5),
                    (Key::Down, KeyAction::Short) => Control::Volume(-5),
                    (Key::Up | Key::Down, KeyAction::Long) => Control::Stop,
                    (Key::Confirm, KeyAction::Long) => continue,
                };
                if controls.send(control).is_err() {
                    return;
                }
                println!("KEY_RX：{key:?} / {action:?} · 时间 {}", crate::log_time());
            }
            Ok(Some(Event::RecordingStarted)) => println!("设备按键触发录音；不上传、不保存"),
            Ok(Some(Event::RecordingFinished { reason, .. })) => println!("录音事件结束：{reason:?}；未保存音频"),
            Ok(Some(Event::Disconnected { reason })) => {
                // The SDK reports a locally requested close through the same event as a device-side one.
                if closing.load(Ordering::SeqCst) {
                    println!("LOCAL_CLOSE_DONE：本端已关闭会话（{reason:?}）· 时间 {}", crate::log_time());
                } else {
                    println!("DEVICE_DISCONNECT_RX：{reason:?} · 时间 {}", crate::log_time());
                }
                let _ = controls.send(Control::Fatal(format!("设备会话结束：{reason:?}")));
                return;
            }
            Ok(None) => {
                let _ = controls.send(Control::Stop);
                return;
            }
            Err(error) => {
                let _ = controls.send(Control::Fatal(error_kind(&error)));
                return;
            }
        }
    }
}

enum Outcome {
    Completed,
    Next,
    Stop,
    Sync(crate::sync::SyncRequest),
}

async fn play_segment(
    device: &Device,
    mut clip: AudioClip,
    volume: &mut u8,
    controls: &mut UnboundedReceiver<Control>,
    syncs: &mut UnboundedReceiver<crate::sync::SyncCommand>,
    report: &mut crate::sync::Report,
    sync_active: &mut bool,
    pending: &mut Option<crate::sync::SyncRequest>,
) -> Result<Outcome, String> {
    report.phase = "playing";
    report.write();
    'playback: loop {
        if clip.samples.is_empty() {
            return Ok(Outcome::Completed);
        }
        let started = Instant::now();
        let playback_clip = clip.clone();
        println!("PLAY_BEGIN：{} · 种子 {} · {} 秒 · 音量 {} · 时间 {}", PRESETS[report.preset], report.seed, playback_clip.samples.len() / 16000, *volume, crate::log_time());
        let play = device.play(&playback_clip, *volume);
        tokio::pin!(play);
        'events: loop {
            tokio::select! {
                result = &mut play => {
                    let end = match result {
                        Ok(end) => end,
                        Err(Error::DeviceFailure) => {
                            let status_started = Instant::now();
                            match device.status().await {
                                Ok(status) => println!("PLAY_FAILURE_STATUS：电量 {:?}% · 充电 {:?} · Wi-Fi {:?} dBm · 查询 {} 毫秒 · 时间 {}", status.battery_percent, status.charging, status.wifi_rssi_dbm, status_started.elapsed().as_millis(), crate::log_time()),
                                Err(error) => println!("PLAY_FAILURE_STATUS_ERROR：{} · 查询 {} 毫秒 · 时间 {}", error_kind(&error), status_started.elapsed().as_millis(), crate::log_time()),
                            }
                            return Err("音频播放失败：设备处理失败".into());
                        }
                        Err(error) => return Err(format!("音频播放失败：{}", error_kind(&error))),
                    };
                    return match end {
                        PlaybackEnd::Completed => Ok(Outcome::Completed),
                        PlaybackEnd::Stopped => Ok(Outcome::Stop),
                        PlaybackEnd::Interrupted => {
                            println!("播放被设备功能中断，不自动重播");
                            Ok(Outcome::Stop)
                        }
                        PlaybackEnd::Limit => Err("播放达到协议边界，不自动重播".into()),
                    };
                }
                control = controls.recv() => {
                    match control {
                        Some(Control::Next) => {
                            println!("NEXT_STOP：收到切换，正在停止当前播放");
                            device.stop().await.map_err(|error| error_kind(&error))?;
                            println!("NEXT_STOP_ACK：停止命令已完成");
                            let end = play.await.map_err(|error| error_kind(&error))?;
                            println!("NEXT_PLAY_END：{end:?}");
                            match end {
                                PlaybackEnd::Stopped => {
                                    tokio::time::sleep(Duration::from_millis(300)).await;
                                    return Ok(Outcome::Next);
                                }
                                PlaybackEnd::Completed => return Ok(Outcome::Next),
                                _ => return Err("切风格时播放未正常结束".into()),
                            }
                        }
                        Some(Control::Stop) => {
                            let _ = device.stop().await;
                            let _ = play.await;
                            return Ok(Outcome::Stop);
                        }
                        Some(Control::Fatal(message)) => return Err(message),
                        Some(Control::Volume(delta)) => {
                            let next = next_volume(*volume, delta);
                            if next == *volume {
                                continue 'events;
                            }
                            let consumed = ((started.elapsed().as_secs_f64() * 16000.0) as usize).min(clip.samples.len());
                            device.stop().await.map_err(|error| error_kind(&error))?;
                            match play.await.map_err(|error| error_kind(&error))? {
                                PlaybackEnd::Stopped => {
                                    clip.samples = clip.samples.split_off(consumed);
                                    *volume = next;
                                    report.volume = next;
                                    report.write();
                                    let preset = report.preset;
                                    let device_status = report.device.clone();
                                    present_optional(device, Screen::Cover(preset), &device_status, report).await?;
                                    println!("音量：{next}；画面已更新，从当前位置附近续播");
                                    continue 'playback;
                                }
                                PlaybackEnd::Completed => {
                                    *volume = next;
                                    report.volume = next;
                                    report.write();
                                    return Ok(Outcome::Completed);
                                }
                                _ => return Err("调整音量时播放未正常结束".into()),
                            }
                        }
                        None => return Err("事件通道已关闭".into()),
                    }
                }
                command = syncs.recv() => {
                    match command {
                        Some(crate::sync::SyncCommand::Push(request)) => {
                            report.sync_id = Some(request.id);
                            if *sync_active && !request.interrupt {
                                println!("网页下一段已排队：种子 {}", request.seed);
                                *pending = Some(request);
                                report.sync_state = "queued";
                                report.write();
                                continue 'events;
                            }
                            report.sync_state = "received";
                            report.write();
                            device.stop().await.map_err(|error| error_kind(&error))?;
                            match play.await.map_err(|error| error_kind(&error))? {
                                PlaybackEnd::Stopped | PlaybackEnd::Completed => return Ok(Outcome::Sync(request)),
                                _ => return Err("同步推送前播放未正常结束".into()),
                            }
                        }
                        Some(crate::sync::SyncCommand::Disable) => {
                            *pending = None;
                            *sync_active = false;
                            report.sync_state = "disabled";
                            report.write();
                            println!("网页同步已关闭；排队段已取消，当前段不中断");
                        }
                        None => return Err("同步通道已关闭".into()),
                    }
                }
            }
        }
    }
}

async fn next_prepared(task: JoinHandle<Result<Prepared, String>>) -> Result<Prepared, String> {
    task.await.map_err(|_| "音频生成任务已取消")?
}

async fn refresh(device: &Device, status: &mut zectrix_sdk::DeviceStatus, updated: &mut Option<Instant>, report: &mut crate::sync::Report) {
    refresh_status(device, status, updated).await;
    report.device = status.clone();
    report.write();
}

enum TransitionRequest {
    Current,
    Next,
    Sync(crate::sync::SyncRequest),
}

enum TransitionResult {
    Ready(Prepared, bool),
    Stop,
}

async fn transition(
    device: &Device,
    settings: &mut Settings,
    controls: &mut UnboundedReceiver<Control>,
    syncs: &mut UnboundedReceiver<crate::sync::SyncCommand>,
    status: &mut zectrix_sdk::DeviceStatus,
    updated: &mut Option<Instant>,
    report: &mut crate::sync::Report,
    mut request: TransitionRequest,
) -> Result<TransitionResult, String> {
    let mut synced = false;
    'transition: loop {
        match request {
            TransitionRequest::Current => {}
            TransitionRequest::Next => {
                settings.preset = (settings.preset + 1) % PRESETS.len();
                settings.seed = random_seed()?;
                settings.overrides.clear();
                synced = false;
                report.sync_id = None;
                report.sync_state = "off";
                println!("切换目标：{} · 随机种子 {}", PRESETS[settings.preset], settings.seed);
                request = TransitionRequest::Current;
            }
            TransitionRequest::Sync(ref source) => {
                settings.preset = source.preset;
                settings.seed = source.seed;
                if source.preset < 8 {
                    settings.seconds = source.seconds;
                    settings.overrides = source.overrides.clone();
                } else {
                    settings.overrides.clear();
                }
                report.sync_id = Some(source.id);
                report.sync_state = "loading";
                synced = true;
            }
        }
        report.preset = settings.preset;
        report.seed = settings.seed;
        report.phase = "generating";
        report.write();
        refresh(device, status, updated, report).await;
        present_optional(device, Screen::Loading(settings.preset), status, report).await?;
        let mut task = match &request {
            TransitionRequest::Sync(source) => tokio::spawn(prepare_sync(source.clone())),
            _ => tokio::spawn(prepare(settings.preset, settings.seed, settings.seconds, settings.overrides.clone())),
        };
        let prepared = loop {
            tokio::select! {
                result = &mut task => {
                    let prepared = result.map_err(|_| "音频生成任务已取消")??;
                    break prepared;
                }
                control = controls.recv() => {
                    match control {
                        Some(Control::Next) => {
                            task.abort();
                            let _ = task.await;
                            request = TransitionRequest::Next;
                            continue 'transition;
                        }
                        Some(Control::Volume(delta)) => {
                            let next = next_volume(settings.volume, delta);
                            if next != settings.volume {
                                settings.volume = next;
                                report.volume = next;
                                report.write();
                                present_optional(device, Screen::Loading(settings.preset), status, report).await?;
                                println!("加载中音量：{next}；画面已更新");
                            }
                        }
                        Some(Control::Stop) => {
                            task.abort();
                            let _ = task.await;
                            report.phase = "closing";
                            report.write();
                            return Ok(TransitionResult::Stop);
                        }
                        Some(Control::Fatal(message)) => {
                            task.abort();
                            let _ = task.await;
                            return Err(message);
                        }
                        None => {
                            task.abort();
                            let _ = task.await;
                            return Err("事件通道已关闭".into());
                        }
                    }
                }
                command = syncs.recv() => {
                    match command {
                        Some(crate::sync::SyncCommand::Push(source)) => {
                            task.abort();
                            let _ = task.await;
                            request = TransitionRequest::Sync(source);
                            continue 'transition;
                        }
                        Some(crate::sync::SyncCommand::Disable) => {
                            synced = false;
                            report.sync_state = "disabled";
                            report.write();
                        }
                        None => {
                            task.abort();
                            let _ = task.await;
                            return Err("同步通道已关闭".into());
                        }
                    }
                }
            }
        };
        report.preset = prepared.preset;
        report.seed = prepared.seed;
        report.seconds = prepared.seconds;
        report.sync_state = if synced { "playing" } else { "off" };
        report.write();
        refresh(device, status, updated, report).await;
        present_optional(device, Screen::Cover(prepared.preset), status, report).await?;
        return Ok(TransitionResult::Ready(prepared, synced));
    }
}

async fn session_loop(
    device: &Device,
    settings: &mut Settings,
    controls: &mut UnboundedReceiver<Control>,
    syncs: &mut UnboundedReceiver<crate::sync::SyncCommand>,
    report: &mut crate::sync::Report,
) -> Result<(), String> {
    if env::var_os("AMBIENT_SEED").is_none() {
        settings.seed = random_seed()?;
        println!("本次随机起始种子：{}", settings.seed);
    }
    report.connected = true;
    report.phase = "generating";
    report.preset = settings.preset;
    report.seed = settings.seed;
    report.seconds = settings.seconds;
    report.volume = settings.volume;
    report.sync_id = None;
    report.sync_state = "off";
    report.write();
    let mut status = zectrix_sdk::DeviceStatus::default();
    let mut status_updated = None;
    let mut sync_active;
    let mut pending = None;
    refresh(device, &mut status, &mut status_updated, report).await;
    present(device, Screen::Startup, &status, report).await?;
    let mut current = match transition(device, settings, controls, syncs, &mut status, &mut status_updated, report, TransitionRequest::Current).await? {
        TransitionResult::Ready(prepared, synced) => {
            sync_active = synced;
            prepared
        }
        TransitionResult::Stop => return Ok(()),
    };
    loop {
        let following = if current.preset >= 8 {
            let mut next = current.clone();
            next.position = (current.position + FIELD_CHUNK_SAMPLES).min(current.clip.samples.len());
            if next.position >= current.clip.samples.len() {
                next.position = 0;
            }
            tokio::spawn(async move { Ok(next) })
        } else {
            let following_seed = loop {
                let seed = random_seed()?;
                if seed != current.seed {
                    break seed;
                }
            };
            tokio::spawn(prepare(current.preset, following_seed, settings.seconds, settings.overrides.clone()))
        };
        let playback_clip = if current.preset >= 8 {
            let end = (current.position + FIELD_CHUNK_SAMPLES).min(current.clip.samples.len());
            AudioClip { samples: current.clip.samples[current.position..end].to_vec() }
        } else {
            current.clip.clone()
        };
        match play_segment(device, playback_clip, &mut settings.volume, controls, syncs, report, &mut sync_active, &mut pending).await? {
            Outcome::Completed => {
                if let Some(request) = pending.take() {
                    following.abort();
                    let _ = following.await;
                    current = match transition(device, settings, controls, syncs, &mut status, &mut status_updated, report, TransitionRequest::Sync(request)).await? {
                        TransitionResult::Ready(prepared, synced) => {
                            sync_active = synced;
                            prepared
                        }
                        TransitionResult::Stop => return Ok(()),
                    };
                } else {
                    current = next_prepared(following).await?;
                    settings.seed = current.seed;
                    sync_active = false;
                    report.seed = current.seed;
                    report.seconds = current.seconds;
                    report.sync_id = None;
                    report.sync_state = "off";
                    if current.preset >= 8 {
                        println!("实地录音接续：{} · 位置 {} 秒", PRESETS[current.preset], current.position / 16000);
                    } else {
                        println!("接续新段：{} · 随机种子 {}", PRESETS[current.preset], current.seed);
                    }
                    refresh(device, &mut status, &mut status_updated, report).await;
                    present_optional(device, Screen::Cover(current.preset), &status, report).await?;
                }
            }
            Outcome::Next => {
                following.abort();
                let _ = following.await;
                pending = None;
                current = match transition(device, settings, controls, syncs, &mut status, &mut status_updated, report, TransitionRequest::Next).await? {
                    TransitionResult::Ready(prepared, synced) => {
                        sync_active = synced;
                        prepared
                    }
                    TransitionResult::Stop => return Ok(()),
                };
            }
            Outcome::Sync(request) => {
                following.abort();
                let _ = following.await;
                pending = None;
                current = match transition(device, settings, controls, syncs, &mut status, &mut status_updated, report, TransitionRequest::Sync(request)).await? {
                    TransitionResult::Ready(prepared, synced) => {
                        sync_active = synced;
                        prepared
                    }
                    TransitionResult::Stop => return Ok(()),
                };
            }
            Outcome::Stop => {
                following.abort();
                let _ = following.await;
                report.phase = "closing";
                report.write();
                return Ok(());
            }
        }
    }
}

async fn shutdown_signal() {
    let mut terminate = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()).expect("无法监听 SIGTERM");
    tokio::select! {
        _ = tokio::signal::ctrl_c() => {}
        _ = terminate.recv() => {}
    }
    STOPPING.store(true, Ordering::SeqCst);
}

async fn run_device(
    device: Device,
    settings: &mut Settings,
    syncs: &mut UnboundedReceiver<crate::sync::SyncCommand>,
    report: &mut crate::sync::Report,
) -> Result<(), String> {
    let session_started = Instant::now();
    let device = Arc::new(device);
    // One channel per session: closing the device always queues a final Disconnected control,
    // which a shared channel would hand to the next session as a fatal event.
    let (sender, mut controls) = unbounded_channel();
    let closing = Arc::new(AtomicBool::new(false));
    let mut events = tokio::spawn(consume_events(device.clone(), sender, closing.clone()));
    let mut result = {
        let operation = session_loop(&device, settings, &mut controls, syncs, report);
        tokio::pin!(operation);
        tokio::select! {
            result = &mut operation => result,
            _ = shutdown_signal() => {
                let _ = device.stop().await;
                Ok(())
            }
        }
    };
    closing.store(true, Ordering::SeqCst);
    let close_result = device.close().await.map_err(|error| error_kind(&error));
    if tokio::time::timeout(Duration::from_secs(3), &mut events).await.is_err() {
        events.abort();
        let _ = events.await;
    }
    if let Err(error) = close_result {
        if result.is_ok() {
            result = Err(error);
        }
    }
    println!("SESSION_CLEANUP：会话时长 {:.1} 秒 · 时间 {}", session_started.elapsed().as_secs_f32(), crate::log_time());
    settings.save()?;
    report.connected = false;
    report.phase = match &result {
        Ok(()) => "offline",
        Err(error) if error.contains("结果未知") => "unknown",
        Err(_) => "error",
    };
    report.write();
    result
}

pub async fn check_field(preset: usize) -> Result<(), String> {
    if !(8..PRESETS.len()).contains(&preset) {
        return Err("field-check 需要预设 8–11".into());
    }
    let prepared = prepare(preset, 0, 300, Vec::new()).await?;
    let peak = prepared.clip.samples.iter().map(|sample| (*sample as i32).abs()).max().unwrap_or(0);
    let nonzero = prepared.clip.samples.iter().filter(|sample| **sample != 0).count();
    println!("FIELD_CHECK_OK：{} · {} 秒 · 峰值 {} · 非零样本 {:.1}%", PRESETS[preset], prepared.seconds, peak, nonzero as f64 * 100.0 / prepared.clip.samples.len() as f64);
    Ok(())
}

pub async fn play_saved() -> Result<(), String> {
    let target = configured_target()?;
    let device = crate::open(&target).await?;
    let mut settings = Settings::load()?;
    let (sync_sender, mut syncs) = unbounded_channel();
    let watcher = tokio::spawn(crate::sync::watch(sync_sender));
    let mut report = crate::sync::Report::new();
    let result = run_device(device, &mut settings, &mut syncs, &mut report).await;
    watcher.abort();
    let _ = watcher.await;
    result
}

pub async fn serve() -> Result<(), String> {
    let target = configured_target()?;
    let expected = target.parse::<IpAddr>().map_err(|_| "常驻管理端需要目标为 IPv4 地址")?;
    let mut settings = Settings::load()?;
    cleanup_cache(&project_root().join("note4-ambient/cache"));
    let mut report = crate::sync::Report::new();
    report.write();
    let (sync_sender, mut syncs) = unbounded_channel();
    let watcher = tokio::spawn(crate::sync::watch(sync_sender));
    let mut listener = ConnectionRequestListener::bind().await.map_err(|error| error_kind(&error))?;
    println!("管理端已就绪：等待指定的 NOTE4 主动连接");
    loop {
        if STOPPING.load(Ordering::SeqCst) {
            break;
        }
        let request = tokio::select! {
            request = listener.next_request() => request.map_err(|error| error_kind(&error))?,
            command = syncs.recv() => {
                match command {
                    Some(crate::sync::SyncCommand::Push(request)) => {
                        report.sync_id = Some(request.id);
                        report.sync_state = "rejected_offline";
                        report.phase = "offline";
                        report.write();
                        println!("网页音频未推送：NOTE4 未连接，不排队、不自动连接");
                    }
                    Some(crate::sync::SyncCommand::Disable) => {
                        report.sync_state = "disabled";
                        report.write();
                    }
                    None => break,
                }
                continue;
            },
            _ = shutdown_signal() => break,
        };
        if request.address.ip() != expected {
            println!("已忽略非指定设备的连接请求");
            continue;
        }
        match request.accept("AMB Atelier").await {
            Ok(device) => {
                if let Err(error) = save_target(&target) {
                    println!("设备配置未保存：{error}");
                }
                report.connected = true;
                report.phase = "starting";
                report.write();
                match run_device(device, &mut settings, &mut syncs, &mut report).await {
                    Ok(()) => println!("设备已释放，等待下一次主动连接"),
                    Err(error) => println!("会话结束：{error} · 时间 {}", crate::log_time()),
                }
            }
            Err(error) => println!("接受连接失败：{error}"),
        }
    }
    watcher.abort();
    let _ = watcher.await;
    report.connected = false;
    report.phase = "offline";
    report.write();
    println!("管理端已停止");
    Ok(())
}
