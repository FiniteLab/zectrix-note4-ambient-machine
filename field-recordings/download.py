#!/usr/bin/env python3
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "audio"
OUT.mkdir(exist_ok=True)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


for item in json.loads((ROOT / "sources.json").read_text()):
    output = OUT / item["audio"]
    if output.is_file() and digest(output) == item["sha256"]:
        print(f"{item['name']}: already verified")
        continue
    downloaded = output.with_suffix(".download")
    normalized = output.with_suffix(".tmp")
    try:
        subprocess.run(["curl", "--silent", "--show-error", "--fail", "--location", "--output", str(downloaded), item["download"]], check=True)
        gain = {"rain-street": "21.3dB", "midnight-road": "32.5dB"}.get(item["name"])
        if gain:
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(downloaded), "-af", f"volume={gain}", "-c:a", "libmp3lame", "-b:a", "192k", str(normalized)], check=True)
            os.replace(normalized, output)
            downloaded.unlink()
        else:
            os.replace(downloaded, output)
        if digest(output) != item["sha256"]:
            raise RuntimeError(f"{item['name']}: hash differs from the reviewed recording")
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(output)], check=True, capture_output=True, text=True)
        seconds = float(json.loads(probe.stdout)["format"]["duration"])
        if abs(seconds - item["seconds"]) > 1:
            raise RuntimeError(f"{item['name']}: duration differs from the reviewed recording")
        print(f"{item['name']}: downloaded and verified ({seconds:.3f} s)")
    finally:
        downloaded.unlink(missing_ok=True)
        normalized.unlink(missing_ok=True)
