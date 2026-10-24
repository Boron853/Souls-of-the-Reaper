# Front Buffer / Internal Resolution — Plan of Attack

## Current findings

The port currently has four distinct resolutions:

| Layer | Value |
|---|---|
| Guest video mode (`VdQueryVideoMode`) | **2560×1440 @ 60 Hz** |
| Requested SDL window | **2560×1440** |
| Actual swapchain | **2560×1440** after the borderless-window fix |
| Guest front buffer / swap packet | **1280×720** |
| Final presented image | 720p source upscaled to 2560×1440 |

The game’s 2D UI and final guest front buffer are fixed at **1280×720**. `resolution = "1440p"` changes the guest video mode and the window/swapchain, but it does **not** raise the game’s fixed front buffer. The presenter upscales the 720p guest output to the 1440p swapchain.

The borderless window was also being maximized by KWin to **2880×1841**, which made the upscale worse. That is fixed: the window/swapchain now stay at the requested **2560×1440**.

## What has already been tested

### 1. Raw front-buffer dimension override

I temporarily forced `RefreshGuestOutput` to use the display size (2560×1440) instead of the guest output size (1280×720).

Result: **not viable as a simple override**.

- The guest output/gamma/FXAA pass is pixel-indexed.
- Forcing a 2560×1440 destination wrote only the top-left 1280×720 region.
- The UI was cropped/small, with the rest black.
- The change was reverted; it is not in `master`.

This confirms that changing the front-buffer dimensions alone does not upscale the source image. A proper upscale/composite pass is required.

### 2. Borderless window sizing

Fixed and committed as `7952537`:

- Window geometry: **2560×1440**
- Swapchain: **2560×1440**
- Correct title/autosave layout
- No KWin maximize to 2880×1841

### 3. Guest video mode

Verified with a temporary log:

```text
VdQueryVideoMode: 2560x1440 @ 60 Hz
WindowSDL: desired 2560x1440
VulkanPresenter: Created 2560x1440 swapchain
SWAP fb CHANGED ... (1280x720)
```

The temporary logs were removed.

### 4. Host render-target measurement

The host render targets are EDRAM tile targets, not a single 1440p scene image:

```text
1280x2048 1xMSAA color
800x3280 1xMSAA color/depth
1120x1176 2xMSAA color
560x1176 4xMSAA color
...
```

This makes the “present the 1440p host RT directly” path (A2) much less
attractive: there is no single 1440p scene image to present.

### 5. Existing `draw_resolution_scale` test

Setting:

```toml
draw_resolution_scale_x = 2
draw_resolution_scale_y = 2
```

changes the swap source to a true 2560×1440 image:

```text
Vulkan draw-scale swap sizing: packet=1280x720,
  src_scaled=2560x1440, src_unscaled=1280x720, active=2560x1440
```

The title screen, UI, and in-game HUD render sharply at 2560×1440. This is the
existing internal supersampling path and does **not** require a front-buffer
dimension override.

Performance on the current Intel Arc B390 / Mesa setup:

- `draw_resolution_scale=1`: roughly **60 FPS**, 720p source upscaled.
- `draw_resolution_scale=2`: roughly **33 FPS**, true 2560×1440 source.

The tradeoff is GPU cost, not a correctness issue.

### 6. Dynamic draw-resolution scaling

`patches/rexglue-dynamic-resolution.patch` makes the draw resolution scale
adjustable at runtime. Because the scale is baked into texture allocation,
render-target sizes, and translated shaders, a change recreates the texture,
render-target, and pipeline caches after the current presentation submission
has completed.

Configuration:

```toml
d3_dynamic_resolution = true
d3_dynamic_resolution_target_fps = 60
d3_dynamic_resolution_min_scale = 1
draw_resolution_scale_x = 2
draw_resolution_scale_y = 2
```

The controller starts at the configured maximum, measures swap work excluding
the frame-limiter sleep, and downscales when the work exceeds the target frame
budget. It only upscales when the projected cost of the next scale fits, which
avoids the 720p/105 FPS ↔ 1440p/34 FPS oscillation. Verified transitions:

