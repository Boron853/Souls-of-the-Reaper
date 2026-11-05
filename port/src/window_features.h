#pragma once
#include <memory>
#include <rex/ui/window.h>
#include <rex/ui/windowed_app_context.h>
// Keeps the window title (guest FPS, render and window size) current, applies
// optional window-mode changes, and logs the guest frame rate every 5 s.
// Create and destroy on the UI thread.
class WindowTelemetry {
public:
  virtual ~WindowTelemetry() = default;
};
std::unique_ptr<WindowTelemetry>
CreateWindowTelemetry(rex::ui::WindowedAppContext &context, rex::ui::Window *window);
