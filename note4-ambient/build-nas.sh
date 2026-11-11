#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PATH="$HOME/.cargo/bin:$PATH"
if [ -d "$root/.tools/bin/nas" ]; then
    export PATH="$root/.tools/bin/nas:$PATH"
fi
if [ -d "$root/.tools/cmake-venv/bin" ]; then
    export PATH="$root/.tools/cmake-venv/bin:$PATH"
fi
if [ -x "$root/.tools/bin/nas/cc" ] && [ -x "$root/.tools/bin/nas/c++" ]; then
    export CC="$root/.tools/bin/nas/cc"
    export CXX="$root/.tools/bin/nas/c++"
fi
export OPUS_STATIC=1
sdk="$root/zectrix-local-push-sdk"
patch="$root/note4-ambient/patches/sdk-diagnostics.patch"
if git -C "$sdk" apply --check "$patch" 2>/dev/null; then
    git -C "$sdk" apply "$patch"
elif ! git -C "$sdk" apply --reverse --check "$patch" 2>/dev/null; then
    printf '%s\n' "SDK source does not match the expected diagnostics patch state." >&2
    exit 1
fi
cd "$root/note4-ambient"
cargo test --locked
cargo build --release --locked
