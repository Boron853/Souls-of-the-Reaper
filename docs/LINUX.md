# Native Linux build

The port targets ReXGlue 0.10.0, whose Linux path uses the **Vulkan** GPU
backend (D3D12 is Windows-only). The build system, generated game code, kernel
hooks, cache device, SDL input and System Link patches are cross-platform; this
document covers what is already wired up and what still needs work.

## Status

| Area | State |
|------|-------|
| CMake presets (`linux-amd64-*`) | upstream, present in `port/CMakePresets.json` |
| SDK patch application | works on the pinned SDK commit |
| Generated-code hand patches | ported to `port/apply_generated_patches.py` |
| Config writer | ported to `apply_config.py` |
| Build/codegen scripts | `port/build_sdk.sh`, `port/build.sh`, `port/codegen.sh` |
| End-to-end installer | `install-diablo3.sh`, `installer/iso_installer_qt.py`, `installer/iso_installer.py`, `port/install_game.py` |
| Prebuilt SDK packaging | `port/package_sdk.sh`, `--sdk-bundle` installer option |
| Window / input / audio | SDL3 (vendored), including borderless windows and HIDAPI controllers |
| Rendering | Vulkan host-RT hooks ported; full build and runtime verified on Intel Arc (Mesa) — see "Rendering" below |

All 24 shared translation units touched by the port patch and all 9 Vulkan
backend translation units compile with Clang 22, and the full CMake build/link
and runtime are verified on a Linux desktop (Intel Arc B390, Mesa 26.1.8) with
real game data. Other GPUs and drivers may still need per-vendor tuning.

## Prerequisites

Use Clang 18 or newer (`port/CMakePresets.json` asks for `clang-20`; the
scripts fall back to `clang`/`clang++` when `clang-20` is absent). The build
targets x86-64-v3 (AVX2), matching the Windows port.

Debian/Ubuntu:

```sh
sudo apt install build-essential git cmake ninja-build clang lld \
  pkg-config libgtk-3-dev libx11-xcb-dev libwayland-dev libwayland-bin \
  libdecor-0-dev libvulkan-dev libasound2-dev libpulse-dev \
  libpipewire-0.3-dev libudev-dev libglvnd-dev python3-tk
```

Fedora:

```sh
sudo dnf install git cmake ninja-build clang lld \
  pkgconf-pkg-config gtk3-devel libX11-devel libxcb-devel \
  wayland-devel libdecor-devel \
  vulkan-loader-devel alsa-lib-devel pulseaudio-libs-devel pipewire-devel \
  systemd-devel libglvnd-devel python3-tkinter
```

Native Wayland support in the vendored SDL3 build requires `wayland-scanner`
at SDK configure time. If it is missing, SDL silently builds without the
Wayland backend and only X11 remains available. `port/build_sdk.sh` passes the
scanner path explicitly when it is on `PATH`.

Or use the provided dev shell:

```sh
nix develop
```

The SDK vendors SDL3, volk/Vulkan-Headers, VulkanMemoryAllocator, SPIRV-Tools,
glslang, FFmpeg and the other third-party libraries. Clone it next to this
repository (or set `REXSDK_DIR`), at the commit in
`port/rexglue.lock.json`:

```sh
git clone https://github.com/rexglue/rexglue-sdk.git
cd rexglue-sdk
git checkout c94f5ebdcb3c9d1a460ca48e04f9758448f8d518   # ReXGlue 0.10.0
git submodule update --init --recursive
```

`port/build_sdk.sh` configures, builds, and installs the SDK; `port/codegen.sh`
and `port/build.sh` use that installation. The scripts apply the SDK patches
automatically via `port/apply_sdk_patches.sh` (idempotently):

- `patches/rexglue-registration.patch`, `rexglue-object-reference.patch`,
  `rexglue-keyboard.patch`, and `rexglue-username.patch` — the ReXGlue 0.10
  codegen/kernel/input/player-name changes.
- `patches/rexglue-systemlink-net.patch` and `patches/systemlink/` — System Link
  (LAN play) sockets and XNet hooks.
- `patches/rexglue-sdk.patch` — the Windows/D3D12 port patch.
- `patches/rexglue-sdk-linux.patch` — the Linux delta: Vulkan host-render-target
  resolve hooks (mode 4 forced color source, mode 5 depth ownership map, mode 8
  cross-map clear inheritance), the texture-fetch `exp_adjust` fix, SDL
  borderless windows, SDL HIDAPI/udev controller enumeration and polling,
  cvar/shared-memory teardown fixes, and the unit-test harness fixes.

