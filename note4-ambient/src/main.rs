use std::{
    env,
    fs,
    io::Write,
    net::IpAddr,
    path::PathBuf,
    sync::Arc,
    time::Duration,
};
use zectrix_sdk::{
    AudioClip, ConnectionRequestListener, Device, DeviceStatus, Error, Event, ImageFormat, Key, KeyAction,
    OpenOptions, PlaybackEnd,
};

mod display;
mod session;
mod sync;

pub(crate) fn error_kind(error: &Error) -> String {
    match error {
        Error::NoDevice => "没有发现可连接的空闲设备".into(),
        Error::MultipleDevices(devices) => format!("发现 {} 台设备，未自动选择", devices.len()),
        Error::Busy => "设备仍被占用，未抢占".into(),
        Error::Disconnected => "设备连接已结束，不自动重连".into(),
        Error::InvalidImage(_) => "PNG 图像无效".into(),
        Error::InvalidAudio(_) => "PCM 音频无效".into(),
        Error::AudioTooLong => "音频超出协议长度".into(),
        Error::ResultUnknown => "操作结果未知，不自动重发".into(),
        Error::ConsumerTooSlow => "事件消费过慢，连接已结束".into(),
        Error::DeviceFailure => "设备处理失败".into(),
        Error::InvalidOptions(message) => format!("参数无效：{message}"),
        Error::TransportFailure(_) => "通信失败（设备地址未输出）".into(),
    }
}

pub(crate) fn config_path() -> Result<PathBuf, String> {
    let home = env::var("HOME").map_err(|_| "无法定位本机配置目录".to_string())?;
    Ok(PathBuf::from(home).join(".config/note4-ambient/target"))
}

pub(crate) fn configured_target() -> Result<String, String> {
    if let Ok(target) = env::var("NOTE4_TARGET") {
        let target = target.trim();
        if !target.is_empty() {
            return Ok(target.to_string());
        }
    }
    if let Ok(path) = env::var("NOTE4_ENV_FILE") {
        let text = fs::read_to_string(path).map_err(|_| "无法读取本机设备环境配置")?;
        for line in text.lines() {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') {
                continue;
            }
            let line = line.strip_prefix("export ").unwrap_or(line);
            let Some((key, value)) = line.split_once('=') else {
                continue;
            };
            if matches!(key.trim(), "ART_CLOCK_DEVICE" | "NOTE4_TARGET") {
                let target = value.trim().trim_matches(|character| character == '\'' || character == '"');
                if target.is_empty() {
                    return Err("本机 NOTE4 目标配置为空".into());
                }
                return Ok(target.to_string());
            }
        }
        return Err("本机设备环境配置中没有 ART_CLOCK_DEVICE".into());
    }
    let path = config_path()?;
    let target = fs::read_to_string(&path)
        .map_err(|_| "未配置 NOTE4 目标，请在本机设置 NOTE4_TARGET".to_string())?;
    let target = target.trim();
    if target.is_empty() {
        return Err("本机 NOTE4 目标配置为空".into());
    }
    Ok(target.to_string())
}

pub(crate) fn save_target(target: &str) -> Result<(), String> {
    use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};

    let path = config_path()?;
    let directory = path.parent().ok_or("配置路径无效")?;
    fs::create_dir_all(directory).map_err(|_| "无法创建本机配置目录")?;
    fs::set_permissions(directory, fs::Permissions::from_mode(0o700))
        .map_err(|_| "无法保护本机配置目录")?;
    let mut file = fs::OpenOptions::new()
        .create(true)
        .truncate(true)
        .write(true)
        .mode(0o600)
        .open(path)
        .map_err(|_| "无法写入本机设备配置")?;
    file.write_all(target.as_bytes())
        .map_err(|_| "无法保存本机设备配置")?;
    Ok(())
}

fn read_pcm(path: &str) -> Result<AudioClip, String> {
    let bytes = fs::read(path).map_err(|_| "无法读取 PCM 文件")?;
    if bytes.is_empty() || bytes.len() % 2 != 0 {
        return Err("PCM 必须是偶数字节且非空的 16 位小端数据".into());
    }
    let samples = bytes
        .chunks_exact(2)
        .map(|chunk| i16::from_le_bytes([chunk[0], chunk[1]]))
        .collect::<Vec<_>>();
    println!("音频已读取：16 kHz · 单声道 · PCM16 · {:.2} 秒", samples.len() as f64 / 16000.0);
    Ok(AudioClip { samples })
}

async fn cover(device: Device, png: Vec<u8>) -> Result<(), String> {
    let result = device.show_with_format(&png, ImageFormat::Gray16).await.map_err(|error| error_kind(&error));
    let close = device.close().await.map_err(|error| error_kind(&error));
    result?;
    close?;
    println!("封面显示完成，连接已关闭");
    Ok(())
}

