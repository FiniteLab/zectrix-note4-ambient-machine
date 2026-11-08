#!/bin/sh
set -eu
umask 077
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
data=${AMBIENT_GUI_DATA:-"$root/out"}
host=${AMBIENT_GUI_HOST:-0.0.0.0}
port=${AMBIENT_GUI_PORT:-8765}
token=${AMBIENT_GUI_TOKEN_FILE:-"$HOME/.config/ambient-gui/token"}
renderer=${AMB_RENDER_BIN:-"$root/../ambient-synth/out/amb-render"}
pid_file="$data/server.pid"
mkdir -p "$data"
chmod 700 "$data"
if [ -f "$pid_file" ]; then
    pid=$(cat "$pid_file")
    case $pid in ''|*[!0-9]*) printf '%s\n' "Invalid PID file: $pid_file" >&2; exit 1;; esac
    if kill -0 "$pid" 2>/dev/null; then
        printf 'AMB Atelier is already running (PID %s).\n' "$pid"
        exit 0
    fi
    rm -f "$pid_file"
fi
if [ ! -x "$renderer" ]; then
    printf '%s\n' "Build the AMB renderer first: $renderer" >&2
    exit 1
fi
if [ ! -s "$token" ]; then
    token_dir=$(dirname -- "$token")
    mkdir -p "$token_dir"
    chmod 700 "$token_dir"
    TOKEN_FILE="$token" python3 -c 'import os, secrets; from pathlib import Path; Path(os.environ["TOKEN_FILE"]).write_text(secrets.token_hex(32) + "\n")'
fi
chmod 600 "$token"
AMBIENT_GUI_HOST=$host
AMBIENT_GUI_PORT=$port
AMBIENT_GUI_TOKEN_FILE=$token
AMBIENT_GUI_DATA=$data
AMB_RENDER_BIN=$renderer
export AMBIENT_GUI_HOST AMBIENT_GUI_PORT AMBIENT_GUI_TOKEN_FILE AMBIENT_GUI_DATA AMB_RENDER_BIN
nohup python3 "$root/server.py" >>"$data/server.log" 2>&1 &
pid=$!
printf '%s\n' "$pid" >"$pid_file"
sleep 1
if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$pid_file"
    printf '%s\n' "AMB Atelier did not start; see $data/server.log" >&2
    exit 1
fi
printf 'AMB Atelier started on port %s (PID %s).\n' "$port" "$pid"
