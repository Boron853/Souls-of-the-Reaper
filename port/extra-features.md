# Optional PC features

The optional PC features modify the base game on Windows and Linux, and the
verified USA update build:

- The press-button launch screen appends ` + Extras` to the original version.
- An Options > Video left/right selector, `Render resolution (restart required)`,
  using the same native control as volume and region. Choose `1x`, `2x` or
  `3x`; the selection is saved immediately.
- An Options > Video `Window mode` selector with `Windowed` and
  `Borderless fullscreen` choices. Changes are saved and applied on the UI
  thread without restarting. F11 toggles the current mode without changing
  the saved preference.
- The startup autosave warning replaces English `Xbox 360 console`,
  `Xbox 360 Console`, `Xbox 360` and `Xbox360` wording with `PC`.
  Other localized wording is preserved.

## Build-time and run-time switches

The build scripts compile the features into the normal executable, but they
stay **off at launch** until the `extra_features` cvar is set
(`--extra_features=true`; the run scripts and graphical launcher do this for
`--extra-features` / `-ExtraFeatures` / "Base + Extras"). Without it every hook
hands straight back to the original game function, so the game keeps its
existing menus, autosave wording and version label, and one executable serves
both modes. The base disc and update still need separate executables because they
use separate audited address maps with shared hook logic.

To compile **without** any of the extra code, build a plain executable with
`--no-extra-features`. It is written to a
`-plain` directory next to the normal one. Direct CMake builds choose with
`-DSOULS_ENABLE_EXTRA_FEATURES=ON|OFF` (default `OFF`).

## Windows

Build and launch (the build script handles the SDK, codegen and generated-code
patches; see the main README):

```powershell
python scripts\build_windows.py --build-sdk --game-dir game
pwsh -File scripts\run_windows.ps1 -ExtraFeatures
```

The binary is
`port\out\build\win-amd64-relwithdebinfo\diablo3.exe`; a `--no-extra-features` build goes to
`win-amd64-plain-relwithdebinfo`.

The source-build launch script defaults to `game\` and `Documents\diablo3`.
Use `-GameDir` and `-UserDataRoot` to select other directories. `-ResScale 2`
explicitly overrides the saved in-game selection for that launch. The graphical
launcher lists the executable twice, as `Base` and `Base + Extras`; the second
adds `--extra_features=true`. Launching the executable directly needs that
flag too.

## Linux

After installing the Linux SDK and generating the base-disc sources:

```sh
python3 scripts/build_linux.py \
  --game-dir /path/to/extracted/disc
python3 scripts/run_linux.py --extra-features \
  --game-dir /path/to/extracted/disc --vulkan_device=1
```

Use `--sdk-prefix /path/to/installed/sdk` to reuse an existing SDK. Omit
`--skip-codegen` for the first build or after changing codegen inputs.
The executable is
`port/out/build/linux-amd64-relwithdebinfo/diablo3`; `--no-extra-features` builds
`port/out/build/linux-amd64-plain-relwithdebinfo/diablo3` instead (run it with
`run_linux.py --plain`).
For direct CMake builds on either platform, use a separate build directory and
pass `-DSOULS_ENABLE_EXTRA_FEATURES=ON` and
`-DSOULS_BASE_XEX=/path/to/extracted/disc/Default.xex`. Generate and patch that
platform's sources first. CMake verifies the executable hash and required
hook function mappings.

The user-data directory is the one selected by `--state-dir` or
`--user_data_root`. With `--extra-features`, `run_linux.py` reads the
`render_scale` value from `pc-settings.ini` there and supplies
`--resolution_scale=N` at startup. Without it the file is ignored. A missing
executable produces an error rather than launching a different build.

### Linux image scaling

`patches/linux/rexglue-present-effects.patch` (applied by `build_linux.py
--build-sdk`) compiles the SDK's built-in spatial present effects into the
Vulkan presenter. They change only how the rendered image is scaled to the
window, not the internal resolution:

```sh
python3 scripts/run_linux.py --extra-features --present_effect=fsr \
  --window_width=1920 --window_height=1080
```

`--present_effect` is `bilinear` (default, plain stretch), `cas` or `fsr`
(FSR 1.0 EASU+RCAS). `fsr2` and `fsr3` need the external FidelityFX runtime and
are not available. The graphical launcher exposes the choice as Image Scaling.
An SDK built before this patch does not know the flag; rebuild it with
`--build-sdk`.

### Linux update

Use the staged update executable and assets:

```sh
python3 scripts/build_linux.py --title-update usa \
  --sdk-prefix /path/to/rexglue-install \
  --game-dir /path/to/updated-disc \
  --cmake /path/to/cmake
python3 scripts/run_linux.py --title-update usa --extra-features --vulkan_device=1 \
  --game-dir /path/to/updated-disc