## Game data

Extract the disc with the bundled XDVDFS reader (no external tools needed;
ReXGlue decrypts the XEX itself):

```sh
python3 port/extract_iso.py "/path/to/Diablo III ... (USA).iso"
```

This writes the layout the manifest expects under `game/` at the repository
root:

```
game/default.xex        Xbox 360 executable (ReXGlue decrypts it)
game/CPKs/*.cpk         all CPK archives from the disc (~7.4 GB)
game/CommonTOC.dat      if the disc has one
```

`--out DIR` selects another game root and `--force` re-extracts files that are
already present. Re-running without `--force` skips files with the right size,
so an interrupted extraction can be resumed. The installer passes the chosen
game-data directory to codegen and writes a local manifest automatically; for
manual builds, use `./port/codegen.sh --game-dir DIR`.

`port/diablo3_manifest.toml` points at `../game/default.xex` relative to
`port/`. Dumps named `Default_decrypted.exe` are accepted and written as
`game/default.xex`.

### Graphical installer

The Qt6/PySide6 installer now runs the complete Linux setup, not just
extraction. It uses native Wayland when available and a dark Fusion theme; the
Tkinter frontend remains as a fallback:

```sh
./install-diablo3.sh
```

Choose the ISO/XISO and game-data folder, then press **Install & build**. The
installer runs these phases in order:

1. extract `game/default.xex`, CPKs, and `CommonTOC.dat`;
2. obtain the pinned ReXGlue SDK checkout (an existing pinned checkout is
   reused; otherwise it is cloned into `.install/rexglue-sdk/`);
3. build and install the SDK, applying the repository patches;
4. run codegen and re-apply the generated-code hand patches;
5. build the Linux game;
6. write the launcher configuration;
7. launch the game if **Launch when finished** is checked.

The first run is the long one (roughly 20–30 minutes depending on the CPU and
network). Later runs reuse the SDK/build directories. The log streams all
child-process output; **Cancel** stops the current phase and the installation.
The display options in the installer are the guest resolution, internal scale
(`1x` = 720p/60 FPS, `2x` = 1440p/higher detail, `3x` = 2160p), and fullscreen.

The GUI can also be pre-filled:

```sh
./install-diablo3.sh --iso "/path/to/disc.iso" --out "$PWD/game"
./install-diablo3.sh --force       # re-extract existing files
```

The headless equivalent, useful for scripts and debugging, is:

```sh
python3 port/install_game.py --iso "/path/to/disc.iso" --launch
python3 port/install_game.py --iso "/path/to/disc.iso" --extract-only
python3 port/install_game.py --iso "/path/to/disc.iso" --sdk-dir /path/to/pinned/rexglue-sdk
```

The wrapper uses Qt6/PySide6 if available, otherwise Tkinter. If neither is
available it falls back to the Nix dev shell (which includes both). On a
distribution build install `python3-pyside6` (or `python3-tk` as a fallback).
If the build toolchain is not on `PATH`, `install_game.py` automatically uses
the Nix dev shell when Nix is available.

### Prebuilt SDK bundle

The SDK build is the longest open-source part of the first install. It can be
built once and shipped as an installer bundle:

```sh
./port/package_sdk.sh
# -> port/out/sdk-bundles/rexglue-sdk-linux-amd64.tar.gz (+ .sha256)
```

Then install with:

```sh
python3 port/install_game.py --iso "/path/to/disc.iso" \
    --sdk-bundle port/out/sdk-bundles/rexglue-sdk-linux-amd64.tar.gz --launch
```

The GUI has an **SDK bundle** field; it also auto-detects
`sdk/rexglue-sdk-linux-amd64.tar.gz` when present. With a bundle, the installer
skips SDK cloning/building and goes straight to codegen, the game build,
configuration, and launch. The bundle contains the SDK headers/libraries/CMake
package and the codegen tool, but **not** game data or generated game code.

The bundle is ABI-specific. Build it on the oldest Linux distribution/glibc
you intend to support (for example Ubuntu 22.04 / glibc 2.35) before publishing
it. A bundle built in Nix on a newer glibc will not run on older systems.

