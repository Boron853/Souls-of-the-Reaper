#!/usr/bin/env bash
# Runtime launcher for the Nix package.
#
# Fetches the newest non-draft Linux installer release from the fork, verifies
# its SHA-256 checksum when SHA256SUMS is available, and runs the graphical
# installer inside the release's own Nix dev shell.
set -euo pipefail

REPO="ccgman123/Souls-of-the-Reaper"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/souls-of-the-reaper"
CACHE_DIR="$DATA_DIR/cache"
INSTALLER_DIR="$DATA_DIR/installer"
GAME_DIR="$DATA_DIR/game"

die() {
  echo "ERROR: $*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Souls of the Reaper — NixOS installer/manager

Usage:
  souls-of-the-reaper play    [launcher options]
  souls-of-the-reaper install [installer options]
  souls-of-the-reaper update  [installer options]
  souls-of-the-reaper launch  [launcher options]
  souls-of-the-reaper status
  souls-of-the-reaper uninstall [--purge]

play      Launch the installed game, or open the installer if not built yet.
install   Fetch the latest release, then open the graphical installer.
update    Fetch the latest release even if it is already cached.
launch    Launch the currently installed build (error if not built).
status    Show the cached release and build paths.
uninstall Remove downloaded installers/cache. --purge also removes game data.

The first install asks for your Xbox 360 ISO and builds the game with the
release's Nix dev shell. Game data is kept in:
  ~/.local/share/souls-of-the-reaper/game
EOF
}

ensure_data_dirs() {
  mkdir -p "$CACHE_DIR" "$INSTALLER_DIR" "$GAME_DIR"
}

latest_release() {
  python3 - "$REPO" <<'PY'
import json
import sys
import urllib.request

repo = sys.argv[1]
url = f"https://api.github.com/repos/{repo}/releases?per_page=20"
request = urllib.request.Request(
    url,
    headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "souls-of-the-reaper-nix-installer",
    },
)
try:
    with urllib.request.urlopen(request, timeout=30) as response:
        releases = json.load(response)
except Exception as exc:  # noqa: BLE001 - report the API failure to the shell
    print(f"GitHub release lookup failed: {exc}", file=sys.stderr)
    sys.exit(1)

for release in releases:
    if release.get("draft"):
        continue
    assets = release.get("assets", [])
    installer = next(
        (
            asset
            for asset in assets
            if asset.get("name", "").startswith("SoulsOfTheReaper-linux-installer-")
            and asset.get("name", "").endswith(".tar.gz")
        ),
        None,
    )
    if not installer:
        continue
    checksums = next(
        (asset for asset in assets if asset.get("name") == "SHA256SUMS"),
        None,
    )
    print(
        "\t".join(
            [
                release["tag_name"],
                installer["browser_download_url"],
                installer["name"],
                checksums["browser_download_url"] if checksums else "",
            ]
        )
    )
    break
else:
    print("No Linux installer release asset found", file=sys.stderr)
    sys.exit(1)
PY
}

verify_checksum() {
  local archive=$1
  local name=$2
  local sums_url=$3
  [ -n "$sums_url" ] || return 0

  local sums="$CACHE_DIR/SHA256SUMS"
  curl -fsSL --retry 3 "$sums_url" -o "$sums"
  local expected
  expected=$(python3 - "$sums" "$name" <<'PY'
import sys
from pathlib import Path

sums = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
name = sys.argv[2]
for line in sums:
    parts = line.split()
    if len(parts) >= 2 and parts[-1].endswith(name):
        print(parts[0])
        break
PY
)
  [ -n "$expected" ] || die "SHA256SUMS does not contain $name"
  local actual
  actual=$(sha256sum "$archive" | awk '{print $1}')
  [ "$expected" = "$actual" ] || die "checksum mismatch for $name"
}