```

The binary is `port/out/build/linux-amd64-update-relwithdebinfo/diablo3`
(`linux-amd64-update-plain-relwithdebinfo` with `--no-extra-features`). It uses the
update user-data directory, and ignores the saved render scale unless launched
with `--extra-features`. For direct
CMake builds, enable both `SOULS_TITLE_UPDATE` and `SOULS_ENABLE_EXTRA_FEATURES`
and set `SOULS_BASE_XEX` to the patched update `Default.xex`. Its required SHA-256 is
`447652ffa8abe4c7b8bed590a3887efc23e1181fd836b7a3192b8a2a37ddf80f`.
On Windows the title update uses the same shared codegen and hooks.

## Saved settings and game behavior

The optional game itself reads the selection from its resolved user-data
directory before graphics setup, so direct executable launches work too.
Normal builds omit this startup behavior. On Linux, the optional app loads
the GPU plugin before applying settings, because the plugin registers the
resolution cvars.

The saved setting takes effect after closing and relaunching the optional
build. The GPU caches are initialized at startup; the menu does not change
resolution live. Explicit `--resolution_scale`, `--draw_resolution_scale_x`
or `--draw_resolution_scale_y` arguments passed through the Linux launch script
override the saved setting. Windows uses `-ResScale` for the same purpose.
When launching the optional executable directly, add
`--pc_use_saved_render_scale=false` alongside explicit scale arguments to
override the menu selection. This flag exists only in optional builds.
The tooltip displays the active axis scales and saved selection. A failed
save keeps the previous selection and reports an error.

Settings are written to a temporary file and replaced on success. Windows uses
[MoveFileExW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexw)
with replacement enabled and wide paths; Linux uses a same-directory rename.

The autosave override changes the temporary guest string returned by the
existing localization function, using the game's string-assignment API.
It applies only to `ConsoleUI:AutosaveWarningScreenText_XBox360`. Game assets
and console save contents are untouched.

## Window mode

Optional builds save the menu preference as `window_mode` in `pc-settings.ini` in
the resolved user-data directory (`1` for windowed, `2` for borderless
fullscreen). The same file holds `render_scale` (`1` to `3`), and saving one
setting keeps the other. Builds that wrote one file per setting
(`pc-render-scale.txt`, `pc-window-mode.txt`) still have those values honoured
until the setting is saved again. Missing or invalid values keep the launch mode. A failed save restores the previous menu
selection. Normal builds do not read or write this preference.

The menu uses action ID 101 and the same audited native selector hooks as render
scale. Guest callbacks save and queue changes; the window dialog applies them on
the UI thread. The current mode is synchronized with F11 when initializing the
selector. Fullscreen uses the SDK's borderless window mode; there is no separate
exclusive-fullscreen choice.

On Linux, explicit `--fullscreen=true` or `--fullscreen=false` passed through
`run_linux.py --extra-features` overrides the saved preference for that launch.
On Windows, use `run_windows.ps1 -ExtraFeatures -WindowMode Windowed` or
`-WindowMode Borderless`. Direct executable launches can override the preference
with `--pc_use_saved_window_mode=false --fullscreen=true` (or `false`).

Tests cover window-mode persistence (invalid values, failed saves) and Linux
launch overrides. The selector hooks themselves have no automated test.

## Base-disc address audit

The base-disc hooks use the unmodified USA Ultimate Evil Edition executable with
SHA-256 `cc918a70940517f974d0fd60d4936c8236e8dc21130cf4a8b8ae915451c289ef`,
validated by CMake for optional builds on both platforms. Regenerate Windows
sources from this same base disc before enabling the hooks.

The base-disc generated calls confirm the string and descriptor helpers used
here. The update address audit below records the corresponding updated functions.

| Purpose | Base-disc address |
| --- | --- |
| Options initialization | `0x826FD808` |
| Selector choice count | `0x826FBFF0` |
| Selector initialization | `0x826FC030` |
| Selector value label | `0x826FC798` |
| Selector change handling | `0x826FCE80` |
| Localization | `0x8282F0F0` |
| Descriptor initialization | `0x826FBD68` |
| Descriptor construction | `0x826FBE30` |
| Video vector insertion | `0x82700AD8` |
| String construction | `0x82CDAD58` |
| String assignment | `0x82CDB0F0` |
| String buffer access | `0x82CD9520` |
| String destruction | `0x82CDA018` |

The Video vector remains at owner + 128. The descriptor action ID is at +32;
ID 100 selects the added row. The base-disc options owner pointer is at
`0x83302514`, with its dirty flag at +344. The autosave localization key was
confirmed at `0x820A4868`; matching uses its text rather than its address.

The hooks delegate existing game functions and preserve the guest context
around injected calls. The menu insertion uses the original vector helper
which copies and destroys the temporary descriptor. The descriptor constructor
consumes the temporary key strings. Normal and optional builds share generated functions and
disc inputs on each platform; only the optional host links the menu, selector,
localization and version hooks.

The render row uses descriptor type 1 (the native left/right selector), with
three zero-based choices mapped to scales 1–3. The selector model at owner + 4
stores the current option ID at +4. Its vtable at `0x820AB768` supplies the
choice count and label callbacks. Initialization uses `0x82749C10` without
notification; user changes enter `0x826FCE80`, resolve the control via
`0x8246C520`, and read its selected index at +472. The callback bounds-checks
the active descriptor through owner +296/+12, saves the setting and marks
the model dirty. A failed save restores the prior selector value without
firing another change event. Value-label updates retain the original row
highlighting and set `SelectorTemplateText` at `0x8207F9A4` to `1x`, `2x` or `3x`.
All unrelated option IDs delegate the original game callbacks.

The version hook delegates the original 1024-byte formatter at `0x823BD130`
and appends the suffix only for the start-screen call returning to `0x8247C004`
with the `%s` format at `0x82003ED0`. That call supplies the build string to
`Root.NormalLayer.ConsoleStart_main.LayoutRoot.Version` (handle `0x832ED860`).
It preserves the returned guest context, checks buffer capacity, and leaves
other formatting calls and the game's actual version data untouched.

## update address audit

Every game-build-specific value (guest function addresses, data addresses,
structure offsets and the expected `Default.xex` SHA-256) lives in one profile
per build, [`src/features/versions/<id>.json`](src/features/versions/). CMake
reads the selected profile (`base`, or `update-usa` with `SOULS_TITLE_UPDATE`;
override with `-DSOULS_FEATURE_VERSION=<id>`), verifies the executable hash and
generated symbols, and writes the header the hooks compile against. Supporting
another build means adding a profile with the same names; no C++ changes.

To generate a candidate profile for a new executable from a verified one:

```sh
python3 scripts/find_feature_addresses.py --reference update-usa \
  --reference-xex game/update/Default.xex --target-xex /path/to/new/Default.xex --id mybuild
