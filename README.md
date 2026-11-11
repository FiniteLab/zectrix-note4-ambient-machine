# Zectrix NOTE4 Ambient Machine

在电脑上运行 AMB-1 生成式氛围合成器，并通过局域网推送到 NOTE4。包含 NAS 后端网页、八组 AMB 声景、四条 CC0 实地录音、设备状态与独立管理端。

## 功能

- 默认 300 秒随机种子连续生成，后台提前准备下一段。
- 确认键切换预设，连续按键会取消旧生成任务，只保留最后目标。
- 上下键调整五档音量（10/25/50/75/100%）；小鸟与音符显示档位，不显示数字。
- 启动、加载和正式封面均为 400×300 连续灰阶 PNG，由 SDK 转换。
- 圆角白底电量与 Wi-Fi 图标；切片接续时，画面及状态未变化则不刷新。
- 网页可查看 NOTE4 状态，并可选择把新生成音频或实地录音交给现有管理端。
- 四条长录音按原始位置分片播放，不从头重复；临时 PCM 自动清理。
- 不自动重连、不抢占设备、不升级固件；`ResultUnknown` 不触发重刷或重播。

## 兼容环境

- NOTE4，固件 3.7.5；不适用于 NOTE4C。
- 本地推送 SDK 0.2.0，固定提交 `0dc44c31ba70ec0c2a558ec53de902663e45d3d3`；`build-nas.sh` 会应用 `note4-ambient/patches/sdk-diagnostics.patch`，只增加原始结果码日志，不改变收发行为。
- AMB 原始参考固定提交 `7c538516d6c52216ff4c8a4881cf2f0dcb07c44b`，CPU 优化补丁位于 `ambient-synth/patches/amb-cpu.patch`。
- Rust、C/C++ 编译器、CMake、Python 3.10+、curl、ffmpeg/ffprobe。

## 获取与构建

```sh
git clone --recurse-submodules git@github.com:FiniteLab/zectrix-note4-ambient-machine.git
cd zectrix-note4-ambient-machine
./ambient-synth/build-amb.sh
./note4-ambient/build-nas.sh
python3 field-recordings/download.py
```

`build-nas.sh` 使用 `OPUS_STATIC=1` 构建 SDK 自带 Opus。已有 `.tools` 工具链会优先复用，否则使用系统工具。

封面源码已经生成并随仓库提供。只有修改绘图时才需要 Pillow：

```sh
python3 ambient-gui/render_covers.py
python3 field-recordings/render_covers.py
python3 note4-ambient/render_startup.py
```

封面生成脚本使用 macOS 系统字体；如需在其他系统重画，请先修改字体路径。

## 本机设备配置

设备地址只保存在本机，不写入仓库：

```sh
umask 077
mkdir -p ~/.config/note4-ambient
read -r -p "NOTE4 局域网 IPv4: " target
printf '%s\n' "$target" >~/.config/note4-ambient/target
unset target
```

确保电脑与 NOTE4 在可互通的局域网，并按 SDK 指引启用待机保持 Wi-Fi。先启动管理端，再启动网页：

```sh
./note4-ambient/start.sh
./ambient-gui/start.sh
```

网页默认监听 `0.0.0.0:8765`。首次启动会在 `~/.config/ambient-gui/token` 生成本机访问令牌，权限为 600。然后在 NOTE4 上主动选择“连接管理端”。网页不会自动连接设备。

## 操作

- 确认短按：下一预设；加载中连续按下会取消旧任务。
- 上/下短按：五档音量。
- 上/下长按：停止、关闭会话并回到原固件；管理端继续等待下一次主动连接。
- 网页“生成后同步到 NOTE4”默认关闭。开启后仅同步之后新生成的音频，缓存命中不重复推送。
- 实地录音主动选择会立即切换；合成器后续预生成段则排队，避免提前切歌。
- 关闭网页同步会取消尚未播放的排队段，不中断当前声音。

## 停止、更新与卸载

```sh
./ambient-gui/stop.sh
./note4-ambient/stop.sh
```

更新：

```sh
git pull --recurse-submodules
git submodule update --init --recursive
./ambient-synth/build-amb.sh
./note4-ambient/build-nas.sh
python3 field-recordings/download.py
```

更新后先确认设备已退出，再重新运行两个启动脚本。已有配置和音频不会被启动、停止或下载脚本主动删除。

卸载时先停止两个服务。程序目录、`~/.config/note4-ambient/`、`~/.config/ambient-gui/` 和 `field-recordings/audio/` 分开处理；没有自动清空个人配置或录音库的卸载步骤。

## 许可与素材

项目及 AMB 修改使用 MPL-2.0，见 `LICENSE`。原始 AMB 项目为 [charlesvestal/fm1-amb](https://github.com/charlesvestal/fm1-amb)。本地推送 SDK 为 [itopinion/zectrix-local-push-sdk](https://github.com/itopinion/zectrix-local-push-sdk)，使用其自带许可。

四条实地录音均为 CC0，作者、原文件、下载地址、处理方式及审查后哈希见 `field-recordings/sources.json`。音频不直接存储在 Git 仓库中，`download.py` 会下载并校验当前版本。
