# Native Wayland Support — Scope and Implementation Plan

Status: **core native-Wayland path implemented; broader matrix pending**
Target: Diablo III Linux port / ReXGlue SDK
Test host: KWin Wayland, Intel Arc B390 (Mesa 26.1.8), 2560×1440

> **Implementation note (2026-10-23):** the current SDK uses **SDL3**, not GTK.
> The v0.10 SDK already contains the Wayland surface type, SDL window
> properties, Vulkan `VK_KHR_wayland_surface` setup, and presenter branch. The
> backend was being compiled out because `wayland-scanner` was unavailable, so
> SDL silently built without Wayland. The current fix adds `wayland-scanner`
> and libdecor to the dev shell, passes the scanner to the SDK build, and lets
> SDL choose the session-native backend (Wayland with X11 fallback). The GTK
> sections below are retained as historical design context, not as the current
> implementation route.

## 1. Summary

The port previously ran through **XWayland**. In the current v0.10/SDL3
architecture, the remaining blockers were not the Wayland surface code (which
upstream already provides), but the build and launcher:

1. SDL was configured with `SDL_WAYLAND=ON` but silently compiled the backend
   out because `wayland-scanner` was missing.
2. The launcher forced `SDL_VIDEODRIVER=x11`.
3. The runtime environment cache did not validate the dynamically loaded
   Wayland/libdecor libraries.

The goal is to use the native **SDL3 Wayland window + `VK_KHR_wayland_surface`**
path, keep X11 as a fallback, and preserve the current rendering, input, audio,
borderless, and fullscreen behavior.

This is a **moderate SDK/window-system change**, not a config toggle. The main
technical risk is GTK3 and Vulkan WSI both owning the same `wl_surface`, so the
plan starts with a **two-day prototype decision gate** before full integration.

## 1a. Current implementation status

The SDL3-based native Wayland path is now working under KWin:

- `SDL_VIDEODRIVER` is no longer forced to `x11` by the launcher.
- SDL reports `SDL video driver: wayland`.
- Vulkan enables `VK_KHR_wayland_surface` and creates a Wayland swapchain.
- The game has no X11 window; `xdotool` cannot find it.
- Gamepad enumeration and the initial menu path work.
- Fullscreen creates a 2880×1919 native-Wayland client surface on the tested
  2880×1920 desktop.

Build/runtime changes:

- `flake.nix` includes `wayland`, `wayland-scanner`, and `libdecor`.
- `port/build_sdk.sh` passes `-DWAYLAND_SCANNER=...` and `-DSDL_WAYLAND=ON` to
  the SDK configure step.
- The launcher cache validates the Wayland and libdecor runtime libraries.
- X11 remains an automatic SDL fallback and can be forced with
  `SDL_VIDEODRIVER=x11`.

Still to validate before declaring the whole matrix complete: gameplay input
and audio over a long session, borderless/fullscreen transitions,
multi-monitor and compositor coverage, and performance parity across modes.

## 2. Goals and non-goals

### Goals

- Run the game in a native Wayland toplevel under KWin (no XWayland window).
- Native 1280×720, 1920×1080, 2560×1440, 4K, and custom `WIDTHxHEIGHT` modes.
- Menu, settings, overlay, mouse/keyboard, gamepad, audio, and present path
  behave as on X11.
- 60 FPS at 2560×1440 on the test host, within ~5% of the XWayland result.
- `borderless` and fullscreen work sensibly on Wayland.
- XWayland remains a reliable fallback selected by environment/launcher.
- Packaged as part of `patches/rexglue-sdk-linux.patch`.

### Non-goals (initial phase)

- GTK4 migration.
- HDR / 10-bit presentation.
- Full fractional-scaling support beyond whatever GTK3 exposes (GTK4's
  `wp_fractional_scale_v1` is out of scope initially).
- Multi-window UI, Wayland layer-shell, or embedding the game in another app.
- Removing X11 support.
- Any game-content modding.

## 3. Current architecture and exact touch points

