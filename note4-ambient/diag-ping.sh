#!/bin/sh
set -eu
umask 077
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
data="$root/out"
pid_file="$data/ping.pid"
log="$data/ping.log"
target_file="$HOME/.config/note4-ambient/target"

is_running() {
    [ -f "$pid_file" ] || return 1
    pid=$(cat "$pid_file")
    case $pid in ''|*[!0-9]*) return 1;; esac
    kill -0 "$pid" 2>/dev/null
}

start() {
    if is_running; then
        printf 'Ping diagnostic is already running (PID %s).\n' "$pid"
        return 0
    fi
    command -v ping >/dev/null 2>&1 || { printf '%s\n' 'ping is not installed.' >&2; return 1; }
    [ -r "$target_file" ] || { printf '%s\n' 'NOTE4 target is not configured.' >&2; return 1; }
    target=$(tr -d '\r\n' <"$target_file")
    case $target in ''|*[!0-9.]*) printf '%s\n' 'NOTE4 target is not an IPv4 address.' >&2; return 1;; esac
    mkdir -p "$data"
    chmod 700 "$data"
    nohup python3 - "$target" >>"$log" 2>&1 <<'PY' &
import signal
import subprocess
import sys

target = sys.argv[1]
process = None
stopping = False

def stop(*_):
    global stopping
    stopping = True
    if process is not None and process.poll() is None:
        process.terminate()

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
try:
    process = subprocess.Popen(
        ["ping", "-n", "-D", "-O", "-i", "1", target],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    if stopping:
        process.terminate()
    for line in process.stdout:
        print(line.replace(target, "[device]"), end="", flush=True)
except Exception:
    print("ping diagnostic stopped with a local execution error", flush=True)
finally:
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
PY
    pid=$!
    printf '%s\n' "$pid" >"$pid_file"
    sleep 0.2
    if ! kill -0 "$pid" 2>/dev/null; then
        rm -f "$pid_file"
        printf '%s\n' 'Ping diagnostic did not start.' >&2
        return 1
    fi
    printf 'Ping diagnostic started (PID %s).\n' "$pid"
}

stop() {
    if ! is_running; then
        rm -f "$pid_file"
        printf '%s\n' 'Ping diagnostic is not running.'
        return 0
    fi
    output=$(readlink "/proc/$pid/fd/1" 2>/dev/null || true)
    if [ "$output" != "$log" ]; then
        printf '%s\n' 'PID does not belong to this ping diagnostic; not stopping it.' >&2
        return 1
    fi
    kill -TERM "$pid"
    count=0
    while kill -0 "$pid" 2>/dev/null; do
        if [ "$count" -ge 50 ]; then
            printf '%s\n' 'Ping diagnostic is still stopping; PID file retained.' >&2
            return 1
        fi
        sleep 0.1
        count=$((count + 1))
    done
    rm -f "$pid_file"
    printf '%s\n' 'Ping diagnostic stopped.'
}

case ${1:-} in
    start) start;;
    stop) stop;;
    status)
        if is_running; then
            printf 'Ping diagnostic is running (PID %s).\n' "$pid"
        else
            printf '%s\n' 'Ping diagnostic is not running.'
        fi
        ;;
    *) printf 'Usage: %s start|stop|status\n' "${0##*/}" >&2; exit 2;;
esac