On NixOS, an Ubuntu/glibc SDK bundle cannot execute directly because its
`/lib64/ld-linux-x86-64.so.2` interpreter is unavailable. The installer
automatically ignores an auto-detected `sdk/` bundle on NixOS and builds the
pinned SDK through the Nix dev shell. Do not pass `--sdk-bundle` on NixOS;
explicit incompatible bundles are rejected with a clear error.

## Build

```sh
# 1. Build and install the pinned ReXGlue 0.10 SDK
./port/build_sdk.sh

# 2. Transcode the guest executable (one time per XEX, ~1 min)
./port/codegen.sh

# 3. Build the native ELF
./port/build.sh -c RelWithDebInfo

# Output: port/out/build/linux-amd64-relwithdebinfo/diablo3
```

`build_sdk.sh` configures, builds, and installs the SDK under
`rexglue-sdk/out/install/linux-amd64`. `codegen.sh` uses the installed SDK (or
builds it first if needed), runs v0.10 codegen, then re-applies the
setjmp/longjmp and main-menu-exit fixes that codegen cannot emit. Re-run
`python3 port/apply_generated_patches.py` after every codegen pass.

Useful options:

```sh
./port/build_sdk.sh --clean       # rebuild/install the SDK from scratch
./port/build.sh -c Debug          # debug runtime
./port/build.sh --clean           # wipe the port build directory
./port/codegen.sh --game-dir /path/to/game
REXSDK_DIR=/path/to/sdk ./port/build_sdk.sh
REXSDK_DIR=/path/to/sdk ./port/build.sh
python3 port/apply_generated_patches.py --generated-dir port/generated/default
```

`codegen.sh --game-dir` writes a local manifest with the chosen game-data
path, so the graphical installer's custom destination works end-to-end.

## Launch

Use the wrapper rather than starting the ELF directly:

```sh
./launch-diablo3.sh
```

A binary built inside the Nix dev shell needs the Nix store Vulkan/ALSA/Pulse/
PipeWire libraries at runtime. The launcher caches the resulting
`LD_LIBRARY_PATH` in `~/.local/share/diablo3/ld_library_path` and starts the
game directly on later runs, avoiding `nix develop` on every launch (about
20-30 s saved). The first launch, a launch after `flake.nix`/`flake.lock`
changes, or a launch after Nix garbage collection removed the libraries
rebuilds the cache once. Logs go to `~/.local/share/diablo3/diablo3.log`.

A binary built against distribution packages (the normal `port/build.sh` flow
with the distro packages above) does **not** need Nix. The launcher detects
that and runs the binary directly with the system Vulkan/ALSA/Pulse paths. The
prebuilt `port/out/.../diablo3` from a Nix build is **not portable** to a
non-NixOS machine - rebuild on the target distribution, or install Nix there.
On Wayland desktops the port now uses the native SDL3 Wayland backend by
default. It presents through `VK_KHR_wayland_surface` and does not create an
XWayland game window. If Wayland initialization is unavailable, SDL falls back
to X11 automatically. Force a backend when needed:

```sh
SDL_VIDEODRIVER=wayland ./launch-diablo3.sh
SDL_VIDEODRIVER=x11 ./launch-diablo3.sh
```

The native Wayland path was verified under KWin: SDL reports the `wayland`
video driver, Vulkan creates a `VK_KHR_wayland_surface` swapchain, gamepad
enumeration works, and `xdotool` cannot find the game window. Fullscreen and
borderless modes still need broader multi-monitor/compositor testing.

```sh
# Distribution build on a non-NixOS system:
./port/codegen.sh
./port/build.sh -c RelWithDebInfo
python3 apply_config.py --game-data-root "$PWD/game"
./launch-diablo3.sh
```

The desktop entry `Souls-of-the-Reaper.desktop` calls the same wrapper; its
paths are machine-specific and can be edited.

### Steam and controllers

To launch through Steam, add `launch-diablo3.sh` itself as the non-Steam game
(not the `.desktop` file). The launcher clears Steam's `LD_PRELOAD` overlay
hook, because the overlay is built against the Steam runtime and can otherwise
pull in a `libGL.so.1` that the Nix-linked build cannot resolve. Steam Input
still works with the overlay disabled.

The Steam Controller 2's physical USB device (`28de:1302`) is read directly by
SDL's HIDAPI and appears as a normal gamepad once SDL can enumerate Linux HID
devices. Steam is **not required** for this: the port opens the physical
controller through `hidraw`, and the kernel `hid-steam` driver does not need to
claim `1302`. If Steam is running, Steam Input may additionally create a
virtual Xbox pad (`28de:11ff`, usually `/dev/input/js0`); the port handles
either device. The port also polls `SDL_GetGamepads()` in addition to handling
hotplug events, so a controller that already existed when the game started is
still opened.