> The table below documents the earlier GTK3 architecture. The current v0.10
> port uses `WindowSDL`; the equivalent Wayland touch points are
> `src/ui/window_sdl.cpp`, `src/ui/surface_gnulinux.*`, and the Vulkan
> instance/presenter Wayland branches.

| Area | File(s) | Current behavior |
|---|---|---|
| GTK backend selection | `src/ui/windowed_app_main_posix.cpp` | `GDK_BACKEND=x11` forced before `gtk_init_check`. |
| Window | `src/ui/window_gtk.cpp`, `include/rex/ui/window_gtk.h` | GTK3 window; `GtkDrawingArea` is the client area; `DrawHandler` calls `OnPaint`. |
| Surface abstraction | `include/rex/ui/surface.h` | Types: Android, XCB, Win32. No Wayland index/flag. |
| Linux surface | `include/rex/ui/surface_gnulinux.h`, `src/ui/surface_gnulinux.cpp` | Only `XcbWindowSurface`; size via `xcb_get_geometry`. |
| Surface creation | `GTKWindow::CreateSurfaceImpl` | Only `GDK_IS_X11_DISPLAY` → `XcbWindowSurface`. |
| Vulkan instance | `src/ui/vulkan/vulkan_instance.cpp`, `include/rex/ui/vulkan/instance.h` | Optional `VK_KHR_xcb_surface`; function table `instance_khr_xcb_surface.inc`. |
| Vulkan presenter | `src/ui/vulkan/vulkan_presenter.cpp` | `GetSurfaceTypesSupportedByInstance` and `CreateSurface` only handle Android/XCB/Win32. |
| Swapchain | `VulkanPresenter::PaintContext::CreateSwapchainForVulkanSurface` | Uses the width/height passed by the caller, clamped to surface capabilities; ignores `currentExtent`. |
| Build | `src/ui/CMakeLists.txt` | GTK3 + `x11-xcb` only. |
| Nix shell | `flake.nix` | GTK3/X11/Vulkan; no explicit Wayland client package. |
| Launcher | `launch-diablo3.sh` | Forces `SDL_VIDEODRIVER=x11`; GTK is separately forced in C++. |

The game window is the GTK window; SDL3 is used for input/audio, not for the
main window. Native Wayland therefore means **GTK Wayland**, not simply
changing `SDL_VIDEODRIVER`.

## 4. Design options (historical — GTK3 path superseded by SDL3)

These options describe the earlier GTK3 window architecture. The current SDK
uses SDL3, whose Wayland properties and Vulkan surface path are already
implemented; they are retained here for historical context.

### Option A — GTK3 Wayland surface directly (recommended first prototype)

Use the `wl_surface` belonging to the GTK drawing area:

```cpp
GdkDisplay* display = gtk_widget_get_display(window_);
GdkWindow* gdk_window = gtk_widget_get_window(drawing_area_);
struct wl_display* wl_display =
    gdk_wayland_display_get_wl_display(display);
struct wl_surface* wl_surface =
    gdk_wayland_window_get_wl_surface(gdk_window);
```

Build a `WaylandWindowSurface` around these, add
`VK_KHR_wayland_surface`, and present into the GTK-owned surface.

Pros: smallest change; reuses GTK menus/settings/input; matches the XCB design
(GTK owns the window, Vulkan presents into it).  
Cons/risk: GTK3 may attach its own `wl_buffer` to the drawing area; Vulkan WSI
also wants to attach buffers. The `DrawHandler` returns `TRUE` without cairo
drawing today, but GTK's frame clock may still commit. This must be proven by a
prototype.

### Option B — child `wl_subsurface` inside GTK (fallback)

Create a dedicated `wl_surface` + `wl_subsurface` with the GTK drawing area's
surface as parent, position it at the drawing area origin, and present there.
GTK does not draw to the child. This avoids buffer ownership conflicts but
requires manual resize/position/visibility handling and a `wl_subcompositor`
roundtrip.

