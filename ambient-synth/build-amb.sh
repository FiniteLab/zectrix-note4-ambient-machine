#!/bin/sh
set -eu
module=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
reference=${AMB_REFERENCE:-"$module/../fm1-amb-reference"}
patch="$module/patches/amb-cpu.patch"
if [ -f "$patch" ]; then
    if git -C "$reference" apply --check "$patch" 2>/dev/null; then
        git -C "$reference" apply "$patch"
    elif ! git -C "$reference" apply --reverse --check "$patch" 2>/dev/null; then
        printf '%s\n' "AMB reference does not match the expected optimization patch state." >&2
        exit 1
    fi
fi
mkdir -p "$module/out"
opt=${OPT:--O3}
if [ "${NATIVE:-0}" = 1 ]; then
    opt="$opt -march=native"
fi
${CC:-cc} $opt -ffp-contract=off -std=c99 -Wall -Wextra -Werror -DEN_HOST \
    -I"$reference/app/dsp" -I"$reference/base/include" \
    -o "$module/out/amb-render" "$module/amb_render.c" "$reference/app/dsp/amb.c" -lm
