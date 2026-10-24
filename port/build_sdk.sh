#!/bin/sh
# build_sdk.sh - build and install the pinned ReXGlue 0.10 SDK on Linux.
#
# Usage:
#   ./port/build_sdk.sh [--clean] [-j N]
#
# Environment:
#   REXSDK_DIR      SDK checkout (default: <repo>/rexglue-sdk)
#   REXSDK_BUILD    SDK build directory (default: <SDK>/out/build/linux-amd64)
#   REXSDK_INSTALL  SDK install prefix (default: <SDK>/out/install/linux-amd64)
#   JOBS            Parallel build jobs

set -eu

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PORT_DIR="$REPO_ROOT/port"
SDK=${REXSDK_DIR:-"$REPO_ROOT/rexglue-sdk"}
SDK_BUILD=${REXSDK_BUILD:-"$SDK/out/build/linux-amd64"}
SDK_INSTALL=${REXSDK_INSTALL:-"$SDK/out/install/linux-amd64"}
JOBS=${JOBS:-}
CLEAN=0

usage() {
    sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

while [ $# -gt 0 ]; do
    case "$1" in
        -j|--jobs) JOBS=$2; shift 2 ;;
        --clean) CLEAN=1; shift ;;
        -h|--help) usage 0 ;;
        *) echo "Unknown argument: $1" >&2; usage 1 ;;
    esac
done

die() { echo "ERROR: $*" >&2; exit 1; }

command -v cmake >/dev/null 2>&1 || die "cmake not found (need >= 3.25)"
command -v ninja >/dev/null 2>&1 || die "ninja not found"
[ -d "$SDK" ] || die "ReXGlue SDK not found at $SDK (clone it or set REXSDK_DIR)"

"$PORT_DIR/apply_sdk_patches.sh" "$SDK"

if [ "$CLEAN" = 1 ]; then
    rm -rf "$SDK_BUILD"
fi

WAYLAND_SCANNER_ARG=""
if command -v wayland-scanner >/dev/null 2>&1; then
    WAYLAND_SCANNER_ARG="-DWAYLAND_SCANNER=$(command -v wayland-scanner)"
else
    echo "WARNING: wayland-scanner not found; SDL will build without native Wayland support." >&2
    echo "         Install libwayland-bin/libwayland-dev or use the Nix dev shell." >&2
fi

echo "==> Configuring ReXGlue SDK"
( cd "$SDK" && cmake --preset linux-amd64 \
    $WAYLAND_SCANNER_ARG \
    -DSDL_WAYLAND=ON \
    -DREXGLUE_ENABLE_TRACY=OFF \
    -DREXGLUE_BUILD_TESTS=OFF \
    -DREXGLUE_USE_D3D12=OFF \
    -DSDL_X11_XTEST=OFF \
    -DSDL_REVISION=SDL-local )

echo "==> Building ReXGlue SDK"
if [ -n "$JOBS" ]; then
    cmake --build "$SDK_BUILD" --config RelWithDebInfo --parallel "$JOBS"
else
    cmake --build "$SDK_BUILD" --config RelWithDebInfo
fi

echo "==> Installing ReXGlue SDK to $SDK_INSTALL"
cmake --install "$SDK_BUILD" --config RelWithDebInfo --prefix "$SDK_INSTALL"

echo "==> OK. SDK installed at $SDK_INSTALL"