### Option C — SDL3 Wayland window (larger pivot)

Create the game window via SDL3 (`SDL_WINDOW_VULKAN`), call
`SDL_Vulkan_CreateSurface`, and keep GTK only for the settings/menu window (or
move the menu to ImGui). This bypasses the GTK surface-ownership problem but is
a window/UI architecture change and loses the single-window GTK menu bar.

### Decision

**Prototype Option A for up to two days.** If presentation is stable (no
protocol errors, no flicker, input works), proceed with A. If GTK buffer
ownership conflicts are unavoidable, prototype B for one to two days. Only
consider C if both fail. Keep XWayland as the default until the chosen option
passes the acceptance matrix.

## 5. Implementation phases

### Phase 0 — Prototype and decision gate (1–2 days)

Create a small standalone GTK3 + Vulkan test (not the game) with:

- GTK3 Wayland window and `GtkDrawingArea`.
- `wl_display`/`wl_surface` from GDK Wayland.
- Vulkan instance with `VK_KHR_surface` + `VK_KHR_wayland_surface`.
- Swapchain (`B8G8R8A8_UNORM`, FIFO) and a clear-color/triangle frame.
- Resize, maximize, and fullscreen events.
- `WAYLAND_DEBUG=1` and Vulkan validation enabled.

Exit criteria:

- `vkCreateWaylandSurfaceKHR` and swapchain creation succeed.
- The frame is visible and correctly sized; no GTK/cairo buffer conflict.
- Resize and fullscreen do not produce protocol errors or a black window.
- `xwininfo`/`xdotool` cannot find the test window (proving native Wayland).

If the prototype fails, record the failure mode (buffer attach conflict,
subsurface required, etc.) and choose B or C before touching the game.

### Phase 1 — Build and Vulkan extension plumbing (1–2 days)

1. **CMake** (`src/ui/CMakeLists.txt`):
   - `pkg_check_modules(WAYLAND_CLIENT REQUIRED wayland-client)`
   - Add include dirs and link `${WAYLAND_CLIENT_LIBRARIES}` on GNU/Linux.
   - Add a compile definition, e.g. `REX_HAS_WAYLAND`, only when found, so
     X11-only builds still compile.
2. **Nix** (`flake.nix`):
   - Add `wayland` (and optionally `wayland-protocols`) to `packages`.
   - Add `${pkgs.wayland}/lib` to `LD_LIBRARY_PATH`.
3. **Vulkan API** (`include/rex/ui/vulkan/api.h`):
   - Under `REX_HAS_WAYLAND`, define `VK_USE_PLATFORM_WAYLAND_KHR` and include
     `<wayland-client.h>` before the Vulkan headers.
4. **Vulkan instance** (`include/rex/ui/vulkan/instance.h`,
   `src/ui/vulkan/vulkan_instance.cpp`):
   - Add `bool ext_KHR_wayland_surface`.
   - Request `VK_KHR_wayland_surface` when `with_surface` and
     `REX_HAS_WAYLAND`.
   - Add `include/rex/ui/vulkan/functions/instance_khr_wayland_surface.inc`:
     `XE_UI_VULKAN_FUNCTION(vkCreateWaylandSurfaceKHR)`.
   - Load it in the function-pointer block alongside XCB.
5. **Surface types**:
   - `include/rex/ui/surface.h`: add
     `kTypeIndex_WaylandWindow` (before XCB on Linux) and
     `kTypeFlag_WaylandWindow`.
   - `include/rex/ui/surface_gnulinux.h`: add `WaylandWindowSurface` holding
     `wl_display*`, `wl_surface*`, and a physical-pixel size (see Phase 2).
   - `src/ui/surface_gnulinux.cpp`: implement `GetSizeImpl`.

### Phase 2 — GTK Wayland surface and sizing (2–3 days)

