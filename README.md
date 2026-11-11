# Souls of the Reaper

<a href="https://recomplauncher.com/game/souls-of-the-reaper"><picture><source media="(prefers-color-scheme: dark)" srcset="https://recomplauncher.com/assets/press/launcher/badge-light.svg"><img alt="Get it on RecompLauncher" src="https://recomplauncher.com/assets/press/launcher/badge-dark.svg" height="48"></picture></a>

Xbox 360 → PC port of Diablo III built on the [ReXGlue SDK](https://github.com/rexglue/rexglue-sdk) — an AOT recompiler that translates the Xbox 360 PPC binary to native x64 C++, with a Xenia-based kernel HLE.

**Status:** Playable and stable (RelWithDebInfo / -O2). Two render paths: ROV (faithful, 60fps) and RTV (fast, up to 240fps with lighting and artifacts fixed).

---

## Option A — Just play (no compilation needed)

Download the latest release from the [Releases](../../releases) page, extract the zip, and run `SoulsOfTheReaper.exe`. On first launch it will ask for your Xbox 360 ISO and set everything up automatically.

---

## Option B — Build from source

### Requirements

- Windows 10/11 x64
- Visual Studio 2022 Community (CMake 3.25+, Ninja, MSVC headers)
- LLVM/Clang 22+ installed to `C:\Program Files\LLVM\`
- [ReXGlue SDK](https://github.com/rexglue/rexglue-sdk) cloned as `rexglue-sdk/` next to this folder
- Diablo III Xbox 360 disc dump:
  - `game/Default_decrypted.exe` — decrypted XEX (flat binary, base 0x82000000)
  - `game/CPKs/` — all CPK archives from the disc (7.4 GB)
  - A valid Diablo III RoS save in `Documents\diablo3\<xuid>\394F07D4\00000001\d3save\`

### Steps

**1. Apply SDK patches**
```powershell
git -C rexglue-sdk apply ..\patches\rexglue-sdk.patch
Copy-Item patches\d3d_screenshot.cpp rexglue-sdk\src\graphics\d3d12\
```

**2. Codegen** (~12 min, one-time per XEX)
```powershell
sdk-bin\win-amd64\bin\rexglue.exe --log-level info --log-file port\cg.log codegen port\diablo3_manifest.toml
port\apply_generated_patches.ps1
```

`apply_generated_patches.ps1` re-applies the hand patches codegen can't produce on its own (see **Known Issues**). Run it every time codegen is (re-)run — it's idempotent, safe to run more than once.

**3. Build**
```powershell
pwsh -File port\build.ps1 -Config RelWithDebInfo
```

Output: `port\out\build\win-amd64-relwithdebinfo\diablo3.exe`

> If only the runtime DLL changed after a rebuild, copy it manually:
> ```powershell
> Copy-Item rexglue-sdk\out\win-amd64\rexruntimerd.dll port\out\build\win-amd64-relwithdebinfo\ -Force
> ```

**4. Build the launcher**

The launcher's compiled exe, icon, and the WebView2 SDK redistributable DLLs aren't in the repo (binaries, not code) - only its source is (`launcher/Launcher.ps1`, `launcher/build_launcher.ps1`, `launcher/v6_borderless_final.html`). To build it:
- Get the WebView2 SDK redistributable DLLs (`Microsoft.Web.WebView2.Core.dll`, `Microsoft.Web.WebView2.WinForms.dll`, `WebView2Loader.dll`) from the [`Microsoft.Web.WebView2`](https://www.nuget.org/packages/Microsoft.Web.WebView2) NuGet package and place them in `launcher\lib\`.
- Supply your own `launcher\ico_launcher.ico` (the original artwork isn't included).
```powershell
Install-Module ps2exe -Scope CurrentUser -Force  # one-time
launcher\build_launcher.ps1
Copy-Item launcher\dist\SoulsOfTheReaper.exe . -Force
```

**5. Run**
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

## Known Issues

### Hand patches to generated code (re-apply after every codegen)

`port/generated/` is rebuilt from scratch by the codegen step, which wipes two fixes it can't produce on its own. Run `port\apply_generated_patches.ps1` after every codegen (see step 2 above) to reapply both:

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