```

It decodes both executables with `d3-image` from `scripts/d3-patch`
(`build_client.py` configures `tools/d3-patch` but builds only `d3-patch`; run
`cmake --build tools/d3-patch --target d3-image`, or pass `--d3-image`). It
finds each function by its masked instruction body, and re-derives data
addresses from the same code. Entries that are not a unique body match are
flagged (`weak`, `ambiguous`, `unresolved`) and must be checked by hand. Run
`--sign <id> --target-xex <xex>` to refresh a profile's runtime signatures.
Generating `update-usa` from the base disc, `base` from the update, and each
profile from its own executable reproduces the checked-in addresses and
signatures. This was checked by hand against the real executables; there is no
automated test for it, because it needs the disc and update.

At runtime the hooks compare each profile function's 12-word `signature` with
guest memory, and disable the extras (with a log warning) on a mismatch; the log
reports how many signatures were verified. Words are masked the same way in
`find_feature_addresses.py` (`mask_word`) and `pc_features.cpp` (`MaskWord`).
Branch targets and D/DS-form displacements and immediates are masked; `li`
constants and the `ld`/`ldu`/`lwa`, `std`/`stdu` sub-opcode are kept. The window
always covers 12 words, even past a `blr`. Short functions therefore also
check the code that follows them; it is the same in both builds:

- `resolve_label` and `selector_control` are entries in a 44-entry
  `li r4,N; b handler` stub table. Their `li` values (4 and 56) and the next
  five entries tell them apart.
- `string_c_str` is `lwz r3,4(r3); blr`, with an identical accessor right after
  it. The masked `lwz` offset cannot be kept, because the same opcode is the
  low half of `lis`/`lwz` address pairs.
- `string_destroy` is a single `b` to the destructor body plus one padding
  word. The rest of its window is the prologue of the next function.

On their own, the words of `resolve_label` match 18 places in the executable,
those of `string_c_str` 3,888 and those of `string_destroy` 12,671. With the
full window, each of the four signatures matches once.

[`extra-features-audit.json`](title_updates/update/extra-features-audit.json)
records the instruction-context matches, corroborating generated call sites,
and the unchanged descriptor/control layouts.

| Purpose | Base disc | update |
| --- | --- | --- |
| Options initialization | `0x826FD808` | `0x82703EF0` |
| Selector count / initialization | `0x826FBFF0` / `0x826FC030` | `0x827026D8` / `0x82702718` |
| Selector label / change | `0x826FC798` / `0x826FCE80` | `0x82702E80` / `0x82703568` |
| Localization | `0x8282F0F0` | `0x82835EE0` |
| Options owner | `0x83302514` | `0x8330340C` |
| Selector text path | `0x8207F9A4` | `0x82080A1C` |
| Start-screen formatting return | `0x8247C004` | `0x8247E340` |

The formatter and `%s` string remain at `0x823BD130` and `0x82003ED0`.
CMake validates the selected executable hash and all seven hooks plus their
helper mappings before enabling the feature source.

## Validation

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
```

Tests cover save/load and failure handling, autosave wording, invalid settings,
command-line precedence, custom user-data directories and normal-build
isolation. The native logic test requires a C++23 compiler. Desktop visual checks and a relaunch at a newly saved scale remain to be
verified.

There is no SDK integration test or headless guest-hook test. The guest hooks in
`pc_features.cpp` (selector, version suffix, autosave wording, runtime signature
check) run only inside the game, for the base disc and the update alike.
