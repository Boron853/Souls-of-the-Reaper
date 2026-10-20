# Souls of the Reaper

Xbox 360 → PC port of Diablo III built on the [ReXGlue SDK](https://github.com/rexglue/rexglue-sdk) — an AOT recompiler that translates the Xbox 360 PPC binary to native x64 C++, with a Xenia-based kernel HLE.

**Status:** Playable and stable (RelWithDebInfo / -O2). Two render paths: ROV (faithful, 60fps) and RTV (fast, up to 240fps with lighting and artifacts fixed).

---

## Option A — Just play (no compilation needed)

Download the latest release from the [Releases](../../releases) page, extract the zip, and run `SoulsOfTheReaper.exe`. On first launch it will ask for your Xbox 360 ISO and set everything up automatically.

---

## Option B — Build from source

### Requirements

- Windows 10/11 x64
- Visual Studio 2022 Community with the C++ and CMake workloads (CMake 3.25+, Ninja, MSVC headers)
- LLVM/Clang 22+ installed to `C:\Program Files\LLVM\`
- Git (the build clones the [ReXGlue SDK](https://github.com/rexglue/rexglue-sdk) for you)
- The USA Diablo III: Ultimate Evil Edition Xbox 360 disc, extracted to `game/` (or pass `-GameDir`):
  - `game/Default.xex` — the disc's unmodified executable (the build checks its SHA-256)
  - `game/CPKs/` — all CPK archives from the disc (7.4 GB)
  - A valid Diablo III RoS save in `Documents\diablo3\<xuid>\394F07D4\00000001\d3save\`

### Steps

**1. Build the SDK and the game** (first run ~25 min: SDK ~10 min, codegen ~12 min)
```powershell
pwsh -File port\build.ps1 -BuildSdk
```

This clones the ReXGlue SDK into `rexglue-sdk/` at the commit pinned in `port/rexglue.lock.json` (v0.10.0), applies the patches in `patches/`, builds and installs it, recompiles `game/Default.xex` into `port/generated/default`, re-applies the hand patches (`port/apply_generated_patches.ps1`, see **Known Issues**) and builds the game.

Later builds can drop `-BuildSdk`; add `-SkipCodegen` to reuse the generated sources after changing only code in `port/src`, and `-GameDir <folder>` if the disc isn't in `game/`.

Output: `port\out\build\win-amd64-relwithdebinfo\diablo3.exe`

**2. Build the launcher**

The launcher's compiled exe, icon, and the WebView2 SDK redistributable DLLs aren't in the repo (binaries, not code) - only its source is (`launcher/Launcher.ps1`, `launcher/build_launcher.ps1`, `launcher/v6_borderless_final.html`). To build it:
- Get the WebView2 SDK redistributable DLLs (`Microsoft.Web.WebView2.Core.dll`, `Microsoft.Web.WebView2.WinForms.dll`, `WebView2Loader.dll`) from the [`Microsoft.Web.WebView2`](https://www.nuget.org/packages/Microsoft.Web.WebView2) NuGet package and place them in `launcher\lib\`.
- Supply your own `launcher\ico_launcher.ico` (the original artwork isn't included).
```powershell
Install-Module ps2exe -Scope CurrentUser -Force  # one-time
launcher\build_launcher.ps1
Copy-Item launcher\dist\SoulsOfTheReaper.exe . -Force
```

**3. Run**
```
SoulsOfTheReaper.exe
```

---

## Controls

Keyboard and up to 4 gamepads all work at once — whoever presses/types first at the title screen becomes player 1, the next becomes player 2, and so on (local co-op, up to 4 players). The launcher (`SoulsOfTheReaper.exe`) only has one control-related option: whether the mouse also drives the camera.

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

## System Link (LAN play)

Copies of the game on different PCs in the same local network can play together through the game's own System Link menu, as on two Xbox 360 consoles linked by a cable or router.

- **Give each PC its own player number.** Add `systemlink_instance = 1` (2, 3, … for further PCs) to `diablo3.toml` next to `diablo3.exe` on every PC but one. Each number gets its own player ID and the default name `User<N>`; `0` (the default) keeps the classic ID, so existing saves keep working. The launcher leaves this line alone.
- **Set a player name** in the launcher's **Player Name** row (up to 15 characters, blank = `User`). It's remembered in `%LOCALAPPDATA%\SoulsOfTheReaper\player_name.txt` and passed to the game as the `SOTR_USERNAME` environment variable, which you can also set yourself when starting `diablo3.exe` directly.
- **Several network adapters?** If a PC is on more than one network (Wi-Fi plus a VM switch, for example), set `systemlink_address = "192.168.1.20"` to the address the other player can reach.
- Allow `diablo3.exe` through Windows Firewall on private networks when asked.
- `systemlink_trace = true` logs the game's network and session calls, to see what's going on when the PCs don't find each other.

The networking lives in `patches/systemlink/` (new SDK source files) and `patches/rexglue-systemlink-net.patch` (the hooks into the SDK's sockets and XNet calls); `patches/rexglue-username.patch` reads the player name.

---

## Known Issues

### Hand patches to generated code (re-apply after every codegen)

`port/generated/` is rebuilt from scratch by the codegen step, which wipes two fixes it can't produce on its own. `port\build.ps1` reapplies both after every codegen; if you run codegen by hand, run `port\apply_generated_patches.ps1` afterwards. It finds each function by name, so it doesn't depend on how codegen splits the output into files:

- **setjmp/longjmp fix** (`sub_831583B0` / `sub_83158680`) — the recompiler mistranslates the guest setjmp/longjmp pair, corrupting Lua's protected-call mechanism and crashing the GC on startup. Replaced with host `ppc_setjmp`/`ppc_longjmp`.
- **Main-menu exit fix** (`sub_82632E00`) — redirects the game's "leave session, return to title screen" routine (reached from the main-menu B → confirm dialog → A/Aceptar flow) to close the game instead, like a normal PC game's Exit option.

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
