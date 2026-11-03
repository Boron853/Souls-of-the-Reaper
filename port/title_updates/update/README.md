# USA Title Update

This build targets the verified update for title `394F07D4`, media `38E299CD`.
The package version is `2`; the executable changes from `0x2` to `0x202`
(displayed by ReXGlue as `0.0.2.2`). Native compilation does not establish
gameplay compatibility. On multi-GPU systems, pass `--vulkan_device=N` to
select the GPU.

| Input | SHA-256 |
| --- | --- |
| Original `Default.xex` | `cc918a70940517f974d0fd60d4936c8236e8dc21130cf4a8b8ae915451c289ef` |
| update package | `faf9feaa28e75035e61a960231d2c27f0bed3b7676db65747fa25352f19bddf3` |
| Patched `Default.xex` | `447652ffa8abe4c7b8bed590a3887efc23e1181fd836b7a3192b8a2a37ddf80f` |

## Game folder layout

By default the update is a small overlay inside the base game folder: `game/update/` holds
the patched `Default.xex`, the four update CPKs and `applied-update-manifest.json`
(about 27 MB). `game/` stays the unmodified disc and is the game root; `game/update`
is mounted as `update:`, and update builds load `game:\update\Default.xex` when it
exists. Create it with `scripts/build_client.py`, or with
`scripts/stage_title_update.py --base game --update ... --patcher ...` (no
`--output`). Pass `--game-dir game` wherever an update command takes `--game-dir`.

The older layout, a complete separately staged folder (`--output`, or
`build_client.py --game-dir-update`), is still detected and works unchanged.
Saves stay separate either way.

## Linux build and launch

Stage the update with the staging command below. By default this creates the
`game/update/` overlay described above; a separate disc directory (the older
layout) is also supported, and the examples below use one. The original disc and
update package remain intact. `applied-update-manifest.json` records input and
output hashes and verified source compatibility.

Build and run from the Souls of the Reaper repository:

```sh
python3 scripts/build_linux.py --title-update usa \
  --sdk-prefix /path/to/rexglue-install \
  --game-dir /path/to/updated-disc \
  --cmake /path/to/cmake
python3 scripts/run_linux.py --title-update usa --vulkan_device=1 \
  --game-dir /path/to/updated-disc
```

After codegen, `--skip-codegen` reuses update sources only if their recorded
executable hash matches. Output is `port/out/build/linux-amd64-update-relwithdebinfo/diablo3`;
generated sources are in `port/generated/update`. The launcher's default
user-data directory is `$XDG_DATA_HOME/souls-of-the-reaper-update` or
`~/.local/share/souls-of-the-reaper-update`; `--state-dir` can override it.
Both launch modes verify the executable hash to prevent using one build with
the other executable. With the overlay layout, `game/` is the game root and
`game/update` is mounted as `update:`. With the older full-copy layout, update
files are already merged into the staged disc, and the launcher mounts that
folder as both `game:` and `update:` so the guest can find the patch CPKs. Either
way the staged folder contains no XEXP, so the executable is not patched a second time.

Keyboard input and F11 work through the shared application/SDK controls.
Mouse input remains opt-in with `--mnk_mouse=true`. Add `--extra-features` to the launch command for the Video
render-resolution selector, PC autosave wording, and ` + Extras` version suffix.
The code is built into the normal `linux-amd64-update-relwithdebinfo/diablo3` under
`port/out/build`; `--no-extra-features` at build time produces
`linux-amd64-update-plain-relwithdebinfo` without it. Both use the same update user-data directory. See the
[extra-feature audit](extra-features-audit.json) and
[feature documentation](../../extra-features.md). Windows builds use the shared update codegen and hooks.

## Reproduce staging

`scripts/build_client.py --iso ... --title-update /path/to/title-update` runs
every step below. It is the same as the launcher's Build panel.

The old external `d3-patch` wrapper compared `digestSource` with the unrelated
`headerDigest` field. The correct comparison is SHA-1 of the base executable's
256-byte RSA signature. The fix is tracked in
[`patches/d3-patch-signature.patch`](../../../patches/d3-patch-signature.patch).
The corrected source is now in [`scripts/d3-patch`](../../../scripts/d3-patch).
`build_client.py` builds it against the XenonRecomp revision pinned in
`xenonrecomp.lock.json`, into `tools/d3-patch/`.
No mismatch override is used for update.

`scripts/extract_update.py` extracts the STFS package. It checks each block's
SHA-1 and writes `update-manifest.json`:

```sh
python3 scripts/extract_update.py /path/to/title-update /path/to/extracted-update
```

For another copy of the staged assets, choose a new output directory. Base
files are hardlinked when possible; replaced files are unlinked first, so the
base disc is never modified:

```sh
python3 scripts/stage_title_update.py \
  --base /path/to/base-disc \
  --update /path/to/extracted-update \
  --patcher /path/to/d3-patch \
  --output /path/to/new/updated-disc
```

The staging script checks the original executable, extraction manifest, every
update file, source identity/version/signature, and patched executable hash
before publishing the staged directory. Existing outputs are not overwritten.

## Address changes

The shared guest fixes move as follows:

| Hook | Base disc | update |
| --- | --- | --- |
| setjmp | `0x831583B0` | `0x83161AD0` |
| longjmp | `0x83158680` | `0x83161DA0` |
| menu Exit | `0x82632E00` | `0x826374E8` |

[`relocations.json`](relocations.json) records the relocated function hints.
Code-context matching locates most entries; special cases are identified in
the record. All leaf hints have code-pointer references in the update read-only
data. This is static corroboration, not a runtime validation of every entry.
The update-specific leaf extent at `0x82517CA0` includes its shared return block
at `0x82517CB4`, resolving the analyzer's backward-branch validation failure.

## Validation

Source compatibility, the patched executable, and all four update CPK hashes are
verified by the tooling, and the regression tests cover source-signature
rejection and relocated hook patching.

## Windows and shared configuration

update manifests, address audits, generated sources (`port/generated/update`), and
optional hooks are shared across host platforms. The SDK must support the
manifest's 0.10 API. update supplies its own UI-thread exit handler on every host; it does not depend
on the base-disc SDK exit patch.

Build on Windows with the one-step script (it builds the pinned SDK, runs the
shared update codegen and compiles the separate update executable):

```powershell
python scripts/build_windows.py --build-sdk --title-update usa --game-dir C:/games/updated-disc
pwsh -File scripts/run_windows.ps1 -TitleUpdate usa -ExtraFeatures -GameDir C:/games/updated-disc
```

update binaries and default save directories remain separate from base
builds on both platforms.

