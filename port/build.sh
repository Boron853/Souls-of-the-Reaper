#!/bin/sh
# build.sh - configure and build the Diablo III port on Linux.
#
# Builds the recompiled game against the ReXGlue SDK installed by
# build_sdk.sh, using the linux-amd64-* CMake presets. Produces a native ELF at
# port/out/build/linux-amd64-<config>/diablo3.
#
# Requirements (Debian/Ubuntu names):
#   clang/clang++ >= 18, lld, cmake >= 3.25, ninja-build, git,
#   pkg-config, libgtk-3-dev, libx11-xcb-dev, libwayland-dev,
#   libdecor-0-dev, libvulkan-dev, libasound2-dev, libpulse-dev,
#   libudev-dev, libglvnd-dev
# The SDK vendors SDL3, Vulkan headers/loader glue (volk), FFmpeg, glslang and
# friends, so those are not system packages.
#
# Usage:
#   ./port/build.sh [-c Debug|Release|RelWithDebInfo] [-j N] [--clean]
#                   [--sdk DIR] [--no-patch]
#
# Environment:
#   REXSDK_DIR      ReXGlue SDK checkout (default: <repo>/rexglue-sdk)
#   REXSDK_INSTALL  SDK install prefix (default: <SDK>/out/install/linux-amd64)
#   REXSDK_PREBUILT 1 when using a prebuilt SDK bundle (no source checkout)
#   CC / CXX        Compiler overrides (default: clang-20 if present, else clang)
#   JOBS            Parallel build jobs

set -eu

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PORT_DIR="$REPO_ROOT/port"

CONFIG=RelWithDebInfo
JOBS=${JOBS:-}
SDK=${REXSDK_DIR:-"$REPO_ROOT/rexglue-sdk"}
SDK_INSTALL=${REXSDK_INSTALL:-"$SDK/out/install/linux-amd64"}
PREBUILT=${REXSDK_PREBUILT:-0}
CLEAN=0
APPLY_PATCH=1

usage() {
    sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

while [ $# -gt 0 ]; do
    case "$1" in
        -c|--config) CONFIG=$2; shift 2 ;;
        -j|--jobs) JOBS=$2; shift 2 ;;
        -s|--sdk) SDK=$2; shift 2 ;;
        --clean) CLEAN=1; shift ;;
        --no-patch) APPLY_PATCH=0; shift ;;
        -h|--help) usage 0 ;;
        *) echo "Unknown argument: $1" >&2; usage 1 ;;
    esac
done

case "$CONFIG" in
    Debug) PRESET=linux-amd64-debug ;;
    Release) PRESET=linux-amd64-release ;;
    RelWithDebInfo) PRESET=linux-amd64-relwithdebinfo ;;
    *) echo "Config must be Debug, Release or RelWithDebInfo" >&2; exit 1 ;;
esac

BUILD_DIR="$PORT_DIR/out/build/$PRESET"

die() { echo "ERROR: $*" >&2; exit 1; }

command -v cmake >/dev/null 2>&1 || die "cmake not found (need >= 3.25)"
command -v ninja >/dev/null 2>&1 || die "ninja not found"
command -v pkg-config >/dev/null 2>&1 || die "pkg-config not found (needed for Wayland/X11)"
if [ "$PREBUILT" != 1 ]; then
    [ -d "$SDK" ] || die "ReXGlue SDK not found at $SDK (clone it or set REXSDK_DIR)"
fi

if [ -n "${CC:-}" ]; then COMPILER_C=$CC; elif command -v clang-20 >/dev/null 2>&1; then COMPILER_C=clang-20; else COMPILER_C=clang; fi
if [ -n "${CXX:-}" ]; then COMPILER_CXX=$CXX; elif command -v clang++-20 >/dev/null 2>&1; then COMPILER_CXX=clang++-20; else COMPILER_CXX=clang++; fi
command -v "$COMPILER_C" >/dev/null 2>&1 || die "C compiler '$COMPILER_C' not found"
command -v "$COMPILER_CXX" >/dev/null 2>&1 || die "C++ compiler '$COMPILER_CXX' not found"