```text
[D3 dynamic resolution] scale 2x -> 1x requested
[D3 dynamic resolution] scale 1x active
[D3 dynamic resolution] scale 1x -> 2x requested
[D3 dynamic resolution] scale 2x active
```

On the Intel Arc B390 with a 60 FPS target, the controller settles at scale 1.
With a 30 FPS target it can keep scale 2. Transitions work in both directions;
the only cost is a brief cache-recreation hitch.

## The two paths

### Path A — presentation upscaling / compositing

This path changes how the guest front buffer is converted to the final swapchain image. It can make the final presentation 1440p, but by itself it does **not** create more internal detail.

#### A1. Add a real upscale step before gamma/FXAA

The existing gamma/FXAA pass assumes source and destination are the same size. Replace that assumption with one of:

1. **Blit/upscale first**
   - Blit the 1280×720 swap texture into a 2560×1440 intermediate image with linear filtering.
   - Run the existing gamma/FXAA pass at 2560×1440 from the intermediate image.
   - Present the 1440p guest output.
   - This preserves the existing color/gamma logic and avoids rewriting the shaders.

2. **Normalized-coordinate sampling in the gamma shader**
   - Add source-width/source-height constants to the swap gamma/FXAA shaders.
   - Sample the source with normalized UVs instead of pixel-indexed coordinates.
   - Dispatch at the destination size.
   - This is cleaner but requires regenerating the shader bytecode.

Expected result: correct 1440p output, still sourced from a 720p image. UI will remain soft; 3D detail depends on whether the 3D host render targets are actually 1440p.

Estimated effort: **1–2 days**, low risk if implemented as a blit + existing gamma pass.

#### A2. Present the 1440p host render target directly

If the 3D host render targets are already 1440p, bypass the 720p guest front buffer for the 3D scene:

- Keep the guest front buffer for the UI.
- Present the 1440p host 3D render target.
- Composite/upscale the 720p UI over it.
- Or add a final host-side composite pass that samples the 1440p scene and the 720p UI.

This is the only presentation-side option that can preserve true 1440p 3D detail while keeping the existing UI layout.

Risks:

- Host render target contents may not include the final scene composite.
- UI compositing and alpha order need to be preserved.
- Aspect ratio/letterboxing must be handled.

Estimated effort: **3–5+ days**, medium/high risk.

### Path B — game-side front-buffer/UI resolution

This is the only path that can make the game genuinely render its **front buffer and UI** at 1440p. It requires changing what the guest game does, not just the host presentation.

#### B1. Override the guest swap packet/front buffer

- The guest swap packet currently reports 1280×720.
- Find the guest function that writes the swap packet/front-buffer dimensions.
- Patch it to use the configured display size, or intercept it in `IssueSwap`.
- Ensure the guest front-buffer texture allocation and all resolve/copy destinations use the new size.
- Ensure the UI render target/layout uses the new size rather than 720p coordinates.

Risk: the game’s UI layout may be authored for 1280×720. Increasing the front buffer can leave the UI small/cropped unless the game’s UI scale/render-target path is also adjusted.

#### B2. Add a game-side UI/render resolution setting

If the game has a fixed 720p UI render target, add or patch a scale factor so:

- 3D render targets use the configured size.
- The UI renders at the same logical layout but a higher physical resolution.
- The swap packet reports the final size.

This is the highest-quality result but the most invasive.

Estimated effort: **high / unknown**; requires locating the guest swap and UI render-target functions, then testing against all menus and gameplay.

## Recommended order

1. **Measure the 3D host render targets.**
   - Add temporary logging to the host render-target creation/resolve path.
   - Confirm whether gameplay is already rendering 3D at 2560×1440 while only the UI/front buffer is 720p.
   - This determines whether Path A2 is worth pursuing.

