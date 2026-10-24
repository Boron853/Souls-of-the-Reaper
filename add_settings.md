# Adding a Resolution Option to Settings → Graphics

## Goal

Add a **Resolution** option under **Settings → Graphics** in the game's main menu, with:

- A selectable list of resolutions
- Controller, keyboard, and mouse navigation
- Live apply when possible, or a clear "restart required" fallback
- Persistence in `diablo3.toml`
- Correct behavior with borderless, windowed, and fullscreen modes

## Current state

- Resolution is currently a **startup cvar** in `rexglue-sdk/src/ui/window.cpp`:
  - `resolution`
  - `video_mode_width` / `video_mode_height`
  - `borderless`, `fullscreen`
  - All are marked `kRequiresRestart`.
- `apply_config.py` writes those values into `<exe dir>/diablo3.toml`.
- The guest video mode is exposed through `xboxkrnl_video.cpp`; `VdQueryVideoMode` reads the cvars dynamically, so a live change may be possible.
- The SDK has no public runtime "set resolution" API. It has `SetFullscreen`, and resize handling flows through:
  - `Window::OnActualSizeUpdate`
  - `Presenter::OnSurfaceResizeFromUIThread`
  - Vulkan swapchain recreation
- The game menu is guest UI data, not the SDK menu:
  - `UI\ConsoleOptions.ui`, `UI\ConsoleGameSettings.ui`, `UI\ConsoleMainMenu.ui` are in `CacheCommon.cpk`.
  - Localized labels such as `StringList\ConsoleOptions.stl` are in `enUS_Common.cpk`.
  - The console CPK format is Blizzard's custom format (`a1b2c3d4`), **not** CriWare. The repo currently has no CPK extract/repack tool.

## Recommended approach

Use a **runtime resolution service** plus a **native overlay row** inside the game's Settings → Graphics screen. Keep direct CPK asset editing as a separate research spike, because the archive/UI formats are proprietary and the tooling cost is high.

### Phase 0 — Reconnaissance and decision gate

1. **Inspect the UI assets**
   - Build a read-only extractor for the custom CPK, or use a community tool in a temporary workflow.
   - Extract `ConsoleOptions.ui`, `ConsoleGameSettings.ui`, and `ConsoleOptions.stl`.
   - Determine whether `.ui` is text/XML, a compiled layout, or something else.

2. **Find the Settings → Graphics screen**
   - Add temporary logging around guest UI screen transitions and menu input.
   - Navigate to Settings → Graphics and record the screen ID/function and the current row list.
   - Use the generated function map plus Ghidra/IDA with the XEX to find string references to the screen names.
   - Remove the temporary logging afterward.

3. **Prove live resize**
   - Add a temporary debug command/button that resizes the window and updates `video_mode_width/height`.
   - Check whether the presenter, swapchain, and guest render targets adapt without a restart.
   - Decide:
     - **Live apply** if it works reliably.
     - **Restart-required** if the guest renderer cannot change mode mid-session.

4. **Choose the menu path**
   - **A. Runtime overlay** — recommended first implementation.
   - **B. True asset patch** — only if the `.ui` format is editable and we can add a row plus callback cleanly.
   - **C. F4 overlay** — fast fallback, but not inside the game's menu.

### Phase 1 — Resolution backend

Add a small display-settings service in the SDK/port:

- `Resolution` model:
  - Presets: 1280×720, 1600×900, 1920×1080, 2560×1440, 3200×1800, 3840×2160
  - "Desktop" (current monitor size)
  - "Custom WxH"
  - Validate against guest mode limits and monitor capabilities.
- `DisplaySettings::Apply(width, height, mode)`:
  - Set `resolution` / `video_mode_width` / `video_mode_height`
  - Add `Window::SetDesiredLogicalSize(width, height)`:
    - GTK: resize the drawing area/window; for borderless, reposition at `0,0`
    - Win32: equivalent `SetWindowPos` / size update
  - Let `OnActualSizeUpdate` trigger presenter/swapchain recreation.
  - Notify or force the guest video-mode path if needed.
- `DisplaySettings::Save()`:
  - Write `resolution`, `borderless`, and optionally `fullscreen` to `diablo3.toml`.
  - Preserve F4 remaps/user cvars; prefer the managed writer behavior used by `apply_config.py`.
- `DisplaySettings::CanApplyLive()`:
  - If false, persist the value and show "Restart required."

Files likely touched:

