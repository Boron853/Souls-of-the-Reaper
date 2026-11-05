#pragma once

#include <algorithm>
#include <string>

#include <rex/cvar.h>

namespace d3 {

struct RenderScale {
  int x, y;
};

// The draw resolution scale per axis that the renderer uses. Mirrors the SDK's
// TextureCache::GetConfigDrawResolutionScale: a non-default shared
// resolution_scale applies to each axis whose own setting is at its default.
inline RenderScale ConfiguredRenderScale() {
  const int shared = std::stoi(rex::cvar::GetFlagByName("resolution_scale"));
  const bool use_shared = rex::cvar::HasNonDefaultValue("resolution_scale");
  const auto axis = [&](const char *name) {
    const int value = use_shared && !rex::cvar::HasNonDefaultValue(name)
                          ? shared
                          : std::stoi(rex::cvar::GetFlagByName(name));
    return std::clamp(value, 1, 7);
  };
  return {axis("draw_resolution_scale_x"), axis("draw_resolution_scale_y")};
}

} // namespace d3
