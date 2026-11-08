#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
data=${AMBIENT_GUI_DATA:-"$root/out"}
pid_file="$data/server.pid"
if [ ! -f "$pid_file" ]; then
    printf '%s\n' "AMB Atelier is not running."
    exit 0
fi
pid=$(cat "$pid_file")
case $pid in ''|*[!0-9]*) printf '%s\n' "Invalid PID file: $pid_file" >&2; exit 1;; esac
if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$pid_file"
    printf '%s\n' "AMB Atelier is not running; removed the stale PID file."
    exit 0
fi
if [ -r "/proc/$pid/cmdline" ]; then
    command=$(tr '\0' ' ' <"/proc/$pid/cmdline")
else
    command=$(ps -p "$pid" -o command=)
fi
case $command in
    *"$root/server.py"*) ;;
    *) printf '%s\n' "PID $pid does not belong to this installation; not stopping it." >&2; exit 1;;
esac
kill -TERM "$pid"
count=0
while kill -0 "$pid" 2>/dev/null; do
    if [ "$count" -ge 150 ]; then
        printf '%s\n' "The server is still finishing its current request; PID file retained." >&2
        exit 1
    fi
    sleep 0.1
    count=$((count + 1))
done
rm -f "$pid_file"
printf '%s\n' "AMB Atelier stopped."
