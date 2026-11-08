#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
pid_file="$root/out/server.pid"
if [ ! -f "$pid_file" ]; then
    printf '%s\n' "Ambient manager is not running."
    exit 0
fi
pid=$(cat "$pid_file")
case $pid in ''|*[!0-9]*) printf '%s\n' "Invalid PID file." >&2; exit 1;; esac
if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$pid_file"
    printf '%s\n' "Ambient manager is not running; removed the stale PID file."
    exit 0
fi
command=$(tr '\0' ' ' <"/proc/$pid/cmdline")
case $command in
    *"$root/target/release/note4-ambient serve"*) ;;
    *) printf '%s\n' "PID $pid does not belong to this ambient manager; not stopping it." >&2; exit 1;;
esac
kill -TERM "$pid"
count=0
while kill -0 "$pid" 2>/dev/null; do
    if [ "$count" -ge 150 ]; then
        printf '%s\n' "The manager is still closing the device session; PID file retained." >&2
        exit 1
    fi
    sleep 0.1
    count=$((count + 1))
done
rm -f "$pid_file"
printf '%s\n' "Ambient manager stopped."
