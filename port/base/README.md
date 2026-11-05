# Linux integration

This path combines the shared Souls of the Reaper application and cache/kernel
overrides with the ReXGlue Vulkan work from the D3 recompilation investigation. It targets
the unmodified USA Ultimate Evil Edition base disc, with executable SHA-256
`cc918a70940517f974d0fd60d4936c8236e8dc21130cf4a8b8ae915451c289ef`.
Linux gameplay validation is still limited; the Windows playable-status claim
does not apply to Linux.

## Title updates

A separate [verified USA update setup](../title_updates/update/README.md) stages the updated executable
and assets, with dedicated codegen, binary and user-data paths. Use
`--title-update usa` with the staged `--game-dir` to build or launch it.
The default remains the unmodified base disc. Add `--extra-features` when
launching update to switch on the PC menu features; Windows uses the same update
guest configuration.

## Build and run

Requirements: Linux x86-64, Python 3, Clang 18+, CMake 3.25+, Ninja, the SDK's
Linux development dependencies, and a Vulkan driver. The CPU baseline is
x86-64-v2. Use `--cmake /path/to/cmake` if CMake is not on PATH.

The simplest route is one command from your disc image (the
[launcher](../../launcher/tauri/README.md#build-the-game) runs the same script):

```sh
python3 scripts/build_client.py --iso /path/to/disc.iso \
  [--title-update /path/to/title-update] [--variants base,update,base-plain,update-plain]
```

It checks the disc, extracts it to `game/`, optionally adds update as a small
`game/update/` overlay, builds the pinned SDK, and compiles the selected builds. Finished
steps are skipped, so you can run it again after an interruption. Use `--check`
to validate the inputs and list the remaining steps.

The individual steps remain available:

```sh
# Optional extraction from your disc dump (existing files are verified).
python3 scripts/extract_disc.py /path/to/disc.iso game

# Clone the pinned SDK, apply Linux fixes, build/install it, generate and build the game.
python3 scripts/build_linux.py --build-sdk
python3 scripts/run_linux.py
```

The SDK commit is recorded in [rexglue.lock.json](rexglue.lock.json).
Its checkout and installed prefix live in `tools/rexglue-sdk-linux` and
`tools/rexglue-install-linux`. Keep this SDK separate from the Windows checkout:
the Windows SDK patch was authored for another SDK revision.

Existing disc files and an installed SDK can be used without copying gigabytes:

```sh
python3 scripts/build_linux.py \
  --sdk-prefix /path/to/installed/sdk \
  --game-dir /path/to/extracted/disc
python3 scripts/run_linux.py --game-dir /path/to/extracted/disc --vulkan_device=1
```

An existing SDK prefix must contain the fixes below; the build script cannot
verify modifications from an installed SDK's version string. `--build-sdk`
verifies the source revision and applies each tracked patch idempotently.
`--sdk-source` selects a source checkout when building the SDK.

Generated Linux sources live in `port/generated/base`, shared by the
Windows build. Rebuild with `--skip-codegen` after changing
host code. Regenerate after changing SDK codegen, manifests, or guest function
hints. Direct CMake builds require previously generated and patched sources.

The output is `port/out/build/linux-amd64-relwithdebinfo/diablo3`. Saves, logs,
and caches default to `$XDG_DATA_HOME/souls-of-the-reaper` (or
`~/.local/share/souls-of-the-reaper`). Override with `--state-dir /path`.
Launch options are forwarded to ReXGlue, and explicit options override defaults.
Linux requires the exact filename `Default.xex`. The launcher uses Vulkan FSI;
the SDK may fall back when a device lacks fragment shader interlock.
Press F11 to toggle fullscreen (the same shared handler is used on Windows). The title bar shows guest swaps per second and
render/window dimensions.

## Keyboard and mouse

Keyboard controller emulation is enabled by default. WASD moves; arrows control
D-pad; Space/Enter = A, Shift = B, J/U = X/Y, O/K = LB/RB, H/L = LT/RT,
Tab/I = inventory, and Escape = pause. C/V press the left/right stick, and
Numpad 8/2/4/6 drives the right stick for dodging (Num Lock enabled).
Press F4 to edit and save bindings in the SDK settings overlay.

The keyboard shares player 1 with the first gamepad. Linux uses the SDK's
stable device-slot assignment, rather than Windows' first-input player assignment.
Mouse input is disabled by default; opt in with:

```sh
python3 scripts/run_linux.py --mnk_mouse=true
```

This enables mouse right-stick movement, left/right clicks = RT/LT, and middle
click = right-stick press. Mouse capture is released when focus is lost or a
UI dialog captures input. Use `--mnk_mode=false` for gamepad-only input.
Existing saved `keybind_*` values are preserved; update them through F4 if an
older SDK layout was saved. The launcher enables keyboard input even if an old
config disabled it; an explicit `--mnk_mode=false` overrides the launcher.

Rebuild the SDK with `--build-sdk` to install the keyboard patch. If supplying
an existing `--sdk-prefix`, it must also include `rexglue-keyboard.patch`.

An [optional extra-features build](../extra-features.md) adds an in-game resolution
scale setting, PC wording for the autosave warning, and ` + Extras` on the
launch-screen version label. They are compiled in by default and switched on by
launching with `--extra-features`; without it the game is unchanged. Build with
`--no-extra-features` to leave the code out of the executable.

To compare the experimental faster host render-target path with FSI, use
`--render_target_path_vulkan=host`. Check lighting, textures and effects as well
as FPS; this path previously produced incorrect graphics. Use
`--render_target_path_vulkan=fsi` to return to the default.

## Diagnostics and checks

```sh
python3 scripts/build_linux.py --probe
python3 scripts/run_linux.py --probe
python3 scripts/run_linux.py --render-smoke --smoke_frames=120
python3 -m unittest discover -s tests -p 'test_linux_tools.py'
```

The probe checks the Xenos plugin and Vulkan device requirements. The smoke
test draws a triangle and checkerboard without game assets. These need access
to GPU device nodes; the windowed test also needs a desktop session. They do
not establish that guest rendering or gameplay is correct.

Shader investigation tools were retained as `scripts/validate_shader_dumps.py`
and `scripts/check_texture_exponents.py`; consult their `--help` output.

## Imported work and adaptations

- `patches/common/rexglue-keyboard.patch`: enables the game keyboard layout, supports
  Shift alongside movement, emits controller keystrokes for menus, gates mouse
  clicks behind mouse mode, and suppresses gameplay input while typing in dialogs.
- `patches/common/rexglue-registration.patch`: faster bulk function registration
  and gap cleanup; `tests/rexglue_registration.cpp` compares against original
  behavior and runs during SDK builds.
- `patches/common/rexglue-texture-exponent.patch`: reads texture exponent bias
  from fetch word 3 rather than unrelated sampler state in word 4.
- `patches/common/rexglue-object-reference.patch`: implements native-object
  retain and avoids corrupting enumerator bodies on reference/dereference.
- `config/`: audited base-disc callbacks, tail-call thunks and 85 leaf entries,
  kept separate from the existing Windows hints.
- `port/probe/`: standalone GPU and rendering diagnostics, with runtime DSO
  staging added for the probe.
- `port/src/window_features.*`: guest frame telemetry using the original SDK
  `VdSwap` via `RTLD_NEXT`, adapted to the shared application's generated header.
- Disc extraction and shader validation scripts from the recomp investigation.

The existing Souls guest setjmp/longjmp and menu-exit patches are applied by
`scripts/apply_generated_patches.py`. Symbol lookup works across changing shard
numbers and fails before editing if a required definition is missing. The jump
state is shared across translation units, since the newer codegen may put the
two functions in different files. The Linux menu-exit hook lives in the host.

The pinned codegen reports an unresolved conditional branch from `0x82FAB400`
to `0x82FAB3DC` and a function at `0x831BF180` larger than its preferred shard
size. These diagnostics require further guest-code investigation; a successful
native build does not prove complete function recovery.

Historical brightness amplification, forced texture formats, verbose GPU
diagnostic SDK patches, XenonRecomp instruction patches, downloaded tools,
generated guest sources, copyrighted assets, and update experiments were not
imported. Normal texture colors and FSI are the Linux defaults.
