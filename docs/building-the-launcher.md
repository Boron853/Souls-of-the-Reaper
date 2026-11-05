# Building the launcher

Two launchers exist. Use the **Tauri launcher** unless you specifically need the legacy one.

| Launcher | Platforms | Source |
| --- | --- | --- |
| Tauri (Rust + WebView) | Windows, Linux | [`launcher/tauri/`](../launcher/tauri/README.md) |
| PowerShell/WebView2 (legacy) | Windows only | [`launcher/Launcher.ps1`](../launcher/Launcher.ps1) |

Both show the same page (`launcher/v6_borderless_final.html`).

## Tauri launcher (Windows and Linux)

### Requirements

- [Rust](https://rustup.rs/) (stable) and Node.js with npm
- Windows: MSVC build tools (Visual Studio 2022 C++ workload) and the WebView2 runtime (already present on Windows 10/11 with Edge)
- Linux: GTK 3 and WebKitGTK 4.1 development packages, e.g.
  - Debian/Ubuntu: `sudo apt install libgtk-3-dev libwebkit2gtk-4.1-dev build-essential libssl-dev libayatana-appindicator3-dev librsvg2-dev`
  - Fedora: `sudo dnf install gtk3-devel webkit2gtk4.1-devel openssl-devel librsvg2-devel`
- See the [Tauri prerequisites](https://v2.tauri.app/start/prerequisites/) for other setups

### Build and run

The commands are the same on both platforms:

```sh
cd launcher/tauri
npm ci
npm run dev       # debug build, opens the launcher
npm run build     # Release build, no installer bundle
```

Outputs:

| Build | Windows | Linux |
| --- | --- | --- |
| Debug | `src-tauri\target\debug\sotr-launcher.exe` | `src-tauri/target/debug/sotr-launcher` |
| Release | `src-tauri\target\release\sotr-launcher.exe` | `src-tauri/target/release/sotr-launcher` |

`npm run prepare-ui` (run automatically) generates `dist/index.html` and the icons; those and `target/` are git-ignored.

### Where to run it

- **Source checkout**: run it from anywhere inside the checkout. It finds `port/out/build/...` variants and offers **Build from disc image…** (in the ⚙ menu), which drives [`scripts/build_client.py`](../scripts/build_client.py) exactly as described in [Building the game](building-the-game.md). It needs Python, Git, CMake 3.25+, Ninja and Clang available (see that guide).
- **No checkout**: a launcher built from a clean, pushed commit downloads the matching sources into the per-user data folder the first time you build (asking first) and builds from there; see [Without a checkout](../launcher/tauri/README.md#without-a-checkout). Set `SOTR_REPO` when building the launcher if `origin` is not the canonical repository.
- **Release install**: place the Release executable beside `diablo3` / `diablo3.exe`. The build panel is not shown there.

### Checks

```sh
npm test                                          # page tests (jsdom)
cargo test --manifest-path src-tauri/Cargo.toml   # discovery, validation, arguments
```

## PowerShell launcher (Windows, legacy)

The compiled exe, icon and WebView2 DLLs are not in the repository, so supply them first:

1. Download the [`Microsoft.Web.WebView2`](https://www.nuget.org/packages/Microsoft.Web.WebView2) NuGet package and copy `Microsoft.Web.WebView2.Core.dll`, `Microsoft.Web.WebView2.WinForms.dll` and `WebView2Loader.dll` into `launcher\lib\`.
2. Provide your own `launcher\ico_launcher.ico`.
3. Build:

```powershell
Install-Module ps2exe -Scope CurrentUser -Force   # one-time
launcher\build_launcher.ps1
Copy-Item launcher\dist\SoulsOfTheReaper.exe . -Force
```

The script embeds the page, icon and DLLs into a single `SoulsOfTheReaper.exe`. It must sit at the repository/release root, next to `apply_config.ps1`, `game\` and `diablo3.exe`.

## Windows installer (optional)

[`installer/SoulsOfTheReaper.iss`](../installer/SoulsOfTheReaper.iss) is an Inno Setup script that packages the game binaries and extracts game data from a user-supplied disc image during install:

```powershell
ISCC.exe installer\SoulsOfTheReaper.iss
```

Note that the installer and `setup.ps1` still package the legacy PowerShell launcher, not the Tauri one.
