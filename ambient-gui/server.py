#!/usr/bin/env python3
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
FIELD_ROOT = ROOT.parent / "field-recordings"
FIELD_PRESETS = json.loads((FIELD_ROOT / "sources.json").read_text())
FIELD_MAP = {item["id"]: item for item in FIELD_PRESETS}
RENDER_BIN = Path(os.environ.get("AMB_RENDER_BIN") or ROOT.parent / "ambient-synth" / "out" / "amb-render")
AUDIO_DIR = Path(os.environ.get("AMBIENT_GUI_DATA") or ROOT / "out")
HOST = os.environ.get("AMBIENT_GUI_HOST", "127.0.0.1")
PORT = int(os.environ.get("AMBIENT_GUI_PORT", "8765"))

PRESETS = [
    {"id": 0, "name": "garden", "title": "温室晨光", "description": "温暖的 Rhodes、柔和钟声与缓慢生长的和声。", "format": "gray16"},
    {"id": 1, "name": "departures", "title": "夜间启程", "description": "稀疏 Rhodes、长回声与安静的低频。", "format": "gray16"},
    {"id": 2, "name": "voices", "title": "远方人声", "description": "呼吸般的共振峰声部与宽松空间。", "format": "gray16"},
    {"id": 3, "name": "afternoon", "title": "午后原野", "description": "明亮和弦、轻盈脉冲与日间空气感。", "format": "gray16"},
    {"id": 4, "name": "night-bus", "title": "雨夜巴士", "description": "金属音色、城市节奏和短促反射。", "format": "gray16"},
    {"id": 5, "name": "shoreline", "title": "月下海岸", "description": "圆润钟声、潮汐般延音与深色空间。", "format": "gray16"},
    {"id": 6, "name": "glass", "title": "玻璃棱镜", "description": "清亮晶体钟声与错位泛音。", "format": "gray4"},
    {"id": 7, "name": "tides", "title": "长潮呼吸", "description": "持续变化的人声、移动声场与长混响。", "format": "gray16"},
]

PARAMETERS = [
    {"name": "pad", "id": 0, "label": "Pad", "min": 0, "max": 100, "group": "layers"},
    {"name": "bells", "id": 1, "label": "Bells", "min": 0, "max": 100, "group": "layers"},
    {"name": "bass", "id": 2, "label": "Bass", "min": 0, "max": 100, "group": "layers"},
    {"name": "pulse", "id": 3, "label": "Pulse", "min": 0, "max": 100, "group": "layers"},
    {"name": "density", "id": 4, "label": "Density", "min": 0, "max": 100, "group": "motion"},
    {"name": "evolve", "id": 5, "label": "Evolve", "min": 0, "max": 100, "group": "motion"},
    {"name": "drift", "id": 6, "label": "Drift", "min": 0, "max": 100, "group": "motion"},
    {"name": "hits", "id": 7, "label": "Hits", "min": 0, "max": 100, "group": "motion"},
    {"name": "echo", "id": 8, "label": "Echo", "min": 0, "max": 100, "group": "space"},
    {"name": "reverb", "id": 10, "label": "Reverb", "min": 0, "max": 100, "group": "space"},
    {"name": "size", "id": 11, "label": "Size", "min": 0, "max": 100, "group": "space"},
    {"name": "bright", "id": 12, "label": "Bright", "min": 0, "max": 100, "group": "tone"},
    {"name": "swell", "id": 13, "label": "Swell", "min": 0, "max": 100, "group": "tone"},
    {"name": "bell_tone", "id": 14, "label": "Bell tone", "min": 0, "max": 100, "group": "tone"},
    {"name": "motion", "id": 15, "label": "Motion", "min": 0, "max": 100, "group": "motion"},
    {"name": "tempo", "id": 18, "label": "Tempo", "min": 30, "max": 120, "group": "motion"},
    {"name": "bell_oct", "id": 21, "label": "Bell octave", "min": -2, "max": 2, "group": "tone"},
    {"name": "pad_tone", "id": 22, "label": "Pad colour", "min": 0, "max": 1, "group": "tone"},
]

PARAMETER_MAP = {parameter["name"]: parameter for parameter in PARAMETERS}
EPHEMERAL_TTL = int(os.environ.get("AMBIENT_EPHEMERAL_SECONDS", "3600"))
if EPHEMERAL_TTL < 300:
    raise SystemExit("连续段保留时间不能少于 300 秒")
