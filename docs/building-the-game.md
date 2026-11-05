# Building the game

The game is an AOT recompilation of the Xbox 360 executable using a pinned [ReXGlue SDK](https://github.com/rexglue/rexglue-sdk) (commit recorded in [`port/base/rexglue.lock.json`](../port/base/rexglue.lock.json)). A full build does, in order:

1. Extract the disc image into `game/` (verifying `Default.xex`).
2. Optionally stage Title Update as a small overlay in `game/update/`.
3. Clone, patch and build the pinned SDK into `tools/` (one-time).
4. Run codegen into `port/generated/`, apply the hand patches (`scripts/apply_generated_patches.py`).
5. Compile the game into `port/out/build/<variant>/`.

Every step is skipped when its output already exists, so an interrupted build can be resumed with the same command. Budget roughly 15 GiB of disk for a first build with update, and 12+ minutes for the first SDK build and codegen.

## Inputs

- **Disc image**: USA Ultimate Evil Edition (`.iso`). Or an already-extracted folder holding `Default.xex` and `CPKs/` (the filename must be exactly `Default.xex`), passed as `--game-dir` instead of `--iso`.
- **Title update** (optional): the USA update package.

## Windows

### Requirements

- Windows 10/11 x64
- Visual Studio 2022 (Community is fine) with the **C++** and **CMake** workloads
- LLVM/Clang **22+** (`C:\Program Files\LLVM\bin` is found automatically)
- Git and Python 3
- Ninja (shipped with the Visual Studio CMake workload)

`scripts/build_windows.py` adds the default install folders of Clang, CMake and Ninja to `PATH` if they are missing. It stops with `Not found on PATH: ...` if something is still unavailable. Run it from a regular PowerShell; Visual Studio's folder is only searched at the default `2022\Community` location, so for other editions put CMake and Ninja on `PATH` yourself.

### One command (from the disc image)

```powershell
python scripts\build_client.py --iso C:\path\to\disc.iso --title-update C:\path\to\title-update-package
```

Drop `--title-update` for a base-only build. `--variants base,update,base-plain,update-plain` selects which executables to compile (`-plain` omits the optional PC features). `--check` validates inputs and lists the remaining steps without building.

### Step by step

If you already have an extracted disc in `game\`:

```powershell
python scripts\build_windows.py --build-sdk --game-dir game
```

- `--build-sdk` clones, patches and builds the SDK (`tools\rexglue-sdk-win`, installed to `tools\rexglue-install-win`). Omit it on later builds. Each run resets the checkout to the pinned commit before patching, so local edits there are discarded.
- `--skip-codegen` reuses generated sources, for when only host code (`port\src`) changed. It fails if they were generated from a different executable, manifest, `config/*.toml`, SDK commit or code-generator patch (recorded in `port\generated\<variant>\codegen-inputs.json`).
- `--title-update usa` builds the update executable (needs the staged overlay, see the [update guide](../port/title_updates/update/README.md)).
- `--no-extra-features` compiles without the optional PC features.
- `--jobs N` sets build parallelism (default: CPU count).

Output: `port\out\build\win-amd64-relwithdebinfo\diablo3.exe`

The SDK is patched with `patches/common/*`, `patches/systemlink/*` and `patches/windows/*`. The Direct3D 12 and Vulkan renderers are compiled into the same executable and chosen at launch.

### Run

```powershell
pwsh -File scripts\run_windows.ps1 -ExtraFeatures
```

Useful flags: `-Backend vulkan` (default is Direct3D 12), `-VulkanPath fsi|host`, `-VulkanDevice N`, `-Username "Name"` (max 15 characters). Saves go to `Documents\diablo3`.

## Linux

### Requirements

- Linux x86-64, Python 3
- Clang 18+, CMake 3.25+, Ninja, Git
- The SDK's development packages (SDL/Vulkan/X11/Wayland-related; see the SDK repository for your distribution)
- A Vulkan driver

Use `--cmake /path/to/cmake` if CMake is not on `PATH`. The CPU baseline is x86-64-v2.

`python3 scripts/build_client.py --print-sdk-status` reports whether the SDK is `missing`, `stale` or `current`. After a build the SDK install folder holds `.sotr-sdk.json` (pinned commit and a hash of the patch folders for this host); when either changes, the SDK counts as `stale` and the next build rebuilds it. An SDK reused with `--sdk-prefix` is trusted as given. The graphical launcher builds with the same script and keeps fetched sources in the per-user data folder when it is not in a checkout.

### One command (from the disc image)

```sh
python3 scripts/build_client.py --iso /path/to/disc.iso \
  [--title-update /path/to/title-update] \
  [--variants base,update,base-plain,update-plain]
```

### Step by step

```sh
# Optional: extract the disc (existing files are verified)
python3 scripts/extract_disc.py /path/to/disc.iso game

# Clone the pinned SDK, patch/build/install it, run codegen and compile
python3 scripts/build_linux.py --build-sdk

python3 scripts/run_linux.py
```

- Use `--game-dir /path/to/extracted/disc` to point at a disc extracted elsewhere.
- Use `--sdk-prefix /path/to/installed/sdk` to reuse an installed SDK. It must already include the tracked patches in `patches/common/`; `--build-sdk` is what applies them.
- `--skip-codegen`, `--title-update usa`, `--no-extra-features` and `--jobs N` behave as on Windows.
- `--probe` builds the asset-free GPU diagnostics instead of the game.

Output: `port/out/build/linux-amd64-relwithdebinfo/diablo3`. Saves, logs and caches live in `$XDG_DATA_HOME/souls-of-the-reaper` (default `~/.local/share/souls-of-the-reaper`); override with `--state-dir`.

More run options, diagnostics and input notes are in the [Linux integration notes](../port/base/README.md).

## Build outputs and variants

| Variant | Directory under `port/out/build/` |
| --- | --- |
| Base | `<platform>-amd64-relwithdebinfo` |
| update | `<platform>-amd64-update-relwithdebinfo` |
| Base, no extras | `<platform>-amd64-plain-relwithdebinfo` |
| update, no extras | `<platform>-amd64-update-plain-relwithdebinfo` |

`<platform>` is `win` or `linux`. Normal builds contain the optional [PC features](../port/extra-features.md); they are switched on at launch with `--extra_features` (`-ExtraFeatures` in `run_windows.ps1`).

## Troubleshooting

- **`SHA-256 mismatch` / `Default.xex missing`**: only the unmodified USA Ultimate Evil Edition disc (and USA update) is supported at this time.
- **Interrupted or failed SDK build, or a new SDK pin**: rerun with `--build-sdk`. The checkout is fetched if needed and reset to the pinned commit, then patched from scratch.
- **Interrupted disc or update extraction**: rerun the same command. Partly written files (`*.part`) are resumed; a file whose content differs from the disc is reported and left alone.
- **Stale generated code after pulling changes** to manifests, `config/*.toml`, the SDK pin or code-generator patches: `build_client.py` and the launcher regenerate automatically; with `build_*.py`, rerun without `--skip-codegen`.
- **Windows and Linux SDKs are separate** (`tools/rexglue-sdk-win` vs `tools/rexglue-sdk-linux`); do not share a prefix between them. Generated sources in `port/generated/` are shared.
- **Tests**: `python3 -m unittest discover -s tests -p test_linux_tools.py`