async fn probe(device: Device) -> Result<(), String> {
    println!("设备连接成功；目标地址与设备 ID 未输出");
    let status = device.status().await;
    device.close().await.map_err(|error| error_kind(&error))?;
    match status {
        Ok(status) => {
            println!("状态查询成功：电量 {:?}% · 充电 {:?} · Wi-Fi {:?} dBm", status.battery_percent, status.charging, status.wifi_rssi_dbm);
            println!("状态接口可用；具体固件版本仍需在设备上核对");
        }
        Err(error) => println!("状态查询未成功：{}；不能据此判断固件版本", error_kind(&error)),
    }
    Ok(())
}

async fn transfer(device: Arc<Device>, png: Vec<u8>, clip: AudioClip) -> Result<PlaybackEnd, Error> {
    device.show_with_format(&png, ImageFormat::Gray16).await?;
    println!("DISPLAY_COMPLETED：设备已报告 gray16 画面刷新完成");
    let end = device.play(&clip, 45).await?;
    println!("PLAYBACK_END：{end:?}");
    Ok(end)
}

async fn consume_events(device: Arc<Device>) -> Result<(), String> {
    loop {
        match device.next_event().await.map_err(|error| error_kind(&error))? {
            Some(Event::Key { key, action }) => match (key, action) {
                (Key::Confirm, KeyAction::Short) => {
                    println!("确认键：停止当前播放");
                    device.stop().await.map_err(|error| error_kind(&error))?;
                }
                (Key::Up | Key::Down, KeyAction::Long) => {
                    println!("长按上下键：停止并退出");
                    device.stop().await.map_err(|error| error_kind(&error))?;
                    return Ok(());
                }
                _ => println!("收到按键：{key:?} / {action:?}"),
            },
            Some(Event::RecordingStarted) => println!("设备按键触发录音；不上传、不保存"),
            Some(Event::RecordingFinished { reason, .. }) => {
                println!("设备录音事件结束：{reason:?}；未保存音频")
            }
            Some(Event::Disconnected { reason }) => {
                println!("设备会话结束：{reason:?}");
                return Ok(());
            }
            None => return Ok(()),
        }
    }
}

async fn demo(device: Device, png: Vec<u8>, clip: AudioClip) -> Result<(), String> {
    let device = Arc::new(device);
    let mut events = tokio::spawn(consume_events(device.clone()));
    let operation = transfer(device.clone(), png, clip);
    tokio::pin!(operation);
    let result = tokio::select! {
        result = &mut operation => result,
        _ = tokio::signal::ctrl_c() => {
            println!("收到停止信号，停止播放并清理连接");
            let _ = device.stop().await;
            operation.await
        }
    };
    device.close().await.map_err(|error| error_kind(&error))?;
    if tokio::time::timeout(Duration::from_secs(3), &mut events).await.is_err() {
        events.abort();
        let _ = events.await;
    }
    result.map_err(|error| error_kind(&error))?;
    println!("SESSION_CLOSED：连接已清理，不自动重连");
    Ok(())
}

async fn open(target: &str) -> Result<Device, String> {
    let device = Device::open(OpenOptions {
        target: Some(target.to_string()),
        client_name: Some("AMB Atelier".into()),
    })
    .await
    .map_err(|error| error_kind(&error))?;
    if let Err(error) = save_target(target) {
        println!("设备配置未保存：{error}");
    }
    Ok(device)
}

async fn listen() -> Result<(), String> {
    let target = configured_target()?;
    let expected = target.parse::<IpAddr>().map_err(|_| "主动连接监听需要目标为 IPv4 地址")?;
    let mut listener = ConnectionRequestListener::bind().await.map_err(|error| error_kind(&error))?;
    println!("正在等待设备主动连接；只接受原艺术时钟目标");
    let request = tokio::select! {
        request = listener.next_request() => request.map_err(|error| error_kind(&error))?,
        _ = tokio::signal::ctrl_c() => {
            println!("监听已停止，未接受设备连接");
            return Ok(());
        }
    };
    if request.address.ip() != expected {
        println!("已忽略非指定设备的连接请求");
        return Err("连接请求不是来自指定 NOTE4，未接受".into());
    }
    let device = request.accept("AMB Atelier").await.map_err(|error| error_kind(&error))?;
    if let Err(error) = save_target(&target) {
        println!("设备配置未保存：{error}");
    }
    probe(device).await
}