if [ "$APPLY_PATCH" = 1 ] && [ "$PREBUILT" != 1 ]; then
    "$PORT_DIR/apply_sdk_patches.sh" "$SDK"
fi

if [ ! -f "$PORT_DIR/generated/default/sources.cmake" ]; then
    die "port/generated/default/sources.cmake is missing. Run ./port/codegen.sh first (needs game/default.xex)."
fi
if [ ! -f "$SDK_INSTALL/lib/cmake/rexglue/rexglueConfig.cmake" ] &&
   [ ! -f "$SDK_INSTALL/lib64/cmake/rexglue/rexglueConfig.cmake" ]; then
    die "ReXGlue SDK is not installed at $SDK_INSTALL. Build/install the SDK first (see docs/LINUX.md)."
fi

SDK_MODE=source
[ "$PREBUILT" = 1 ] && SDK_MODE=prebuilt
SDK_STAMP_VALUE="$SDK_INSTALL|$SDK_MODE"
SDK_STAMP="$BUILD_DIR/.sotr-sdk-prefix"
if [ -d "$BUILD_DIR" ]; then
    cached_prefix=""
    if [ -f "$BUILD_DIR/CMakeCache.txt" ]; then
        cached_prefix=$(sed -n 's/^CMAKE_PREFIX_PATH:[^=]*=//p' "$BUILD_DIR/CMakeCache.txt" | head -n 1)
    fi
    if [ -f "$SDK_STAMP" ] && [ "$(cat "$SDK_STAMP")" != "$SDK_STAMP_VALUE" ]; then
        echo "==> SDK prefix/mode changed; cleaning CMake cache"
        rm -rf "$BUILD_DIR"
    elif [ -n "$cached_prefix" ] && [ "$cached_prefix" != "$SDK_INSTALL" ]; then
        echo "==> SDK prefix changed; cleaning CMake cache"
        rm -rf "$BUILD_DIR"
    fi
fi

if [ "$CLEAN" = 1 ] && [ -d "$BUILD_DIR" ]; then
    echo "==> Cleaning $BUILD_DIR"
    rm -rf "$BUILD_DIR"
fi
mkdir -p "$BUILD_DIR"
printf '%s\n' "$SDK_STAMP_VALUE" > "$SDK_STAMP"

REXGLUE_CMAKE_DIR="$SDK_INSTALL/lib64/cmake/rexglue"
[ -d "$REXGLUE_CMAKE_DIR" ] || REXGLUE_CMAKE_DIR="$SDK_INSTALL/lib/cmake/rexglue"

CMAKE_ARGS="-DCMAKE_PREFIX_PATH=$SDK_INSTALL -DREXGLUE_ENABLE_TRACY=OFF"
if [ -d "$REXGLUE_CMAKE_DIR" ]; then
    # CMAKE_PREFIX_PATH alone does not override an existing rexglue_DIR cache
    # entry when switching between SDK install prefixes (for example from a
    # developer checkout to the installer-managed .install SDK).
    CMAKE_ARGS="$CMAKE_ARGS -Drexglue_DIR=$REXGLUE_CMAKE_DIR"
fi
# Override the preset compiler only when the user asked for a specific one or
# clang-20 is unavailable (the preset hardcodes clang-20).
if [ -n "${CC:-}${CXX:-}" ] || ! command -v clang-20 >/dev/null 2>&1; then
    CMAKE_ARGS="$CMAKE_ARGS -DCMAKE_C_COMPILER=$COMPILER_C -DCMAKE_CXX_COMPILER=$COMPILER_CXX"
fi

echo "==> Configuring ($PRESET)"
# --preset resolves CMakePresets.json from the working directory.
# shellcheck disable=SC2086
( cd "$PORT_DIR" && cmake --preset "$PRESET" $CMAKE_ARGS )

echo "==> Building diablo3 ($PRESET)"
if [ -n "$JOBS" ]; then
    cmake --build "$BUILD_DIR" --target diablo3 --parallel "$JOBS"
else
    cmake --build "$BUILD_DIR" --target diablo3
fi

echo "==> OK. Binary at $BUILD_DIR/diablo3"
