#!/usr/bin/env bash
# Launch the Diablo III Linux port with the runtime libraries it needs
# (Vulkan loader, Wayland/X11, ALSA/PulseAudio/PipeWire). SDL selects the
# native session backend by default; set SDL_VIDEODRIVER to override it.
#
# A binary built inside the Nix dev shell needs the Nix store runtime paths.
# The first such launch caches LD_LIBRARY_PATH, so later launches skip
# `nix develop` entirely. A binary built against distribution packages (for
# example with apt/dnf/pacman) is started directly and does not require Nix.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

BIN="$ROOT/port/out/build/linux-amd64-relwithdebinfo/diablo3"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/diablo3"
ENV_CACHE="$DATA_DIR/ld_library_path"
LOG="$DATA_DIR/diablo3.log"

NIX=""
if [ -n "${NIX_BIN:-}" ] && [ -x "${NIX_BIN}" ]; then
  NIX="$NIX_BIN"
elif [ -x /run/current-system/sw/bin/nix ]; then
  NIX=/run/current-system/sw/bin/nix
elif command -v nix >/dev/null 2>&1; then
  NIX="$(command -v nix)"
fi

mkdir -p "$DATA_DIR"

# Distinguish a Nix-linked binary from a distribution build. The Nix store
# path is embedded in the RUNPATH (and in debug strings); a distro build has
# no /nix/store dependency.
binary_uses_nix=0
if grep -aq '/nix/store' "$BIN" 2>/dev/null; then
  binary_uses_nix=1
fi

if [ "$binary_uses_nix" = 1 ]; then
  if [ -z "$NIX" ]; then
    echo "This diablo3 binary links against Nix store libraries, but nix was not found." >&2
    echo "Either install Nix, or rebuild on this system with ./port/build.sh." >&2
    exit 1
  fi

  needs_env=0
  if [ ! -s "$ENV_CACHE" ]; then
    needs_env=1
  elif [ "$ROOT/flake.lock" -nt "$ENV_CACHE" ] || [ "$ROOT/flake.nix" -nt "$ENV_CACHE" ]; then
    needs_env=1
  else
    # If Nix garbage collection removed the dev-shell libraries, rebuild the
    # cache. Check the libraries that are dlopen()ed at startup: Vulkan, GTK's
    # GLX probe (libGL), SDL's udev/HIDAPI enumeration (libudev), and SDL's
    # dynamically loaded Wayland/X11 backends.
    IFS=':' read -r -a cached_dirs < "$ENV_CACHE"
    vulkan_found=0
    libgl_found=0
    libudev_found=0
    libx11_found=0
    libwayland_found=0
    libdecor_found=0
    for dir in "${cached_dirs[@]}"; do
      if [ -n "$dir" ]; then
        [ -e "$dir/libvulkan.so.1" ] && vulkan_found=1
        [ -e "$dir/libGL.so.1" ] && libgl_found=1
        [ -e "$dir/libudev.so.1" ] && libudev_found=1
        [ -e "$dir/libX11.so.6" ] && libx11_found=1
        [ -e "$dir/libwayland-client.so.0" ] && libwayland_found=1
        [ -e "$dir/libdecor-0.so.0" ] && libdecor_found=1
      fi
    done
    if [ "$vulkan_found" = 0 ] || [ "$libgl_found" = 0 ] || [ "$libudev_found" = 0 ] ||
       [ "$libx11_found" = 0 ] || [ "$libwayland_found" = 0 ] || [ "$libdecor_found" = 0 ]; then
      needs_env=1
    fi
  fi

  if [ "$needs_env" = 1 ]; then
    echo "Preparing the Nix runtime environment (first launch only)..." >&2
    tmp_env="$(mktemp "$DATA_DIR/ld_library_path.XXXXXX")"
    trap 'rm -f "$tmp_env"' EXIT
    # The dev-shell hook prints its banner before the environment; the final
    # line is the actual LD_LIBRARY_PATH value.
    "$NIX" develop "path:$ROOT" --command bash -c 'printenv LD_LIBRARY_PATH' \
      | tail -n 1 > "$tmp_env"
    if [ ! -s "$tmp_env" ]; then
      echo "Failed to obtain LD_LIBRARY_PATH from the Nix dev shell." >&2
      exit 1
    fi
    mv "$tmp_env" "$ENV_CACHE"
    trap - EXIT
  fi

  export LD_LIBRARY_PATH="$(cat "$ENV_CACHE")"
else
  # Distribution build: the system linker and Vulkan loader paths are used.
  # Preserve any LD_LIBRARY_PATH the caller intentionally set.
  :
fi

# Steam preloads gameoverlayrenderer.so into every game. The overlay is built
# against the Steam runtime and pulls in libGL, which a Nix-linked build does
# not expose; the game then dies before its first frame. The overlay is not
# needed for input, so drop Steam's preload and keep the game's own runtime.
unset LD_PRELOAD

export DISPLAY="${DISPLAY:-:0}"
# Do not force X11: SDL picks Wayland on a Wayland session and falls back to
# X11 when no Wayland display is available. Set SDL_VIDEODRIVER explicitly to
# force a backend (for example, SDL_VIDEODRIVER=x11 ./launch-diablo3.sh).

exec "$BIN" --log_file "$LOG" "$@"