1. **Backend selection** (`src/ui/windowed_app_main_posix.cpp`):
   - Stop unconditionally forcing `GDK_BACKEND=x11`.
   - Add a pre-GTK environment variable, e.g. `REX_UI_BACKEND=auto|x11|wayland`.
     It must be read before `gtk_init_check` because the config/TOML is loaded
     later.
   - `auto`: leave `GDK_BACKEND` unset when `WAYLAND_DISPLAY` is present,
     otherwise use X11. `wayland`/`x11` set the backend explicitly.
   - On `wayland` failure, optionally re-exec once with
     `REX_UI_BACKEND=x11` and a fallback guard env var.
2. **Surface creation** (`src/ui/window_gtk.cpp`,
   `include/rex/ui/window_gtk.h`):
   - In `CreateSurfaceImpl`, check `GDK_IS_WAYLAND_DISPLAY(display)` and return
     `WaylandWindowSurface(gdk_wayland_display_get_wl_display(display),
     gdk_wayland_window_get_wl_surface(drawing_area_window), physical_width,
     physical_height)`.
   - Keep the XCB branch for X11.
3. **Sizing and scale**:
   - `GTKWindow::HandleSizeUpdate` currently reports the logical drawing-area
     allocation. For Wayland, the swapchain needs physical pixels:
     `physical = logical * gdk_window_get_scale_factor(gdk_window)`.
     Store both and make `WaylandWindowSurface::GetSizeImpl` return the
     physical size.
   - GTK3 supports integer scale factors; fractional scaling is a follow-up.
   - On configure/resize, update the stored size and let the presenter recreate
     the swapchain.
4. **Drawing ownership**:
   - Confirm `DrawHandler` does not attach a cairo buffer on Wayland. If it
     does, try `gtk_widget_set_double_buffered(drawing_area_, FALSE)` or switch
     to the child-subsurface design (Option B).
   - Keep `gtk_widget_queue_draw`/`OnPaint` timing; verify GTK frame clock
     callbacks do not fight Vulkan presentation.

### Phase 3 — Presenter and swapchain (2–3 days)

1. `VulkanPresenter::GetSurfaceTypesSupportedByInstance`: add
   `kTypeFlag_WaylandWindow` when `ext_KHR_wayland_surface`.
2. `ConnectOrReconnectPaintingToSurfaceFromUIThread`:
   - Add `case Surface::kTypeIndex_WaylandWindow`:
     ```cpp
     auto& w = static_cast<const WaylandWindowSurface&>(new_surface);
     VkWaylandSurfaceCreateInfoKHR info{};
     info.sType = VK_STRUCTURE_TYPE_WAYLAND_SURFACE_CREATE_INFO_KHR;
     info.display = w.display();
     info.surface = w.surface();
     ifn.vkCreateWaylandSurfaceKHR(instance, &info, nullptr,
                                   &paint_context_.vulkan_surface);
     ```
3. **Swapchain extent**:
   - `CreateSwapchainForVulkanSurface` already accepts the surface width/height.
     On Wayland, `VkSurfaceCapabilitiesKHR.currentExtent` may be
     `0xFFFFFFFF`; do not treat that as an error. Use the physical size passed
     from `Surface::GetSize`, clamped to `minImageExtent`/`maxImageExtent`.
   - If `currentExtent` is a concrete value, prefer it.
4. **Composite alpha / present modes**:
   - Keep `OPAQUE` preference; Wayland compositors generally support it.
   - Verify FIFO/MAILBOX/IMMEDIATE availability under KWin; keep the existing
     FIFO fallback.
5. **Resize/fullscreen**:
   - Test `VK_ERROR_OUT_OF_DATE_KHR`/`VK_SUBOPTIMAL_KHR` handling on Wayland
     configure events.
   - Ensure `RequestPaint` does not spin when the window is hidden/zero-area.

### Phase 4 — Window behavior: borderless, fullscreen, input (1–2 days)

