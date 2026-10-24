#!/bin/sh
# apply_sdk_patches.sh - apply the port's ReXGlue SDK patches, idempotently.
#
# The SDK is pinned in port/rexglue.lock.json. The patches are applied in the
# same order as port/build.ps1: System Link source files first, then the
# registration/object-reference/keyboard/username/System Link patches, then the
# Windows/D3D12 runtime patch, and finally the Linux delta.
#
# A stamp file records the patch-set hash so repeated builds skip the patch
# step. If the patches changed, use a clean SDK checkout.
#
# Usage: ./port/apply_sdk_patches.sh [SDK_DIR]
# Default SDK_DIR: <repo>/rexglue-sdk (or REXSDK_DIR).

set -eu

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SDK=${1:-${REXSDK_DIR:-"$REPO_ROOT/rexglue-sdk"}}
LOCK="$REPO_ROOT/port/rexglue.lock.json"
SYSTEMLINK_DIR="$REPO_ROOT/patches/systemlink"
STAMP="$SDK/.sotr-patches"

SDK_PATCHES="
rexglue-registration.patch
rexglue-object-reference.patch
rexglue-keyboard.patch
rexglue-username.patch
rexglue-systemlink-net.patch
rexglue-sdk.patch
rexglue-sdk-linux.patch
rexglue-dynamic-resolution.patch
"

[ -d "$SDK" ] || { echo "ERROR: SDK not found at $SDK" >&2; exit 1; }
git -C "$SDK" rev-parse --git-dir >/dev/null 2>&1 || {
    echo "ERROR: $SDK is not a git checkout; patches are applied with git apply" >&2
    exit 1
}

if [ -f "$LOCK" ]; then
    expected=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["commit"])' "$LOCK")
    actual=$(git -C "$SDK" rev-parse HEAD)
    if [ "$actual" != "$expected" ]; then
        echo "WARNING: SDK HEAD is $actual; rexglue.lock.json expects $expected." >&2
        echo "         Applying patches anyway; use a clean checkout for a reproducible build." >&2
    fi
fi

patch_hash() {
    {
        for patch_name in $SDK_PATCHES; do
            printf '%s\n' "$REPO_ROOT/patches/$patch_name"
        done
        find "$SYSTEMLINK_DIR" -type f | sort
    } | xargs sha256sum | sha256sum | cut -d' ' -f1
}

PATCH_HASH=$(patch_hash)
if [ -f "$STAMP" ] && [ "$(cat "$STAMP")" = "$PATCH_HASH" ]; then
    echo "==> SDK patches already applied (stamp matches)"
    exit 0
fi

if [ -n "$(git -C "$SDK" status --porcelain --untracked-files=no)" ]; then
    echo "ERROR: SDK has local modifications but no matching patch stamp." >&2
    echo "       Use a clean SDK checkout at the pinned revision." >&2
    exit 1
fi

if [ -d "$SYSTEMLINK_DIR" ]; then
    echo "==> Copying System Link SDK sources"
    cp -a "$SYSTEMLINK_DIR"/. "$SDK"/
fi

apply_one() {
    patch=$1
    [ -f "$patch" ] || { echo "ERROR: missing $patch" >&2; exit 1; }
    name=$(basename "$patch")
    if [ ! -s "$patch" ]; then
        echo "==> $name is empty, skipping"
        return
    fi
    if git -C "$SDK" apply --check "$patch" >/dev/null 2>&1; then
        echo "==> Applying $name"
        git -C "$SDK" apply "$patch"
    else
        echo "ERROR: cannot apply $name." >&2
        echo "       The SDK tree is modified or is not the pinned revision." >&2
        exit 1
    fi
}

for patch_name in $SDK_PATCHES; do
    apply_one "$REPO_ROOT/patches/$patch_name"
done

printf '%s\n' "$PATCH_HASH" > "$STAMP"
echo "==> SDK patches applied"
