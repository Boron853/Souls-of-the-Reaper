#include <cstdio>
#include <rex/logging.h>
#include <rex/system/gpu_plugin.h>
#include <rex/ui/vulkan/provider.h>

int main() {
  rex::LogConfig logging;
  logging.log_to_console = true;
  logging.default_level = spdlog::level::warn;
  rex::InitLogging(logging);
  auto graphics = rex::system::LoadGpuPlugin("xenos", "vulkan");
  if (!graphics) {
    std::fputs("FAIL: Xenos Vulkan plugin could not be loaded.\n", stderr);
    return 1;
  }
  auto provider = rex::ui::vulkan::VulkanProvider::Create(true, false);
  if (!provider) {
    std::fputs(
        "FAIL: no device supports the runtime's Vulkan GPU requirements.\n",
        stderr);
    return 2;
  }
  const auto &properties = provider->vulkan_device()->properties();
  std::printf("PASS: Xenos Vulkan plugin loaded; GPU device initialized: %s "
              "(Vulkan %u.%u).\n",
              properties.deviceName,
              VK_API_VERSION_MAJOR(properties.apiVersion),
              VK_API_VERSION_MINOR(properties.apiVersion));
  provider.reset();
  graphics.reset();
  rex::ShutdownLogging();
  return 0;
}
