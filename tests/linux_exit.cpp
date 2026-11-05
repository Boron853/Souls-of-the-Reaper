// The guest's "return to title" exit hooks must close the window from the UI thread:
// closing synchronously on the calling guest thread skips the final process exit.
// Built against tests/fixtures/exit (stand-ins for the SDK headers) together with
// port/src/base_exit.cpp and port/src/title_update_exit.cpp.
#include <rex/runtime.h>

#include <cassert>
#include <initializer_list>

extern "C" void D3RequestGameExit();
extern "C" void D3RequestTitleUpdateExit();

int main() {
  for (auto request : {D3RequestGameExit, D3RequestTitleUpdateExit}) {
    rex::Runtime::current() = nullptr;
    request();  // no runtime yet: nothing to close

    rex::Runtime runtime;
    rex::Runtime::current() = &runtime;
    request();  // no window yet

    rex::ui::Window window;
    runtime.window = &window;
    request();
    assert(window.close_requests == 0);  // not closed on the guest thread
    assert(window.context.queued.size() == 1);
    window.context.RunUIThreadCallbacks();
    assert(window.close_requests == 1);  // closed once, from the UI thread
  }
  rex::Runtime::current() = nullptr;
}
