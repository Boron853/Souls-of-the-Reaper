#include <rex/runtime.h>
#include <rex/ui/window.h>

// The title update owns its exit hook on every host, independent of base-disc SDK patches.
extern "C" void D3RequestTitleUpdateExit() {
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
