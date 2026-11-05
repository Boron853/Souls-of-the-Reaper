# Cross-platform launcher

A Tauri 2 launcher for Linux and Windows. It shows the same page as the
Windows `Launcher.ps1` (`../v6_borderless_final.html`) and replaces the
PowerShell/WebView2 host with Rust. Linux has been built and run on a desktop.
On Windows 11 a Release launcher outside a source checkout has fetched its
sources, built the SDK and compiled the game through the Build panel (the same
`scripts/build_client.py` as Linux), then started the game with Play.

## What it offers

- **Game Version** lists the builds it finds: `Base`, `Base + Extras`, `update`
  and `Update + Extras`. `+ Extras` is the same executable launched with
  `--extra_features=true`. A source checkout offers each built
  `port/out/build/<platform>-amd64[-update][-plain]-<config>` variant
  (RelWithDebInfo first, then Release and Debug). A release install uses the
  `diablo3`/`diablo3.exe` beside the launcher. Its update flavour comes from
  `game/Default.xex`; whether it carries the extras is read from the executable itself. `-plain` builds are compiled without them and only offer the plain choice.
- **Extras builds** add an `In-game` choice for Internal Resolution and
  Display. It keeps the value saved in the game's Options > Video menu. Any
  other choice overrides it for that launch
  (`--pc_use_saved_render_scale=false` / `--pc_use_saved_window_mode=false`).
- **Linux** shows the Vulkan render path (FSI, or the experimental Host path),
  VSync and Image Scaling (`Off`, `FSR` or `CAS`, passed as
  `--present_effect=bilinear|fsr|cas`). It hides Frame Rate, because the Linux
  SDK has no frame limiter. The spatial effects only change how the rendered
  image is scaled to the window, not the internal resolution, and need an SDK
  built with `patches/linux/rexglue-present-effects.patch`; rebuild the SDK
  after updating (older builds reject the flag). `Off` is the default.
- **Linux** launch settings (⚙) have a Display server choice: `Auto` passes
  nothing and lets SDL choose, `Wayland` and `X11` pass
  `--video_driver=wayland|x11`. It is saved with the other launch settings.
- **Windows** offers a Renderer choice. Direct3D 12 keeps ROV/RTV, frame limit and
  FSR/CAS. Vulkan (`--gpu_backend=vulkan`) shows the same render path and device
  options as Linux, plus VSync and the same Image Scaling choice.
- **Play** checks that `Default.xex` matches the selected build (base disc or
  staged update). For update it also checks the four update CPKs and mounts the folder
  as `update:`. It then starts the game and closes the launcher. If the game
  exits during startup, the launcher stays open and shows the error.

Options are passed as command-line arguments; `diablo3.toml` and F4 keybinds
are never modified. Launch rules mirror `scripts/run_linux.py` and
`scripts/run_windows.ps1`.

## Build the game

