#!/bin/sh
set -eu
umask 077
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
data="$root/out"
pid_file="$data/server.pid"
if systemctl --user is-active --quiet art-clock.service || pgrep -x art-clock >/dev/null 2>&1; then
    printf '%s\n' "art-clock is running; stop it before starting the ambient manager." >&2
    exit 1
fi
if [ -f "$pid_file" ]; then
    pid=$(cat "$pid_file")
    case $pid in ''|*[!0-9]*) printf '%s\n' "Invalid PID file." >&2; exit 1;; esac
    if kill -0 "$pid" 2>/dev/null; then
        printf 'Ambient manager is already running (PID %s).\n' "$pid"
        exit 0
    fi
    rm -f "$pid_file"
fi
if [ -n "$(ss -ulpnH 'sport = :32343')" ]; then
    printf '%s\n' "UDP 32343 is already occupied; not starting another manager." >&2
    exit 1
fi
if [ ! -x "$root/target/release/note4-ambient" ]; then
    printf '%s\n' "Build note4-ambient first." >&2
    exit 1
fi
for name in garden departures voices afternoon night-bus shoreline glass tides rain-street cafe city-voices midnight-road; do
    if [ ! -s "$root/assets/loading-$name.png" ]; then
        printf 'Missing loading asset: %s\n' "$root/assets/loading-$name.png" >&2
        exit 1
    fi
done
if [ ! -s "$root/assets/startup.png" ]; then
    printf '%s\n' "Missing startup asset." >&2
    exit 1
fi
if [ ! -s "$HOME/.config/note4-ambient/target" ]; then
    printf '%s\n' "Configure the NOTE4 target locally before starting." >&2
    exit 1
fi
mkdir -p "$data"
chmod 700 "$data"
nohup "$root/target/release/note4-ambient" serve >>"$data/server.log" 2>&1 &
pid=$!
printf '%s\n' "$pid" >"$pid_file"
sleep 1
if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$pid_file"
    printf '%s\n' "Ambient manager did not start; see $data/server.log" >&2
    exit 1
fi
printf 'Ambient manager started (PID %s).\n' "$pid"
