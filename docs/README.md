# Documentation

| Guide | Covers |
| --- | --- |
| [Building the game](building-the-game.md) | Compiling `diablo3` / `diablo3.exe` on Windows and Linux |
| [Building the launcher](building-the-launcher.md) | The cross-platform Tauri launcher and the legacy PowerShell launcher (Windows) |

Related notes that live next to the code:

- [Linux integration notes](../port/base/README.md): diagnostics, saves, GPU selection, input
- [Title Update setup](../port/title_updates/update/README.md)
- [Optional PC features](../port/extra-features.md)
- [Tauri launcher reference](../launcher/tauri/README.md): options, launch settings, tests

## What you need to supply

The repository contains no game data. You need your own **USA Diablo III: Ultimate Evil Edition** (Xbox 360) disc image, and optionally the USA **Title Update** package. The build verifies SHA-256 hashes of `Default.xex` and refuses other editions.