render_lock = threading.Lock()
cleanup_lock = threading.Lock()
last_cleanup = None
NOTE4_STATUS = Path(os.environ.get("NOTE4_STATUS_FILE") or ROOT.parent / "note4-ambient/out/status.json")
NOTE4_SPOOL = Path(os.environ.get("NOTE4_SYNC_SPOOL") or ROOT.parent / "note4-ambient/spool")
SYNC_FILE = Path(os.environ.get("AMBIENT_SYNC_FILE") or Path.home() / ".config/ambient-gui/note4-sync")


def local_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w") as file:
        file.write(text)
    os.replace(temporary, path)


def sync_enabled():
    try:
        return SYNC_FILE.read_text().strip() == "1"
    except OSError:
        return False


def note4_status():
    try:
        raw = json.loads(NOTE4_STATUS.read_text())
        pid = raw["pid"]
        if type(pid) is not int or pid <= 0:
            raise ValueError("pid")
        try:
            os.kill(pid, 0)
            online = True
        except ProcessLookupError:
            online = False
        except PermissionError:
            online = True
        except OSError:
            online = False
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return {"managerOnline": False, "connected": False, "phase": "manager_offline"}
    fields = {name: raw.get(name) for name in ("updated", "preset", "seed", "seconds", "volume", "battery", "charging", "wifi", "syncId")}
    fields.update({
        "managerOnline": online,
        "connected": bool(raw.get("connected")) and online,
        "phase": raw.get("phase", "offline") if online else "manager_offline",
        "syncState": raw.get("syncState", "off"),
    })
    return fields


def queue_sync(output, preset, seconds, seed, normalized, interrupt=False):
    if not sync_enabled():
        return {"enabled": False, "requested": False, "reason": "disabled"}
    if not note4_status()["connected"]:
        return {"enabled": True, "requested": False, "reason": "offline"}
    identifier = time.time_ns()
    lines = ["v=1", f"id={identifier}", f"audio={output.name}", f"preset={preset}", f"seconds={seconds}", f"seed={seed}"]
    if interrupt:
        lines.append("interrupt=1")
    for name, value in sorted(normalized.items(), key=lambda item: PARAMETER_MAP[item[0]]["id"]):
        lines.append(f"set={PARAMETER_MAP[name]['id']}={value}")
    try:
        local_write(NOTE4_SPOOL / f"request-{identifier}.cmd", "\n".join(lines) + "\n")
    except OSError:
        return {"enabled": True, "requested": False, "reason": "local_error"}
    return {"enabled": True, "requested": True, "id": identifier}


def queue_volume(level):
    if not note4_status()["connected"]:
        return {"requested": False, "reason": "offline"}
    identifier = time.time_ns()
    try:
        local_write(NOTE4_SPOOL / f"volume-{identifier}.cmd", f"volume={level}\n")
    except OSError:
        return {"requested": False, "reason": "local_error"}
    return {"requested": True, "value": level, "id": identifier}


def cleanup_ephemeral():
    global last_cleanup
    with cleanup_lock:
        now = time.monotonic()
        if last_cleanup is not None and now - last_cleanup < 300:
            return
        last_cleanup = now
        if not AUDIO_DIR.is_dir():
            return
        cutoff = time.time() - EPHEMERAL_TTL
        removed = 0
        errors = 0
        for pattern, expression in (("e-*.wav", r"e-[0-9a-f]{20}\.wav"), ("?-*.tmp", r"[er]-[0-9a-f]{20}\.tmp")):
            for candidate in AUDIO_DIR.glob(pattern):
                if not re.fullmatch(expression, candidate.name):
                    continue
                try:
                    if candidate.stat().st_mtime < cutoff:
                        candidate.unlink()
                        removed += 1
                except OSError:
                    errors += 1
        if removed or errors:
            print(f"Audio cleanup: removed={removed}, errors={errors}", flush=True)


def cleanup_worker():
    while True:
        cleanup_ephemeral()
        time.sleep(300)