1. **Borderless** (`GTKWindow::OpenImpl`):
   - `gtk_window_set_decorated(FALSE)` remains.
   - Wayland does **not** allow clients to position toplevels; `gtk_window_move`
     is ignored. For `borderless` on Wayland, use `gtk_window_maximize` (or
     `gtk_window_fullscreen` for `fullscreen=true`) and let the compositor
     place the window.
   - Document that a native 2560×1440 borderless window may be centered by the
     compositor rather than placed at 0,0.
2. **Fullscreen**:
   - Use `gtk_window_fullscreen`; retest after removing the X11-only
     `GDK_BACKEND` override. The earlier SDL fullscreen bug was in the SDL/WM
     path, not GTK Wayland, but verify.
3. **Input**:
   - GTK keyboard/mouse events should continue to work via the GDK Wayland
     backend.
   - Test gamepad (SDL3) with `SDL_VIDEODRIVER=wayland` and unset; ensure the
     input thread does not require an X11 video driver.
   - Test focus, Alt-Tab, minimize/restore, relative mouse, and the F4 overlay.
4. **Launcher/docs**:
   - `launch-diablo3.sh`: use `REX_UI_BACKEND=auto` (or `wayland`), and set
     `SDL_VIDEODRIVER=wayland` when testing; keep an X11 fallback profile.
   - `apply_config.py`/docs: backend is a pre-GTK env var, not a TOML cvar;
     document both commands.

### Phase 5 — Testing, performance, and packaging (2–3 days)

- Full acceptance matrix (Section 7).
- Regenerate `patches/rexglue-sdk-linux.patch` with all new files and the
  CMake/flake changes; verify against the pinned SDK base.
- Update `docs/LINUX.md` and `wayland-plan.md` status.
- Keep the X11 path as the default until Wayland passes; then consider
  `auto` as default with an explicit X11 escape hatch.

## 6. Code-level task list

- [ ] `include/rex/ui/surface.h`: add Wayland type index/flag.
- [ ] `include/rex/ui/surface_gnulinux.h`: add `WaylandWindowSurface`.
- [ ] `src/ui/surface_gnulinux.cpp`: Wayland size implementation.
- [ ] `src/ui/window_gtk.cpp`: Wayland surface branch + physical-pixel size.
- [ ] `include/rex/ui/window_gtk.h`: any new members/helpers.
- [ ] `src/ui/windowed_app_main_posix.cpp`: backend selection/fallback.
- [ ] `include/rex/ui/vulkan/api.h`: `VK_USE_PLATFORM_WAYLAND_KHR` guard.
- [ ] `include/rex/ui/vulkan/instance.h`: extension flag/function pointer.
- [ ] `src/ui/vulkan/vulkan_instance.cpp`: request/load Wayland extension.
- [ ] `include/rex/ui/vulkan/functions/instance_khr_wayland_surface.inc`: new.
- [ ] `src/ui/vulkan/vulkan_presenter.cpp`: surface type + creation + extent.
- [ ] `src/ui/CMakeLists.txt`: Wayland client dependency + define.
- [ ] `flake.nix`: Wayland packages / `LD_LIBRARY_PATH`.
- [ ] `launch-diablo3.sh`: backend env + fallback.
- [ ] `docs/LINUX.md`: native Wayland usage/fallback.
- [ ] `patches/rexglue-sdk-linux.patch`: regenerate and verify.

## 7. Test matrix

| Test | Expected |
|---|---|
| KWin Wayland, 1280×720 windowed | Native Wayland window, 60 FPS, menu/audio/input. |
| KWin Wayland, 1920×1080 | Correct extent, no scaling blur, 60 FPS. |
| KWin Wayland, 2560×1440 borderless | Fills/centers per compositor, no decorations, 60 FPS. |
| KWin Wayland, 2560×1440 fullscreen | Fullscreen, Alt-Tab out/in, no protocol errors. |
| 4K mode (if monitor supports) | Swapchain/GPU limits respected, stable. |
| Resize/maximize/restore | Swapchain recreated, no black frame/crash. |
| Scale 1.0 and 2.0 (integer) | Correct physical size; no double scaling. |
| Fractional scale 1.25/1.5 | Documented behavior; no crash; blur acceptable initially. |
| Multi-monitor, mixed scale | Window move triggers resize/recreate correctly. |
| Mouse/keyboard/gamepad/F4 overlay | Same as X11. |
| Audio | `Audio system initialized`, no ALSA/Pulse errors. |
| XWayland fallback (`REX_UI_BACKEND=x11`) | Unchanged current behavior. |
| SIGKILL / shm cleanup | No `/dev/shm/xenia_memory_*` leftovers. |
| Patch series on clean SDK base | Applies and builds. |

