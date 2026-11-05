// Minimal stand-in for the SDK's rex/runtime.h: just what the exit hooks use.
#pragma once
#include <rex/ui/window.h>

namespace rex {

class Runtime {
 public:
  static Runtime*& current() {
    static Runtime* runtime = nullptr;
    return runtime;
  }
  static Runtime* instance() { return current(); }
  ui::Window* display_window() { return window; }
  ui::Window* window = nullptr;
};

}  // namespace rex
