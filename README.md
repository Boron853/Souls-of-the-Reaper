# Souls of the Reaper

Xbox 360 → PC port of Diablo III built on the [ReXGlue SDK](https://github.com/rexglue/rexglue-sdk) — an AOT recompiler that translates the Xbox 360 PPC binary to native x64 C++, with a Xenia-based kernel HLE, D3D12 GPU (Xenos), XMA audio, and threading.

**Status:** Playable at 60fps stable (RelWithDebInfo / -O2). ROV render path required.

---

## Option A — Just play (no compilation needed)

Download the latest release from the [Releases](../../releases) page, extract the zip, and run `launch.bat`. On first launch it will ask for your Xbox 360 ISO and set everything up automatically.

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
```

After codegen, apply the setjmp fix (see **Known Issues**).

**3. Build**
```powershell
pwsh -File port\build.ps1 -Config RelWithDebInfo
```

Output: `port\out\build\win-amd64-relwithdebinfo\diablo3.exe`

> If only the runtime DLL changed after a rebuild, copy it manually:
> ```powershell
> Copy-Item rexglue-sdk\out\win-amd64\rexruntimerd.dll port\out\build\win-amd64-relwithdebinfo\ -Force
> ```

**4. Run**
```
launch.bat
```

---

## Controls

Three modes selectable from `launch.bat`:

| Mode | Description |
|------|-------------|
| 1 — Gamepad | Standard Xbox 360 controller |
| 2 — Keyboard only | WASD + buttons, mouse disabled |
| 3 — Keyboard + mouse | WASD; mouse = right stick (dodge); clicks = triggers/R3 |

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

### setjmp fix (re-apply after every codegen)

In `port/generated/default/diablo3_recomp.108.cpp`, replace the bodies of `sub_831583B0` and `sub_83158680` with calls to `ppc_setjmp` / `ppc_longjmp` (from `<rex/init.h>`). Without this the game crashes on Lua GC startup.

### Save requirement

"Create new character" with zero saves is not yet functional. A Diablo III RoS save must exist at:
```
%USERPROFILE%\Documents\diablo3\<xuid>\394F07D4\00000001\d3save\
```

### ROV render path

`render_target_path_d3d12 = "rov"` is required. Diablo III uses EDRAM aliasing in its deferred lighting pass; ROV emulates this correctly. RTV renders the world black.

---

## Project Layout

```
souls-of-the-reaper/
├── launch.bat             # Game launcher (control mode + FPS selector)
├── setup.ps1              # First-run setup: extracts game data from ISO
├── apply_config.ps1       # TOML config merger used by launch.bat
├── patches/
│   ├── rexglue-sdk.patch  # SDK modifications (git diff)
│   └── d3d_screenshot.cpp # New file added to the SDK
└── port/
    ├── src/               # Port-specific C++ (kernel overrides, FATX cache device)
    ├── diablo3_manifest.toml
    ├── diablo3_overrides.toml
    ├── CMakeLists.txt
    ├── CMakePresets.json
    └── build.ps1
```

---

## Credits

- [ReXGlue SDK](https://github.com/rexglue/rexglue-sdk) — recompiler + runtime (based on [Xenia](https://xenia.jp/))
- Blizzard Entertainment — Diablo III