Instrumentation/commands:

```sh
WAYLAND_DISPLAY=wayland-0 GDK_BACKEND=wayland \
  REX_UI_BACKEND=wayland WAYLAND_DEBUG=1 \
  ./launch-diablo3.sh

# Prove it is not an XWayland window:
xdotool search --name "Diablo III"   # should find nothing
```

## 8. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| GTK3 owns/attaches buffers to the drawing area `wl_surface` | Vulkan presentation conflicts, black/flicker | Prototype A; if it fails, use a child `wl_subsurface` (Option B). |
| `currentExtent == 0xFFFFFFFF` on Wayland | Swapchain extent wrong/creation fails | Use `Surface::GetSize` physical pixels; prefer concrete `currentExtent` when provided. |
| Fractional scaling in GTK3 | Blurry or wrong-size output | Scope to integer scale first; document; follow-up with GTK4/fractional-scale protocol. |
| `gtk_window_move` ignored on Wayland | Borderless not at 0,0 | Use maximize/fullscreen; document compositor-controlled placement. |
| SDL input/audio expects X11 video | Gamepad/mouse issues | Test `SDL_VIDEODRIVER=wayland`, unset, and X11; SDL is independent of the GTK window. |
| NVIDIA/Wayland driver differences | Surface/swapchain failures | Keep XWayland fallback; test Intel/Mesa first (current host), then NVIDIA if available. |
| GTK frame clock vs. Vulkan present | Pacing/jitter | Use the existing `RequestPaint`/`OnPaint` path; measure frame times; add frame-callback pacing only if needed. |
| Regression to X11 | Existing users break | Do not remove XCB; `REX_UI_BACKEND=x11` remains tested. |

## 9. Effort estimate

| Phase | Estimate |
|---|---|
| 0 — Prototype/decision | 1–2 days |
| 1 — Build + Vulkan extension plumbing | 1–2 days |
| 2 — GTK Wayland surface/sizing | 2–3 days |
| 3 — Presenter/swapchain | 2–3 days |
| 4 — Borderless/fullscreen/input | 1–2 days |
| 5 — Testing/perf/packaging | 2–3 days |
| **Total (Option A)** | **~9–15 developer days** |
| If Option B (subsurface) needed | +2–3 days |
| If Option C (SDL window) needed | +1–2 weeks |

## 10. Acceptance criteria

Native Wayland is considered done when:

- `REX_UI_BACKEND=wayland` starts the game with **no XWayland window**.
- 2560×1440 (and 1080p/4K where available) renders at 60 FPS within ~5% of
  XWayland.
- Menu, settings, overlay, mouse/keyboard, gamepad, and audio are functional.
- Borderless and fullscreen behave predictably; no protocol errors with
  `WAYLAND_DEBUG=1`.
- Resize, maximize/restore, Alt-Tab, and multi-monitor operations do not crash
  or leave a black window.
- `REX_UI_BACKEND=x11` still reproduces the current verified behavior.
- The SDK patch series applies cleanly to the pinned base and builds.
- No shared-memory leftovers after SIGKILL.

## 11. Recommendation

Start with **Phase 0 (Option A prototype)**. It is the cheapest way to answer
the only architectural question that matters: whether GTK3's Wayland surface
can coexist with Vulkan WSI. If it can, the rest is a straightforward extension
of the existing XCB plumbing. If it cannot, the child-subsurface fallback is
still contained; the SDL window pivot should be a last resort.
