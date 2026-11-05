# Souls of the Reaper

Xbox 360 → PC port of Diablo III built on the [ReXGlue SDK](https://github.com/rexglue/rexglue-sdk) — an AOT recompiler that translates the Xbox 360 PPC binary to native x64 C++, with a Xenia-based kernel HLE.

**Windows status:** Playable and stable (RelWithDebInfo / -O2) with the Direct3D 12 renderer: ROV (faithful, 60fps) or RTV (fast, up to 240fps with lighting and artifacts fixed). The Vulkan renderer is built into the same executable and is selected at launch (see [Vulkan renderer](#vulkan-renderer)). **Linux:** runs on Vulkan; see the Linux build notes below.

---

## Option A — Just play (no compilation needed)

Download the latest release from the [Releases](../../releases) page, extract the zip, and run `SoulsOfTheReaper.exe`. On first launch it will ask for your Xbox 360 ISO and set everything up automatically.

---

## Option B — Build from source

Detailed guides live in [`docs/`](docs/README.md): [building the game](docs/building-the-game.md) and [building the launcher](docs/building-the-launcher.md).

On Linux or Windows, one command builds everything from your own disc image (and,
optionally, the USA Title Update package). The launcher's Build panel runs the same script:

```sh
python3 scripts/build_client.py --iso /path/to/disc.iso [--title-update /path/to/title-update]
```

The matching USA update can also be built separately; see the
[title update setup](port/title_updates/update/README.md).

A [cross-platform launcher](launcher/tauri/README.md) (Tauri) reuses the existing
interface on Linux and Windows and selects base, extras and update builds.

### Linux (Vulkan)

The Linux integration shares this port's game application and imports the
ReXGlue/Vulkan recomp work, including texture-color and object-lifetime fixes,
audited function entries, GPU diagnostics, fullscreen and frame telemetry.
It uses a separately pinned SDK and the unmodified USA Ultimate Evil Edition
base disc.

```sh
python3 scripts/build_linux.py --build-sdk --game-dir /path/to/extracted/disc
python3 scripts/run_linux.py --game-dir /path/to/extracted/disc
```

See [Linux build, diagnostics and integration notes](port/base/README.md) for
requirements, reuse of an existing SDK, saves, and GPU selection.

The [optional PC features](port/extra-features.md) add a saved
resolution-scale setting and live window-mode selector to Options > Video, PC wording to the autosave
warning, and ` + Extras` to the launch-screen version label. They are built into
the normal executable and switched on at launch: `--extra-features` on Linux,
`-ExtraFeatures` on Windows, or "Base + Extras" in the launcher. Build with
`--no-extra-features` (Windows too) to leave the code out entirely.

### Windows

#### Requirements

- Windows 10/11 x64
- Visual Studio 2022 Community with the C++ and CMake workloads
- LLVM/Clang 22+ (`C:\Program Files\LLVM\` is found automatically), Git and Python 3
- The USA Ultimate Evil Edition disc extracted to a folder (default `game\`) holding `Default.xex` and `CPKs\`.
  The build verifies the executable's SHA-256 before generating code.

#### Steps

The optional features are already built in. Launch with them using
`pwsh -File scripts\run_windows.ps1 -ExtraFeatures`; add `--no-extra-features`
to the build command in step 1 to compile without them.
See [optional game features](port/extra-features.md) for details.

**1. Build** (one command; the first run also clones, patches and builds the pinned SDK, and
runs codegen, ~12 min)
```powershell
python scripts\build_windows.py --build-sdk --game-dir game
```

This applies the shared patches in `patches/common/` and the Windows patches in
`patches/windows/` to the pinned ReXGlue SDK (`tools/rexglue-sdk-win`), runs
codegen into `port/generated/base`, applies the hand patches to the generated
code (`scripts/apply_generated_patches.py`) and compiles the game. Later builds
can drop `--build-sdk`, and `--skip-codegen` reuses generated sources.

Output: `port\out\build\win-amd64-relwithdebinfo\diablo3.exe`

The [graphical launcher](launcher/tauri/README.md) runs the same script from its
Build panel when given the ISO and title update.

**1b. Build the title update (optional)**

To also build the USA Title Update executable, pass the USA Title Update package
to the one-command build, which extracts the disc, stages the update
as a small overlay in `game\update\` and compiles every selected build:
```powershell
python scripts\build_client.py --iso C:\path\to\disc.iso --title-update C:\path\to\title-update-package
```

If `game\` is already extracted and the overlay is staged, build just the update executable with
`python scripts\build_windows.py --title-update usa --game-dir game`. Output:
`port\out\build\win-amd64-update-relwithdebinfo\diablo3.exe`. Staging and verification details are in the
[title update setup](port/title_updates/update/README.md) and [building the game](docs/building-the-game.md).

**2. Run**
```powershell
pwsh -File scripts\run_windows.ps1 -ExtraFeatures
```

Pass `-Username "Name"` to set the in-game player name (up to 15 characters).

#### Vulkan renderer

The Windows build compiles the Direct3D 12 and Vulkan renderers into one executable (`patches/windows/rexglue-gpu-backend.patch` adds the `gpu_backend` setting), so no separate build is needed. Pick one at launch:

```powershell
pwsh -File scripts\run_windows.ps1 -Backend vulkan -ExtraFeatures
```

`-VulkanPath fsi` (default, faithful; needs fragment shader interlock) or `host` chooses the render-target path, and `-VulkanDevice N` picks a GPU by index. The graphical launcher offers the same choice as a Renderer option. It needs a Vulkan-capable GPU and driver.

**3. Build the launcher (optional)**

The [Tauri launcher](launcher/tauri/README.md) picks base, extras and update builds, sets the
renderer and other launch options, and has a **Build from disc image…** panel (⚙ menu) that runs
`scripts\build_client.py`. Besides the game's requirements it needs:
- [Rust](https://rustup.rs/) (stable) with the MSVC toolchain (the Visual Studio 2022 C++ workload covers the build tools)
- [Node.js](https://nodejs.org/) with npm
- The WebView2 runtime (already present on Windows 10/11 with Edge)

```powershell
cd launcher\tauri
npm ci
npm run build
```

Output: `launcher\tauri\src-tauri\target\release\sotr-launcher.exe`. Run it from anywhere inside the
checkout and it finds the builds under `port\out\build\`. See
[building the launcher](docs/building-the-launcher.md) for the debug build, tests and other details.

**4. Start it**
```powershell
launcher\tauri\src-tauri\target\release\sotr-launcher.exe
```

---

## Controls

Keyboard and up to 4 gamepads all work at once — whoever presses/types first at the title screen becomes player 1, the next becomes player 2, and so on (local co-op, up to 4 players). The launcher (`sotr-launcher.exe`) only has one control-related option: whether the mouse also drives the camera.

| Mode | Description |
|------|-------------|
| Keyboard only | WASD + buttons, mouse disabled |
| Keyboard + mouse | WASD; mouse = right stick (dodge); clicks = triggers/R3 |
| Gamepad | Any connected Xbox 360-compatible controller, no setup needed |

**Default keyboard layout:**

| Key | Action |
|-----|--------|
| WASD | Move |
| Arrow keys | D-Pad |
| Space / Enter | A button |
| Esc | Pause |
| Shift | B button |
| U / J | Y / X |
| O / K | LB / RB |
| H / L | LT / RT |
| Tab / I | Inventory |
| F4 | Rebind keys in-game |

---

## Known Issues

### Hand patches to generated code (re-apply after every codegen)

The generated code needs two game-specific fixes after codegen. Both build scripts apply them automatically to `port/generated/base/` (and `port/generated/update/` for title update builds) (`scripts/apply_generated_patches.py`):

- **setjmp/longjmp fix** (`sub_831583B0` / `sub_83158680`) — the recompiler mistranslates the guest setjmp/longjmp pair, corrupting Lua's protected-call mechanism and crashing the GC on startup. Direct setjmp calls are expanded inline at each call site (`D3_GUEST_SETJMP`, `port/src/guest_jump.h`) and longjmp uses host `ppc_longjmp`. The title update build patches the matching update-build functions.
- **Main-menu exit fix** (`sub_82632E00`) — redirects the game's "leave session, return to title screen" routine (reached from the main-menu B → confirm dialog → A/Aceptar flow) to close the game instead, like a normal PC game's Exit option.

  On Linux the close is queued on the UI thread. SDL closes synchronously;
  closing from a guest thread would terminate that thread during shutdown
  before the application reaches its final process-exit step.

### Game exe icon (optional, cosmetic)

`diablo3.exe`'s icon is a post-build resource patch (`tools\set_game_icon.ps1` + `rcedit.exe`, both third-party tools not included) applied over `ico_game.ico` (custom artwork, not included). Skipping this just leaves the generic exe icon - it has no effect on gameplay.

### Render paths (ROV / RTV)

Diablo III uses EDRAM aliasing in its deferred lighting pass, which historically broke the faster RTV path (world rendered black).

- **ROV** (`render_target_path_d3d12 = "rov"`) — the faithful path. Emulates the EDRAM aliasing correctly out of the box; stable 60fps.
- **RTV** (`render_target_path_d3d12 = "rtv"`) — the fast path, up to 240fps. Now fully playable once two cvars are set (done automatically by `apply_config.ps1`):
  - `rtv_color_depth_ownership_mode = 8` — cross-map "clear-like" ownership inheritance, restores the ground lighting that D3 seeds via an aliased D24S8 depth clear.
  - `execute_unclipped_draw_vs_on_cpu = true` — runs the vertex shader of unclipped screen-space quads on the CPU to claim only the real EDRAM area, eliminating the lossy round-trips that caused the smoke distortion and the red/blue silhouette lines.

---

## Credits

- [ReXGlue SDK](https://github.com/rexglue/rexglue-sdk) — recompiler + runtime (based on [Xenia](https://xenia.jp/))
