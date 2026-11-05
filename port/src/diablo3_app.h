// diablo3 - ReXGlue Recompiled Project

#pragma once

// Every host loads the Xenos GPU plugin shipped with the pinned SDK.
#define SOULS_GPU_PLUGIN 1

#include <string>
#include <filesystem>
#include <memory>

#include <rex/cvar.h>
#include <rex/rex_app.h>
#include <rex/runtime.h>
#include <rex/filesystem/vfs.h>
#include <rex/filesystem/devices/host_path_device.h>
#include <rex/logging.h>

#include "cache_device.h"
#include "window_features.h"
#ifdef SOULS_ENABLE_EXTRA_FEATURES
#include "features/pc_features.h"
#ifdef SOULS_GPU_PLUGIN
#include <rex/system/gpu_plugin.h>
#endif
#endif
#include <rex/ui/keybinds.h>

class Diablo3App : public rex::ReXApp {
 public:
  using rex::ReXApp::ReXApp;

  static std::unique_ptr<rex::ui::WindowedApp> Create(
      rex::ui::WindowedAppContext& ctx) {
    return std::unique_ptr<Diablo3App>(new Diablo3App(ctx, "diablo3",
        PPCImageConfig));
  }

  // Clean title bar text instead of the SDK default ("diablo3 [rexglue-vX.Y.Z-
  // ...]"). GetName() ("diablo3") is untouched on purpose - it also names the
  // user data folder and the config TOML file, and changing it would break
  // existing installs.
#if !defined(__linux__) && !defined(SOULS_TITLE_UPDATE)
  std::string OnGetWindowTitle() override { return "Diablo III: Reaper of Souls"; }
#endif

#if defined(SOULS_GPU_PLUGIN) || defined(SOULS_ENABLE_EXTRA_FEATURES)
  void OnPreSetup(rex::RuntimeConfig& config) override {
#ifdef SOULS_GPU_PLUGIN
    config.gpu_plugin = "xenos";
#else
    (void)config;
#endif
#ifdef SOULS_ENABLE_EXTRA_FEATURES
    d3::features::InitializeExtras();
    if (d3::features::Enabled()) {
#ifdef SOULS_GPU_PLUGIN
      // GPU cvars are registered by the plugin, before its presentation/setup.
      // Honour --gpu_backend here too: this early load bypasses ReXApp, which
      // would otherwise pass it. "any" resolves to D3D12 when it is compiled in.
      // The cvar only exists where the SDK defines it (Windows patch); on Linux
      // the lookup is empty, which the plugin rejects, so fall back to "any".
      std::string gpu_backend = rex::cvar::GetFlagByName("gpu_backend");
      if (gpu_backend.empty()) gpu_backend = "any";
      config.graphics = rex::system::LoadGpuPlugin(config.gpu_plugin, gpu_backend);
      if (!config.graphics) {
        REX_FATAL("Unable to load the Xenos GPU plugin for the optional PC build");
      }
#endif
      d3::features::ApplySavedRenderScale(user_data_root());
    }
#endif
  }
#endif
#ifdef SOULS_GPU_PLUGIN
  void OnLoadXexImage(std::string& xex_image) override {
    xex_image = "game:\\Default.xex";
#ifdef SOULS_TITLE_UPDATE
    // Overlay layout: the pristine disc is the game root and the patched
    // executable sits in <game>/update beside the update CPKs (mounted as update:).
    std::error_code ec;
    if (std::filesystem::is_regular_file(game_data_root() / "update" / "Default.xex", ec)) {
      xex_image = "game:\\update\\Default.xex";
    } else if (std::filesystem::is_regular_file(game_data_root() / "tu2" / "Default.xex", ec)) {
      xex_image = "game:\\tu2\\Default.xex";  // overlay staged before it was renamed
    }
#endif
  }
#endif
  void OnCreateDialogs(rex::ui::ImGuiDrawer* drawer) override {
#ifdef SOULS_ENABLE_EXTRA_FEATURES
    d3::features::InitializeWindowMode(*window(), user_data_root());
#endif
    (void)drawer;
    title_ = CreateWindowTelemetry(app_context(), window());
  }
  void OnShutdown() override { title_.reset(); }
  void OnKeyDown(rex::ui::KeyEvent& event) override {
    if (event.virtual_key() == rex::ui::VirtualKey::kF11) {
      if (!event.prev_state()) window()->SetFullscreen(!window()->IsFullscreen());
      event.set_handled(true);
      return;
    }
    rex::ui::ProcessKeyEvent(event);
  }

  // FATX cache device setup.
  // Diablo mounts cache:\ as a FATX volume by reading \Device\Harddisk0\Partition0
  // for a "Josh" superblock at 0x800. The SDK's NullDevice returns zeros,
  // causing the mount to fail and the game to deadlock in IoDismountVolume.
  // We replace it with a CacheDevice that serves the synthetic superblock.
  void OnPostSetup() override {
    auto* rt = runtime();
    if (!rt || !rt->file_system()) {
      return;
    }
    auto* fs = rt->file_system();

    // Replace the SDK's NullDevice with our FATX cache device.
    constexpr const char* kHddMount = "\\Device\\Harddisk0";
    fs->UnregisterDevice(kHddMount);

    auto device = std::make_unique<d3::CacheDevice>(kHddMount);
    if (!device->Initialize() || !fs->RegisterDevice(std::move(device))) {
      REXLOG_ERROR("Failed to register CacheDevice at {}", kHddMount);
      return;
    }
    REXLOG_INFO("CacheDevice (Josh) mounted at {}", kHddMount);

    // Back cache:\ with a writable host folder so cache workers don't spin.
    std::filesystem::path host_cache = cache_root() / "title_cache";
    std::error_code ec;
    std::filesystem::create_directories(host_cache, ec);
    constexpr const char* kCacheMount = "\\Device\\Cache";
    auto cache_dev = std::make_unique<rex::filesystem::HostPathDevice>(
        kCacheMount, host_cache, /*read_only=*/false);
    if (cache_dev->Initialize() && fs->RegisterDevice(std::move(cache_dev))) {
      fs->RegisterSymbolicLink("cache:", kCacheMount);
      REXLOG_INFO("cache: volume backed by {} ({})", host_cache.string(),
                  kCacheMount);
    } else {
      REXLOG_ERROR("Failed to register cache: volume");
    }
  }
 private:
  std::unique_ptr<WindowTelemetry> title_;
};