2. **Implement Path A1 as a controlled experiment.**
   - Blit the 720p swap texture to a 1440p intermediate.
   - Run the existing gamma/FXAA pass at 1440p.
   - Verify layout, color, gamma, letterboxing, and FPS.
   - This proves the presentation path and removes the top-left/crop bug.

3. **If A1 only improves presentation, not detail:**
   - Investigate Path A2 if the host 3D targets are 1440p.
   - Otherwise evaluate Path B for true internal resolution.

4. **Only pursue Path B after A1/A2 measurements.**
   - Do not modify guest swap dimensions blindly; the UI layout and guest memory sizing must be handled together.

## Test matrix

For each attempted path:

- Title screen, autosave, main menu
- Character select and in-game HUD
- 3D scene with lighting, shadows, particles
- 16:9 and 21:9 letterboxing
- 720p, 1080p, 1440p, 4K guest modes
- Borderless and fullscreen
- Controller and keyboard input
- Steam launch and direct launch
- FPS/frame-time
- No crop, no top-left-only rendering, no double scaling
- No black UI/font alpha regression
- Screenshot comparison at 1:1 window size

## Key files

- `patches/rexglue-dynamic-resolution.patch`
  - runtime scale controller and cache recreation
- `apply_config.py`
  - `--dynamic-resolution`, `--dynamic-target-fps`, `--dynamic-min-scale`
- `rexglue-sdk/src/graphics/vulkan/command_processor.cpp`
  - `IssueSwap`, `RefreshGuestOutput`, swap gamma/FXAA dispatch, dynamic scale controller
- `rexglue-sdk/src/graphics/vulkan/texture_cache.cpp`
  - `RequestSwapTexture`
- `rexglue-sdk/src/graphics/shaders/vulkan_spirv/apply_gamma_*`
  - gamma/FXAA bytecode; may need regeneration
- `rexglue-sdk/src/ui/vulkan/vulkan_presenter.cpp`
  - `RefreshGuestOutputImpl`, guest-output paint config
- `rexglue-sdk/src/graphics/vulkan/render_target_cache.cpp`
  - host render-target allocation/resolve
- `rexglue-sdk/src/kernel/xboxkrnl/xboxkrnl_video.cpp`
  - `VdQueryVideoMode`
- `port/generated/default/`
  - guest swap/front-buffer functions once identified
- `port/src/diablo3_app.h`
  - runtime/config integration
- `docs/LINUX.md`
  - resolution behavior and limitations

## Decision

The measurement changed the recommendation:

- **True 1440p UI/3D is already available through `draw_resolution_scale_x/y = 2`.**
  - No front-buffer override is needed.
  - It produces a 2560×1440 swap source and sharp UI/HUD.
  - Cost: about 33 FPS on the current hardware versus ~60 FPS at scale 1.
- **Dynamic resolution is now implemented** to choose between those scales for
  a selected frame-rate budget (60 FPS → 1x on this GPU, 30 FPS → 2x).
- **Path A1 is only useful for presentation polish** if scale 2 is too slow; it
  cannot add detail beyond the 720p source.
- **Path A2 is not attractive** because the host targets are EDRAM tiles rather
  than one 1440p scene image.
- **Path B remains the only way to get 1440p at 60 FPS** on this GPU, by
  optimizing/reworking the game-side render path or reducing the cost of the
  2x render targets.

Recommended usage:

```sh
# True 1440p internal rendering (about 33 FPS on this machine)
python3 apply_config.py --res-scale 2 --resolution 1440p

# 60 FPS presentation, 720p source upscaled to 1440p
python3 apply_config.py --res-scale 1 --resolution 1440p

# Pick the highest scale that fits 60 FPS (1x on the tested GPU)
python3 apply_config.py --res-scale 2 --resolution 1440p \
    --dynamic-resolution true --dynamic-target-fps 60
```

The current state is: 1440p swapchain/window, 1440p swap source when
`--res-scale 2` is used. Raw front-buffer dimension override is not sufficient.
