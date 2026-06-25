// diablo3 - ReXGlue Recompiled Project

#pragma once

#include <filesystem>
#include <memory>

#include <rex/rex_app.h>
#include <rex/runtime.h>
#include <rex/filesystem/vfs.h>
#include <rex/filesystem/devices/host_path_device.h>
#include <rex/logging.h>

#include "cache_device.h"

class Diablo3App : public rex::ReXApp {
 public:
  using rex::ReXApp::ReXApp;

  static std::unique_ptr<rex::ui::WindowedApp> Create(
      rex::ui::WindowedAppContext& ctx) {
    return std::unique_ptr<Diablo3App>(new Diablo3App(ctx, "diablo3",
        PPCImageConfig));
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
};