Steam stores controller configurations per Steam AppID on the PC
(`~/.local/share/Steam/controller_base` and `userdata/.../controller_config`);
the controller itself does not remember a per-game profile. Launching the
wrapper outside Steam gets the controller's own/default mapping, not a Steam
game profile. A userspace bridge such as `sc-controller` is only needed if you
want a virtual pad on a setup where SDL cannot access the controller directly.

SDL's HIDAPI uses `libudev` to enumerate Linux input and `hidraw` devices. The
Nix dev shell includes it; on a distribution build install `libudev-dev`
(Debian/Ubuntu) or `systemd-devel` (Fedora). If the controller is not detected,
check that the device exists and that your user can read it:

```sh
lsusb | grep 28de
getfacl /dev/hidraw*
```

### System Link (LAN)

The v0.10 SDK integration includes the game's native System Link mode, so two
or more Linux PCs on the same LAN can see each other in the in-game menu.

- Give every PC except one a unique player number in `diablo3.toml`:
  ```toml
  systemlink_instance = 1
  ```
  Use `2`, `3`, ... on additional PCs. `0` is the classic/default ID.
- Set a player name through the environment when launching:
  ```sh
  SOTR_USERNAME="Player" ./launch-diablo3.sh
  ```
- On a machine with multiple adapters, select the LAN address:
  ```toml
  systemlink_address = "192.168.1.20"
  ```
- Add `systemlink_trace = true` to log discovery/session traffic when debugging
  connectivity.

The implementation lives in `patches/systemlink/` and
`patches/rexglue-systemlink-net.patch`; the player name is supplied by
`patches/rexglue-username.patch`.

## Configuration

The runtime reads `<exe dir>/diablo3.toml`. `apply_config.py` writes the
launcher-managed cvars while preserving F4 overlay remaps:

```sh
python3 apply_config.py --game-data-root "$PWD/game" --fps 60
python3 apply_config.py --platform windows --rtp rtv --fps 120   # D3D12 keys
```

Linux writes `render_target_path_vulkan = "host"` plus the shared rendering
cvars used by the Windows RTV path (`rtv_color_depth_ownership_mode = 8`,
`execute_unclipped_draw_vs_on_cpu = true`). The D3D12-only
`render_target_path_d3d12` key is omitted. Run the binary with `--help` to see
equivalent path overrides (`--game_data_root`, `--user_data_root`,
`--log_file`, ...).

### Resolution and widescreen

`resolution` changes the guest video mode and the startup window together:

```sh
python3 apply_config.py --resolution 1080p
python3 apply_config.py --resolution 1440p
python3 apply_config.py --resolution 2560x1440
```

Accepted values are `720p`, `1080p`, `1440p`, `1800p`, `2160p`/`4k`, and
arbitrary `WIDTHxHEIGHT` strings. This changes the guest video mode and the
window/swapchain size. The game's final guest swap/front buffer is still
**1280×720**, so the presenter upscales that image to the configured window;
`resolution` alone does not raise the fixed front buffer.

`draw_resolution_scale_x/y` (or `--res-scale`) is the real internal rendering
control. At `--res-scale 2` the swap source becomes **2560×1440**, giving sharp
UI and 3D at 1440p. On the tested Intel Arc B390 this runs at roughly **33 FPS**,
versus about **60 FPS** at `--res-scale 1` with a 720p source upscaled to
1440p:

```sh
# True 1440p internal rendering (~33 FPS on the tested GPU)
python3 apply_config.py --res-scale 2 --resolution 1440p

# 60 FPS presentation, 720p source upscaled to 1440p
python3 apply_config.py --res-scale 1 --resolution 1440p
```

#### Dynamic resolution

`--dynamic-resolution true` makes the port choose the highest draw resolution
scale that fits a frame-time budget instead of using a single fixed scale. It
starts at the configured `--res-scale`, downscales when rendering work exceeds
the target, and only scales back up when the projected cost of the next scale
still fits. The change happens at a swap boundary and recreates the affected
GPU caches, so expect a brief hitch at each transition.