fetch_release() {
  local force=${1:-0}
  ensure_data_dirs

  local release tag url name sums_url
  release=$(latest_release) || die "could not find the latest Linux release"
  IFS=$'\t' read -r tag url name sums_url <<<"$release"
  [ -n "$tag" ] && [ -n "$url" ] && [ -n "$name" ] || die "invalid release metadata"

  local current_tag=""
  if [ -L "$INSTALLER_DIR/current" ]; then
    current_tag=$(basename "$(readlink "$INSTALLER_DIR/current")")
  fi
  local dest="$INSTALLER_DIR/$tag"

  if [ "$force" != 1 ] && [ "$current_tag" = "$tag" ] &&
     [ -x "$dest/install-diablo3.sh" ]; then
    echo "Using cached installer $tag"
    return 0
  fi

  local archive="$CACHE_DIR/${tag}-${name}"
  echo "Downloading $tag ($name)..."
  curl -fsSL --retry 3 "$url" -o "$archive"
  verify_checksum "$archive" "$name" "$sums_url"

  local tmp="$INSTALLER_DIR/.${tag}.tmp"
  rm -rf "$tmp"
  mkdir -p "$tmp"
  tar -xzf "$archive" -C "$tmp" --strip-components=1
  [ -x "$tmp/install-diablo3.sh" ] || die "release archive has no install-diablo3.sh"

  rm -rf "$dest"
  mv "$tmp" "$dest"
  ln -sfn "$tag" "$INSTALLER_DIR/current"
  echo "Installed release $tag at $dest"
}

current_installer() {
  [ -L "$INSTALLER_DIR/current" ] || die "no installer installed; run: souls-of-the-reaper install"
  readlink -f "$INSTALLER_DIR/current"
}

cmd_play() {
  if [ -L "$INSTALLER_DIR/current" ]; then
    local dir
    dir=$(readlink -f "$INSTALLER_DIR/current")
    if [ -x "$dir/port/out/build/linux-amd64-relwithdebinfo/diablo3" ] &&
       [ -f "$dir/port/out/build/linux-amd64-relwithdebinfo/diablo3.toml" ] &&
       [ -f "$GAME_DIR/default.xex" ]; then
      exec "$dir/launch-diablo3.sh" "$@"
    fi
  fi
  cmd_install 0 "$@"
}

cmd_install() {
  local force=${1:-0}
  shift || true
  fetch_release "$force"
  local dir
  dir=$(current_installer)
  mkdir -p "$GAME_DIR"
  cd "$dir"
  exec nix develop "path:$dir" --command "$dir/install-diablo3.sh" --out "$GAME_DIR" "$@"
}

cmd_update() {
  cmd_install 1 "$@"
}

cmd_launch() {
  local dir
  dir=$(current_installer)
  exec "$dir/launch-diablo3.sh" "$@"
}

cmd_status() {
  ensure_data_dirs
  echo "Data directory: $DATA_DIR"
  echo "Game data:     $GAME_DIR"
  if [ -L "$INSTALLER_DIR/current" ]; then
    echo "Release:       $(basename "$(readlink "$INSTALLER_DIR/current")")"
    echo "Installer:     $(readlink -f "$INSTALLER_DIR/current")"
    if [ -x "$(readlink -f "$INSTALLER_DIR/current")/port/out/build/linux-amd64-relwithdebinfo/diablo3" ]; then
      echo "Build:         installed"
    else
      echo "Build:         not built yet"
    fi
  else
    echo "Release:       none"
  fi
}

cmd_uninstall() {
  local purge=0
  if [ "${1:-}" = "--purge" ]; then
    purge=1
  fi
  rm -rf "$INSTALLER_DIR" "$CACHE_DIR"
  if [ "$purge" = 1 ]; then
    rm -rf "$GAME_DIR"
    echo "Removed installer, cache, and game data."
  else
    echo "Removed installer and cache; game data preserved at $GAME_DIR"
  fi
}

case "${1:-play}" in
  play) shift || true; cmd_play "$@" ;;
  install) shift || true; cmd_install 0 "$@" ;;
  update) shift || true; cmd_update "$@" ;;
  launch) shift || true; cmd_launch "$@" ;;
  status) shift || true; cmd_status "$@" ;;
  uninstall) shift || true; cmd_uninstall "$@" ;;
  -h|--help|help) usage ;;
  *) usage; exit 2 ;;
esac
