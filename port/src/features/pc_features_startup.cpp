#include "pc_features.h"
#include "pc_features_logic.h"

#include <rex/cvar.h>
#include <rex/logging.h>
#include <rex/ui/window.h>
#include <atomic>
#include <mutex>
#include <cstdint>
#include <string>

REXCVAR_DEFINE_BOOL(
    extra_features, false, "PC features",
    "Enable the optional PC features: render resolution and window mode menus, "
    "PC autosave wording and the Extras version label");

REXCVAR_DEFINE_BOOL(
    pc_use_saved_render_scale, true, "PC features",
    "Apply the scale saved in the game's Video options on startup");

REXCVAR_DEFINE_BOOL(pc_use_saved_window_mode, true, "PC features",
                   "Apply the window mode saved in Video options on startup");

namespace {
std::atomic<bool> extras_enabled{false};
std::filesystem::path window_mode_path;
std::mutex window_mode_mutex;
int selected_window_mode = 1;
int pending_window_mode = 0;
uint64_t window_mode_revision = 0;
}

namespace d3::features {
bool Enabled() { return extras_enabled.load(std::memory_order_relaxed); }

void InitializeExtras() {
  const bool on = rex::cvar::GetFlagByName("extra_features") == "true";
  extras_enabled.store(on, std::memory_order_relaxed);
  REXLOG_INFO("PC features: {}", on ? "enabled" : "disabled (pass --extra_features to enable)");
}

void InitializeWindowMode(rex::ui::Window &window,
                          const std::filesystem::path &user_data_root) {
  if (!Enabled())
    return;
  window_mode_path = user_data_root / kSettingsFile;
  if (rex::cvar::GetFlagByName("pc_use_saved_window_mode") == "true") {
    const auto saved = ReadWindowMode(window_mode_path, 0);
    if (saved)
      window.SetFullscreen(saved == 2);
  }
  selected_window_mode = window.IsFullscreen() ? 2 : 1;
}

int SelectedWindowMode() {
  const std::lock_guard lock(window_mode_mutex);
  return selected_window_mode;
}

bool SelectWindowMode(int mode) {
  const std::lock_guard lock(window_mode_mutex);
  try {
    SaveWindowMode(window_mode_path, mode);
    selected_window_mode = mode;
    pending_window_mode = mode;
    ++window_mode_revision;
    return true;
  } catch (const std::exception &error) {
    REXLOG_ERROR("PC window mode: {}", error.what());
    return false;
  }
}

void UpdateWindowMode(rex::ui::Window &window) {
  if (!Enabled())
    return;
  int mode;
  uint64_t revision;
  {
    const std::lock_guard lock(window_mode_mutex);
    mode = pending_window_mode;
    pending_window_mode = 0;
    revision = window_mode_revision;
  }
  // Native resize/fullscreen callbacks may re-enter painting. Never hold the
  // settings mutex across window APIs.
  if (mode) {
    window.SetFullscreen(mode == 2);
    REXLOG_INFO("PC window mode: {}", WindowModeLabel(window.IsFullscreen() ? 2 : 1));
  }
  const std::lock_guard lock(window_mode_mutex);
  // Do not overwrite a newer request posted while the native call was running.
  if (revision == window_mode_revision)
    selected_window_mode = window.IsFullscreen() ? 2 : 1;
}

void ApplySavedRenderScale(const std::filesystem::path &user_data_root) {
  if (!Enabled())
    return;
  if (rex::cvar::GetFlagByName("pc_use_saved_render_scale") != "true")
    return;
  const auto scale = ReadRenderScale(user_data_root / kSettingsFile, 0);
  if (!scale)
    return;
  const auto value = std::to_string(scale);
  // The shared resolution_scale too: when it is set (diablo3.toml, command
  // line) it overrides every axis left at its default, so a saved 1x would
  // otherwise lose to resolution_scale = 2.
  const bool shared = rex::cvar::SetFlagByName("resolution_scale", value);
  const bool x = rex::cvar::SetFlagByName("draw_resolution_scale_x", value);
  const bool y = rex::cvar::SetFlagByName("draw_resolution_scale_y", value);
  if (shared && x && y)
    REXLOG_INFO("PC settings: applying saved render resolution {}x", scale);
  else
    REXLOG_ERROR("PC settings: unable to apply saved render resolution");
}
} // namespace d3::features
