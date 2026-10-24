#!/bin/sh
# package_sdk.sh - package a built ReXGlue SDK as an installer-ready bundle.
#
# The bundle contains the installed SDK headers/libraries/CMake package, the
# codegen executable, and a small launcher for the codegen tool. The installer
# can consume it with --sdk-bundle, skipping the SDK clone/build phases.
#
# Usage:
#   ./port/package_sdk.sh [SDK_DIR] [OUTPUT.tar.gz]
#
# Environment:
#   REXSDK_DIR      SDK checkout (default: <repo>/.install/rexglue-sdk)
#   REXSDK_INSTALL  SDK install prefix (default: <SDK>/out/install/linux-amd64)
#
# The resulting SDK is specific to the build host's CPU/glibc/libstdc++ ABI.
# Build it on the oldest Linux distribution you intend to support (for example
# Ubuntu 22.04 / glibc 2.35) before publishing it.
set -eu

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PORT_DIR="$REPO_ROOT/port"
SDK=${1:-${REXSDK_DIR:-"$REPO_ROOT/.install/rexglue-sdk"}}
OUT=${2:-"$REPO_ROOT/port/out/sdk-bundles/rexglue-sdk-linux-amd64.tar.gz"}
SDK_INSTALL=${REXSDK_INSTALL:-"$SDK/out/install/linux-amd64"}
STAGE="$REPO_ROOT/port/out/sdk-bundles/stage"
BUNDLE_ROOT="$STAGE/rexglue-sdk"

die() { echo "ERROR: $*" >&2; exit 1; }

command -v tar >/dev/null 2>&1 || die "tar not found"
command -v python3 >/dev/null 2>&1 || die "python3 not found"
[ -d "$SDK_INSTALL" ] || die "SDK install prefix not found: $SDK_INSTALL"

CODEGEN=""
for candidate in \
    "$SDK/out/linux-amd64/RelWithDebInfo/rexgluerd" \
    "$SDK/out/linux-amd64/RelWithDebInfo/rexglue" \
    "$SDK/out/build/linux-amd64/RelWithDebInfo/rexgluerd" \
    "$SDK/out/build/linux-amd64/RelWithDebInfo/rexglue" \
    "$SDK_INSTALL/bin/rexglue"; do
    if [ -x "$candidate" ]; then
        CODEGEN=$candidate
        break
    fi
done
[ -n "$CODEGEN" ] || die "could not find the built codegen executable under $SDK"

rm -rf "$STAGE"
mkdir -p "$BUNDLE_ROOT/install" "$BUNDLE_ROOT/install/bin" "$BUNDLE_ROOT/install/libexec"

echo "==> Copying SDK install prefix"
cp -a "$SDK_INSTALL"/. "$BUNDLE_ROOT/install"/

echo "==> Copying codegen executable"
cp "$CODEGEN" "$BUNDLE_ROOT/install/libexec/rexgluerd"
chmod +x "$BUNDLE_ROOT/install/libexec/rexgluerd"

cat > "$BUNDLE_ROOT/install/bin/rexglue" <<'EOF'
#!/bin/sh
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
install=$(CDPATH= cd -- "$here/.." && pwd)
export LD_LIBRARY_PATH="$install/lib64:$install/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$install/libexec/rexgluerd" "$@"
EOF
chmod +x "$BUNDLE_ROOT/install/bin/rexglue"

python3 - "$SDK" "$BUNDLE_ROOT/metadata.json" <<'PY'
import datetime
import json
import subprocess
import sys
from pathlib import Path

sdk = Path(sys.argv[1])
target = Path(sys.argv[2])
commit = subprocess.run(
    ["git", "-C", str(sdk), "rev-parse", "HEAD"],
    check=False,
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
    text=True,
).stdout.strip()
metadata = {
    "format": 1,
    "kind": "rexglue-sdk",
    "platform": "linux-amd64",
    "configuration": "RelWithDebInfo",
    "sdk_commit": commit,
    "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
}
target.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
PY

cat > "$BUNDLE_ROOT/README.txt" <<'EOF'
ReXGlue SDK bundle for the Linux installer.

Use with:
  python3 port/install_game.py --sdk-bundle /path/to/this-bundle.tar.gz ...

This bundle contains open-source SDK headers/libraries and the codegen tool.
It does not contain game data or generated game code. It is built for the
CPU/glibc/libstdc++ ABI of the machine that produced it; build it on the oldest
Linux distribution you intend to support before publishing it.
EOF

mkdir -p "$(dirname -- "$OUT")"
echo "==> Creating $OUT"
tar -czf "$OUT" -C "$STAGE" rexglue-sdk
sha256sum "$OUT" > "$OUT.sha256"
echo "==> Bundle: $OUT"
echo "==> SHA-256: $OUT.sha256"
du -h "$OUT"
