#pragma once

#include <filesystem>

namespace rex::ui { class Window; }

namespace d3::features {
// True when launched with --extra_features. Valid after InitializeExtras().
bool Enabled();
// Reads the `extra_features` cvar; call once the command line is parsed.
void InitializeExtras();
// Called before the graphics backend creates resolution-dependent resources.
void ApplySavedRenderScale(const std::filesystem::path &user_data_root);
// Initialize and service window changes on the UI thread. Guest hooks only
// save and enqueue requests; they never call native window APIs.
void InitializeWindowMode(rex::ui::Window &window,
                          const std::filesystem::path &user_data_root);
void UpdateWindowMode(rex::ui::Window &window);
int SelectedWindowMode(); // 1 = windowed, 2 = borderless fullscreen.
bool SelectWindowMode(int mode);
} // namespace d3::features
