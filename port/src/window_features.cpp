#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <tlhelp32.h>
#endif
#include "window_features.h"
#include "render_scale.h"
#ifdef SOULS_ENABLE_EXTRA_FEATURES
#include "features/pc_features.h"
#endif
#ifdef SOULS_TITLE_UPDATE
#include "generated/update/diablo3_pch.h"
#else
#include "generated/base/diablo3_pch.h"
#endif
#ifndef _WIN32
#include <dlfcn.h>
#endif
#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <iomanip>
#include <mutex>
#include <rex/cvar.h>
#include <rex/logging.h>
#include <sstream>
#include <thread>
namespace {
std::atomic<uint64_t> swaps{0};
std::atomic<uint64_t> dimensions{0};
// Name of the renderer in use, taken from what the process actually loaded so
// the title never claims a backend that failed to start. Both renderers live in
// one GPU plugin; gpu_backend picks one at launch and 'any' resolves to D3D12.
std::string_view RendererName() {
#ifdef _WIN32
  if (rex::cvar::GetFlagByName("gpu_backend") == "vulkan")
    return GetModuleHandleW(L"vulkan-1.dll") ? "Vulkan" : "Renderer pending";
  return GetModuleHandleW(L"d3d12.dll") ? "D3D12" : "Renderer pending";
#else
  return "Vulkan";
#endif
}

using OriginalSwap = void (*)(PPCContext &, uint8_t *);
OriginalSwap ResolveOriginalSwap() {
#ifdef _WIN32
  // Find the export in a loaded DLL, independent of the SDK's configuration
  // suffix (Debug / Release / RelWithDebInfo) and installation directory.
  const auto modules = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE, GetCurrentProcessId());
  if (modules == INVALID_HANDLE_VALUE)
    return nullptr;
  MODULEENTRY32W module{};
  module.dwSize = sizeof(module);
  OriginalSwap original = nullptr;
  if (Module32FirstW(modules, &module)) {
    do {
      // The executable defines our wrapper; only inspect DLLs for the SDK.
      if (module.hModule == GetModuleHandleW(nullptr))
        continue;
      original = reinterpret_cast<OriginalSwap>(
          GetProcAddress(module.hModule, "__imp__VdSwap"));
      if (original)
        break;
    } while (Module32NextW(modules, &module));
  }
  CloseHandle(modules);
  return original;
#else
  return reinterpret_cast<OriginalSwap>(dlsym(RTLD_NEXT, "__imp__VdSwap"));
#endif
}
// Title-bar status and guest frame-rate log. A ticker thread posts updates to
// the UI thread instead of keeping an ImGui dialog open: any open dialog makes
// the drawer repaint continuously, presenting uncapped frames.
class WindowStatus final : public WindowTelemetry {
public:
  WindowStatus(rex::ui::WindowedAppContext &context, rex::ui::Window *window)
      : context_(context), window_(window) {
    window_->SetTitle("Souls of the Reaper | Starting | " + std::string(RendererName()));
    ticker_ = std::thread([this] { Run(); });
  }
  ~WindowStatus() override {
    // Destroyed on the UI thread, so no queued update can be running now.
    *alive_ = false;
    {
      const std::lock_guard lock(mutex_);
      stopping_ = true;
    }
    wake_.notify_all();
    ticker_.join();
  }

private:
  void Run() {
    using namespace std::chrono;
    auto previous = steady_clock::now(), log_start = previous;
    auto previous_count = swaps.load(std::memory_order_relaxed);
    auto log_count = previous_count;
    double log_low = -1;
    std::unique_lock lock(mutex_);
    while (!wake_.wait_for(lock, milliseconds(500), [this] { return stopping_; })) {
      const auto now = steady_clock::now();
      const auto count = swaps.load(std::memory_order_relaxed);
      const double fps =
          double(count - previous_count) / duration<double>(now - previous).count();
      previous = now;
      previous_count = count;
      log_low = log_low < 0 ? fps : std::min(log_low, fps);
      if (now - log_start >= seconds(5)) {
        const double average =
            double(count - log_count) / duration<double>(now - log_start).count();
        REXLOG_INFO("Frame telemetry: guest {:.1f} FPS average, {:.1f} lowest 0.5 s",
                    average, log_low);
        log_start = now;
        log_count = count;
        log_low = -1;
      }
      context_.CallInUIThread([alive = alive_, window = window_, fps] {
        if (*alive)
          Update(*window, fps);
      });
    }
  }

  static void Update(rex::ui::Window &window, double fps) {
#ifdef SOULS_ENABLE_EXTRA_FEATURES
    d3::features::UpdateWindowMode(window);
#endif
    // Read after setup too: optional saved settings are applied after dialogs
    // are created.
    const auto [scale_x, scale_y] = d3::ConfiguredRenderScale();
    const auto size = dimensions.load(std::memory_order_relaxed);
    std::ostringstream title;
    title << "Souls of the Reaper | " << std::fixed << std::setprecision(1) << fps << " FPS";
    if (size)
      title << " | Render " << (size >> 32) * scale_x << 'x'
            << uint32_t(size) * scale_y;
    title << " | Window " << window.GetActualPhysicalWidth() << 'x'
          << window.GetActualPhysicalHeight() << " | " << RendererName();
    window.SetTitle(title.str());
  }

  rex::ui::WindowedAppContext &context_;
  rex::ui::Window *window_;
  std::shared_ptr<bool> alive_ = std::make_shared<bool>(true);
  std::mutex mutex_;
  std::condition_variable wake_;
  bool stopping_ = false;
  std::thread ticker_;
};
} // namespace
// Preserve the SDK import implementation while observing guest frame swaps.
extern "C" void __imp__VdSwap(PPCContext &ctx, uint8_t *base) {
  static const auto original = ResolveOriginalSwap();
  if (!original)
    REX_FATAL("Unable to resolve SDK VdSwap for frame telemetry");
  const auto width_pointer = REX_LOAD_U32(ctx.r1.u32 + 0x54);
  const auto height_pointer = REX_LOAD_U32(ctx.r1.u32 + 0x5C);
  const auto width = REX_LOAD_U32(width_pointer),
             height = REX_LOAD_U32(height_pointer);
  original(ctx, base);
  dimensions.store((uint64_t(width) << 32) | height, std::memory_order_relaxed);
  swaps.fetch_add(1, std::memory_order_relaxed);
}
std::unique_ptr<WindowTelemetry>
CreateWindowTelemetry(rex::ui::WindowedAppContext &context, rex::ui::Window *window) {
  return std::make_unique<WindowStatus>(context, window);
}