```sh
# Prefer 60 FPS: starts at 2x, drops to 1x when 1440p cannot hold 60
python3 apply_config.py --res-scale 2 --resolution 1440p \
    --fps 60 --dynamic-resolution true --dynamic-target-fps 60

# Prefer detail: allow 2x at a 30 FPS budget
python3 apply_config.py --res-scale 2 --resolution 1440p \
    --fps 60 --dynamic-resolution true --dynamic-target-fps 30

# Unlocked frame rate with dynamic resolution
python3 apply_config.py --res-scale 2 --resolution 1440p \
    --fps 0 --dynamic-resolution true --dynamic-target-fps 60
```

`--dynamic-min-scale` sets the lowest scale the controller may use (default
`1`). `--dynamic-target-fps` defaults to `--fps` when that is non-zero, or 60
when `--fps 0`; it is independent of the `d3_frame_limit` cap, so an unlocked
run can still use a 60 FPS resolution budget. On the tested Intel Arc B390, a
60 FPS target at 1440p settles at **1x/720p**, while a 30 FPS target keeps
**2x/1440p**; the transition itself is logged as `[D3 dynamic resolution]`.

Diablo III's 3D viewport is 16:9. A 16:9 mode fills the window correctly. A
wider mode such as `2560x1080` renders the full-width title art, but the menu
and gameplay are letterboxed to 16:9 because the game clamps the in-game
aspect; true 21:9 FOV would require a game-side patch. `fullscreen = true` now
uses SDL desktop fullscreen. On the tested 2880×1920 desktop it creates a
2880×1920 swapchain (native Wayland reports 2880×1919 client pixels) and
letterboxes the 16:9 game image to 2880×1620. Use the borderless window when
you want an exact windowed size:

```sh
python3 apply_config.py --resolution 1440p --borderless true
```

`borderless = true` removes the window decorations and places the client area
at the top-left, so `resolution = "1440p"` (2560x1440) or `"4k"`
(3840x2160) fills the screen exactly on a matching monitor.

## Rendering

The port's EDRAM fixes are split between the shared `RenderTargetCache` and the
backends:

- The shared ownership/inheritance logic in
  `src/graphics/pipeline/render_target/cache.cpp` is compiled on both platforms.
- `patches/rexglue-sdk-linux.patch` (the consolidated Linux SDK delta) wires it
  into the Vulkan backend:
  - `SetCurrentResolveIsDepth()` so a depth resolve reads the separate depth
    ownership map (mode 5).
  - Mode 4: resolve the lit-scene color render target directly, bypassing the
    color/depth-interleaved owners (base `0x040C`).
  - Mode 8: run cross-map clear inheritance before dumping a color resolve so
    the aliased D24S8 clear reaches the ground-light atlas.
  - The unclipped-draw CPU vertex-shader estimation cvar is shared and is
    enabled by `apply_config.py`.
- The Vulkan fetch translator takes the texture result exponent adjustment
  (`exp_adjust`) from fetch-constant word 3, not the word-4 LOD bias. The old
  field mix scaled textures by up to 64x, which made the menu font nearly
  transparent and the world black. A regression test lives in
  `tests/unit/graphics/texture_fetch_constant_test.cpp`.
- The D3D12-only diagnostic logger (`d3d_screenshot.cpp`, RTLOG) is not built;
  `patches/rexglue-sdk-linux.patch` supplies a no-op `RtLogActive()`.
- `patches/rexglue-sdk-common.patch` and `patches/rexglue-sdk-vulkan.patch` are
  retained only as empty historical compatibility stubs; the v0.10 patch flow
  no longer references them.

Verified on the Linux desktop with an Intel Arc B390 (Mesa 26.1.8): native
2560x1440 at 60 FPS, readable UI, visible world and lighting, audio
initialized, and no shared-memory leftovers after SIGKILL. Other GPUs and
drivers may still need per-vendor tuning.

## Other differences from the Windows release

- The WebView2 launcher, Inno Setup installer and `ps2exe` packaging are
  Windows-only. On Linux, use the CLI scripts above; `port/extract_iso.py`
  replaces `setup.ps1`'s extraction step.
- `apply_config.ps1` / `apply_generated_patches.ps1` still work via PowerShell
  on Windows; the Python versions are drop-in equivalents.
- The Windows exe icon patch is cosmetic and skipped on Linux.
- Controllers use the SDK's patched SDL3 input driver (up to 4 gamepads).
  The driver polls `SDL_GetGamepads()` as well as handling hotplug events, so
  a Steam Controller or Steam Input virtual pad that predates the game is
  still found. Keyboard/mouse bindings are the same.