async fn listen_new() -> Result<(), String> {
    let mut listener = ConnectionRequestListener::bind().await.map_err(|error| error_kind(&error))?;
    println!("等待本次由用户确认的设备主动连接");
    let request = tokio::select! {
        request = listener.next_request() => request.map_err(|error| error_kind(&error))?,
        _ = tokio::signal::ctrl_c() => {
            println!("监听已停止，未接受设备连接");
            return Ok(());
        }
    };
    let target = request.address.ip().to_string();
    let device = request.accept("AMB Atelier").await.map_err(|error| error_kind(&error))?;
    if let Err(error) = save_target(&target) {
        println!("设备配置未保存：{error}");
    }
    probe(device).await
}

fn preview(arguments: &mut impl Iterator<Item = String>) -> Result<(), String> {
    let preset = arguments.next().ok_or("preview 需要预设编号")?.parse::<usize>().map_err(|_| "预设编号无效")?;
    let battery = arguments.next().ok_or("preview 需要电量")?.parse::<u8>().map_err(|_| "电量无效")?;
    let rssi = arguments.next().ok_or("preview 需要 Wi-Fi dBm")?.parse::<i8>().map_err(|_| "Wi-Fi dBm 无效")?;
    let output = arguments.next().ok_or("preview 需要输出 PNG 路径")?;
    let volume = match arguments.next() {
        Some(value) => value.parse::<u8>().map_err(|_| "预览音量无效")?,
        None => 45,
    };
    if arguments.next().is_some() || preset >= session::PRESETS.len() || battery > 100 || volume > 100 || !(-127..=0).contains(&rssi) {
        return Err("preview 参数应为 <预设0-11> <电量0-100> <WiFi -127至0> <输出.png> [音量0-100]".into());
    }
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().to_path_buf();
    let source = root.join("ambient-gui/covers").join(format!("{}.png", session::PRESETS[preset]));
    let png = fs::read(source).map_err(|_| "无法读取预览封面")?;
    let status = DeviceStatus { battery_percent: Some(battery), charging: Some(false), wifi_rssi_dbm: Some(rssi) };
    let png = display::render(&png, &status, volume)?;
    fs::write(output, png).map_err(|_| "无法写入状态预览 PNG")?;
    println!("状态预览已生成：400×300 原始 PNG，未连接设备");
    Ok(())
}

async fn run() -> Result<(), String> {
    let mut arguments = env::args().skip(1);
    let command = arguments.next().unwrap_or_else(|| "probe".into());
    match command.as_str() {
        "probe" => {
            if arguments.next().is_some() {
                return Err("probe 不接受额外参数".into());
            }
            let target = configured_target()?;
            probe(open(&target).await?).await
        }
        "listen" => {
            if arguments.next().is_some() {
                return Err("listen 不接受额外参数".into());
            }
            listen().await
        }
        "listen-new" => {
            if arguments.next().is_some() {
                return Err("listen-new 不接受额外参数".into());
            }
            listen_new().await
        }
        "serve" => {
            if arguments.next().is_some() {
                return Err("serve 不接受额外参数".into());
            }
            session::serve().await
        }
        "play" => {
            if arguments.next().is_some() {
                return Err("play 不接受额外参数".into());
            }
            session::play_saved().await
        }
        "cover" => {
            let png = arguments.next().ok_or("cover 需要原始 PNG 路径")?;
            if arguments.next().is_some() {
                return Err("cover 参数过多".into());
            }
            let png = fs::read(png).map_err(|_| "无法读取原始 PNG")?;
            let target = configured_target()?;
            cover(open(&target).await?, png).await
        }
        "demo" => {
            let png = arguments.next().ok_or("demo 需要原始 PNG 路径")?;
            let pcm = arguments.next().ok_or("demo 需要 16 kHz 单声道 PCM16 路径")?;
            if arguments.next().is_some() {
                return Err("demo 参数过多".into());
            }
            let png = fs::read(png).map_err(|_| "无法读取原始 PNG")?;
            let clip = read_pcm(&pcm)?;
            let target = configured_target()?;
            demo(open(&target).await?, png, clip).await
        }
        "preview" => preview(&mut arguments),
        "field-check" => {
            let preset = arguments.next().ok_or("field-check 需要预设 8–11")?.parse::<usize>().map_err(|_| "实地录音编号无效")?;
            if arguments.next().is_some() {
                return Err("field-check 参数过多".into());
            }
            session::check_field(preset).await
        }
        _ => Err("用法：note4-ambient probe | serve | play | listen | listen-new | preview <预设0-11> <电量> <WiFi-dBm> <输出.png> | field-check <预设8-11> | demo <原始.png> <16k-mono-s16le.pcm>".into()),
    }
}

#[tokio::main]
async fn main() {
    if let Err(error) = run().await {
        eprintln!("{error}");
        std::process::exit(1);
    }
}
