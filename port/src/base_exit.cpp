#include <rex/runtime.h>
#include <rex/ui/window.h>

// Host hook for the guest "return to title screen" routine (all hosts, base disc).
extern "C" void D3RequestGameExit() {
  if (auto *runtime = rex::Runtime::instance()) {
    if (auto *window = runtime->display_window()) {
      // SDL closes synchronously. OnClosing calls TerminateTitle, which
      // self-terminates when invoked on a guest thread, skipping the final
      // process exit. Run the entire close path on the UI thread instead.
      window->app_context().CallInUIThreadDeferred(
          [window] { window->RequestClose(); });
    }
  }
}