In a source checkout, or in a launcher built from a clean pushed commit (see
[Without a checkout](#without-a-checkout)), **Build from disc image…** (in ⚙) runs
[`scripts/build_client.py`](../../scripts/build_client.py). The panel also opens
by itself when no build is found. Choose:

- the USA Ultimate Evil Edition disc image (ISO);
- optionally, the USA Title Update package;
- what to build: **Title Update** (an overlay on the base game files, which are always extracted and never modified) and **Optional PC features** (off compiles the `(no extras)` versions). A "Will compile:" line spells out the result.

The script writes into the game folders from Launch settings (`game/` and
`game/update/` by default; an existing `game-update/` is still used). It runs these steps and skips any that are already done:

1. Check the disc's `Default.xex` before copying anything, then extract the disc.
2. Extract the title update, build the `d3-patch` tool and stage update as a small
   `update/` overlay inside the game folder (about 27 MB: the patched executable and
   the update CPKs; the disc files are not copied).
3. Build the pinned ReXGlue SDK once (`tools/`).
4. Generate code and compile each selected build. Generated code is reused for
   later builds of the same executable.

The launcher embeds the source revision it was built from (`build.rs` reads
`git rev-parse HEAD` and whether the tree has changes) and shows it in the
launch settings. Without git data it reads `unknown`; CI or a source archive
can set `SOTR_COMMIT` and `SOTR_DIRTY=0|1` instead. Release builds should set
`SOTR_REQUIRE_CLEAN=1`, which fails the build for a modified tree or an
unknown revision.

Before it runs anything, the launcher itself (not the Python scripts, since
Windows may have no Python) checks for Python 3, Git, Clang, CMake 3.25+, Ninja
and, on Windows, the Visual Studio C++ tools. The panel lists each one with a
download link when it is missing, and **Build** stays blocked until they are
found (**Check tools** rechecks after an install). On Windows with winget, the
panel also offers **Install missing tools with winget**, which installs each
missing one in turn (`Python.Python.3.13` per user and on `PATH`, `Git.Git`,
`LLVM.LLVM`, `Kitware.CMake` pinned to 3.31.8 because CMake 4 rejects old
third-party minimums, `Ninja-build.Ninja`, and last
`Microsoft.VisualStudio.2022.BuildTools` with the C++ workload and the Windows
SDK). Its note says that it accepts the packages' license agreements; Windows
asks for administrator approval for most of them. The tool check reads the user
and machine `PATH` from the registry, so tools installed while the launcher is
open are found without a restart. Clang, CMake and Ninja
installed in the usual Visual Studio or LLVM folders are found and passed on to
the build even when they are not on `PATH`. The ReXGlue SDK is not a tool you
install: when it is not built yet, the panel asks before fetching the pinned
commit (`port/base/rexglue.lock.json`) and building it, which takes about 3 GB
and 12+ minutes. Answering *Not now* downloads nothing; the script itself is
also told not to (`--no-sdk-download`) unless the panel got a yes.

Progress and output appear in the panel. **Cancel build** stops the script and
the compilers it started, and so does closing the launcher; running it again
continues where it stopped. When the build finishes, Game Version lists the new
builds.

The Clang found must be new enough (18+ on Linux, 22+ on Windows). Warnings
that do not block Build are listed too: no Vulkan driver, no X11 or Wayland
development files (Linux), and under 15 GiB free where the build runs.

The SDK state comes from `scripts/build_client.py --print-sdk-status`, so the
install paths live in one place. An SDK counts as built only when it matches the
pinned commit and the current `patches/` (stamped in `.sotr-sdk.json` in the
install folder). One built from another commit or patch set, or before stamps
existed, shows as out of date and is rebuilt after the same kind of approval.

### Without a checkout

A launcher outside a source checkout can still build when it was compiled from a
clean, fully pushed commit (`BuildInfo::fetchable`). On Build it asks once to
download the game sources for that commit (and the SDK, if needed), then
clones them with `git fetch --depth 1` into `build/sources/<commit>` beside the
launcher, where `<commit>` is the first 12 characters of the commit id (a folder
named after the full id, from earlier launchers, is still used). A launcher in a
folder it cannot write to uses `SoulsOfTheReaper/sources/<commit>` under the
per-user data folder instead (`~/.local/share` on Linux, `%LOCALAPPDATA%` on
Windows). Without git it downloads GitHub's archive of that commit with `curl`
and `tar` instead; git is still required afterwards, because the build script
clones the SDK with it. The SDK, XenonRecomp and `port/out` live inside that
folder. Delete the commit's folder to start over.

On Windows the clones turn on `core.longpaths`: the SDK checkout inside the
fetched sources passes the 260-character path limit when the launcher sits in
a deep folder. Keep the launcher's folder path short (under about 60
characters) all the same, since not every compiler tool handles long paths.

The remote comes from `SOTR_REPO` at launcher build time, defaulting to the
`origin` remote, so set it to the canonical repository for releases and make
sure the commit is pushed there.

Requirements: Python 3, git, CMake 3.25+ (choose its path in the panel if it
is not on `PATH`), Ninja and Clang. Linux also needs the SDK's development
packages. On Windows install Visual Studio 2022 with the C++ and CMake
workloads and LLVM Clang 22+; the usual install folders of Clang, CMake and
Ninja are added to `PATH` automatically, and the build runs
`scripts/build_windows.py` (the one-time SDK build and the compile both happen
in the panel). Allow about 15 GiB of free space for a first build with update. A
release install beside `diablo3` has no sources and no panel.

## Launch settings (⚙)

Game folder, save folders for base and update builds, and the Vulkan device (Linux, and Windows when the Vulkan renderer is selected). The title update has no game folder of its own: it uses the base game folder, whose `update/` folder holds the update (an older full `game-update/` copy is still used if present).
Empty fields use these defaults:

| | Game folder | Save folder |
| --- | --- | --- |
| Base / extras | `game/` | Linux: `$XDG_DATA_HOME/souls-of-the-reaper`; Windows: `Documents\diablo3` |
| update | same as Base (`game/update/` overlay; or `game-update/` if that older full copy exists) | `…/souls-of-the-reaper-update`; Windows: `Documents\diablo3-update` |

Installs made before the update was renamed keep working: a `game/tu2/` overlay or
`game-tu2/` folder, `…-tu2` save folders (used while the new-name folder does not
exist) and the old `gameDirTu2`/`userDataRootTu2` settings keys are all still read.
Rebuild once so the executables are named `…-update-…`.

Game folders sit at the repository root for a source checkout, or beside the
launcher for an install. Settings and the last menu choices are saved in
`launcher.json` under Tauri's app config directory
(`~/.config/org.soulsofthereaper.launcher` on Linux). Settings from the
first prototype move to the update fields when it was set to the update. The game's
output goes to `launcher-stdio.log` in the save folder; on Linux the game log
is `diablo3.log` there.

## Run and build

Install Rust, Node.js/npm and the
[Tauri prerequisites](https://v2.tauri.app/start/prerequisites/). Linux needs
the GTK 3 and WebKitGTK 4.1 development packages; Windows needs the MSVC build
tools and the WebView2 runtime (included with Edge on Windows 10/11).

```sh
cd launcher/tauri
npm ci
npm run dev          # or: npm run build (Release, no installer bundle)
```

The debug executable is `src-tauri/target/debug/sotr-launcher` (`.exe` on
Windows); `npm run build` produces `src-tauri/target/release/sotr-launcher`. Run it from
anywhere inside the checkout, or place a Release build beside an installed
`diablo3`. `prepare-ui.mjs` generates `dist/index.html` and icons; generated
files, dependencies and build outputs are ignored.

## Checks

```sh
npm test                                      # page tests (jsdom), both hosts
cargo test --manifest-path src-tauri/Cargo.toml   # discovery, validation, arguments
```

The page tests run both the generated Tauri page and the unmodified page as
`Launcher.ps1` loads it, so the original Windows launcher stays covered. The
Rust tests cover both platforms' arguments on any host.

## Known gaps

- On Wayland with NVIDIA, the launcher window captured blank in a desktop test
  but rendered correctly under XWayland (`GDK_BACKEND=x11`).
- Windows: installing the tools by hand (download links, no winget) has not been
  tried on a machine that lacks them, and neither has a machine that already has
  CMake 4. Focus hand-off to the game uses `AllowSetForegroundWindow` only;
  `Launcher.ps1` also polled and raised the game window.
- The Remap Controls screen still does not send its bindings, as in
  `Launcher.ps1`; use the in-game F4 menu.
- The installer and `setup.ps1` still package and start `Launcher.ps1`'s
  `SoulsOfTheReaper.exe`.
- Building needs Python 3 and git, from a source checkout or via the fetched
  sources above. Compiling is automated on Linux and Windows, and only the
  USA disc and USA update are accepted.
- Fetching sources has been tried on Linux and Windows. An SDK built before
  stamps existed is rebuilt once.
