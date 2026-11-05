# Experimental PS3 save importer for update

`scripts/import_ps3_save.py` inspects an extracted RPCS3 Diablo III: Reaper of
Souls save and can produce a separate state directory for the Xbox update build.
It uses only Python's standard library. Imported gameplay and save/reload
compatibility have not been validated.

> **Not everything is imported.** This is an early, partial importer. Treat the
> result as a starting point, not a faithful copy of your PS3 save.
>
> | Imported (bytes copied unchanged) | Not imported or not handled |
> | --- | --- |
> | Account data (`account.dat`) | `HEROES.IDX` (used only to validate, not copied) |
> | Profile data (`profile.dat`) | Preferences (`PREFS.DAT`) |
> | Hero files (`heroes/<id>.dat`) | Platform metadata (`PARAM.SFO`, `PARAM.PFD`, `ICON0.PNG`) |
> | | Xbox content header (none is created) |
> | | Saves from other versions or editions (only account version 108 and hero/digest version 905) |
> | | Physical-console exports with extra protection (not decrypted) |
>
> Imported data is copied as-is, with no conversion of platform-specific values, so
> some of it may not load or behave correctly in the Xbox update build. Character
> selection, inventory and equipment, stash, currency, quests, progression and
> hardcore status have not been confirmed to carry over. It works only with the
> update build, and only in one direction (PS3 to this port, never back).

## Inspect without writing

```sh
python3 scripts/import_ps3_save.py /path/to/BLUS31437-AUTOSAVE
```

Optionally compare versions and hero filenames against an existing Xbox update
save, also read-only:

```sh
python3 scripts/import_ps3_save.py /path/to/BLUS31437-AUTOSAVE \
  --reference-save /path/to/xbox-state/B13EBABEBABEBABE/394F07D4/00000001/d3save
```

Inspection reports account and hero versions, embedded hero IDs, the proposed
filenames, and payload hashes. The format check currently accepts account
version 108 and hero/digest version 905, observed in the local PS3 and Xbox update
references. Matching versions do not establish compatibility of every nested
field or platform-specific value. Saves with other versions (for example from
other editions) are refused at import with a message naming the versions found;
inspection still works so the report can be examined.

## Import into a new directory

```sh
python3 scripts/import_ps3_save.py /path/to/BLUS31437-AUTOSAVE \
  --output-state /path/to/new-ps3-import-state
```

The output directory must not exist. The importer refuses to merge or overwrite
an existing state directory, or write within/above the PS3 source or optional
Xbox reference directory. It checks index/hero ID consistency, filenames,
duplicate identifiers, bounded file sizes and protobuf structure. Input payload
files must be regular files rather than symlinks.

Output:

```text
new-ps3-import-state/
  import-report.json
  B13EBABEBABEBABE/394F07D4/00000001/d3save/
    account.dat
    profile.dat
    heroes/<16-digit-hero-id>.dat
```

The default XUID is the SDK's default emulated profile. `--xuid` selects another
16-digit hexadecimal profile ID; it controls the storage directory only and
does not rewrite account or hero identities inside the payloads.

Account, profile and hero file bytes are preserved exactly, including unknown
protobuf fields and the original rolling XOR encoding. PS3 hero filenames use
the low 32 bits of the embedded ID; the Xbox reference uses all 64 bits. The
importer checks this relationship rather than inventing new hero IDs.

`HEROES.IDX` is used for validation but not copied. PS3 preferences and platform
metadata (`PREFS.DAT`, `PARAM.SFO`, `PARAM.PFD`, `ICON0.PNG`) are omitted. The
inspected RPCS3 reference has no `PARAM.PFD`; this tool does not decrypt the
additional protection on physical-console exports. Preferences regeneration
and any platform-specific payload adjustments still need runtime testing.

No Xbox content header is fabricated. The inspected SDK's content manager can
enumerate directories without a header by constructing metadata from the path;
complete game loading still needs validation.

## Try the imported save with update

```sh
python3 scripts/run_linux.py --title-update usa --extra-features \
  --game-dir /path/to/updated-disc \
  --state-dir /path/to/new-ps3-import-state --vulkan_device=1
```

You can also import and launch in one command:

```sh
python3 scripts/run_linux.py --title-update usa --extra-features \
  --game-dir /path/to/updated-disc \
  --import-ps3-save /path/to/BLUS31437-AUTOSAVE --vulkan_device=1
```

Without `--state-dir`, this selects a separate `souls-of-the-reaper-update-ps3-import`
application-data directory. On first launch it imports the source; later launches
reuse the imported save without replacing subsequent gameplay progress. An
existing directory without a matching import report is rejected. To start another
import, select a new `--state-dir`.

This uses the imported state rather than your usual update state. Future game saves
write to that imported state. The importer never mounts the RPCS3 source as a
writable save location.

Validate character selection, inventory/equipment, stash, currency, quests,
progression and hardcore status, then save, exit and reload. The report retains
`runtime_validated: false`; it records import provenance rather than tracking
later gameplay checks. This is a one-way experimental import, not PS3 export or
bidirectional synchronization.

The save encoding and field interpretation were investigated using
[GoobyCorp/D3Edit](https://github.com/GoobyCorp/D3Edit/blob/master/D3Edit.py)
and its published protobuf descriptors, then compared against the local saves.
No editor runtime or generated protobuf modules are required by the importer.

Regression checks are part of:

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
```
