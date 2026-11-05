// Minimal stand-in for the SDK's rex/ui/window.h: just what the exit hooks use.
#pragma once
#include <functional>
#include <utility>
#include <vector>

namespace rex::ui {

class AppContext {
 public:
  void CallInUIThreadDeferred(std::function<void()> function) { queued.push_back(std::move(function)); }
  // Runs what the UI thread would run on its next loop iteration.
  void RunUIThreadCallbacks() {
    auto pending = std::move(queued);
    queued.clear();
    for (auto& function : pending) function();
  }
  std::vector<std::function<void()>> queued;
};

class Window {
 public:
  AppContext& app_context() { return context; }
  void RequestClose() { ++close_requests; }
  AppContext context;
  int close_requests = 0;
};

}  // namespace rex::ui
