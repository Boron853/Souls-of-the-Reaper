#include "pc_features_logic.h"

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <system_error>
#include <windows.h>
#endif

namespace d3::features {
void ReplaceRenderScaleFile(const std::filesystem::path &temporary,
                            const std::filesystem::path &destination) {
#ifdef _WIN32
  // Replace an existing selection without deleting it first. Wide paths keep
  // user-data directories with non-ASCII names intact.
  if (!MoveFileExW(temporary.c_str(), destination.c_str(),
                   MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
    throw std::system_error(static_cast<int>(GetLastError()),
                            std::system_category(),
                            "Render scale replacement failed");
  }
#else
  std::filesystem::rename(temporary, destination);
#endif
}
} // namespace d3::features
