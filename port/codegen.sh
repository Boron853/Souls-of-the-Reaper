#!/bin/sh
# codegen.sh - run ReXGlue 0.10 codegen for the Diablo III port on Linux.
#
# Uses the SDK installed by build_sdk.sh (building it first if needed),
# translates game/default.xex into port/generated/default/, then re-applies the
# hand patches that codegen cannot emit (setjmp/longjmp and main-menu exit).
#
# This is the Linux equivalent of steps 1-2 in the README.
#
# Requirements: same as build.sh (clang >= 18, cmake, ninja, pkg-config,
# Wayland/X11/Vulkan/audio development headers), plus the decrypted Xbox 360 XEX
# at game/default.xex (manifest paths are relative to port/).
#
# Usage:
#   ./port/codegen.sh [--sdk DIR] [--game-dir DIR] [--force] [-j N]
#
# Environment:
#   REXSDK_DIR      ReXGlue SDK checkout (default: <repo>/rexglue-sdk)
#   REXSDK_INSTALL  SDK install prefix (default: <SDK>/out/install/linux-amd64)
#   REXSDK_PREBUILT 1 when using a prebuilt SDK bundle (no source checkout)
#   GAME_DIR        Extracted game data directory (default: <repo>/game)
#   CC / CXX        Compiler overrides
#   JOBS            Parallel build jobs

set -eu

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PORT_DIR="$REPO_ROOT/port"
MANIFEST="$PORT_DIR/diablo3_manifest.toml"

SDK=${REXSDK_DIR:-"$REPO_ROOT/rexglue-sdk"}
SDK_INSTALL=${REXSDK_INSTALL:-"$SDK/out/install/linux-amd64"}
PREBUILT=${REXSDK_PREBUILT:-0}
GAME_DIR=${GAME_DIR:-"$REPO_ROOT/game"}
JOBS=${JOBS:-}
FORCE=""

usage() {
    sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

while [ $# -gt 0 ]; do
    case "$1" in
        -s|--sdk) SDK=$2; shift 2 ;;
        -g|--game-dir) GAME_DIR=$2; shift 2 ;;
        -j|--jobs) JOBS=$2; shift 2 ;;
        -f|--force) FORCE="-f"; shift ;;
        -h|--help) usage 0 ;;
        *) echo "Unknown argument: $1" >&2; usage 1 ;;
    esac
done

die() { echo "ERROR: $*" >&2; exit 1; }

case "$GAME_DIR" in
    /*) ;;
    *) GAME_DIR="$REPO_ROOT/$GAME_DIR" ;;
esac
XEX="$GAME_DIR/default.xex"

command -v cmake >/dev/null 2>&1 || die "cmake not found (need >= 3.25)"
command -v ninja >/dev/null 2>&1 || die "ninja not found"
command -v pkg-config >/dev/null 2>&1 || die "pkg-config not found (needed for Wayland/X11)"
if [ "$PREBUILT" != 1 ]; then
    [ -d "$SDK" ] || die "ReXGlue SDK not found at $SDK (clone it or set REXSDK_DIR)"
fi
[ -f "$MANIFEST" ] || die "manifest not found: $MANIFEST"
[ -f "$XEX" ] || die "missing $XEX (decrypted XEX; see docs/LINUX.md)"

# Codegen resolves manifest paths relative to port/. Write a local manifest
# when the game data is not in the default game/ directory.
if [ "$GAME_DIR" != "$REPO_ROOT/game" ]; then
    LOCAL_MANIFEST="$PORT_DIR/local_manifest.toml"
    python3 - "$MANIFEST" "$LOCAL_MANIFEST" "$GAME_DIR" <<'PY'
import json
import sys
from pathlib import Path

source, target, game_dir = sys.argv[1:4]
text = Path(source).read_text(encoding="utf-8")
text = text.replace(
    'game_root = "../game"',
    f"game_root = {json.dumps(game_dir)}",
    1,
)
text = text.replace(
    'file_path = "../game/default.xex"',
    f"file_path = {json.dumps(game_dir + '/default.xex')}",
    1,
)
Path(target).write_text(text, encoding="utf-8")
PY
    MANIFEST="$LOCAL_MANIFEST"
fi

if [ -n "${CC:-}" ]; then COMPILER_C=$CC; elif command -v clang-20 >/dev/null 2>&1; then COMPILER_C=clang-20; else COMPILER_C=clang; fi
if [ -n "${CXX:-}" ]; then COMPILER_CXX=$CXX; elif command -v clang++-20 >/dev/null 2>&1; then COMPILER_CXX=clang++-20; else COMPILER_CXX=clang++; fi

if [ "$PREBUILT" != 1 ]; then
    "$PORT_DIR/apply_sdk_patches.sh" "$SDK"
fi

REXGLUE="$SDK_INSTALL/bin/rexglue"
if [ "$PREBUILT" = 1 ]; then
    [ -x "$REXGLUE" ] || die "prebuilt SDK is missing $REXGLUE"
else
    [ -x "$REXGLUE" ] || REXGLUE="$SDK/out/build/linux-amd64/RelWithDebInfo/rexgluerd"
    [ -x "$REXGLUE" ] || REXGLUE="$SDK/out/build/linux-amd64/RelWithDebInfo/rexglue"
    [ -x "$REXGLUE" ] || REXGLUE="$SDK/out/linux-amd64/RelWithDebInfo/rexgluerd"
    [ -x "$REXGLUE" ] || REXGLUE="$SDK/out/linux-amd64/RelWithDebInfo/rexglue"
    [ -x "$REXGLUE" ] || REXGLUE="$SDK/out/linux-amd64/rexglue"
    if [ ! -x "$REXGLUE" ]; then
        echo "==> ReXGlue SDK is not built/installed; building it now"
        if [ -n "$JOBS" ]; then
            "$PORT_DIR/build_sdk.sh" -j "$JOBS"
        else
            "$PORT_DIR/build_sdk.sh"
        fi
        REXGLUE="$SDK_INSTALL/bin/rexglue"
        [ -x "$REXGLUE" ] || REXGLUE="$SDK/out/build/linux-amd64/RelWithDebInfo/rexglue"
    fi
fi
[ -x "$REXGLUE" ] || die "could not locate the built rexglue binary"

echo "==> Running codegen (this takes ~12 minutes)"
# shellcheck disable=SC2086
( cd "$REPO_ROOT" && "$REXGLUE" --log-level info --log-file "$PORT_DIR/cg.log" $FORCE codegen "$MANIFEST" )

echo "==> Re-applying hand patches to port/generated"
python3 "$PORT_DIR/apply_generated_patches.py"

echo "==> OK. Generated code is in $PORT_DIR/generated"