class Handler(BaseHTTPRequestHandler):
    server_version = "AmbientGUI/1.0"

    def log_message(self, *args):
        pass

    def send(self, data, status=200, mime="application/json", headers=None):
        body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def stream(self, path, mime):
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        with path.open("rb") as source:
            shutil.copyfileobj(source, self.wfile, 64 * 1024)

    def body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 65536:
            raise ValueError("invalid body")
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("invalid body")
        return value

    def do_GET(self):
        cleanup_ephemeral()
        path = urlsplit(self.path).path
        if path == "/api/health":
            return self.send({"ok": True, "presets": len(PRESETS), "rendererReady": RENDER_BIN.is_file() and os.access(RENDER_BIN, os.X_OK), "authRequired": False, "ephemeralRetention": EPHEMERAL_TTL})
        if path == "/api/presets":
            return self.send({"presets": PRESETS, "parameters": PARAMETERS, "fields": FIELD_PRESETS})
        if path == "/api/note4":
            return self.send({"syncEnabled": sync_enabled(), "device": note4_status()})
        if path.startswith("/api/recipe"):
            query = urlsplit(self.path).query
            match = re.fullmatch(r"preset=([0-7])", query)
            if not match:
                return self.send({"error": "预设无效"}, 400)
            try:
                result = subprocess.run([str(RENDER_BIN), "--defaults", match.group(1)], capture_output=True, text=True, timeout=5, check=False)
            except (OSError, subprocess.TimeoutExpired):
                return self.send({"error": "无法读取配方，请检查渲染器"}, 503)
            if result.returncode != 0:
                return self.send({"error": "无法读取配方"}, 500)
            values = {}
            for line in result.stdout.splitlines():
                identifier, value = map(int, line.split())
                parameter = next((item for item in PARAMETERS if item["id"] == identifier), None)
                if parameter:
                    values[parameter["name"]] = value
            return self.send({"values": values})
        if path.startswith("/field-audio/"):
            name = path.rsplit("/", 1)[-1]
            field = next((item for item in FIELD_PRESETS if item["audio"] == name), None)
            audio = FIELD_ROOT / "audio" / name
            if field is None or not audio.is_file():
                return self.send({"error": "实地录音不存在"}, 404)
            return self.stream(audio, "audio/mpeg")
        if path.startswith("/audio/"):
            name = path.rsplit("/", 1)[-1]
            if not re.fullmatch(r"[er]-[0-9a-f]{20}\.wav", name):
                return self.send({"error": "音频不存在"}, 404)
            audio = AUDIO_DIR / name
            if not audio.is_file():
                return self.send({"error": "音频不存在"}, 404)
            return self.stream(audio, "audio/wav")
        if path.startswith("/covers/"):
            name = path.rsplit("/", 1)[-1]
            if not re.fullmatch(r"[a-z-]+\.png", name):
                return self.send({"error": "封面不存在"}, 404)
            cover = ROOT / "covers" / name
            if not cover.is_file():
                return self.send({"error": "封面不存在"}, 404)
            return self.stream(cover, "image/png")
        files = {"/": ("index.html", "text/html; charset=utf-8"), "/app.css": ("app.css", "text/css; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"), "/continuous.js": ("continuous.js", "text/javascript; charset=utf-8")}
        if path in files:
            name, mime = files[path]
            return self.stream(ROOT / "static" / name, mime)
        return self.send({"error": "Not found"}, 404)

    def do_POST(self):
        path = urlsplit(self.path).path
        if path not in ("/api/render", "/api/note4", "/api/note4/volume", "/api/field/play"):
            return self.send({"error": "Not found"}, 404)
        if path == "/api/note4/volume":
            try:
                level = self.body().get("volume")
                if type(level) is not int or level not in (10, 25, 50, 75, 100):
                    raise ValueError("volume")
            except (ValueError, KeyError, json.JSONDecodeError):
                return self.send({"error": "音量档位无效"}, 400)
            result = queue_volume(level)
            if not result["requested"] and result["reason"] == "offline":
                return self.send({"error": "NOTE4 未连接，未推送音量", "device": note4_status()}, 409)
            if not result["requested"]:
                return self.send({"error": "无法通知 NOTE4 管理端"}, 503)
            return self.send({"ok": True, "syncEnabled": sync_enabled(), "device": note4_status(), "volume": result})
        if path == "/api/note4":
            try:
                enabled = self.body().get("enabled")
                if type(enabled) is not bool:
                    raise ValueError("enabled")
                local_write(SYNC_FILE, "1\n" if enabled else "0\n")
                if not enabled:
                    local_write(NOTE4_SPOOL / f"request-{time.time_ns()}.cmd", "disable\n")
            except (ValueError, KeyError, json.JSONDecodeError):
                return self.send({"error": "同步开关参数无效"}, 400)
            except OSError:
                return self.send({"error": "无法保存同步开关或通知管理端"}, 503)
            return self.send({"ok": True, "syncEnabled": enabled, "device": note4_status()})
        if path == "/api/field/play":
            try:
                identifier = self.body().get("id")
                if type(identifier) is not int or identifier not in FIELD_MAP:
                    raise ValueError("id")
                field = FIELD_MAP[identifier]
                audio = FIELD_ROOT / "audio" / field["audio"]
                if not audio.is_file():
                    return self.send({"error": "实地录音文件不存在"}, 404)
                sync = queue_sync(audio, field["id"], field["seconds"], 0, {}, interrupt=True)
            except (ValueError, KeyError, json.JSONDecodeError):
                return self.send({"error": "实地录音编号无效"}, 400)
            return self.send({"ok": True, "field": field, "note4": sync})
        try:
            request = self.body()
            preset = request.get("preset", -1)
            seconds = request.get("seconds", 300)
            seed = request.get("seed", 42)
            ephemeral = request.get("ephemeral", False)
            interrupt = request.get("interrupt", False)
            if type(preset) is not int or not 0 <= preset < len(PRESETS):
                raise ValueError("preset")
            if type(seconds) is not int or not 15 <= seconds <= 300:
                raise ValueError("seconds")
            if type(seed) is not int or not 0 <= seed <= 65535:
                raise ValueError("seed")
            if type(ephemeral) is not bool or type(interrupt) is not bool:
                raise ValueError("flags")
            overrides = request.get("overrides", {})
            if not isinstance(overrides, dict):
                raise ValueError("overrides")
            normalized = {}
            for name, value in overrides.items():
                parameter = PARAMETER_MAP[name]
                if type(value) is not int or not parameter["min"] <= value <= parameter["max"]:
                    raise ValueError(name)
                normalized[name] = value
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            return self.send({"error": "预设、时长或参数值无效"}, 400)
        identity = hashlib.sha256(json.dumps({"preset": preset, "seconds": seconds, "seed": seed, "overrides": normalized}, sort_keys=True).encode()).hexdigest()[:20]
        output = AUDIO_DIR / f"{'e' if ephemeral else 'r'}-{identity}.wav"
        if output.is_file():
            if ephemeral:
                output.touch()
            return self.send({"audio": f"/audio/{output.name}", "cached": True, "seconds": seconds, "preset": preset, "seed": seed, "expiresIn": EPHEMERAL_TTL if ephemeral else None, "note4": {"enabled": sync_enabled(), "requested": False, "reason": "cached"}})
        if not render_lock.acquire(blocking=False):
            return self.send({"error": "另一个渲染正在进行，请稍后"}, 429)
        temporary = output.with_suffix(".tmp")
        try:
            AUDIO_DIR.mkdir(parents=True, exist_ok=True)
            AUDIO_DIR.chmod(0o700)
            arguments = [str(RENDER_BIN), str(preset), str(seconds), str(temporary), str(seed)]
            for name, value in sorted(normalized.items()):
                arguments.extend(["--set", f"{PARAMETER_MAP[name]['id']}={value}"])
            result = subprocess.run(arguments, capture_output=True, text=True, timeout=180, check=False)
            if result.returncode != 0:
                return self.send({"error": "渲染失败", "detail": (result.stderr or result.stdout)[-1000:]}, 500)
            temporary.replace(output)
            sync = queue_sync(output, preset, seconds, seed, normalized, interrupt=interrupt)
            return self.send({"audio": f"/audio/{output.name}", "cached": False, "seconds": seconds, "preset": preset, "seed": seed, "expiresIn": EPHEMERAL_TTL if ephemeral else None, "summary": result.stdout.strip(), "note4": sync})
        except subprocess.TimeoutExpired:
            return self.send({"error": "渲染超时"}, 504)
        except OSError:
            return self.send({"error": "渲染器或输出目录不可用"}, 503)
        finally:
            temporary.unlink(missing_ok=True)
            render_lock.release()


if __name__ == "__main__":
    import signal

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = False
    server.block_on_close = True
    threading.Thread(target=cleanup_worker, name="audio-cleanup", daemon=True).start()

    def stop(signum, frame):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(f"Ambient GUI: http://{HOST}:{PORT}/", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
