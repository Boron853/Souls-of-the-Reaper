#!/usr/bin/env bash
# Launch the graphical Diablo III Linux installer.
#
# The Qt6 GUI extracts the ISO, builds the pinned SDK, runs codegen, builds the
# game, writes the configuration, and optionally launches it. Tkinter remains
# a fallback. For a headless run:
#   python3 port/install_game.py --iso /path/disc.iso --launch
#
# The Qt6 GUI uses native Wayland when available and a dark Fusion palette.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
GUI_QT="$ROOT/installer/iso_installer_qt.py"
GUI_TK="$ROOT/installer/iso_installer.py"

if [ -n "${WAYLAND_DISPLAY:-}" ]; then
  export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-wayland}"
else
  export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
fi
export QT_STYLE_OVERRIDE="${QT_STYLE_OVERRIDE:-Fusion}"

if python3 -c 'import PySide6' >/dev/null 2>&1; then
  exec python3 "$GUI_QT" "$@"
fi

if python3 -c 'import tkinter' >/dev/null 2>&1; then
  exec python3 "$GUI_TK" "$@"
fi

NIX=""
if [ -x /run/current-system/sw/bin/nix ]; then
  NIX=/run/current-system/sw/bin/nix
elif command -v nix >/dev/null 2>&1; then
  NIX="$(command -v nix)"
fi

if [ -n "$NIX" ]; then
  exec "$NIX" develop "path:$ROOT" --command python3 "$GUI_QT" "$@"
fi

cat >&2 <<EOF
Qt6/PySide6 or Tkinter is required to run the graphical installer.

On Debian/Ubuntu:  sudo apt install python3-pyside6 python3-tk
On Fedora:         sudo dnf install python3-pyside6 python3-tkinter
Or use the Nix dev shell: nix develop

Alternatively, run the headless installer:
  python3 "$ROOT/port/install_game.py" --iso /path/to/diablo.iso --launch
EOF
exit 1