- `rexglue-sdk/include/rex/graphics/video_mode_util.h`
- `rexglue-sdk/src/ui/window.cpp` / `.h`
- `rexglue-sdk/src/ui/window_gtk.cpp`
- `rexglue-sdk/src/ui/window_win.cpp`
- `rexglue-sdk/src/ui/presenter.cpp`
- `rexglue-sdk/src/ui/vulkan/vulkan_presenter.cpp`
- `rexglue-sdk/src/kernel/xboxkrnl/xboxkrnl_video.cpp`
- `port/src/diablo3_app.h` or a new `port/src/resolution_menu.cpp`
- `apply_config.py` / config handling

### Phase 2 — Menu integration

#### Recommended: native overlay in Settings → Graphics

- Add a `ResolutionMenu` overlay that draws only while the Settings → Graphics screen is active.
- Display a row or modal panel:

```text
Graphics
  Resolution         2560x1440   >
  Window Mode        Borderless  >
  [Apply]  [Cancel]
```

- Use the existing ImGui renderer/input layer.
- When the panel is open:
  - Capture controller/keyboard/mouse input so the game menu does not also react.
  - D-pad/stick to change selection; A/Enter to confirm; B/Esc to cancel.
  - Restore game input when closed.
- Apply behavior:
  - Apply the new mode.
  - Show a 10-second "Keep this resolution?" confirmation for fullscreen/windowed changes.
  - Revert automatically if the user does not confirm.
  - If live apply fails, keep the old mode and show an error.
- Persist only after confirmation.

This gives the appearance and behavior of a menu option without modifying guest UI assets.

#### Optional: true game-menu asset patch

If the `.ui` files turn out to be editable:

1. Add a `Resolution` row and localized string entry.
2. Add a callback or hook the row's action to the native `DisplaySettings` API.
3. Repack or override `CacheCommon.cpk` / `enUS_Common.cpk`.
4. Add a reproducible `apply_ui_patch.py` that patches the user's game data, rather than shipping modified CPKs.

This is higher risk because:

- The CPK format is custom.
- The `.ui` format may be compiled/opaque.
- Repacking large archives is expensive and version-sensitive.

#### Fallback: F4 overlay

Add a "Display" section to `settings_overlay.cpp` with a resolution dropdown. This is useful as a development harness and a fallback, but does not satisfy the "inside the main menu" requirement.

### Phase 3 — Persistence and startup behavior

- On startup, `diablo3.toml` remains the source of truth.
- The menu writes the same keys `apply_config.py` manages.
- Preserve:
  - F4 overlay remaps
  - User cvars
  - Comments where possible
- Add a "Restart required" pending state if live apply is unavailable.
- Ensure the launcher and Steam shortcut still use the same config path.
- If launched through Steam, Steam Input/virtual pad behavior remains unchanged.

### Phase 4 — Testing

**Unit tests**

- Resolution preset parsing and formatting
- Custom resolution validation
- Config round-trip and preservation of unknown keys
- "Desktop" resolution detection
- Invalid/unsupported mode rejection

**Manual/integration tests**

- 720p → 1080p → 1440p → 4K
- Borderless, windowed, fullscreen
- Multi-monitor and DPI changes
- XWayland and native X11
- 16:9 and 21:9 input (gameplay may letterbox)
- Controller navigation and keyboard/mouse
- Apply/cancel/revert countdown
- Restart persistence
- Steam launch and direct launch
- F4 remaps still work
- No temporary diagnostics left in the build

**Regression checks**

- Existing 1440p borderless startup
- Font/texture rendering
- Controller enumeration
- No swapchain or shared-memory leaks

### Risks and decisions

- **Live resize is the main technical risk.** The presenter can recreate the swapchain, but the guest renderer may cache the video mode. If so, use restart-required as the first release.
- **True in-game menu editing is a research project.** Do not commit to CPK asset modification until the `.ui` format is understood.
- **Input focus:** the overlay must not leak input to the game menu.
- **21:9:** the game viewport is 16:9; widescreen modes letterbox. The menu should either offer only 16:9 presets or clearly label wider modes.
- **Config ownership:** avoid two writers fighting over `diablo3.toml`; use one managed writer.
- **Distribution:** do not ship modified game CPKs; patch the user's data locally.

### Suggested order

1. Recon spike: extract UI assets, find the screen, prove live resize.
2. Implement the resolution backend and persistence.
3. Add the overlay row in Settings → Graphics.
4. Test and document.
5. Only then decide whether a true asset-level menu row is worth pursuing.

Estimated effort: **backend + persistence ~2–3 days**, **menu overlay/hook ~3–5 days**, **testing/docs ~1–2 days**, with an additional **3–5+ day research spike** if we attempt direct CPK/UI asset editing.
