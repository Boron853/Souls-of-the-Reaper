#pragma once

#include <charconv>
#include <filesystem>
#include <fstream>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <system_error>

namespace d3::features {

// Optional PC settings live together in one key=value file in the user data
// directory. Each setting is written back with every other key preserved.
inline constexpr const char *kSettingsFile = "pc-settings.ini";

inline std::optional<int> ParseNumber(std::string_view text) {
  int value = 0;
  const auto *first = text.data();
  const auto *last = first + text.size();
  const auto result = std::from_chars(first, last, value);
  if (result.ec != std::errc() || result.ptr != last)
    return std::nullopt;
  return value;
}

inline std::map<std::string, std::string> ReadSettings(
    const std::filesystem::path &path) {
  std::map<std::string, std::string> values;
  std::ifstream file(path);
  std::string line;
  while (std::getline(file, line)) {
    if (!line.empty() && line.back() == '\r')
      line.pop_back();
    const auto equals = line.find('=');
    if (equals == std::string::npos)
      continue;
    values[line.substr(0, equals)] = line.substr(equals + 1);
  }
  return values;
}

// Earlier builds saved each setting as a bare number in its own file. They are
// still read when the settings file has no value, so existing choices carry over.
inline std::optional<int> ReadLegacyNumber(const std::filesystem::path &path) {
  std::ifstream file(path);
  std::string text;
  if (!(file >> text))
    return std::nullopt;
  file >> std::ws;
  return file.eof() ? ParseNumber(text) : std::nullopt;
}

inline int ReadSetting(const std::filesystem::path &path, const char *key,
                       const char *legacy_name, int low, int high,
                       int fallback) {
  const auto values = ReadSettings(path);
  const auto found = values.find(key);
  auto value = found == values.end() ? std::nullopt : ParseNumber(found->second);
  if (found == values.end())
    value = ReadLegacyNumber(path.parent_path() / legacy_name);
  return value && *value >= low && *value <= high ? *value : fallback;
}

inline int ReadRenderScale(const std::filesystem::path &path, int fallback) {
  return ReadSetting(path, "render_scale", "pc-render-scale.txt", 1, 3, fallback);
}

inline int ReadWindowMode(const std::filesystem::path &path, int fallback) {
  return ReadSetting(path, "window_mode", "pc-window-mode.txt", 1, 2, fallback);
}

inline std::string_view WindowModeLabel(int mode) {
  return mode == 1 ? "Windowed" : "Borderless fullscreen";
}

void ReplaceRenderScaleFile(const std::filesystem::path &temporary,
                            const std::filesystem::path &destination);

// Replace the file only after writing a complete temporary copy.
inline void SaveSetting(const std::filesystem::path &path, const char *key,
                        int value) {
  auto values = ReadSettings(path);
  values[key] = std::to_string(value);
  auto temporary = path;
  temporary += ".tmp";
  try {
    std::filesystem::create_directories(path.parent_path());
    std::ofstream file(temporary, std::ios::trunc);
    for (const auto &[name, text] : values)
      file << name << '=' << text << '\n';
    file.close();
    if (!file)
      throw std::runtime_error("Settings write failed");
    ReplaceRenderScaleFile(temporary, path);
  } catch (...) {
    std::error_code ignored;
    std::filesystem::remove(temporary, ignored);
    throw;
  }
}

inline void SaveRenderScale(const std::filesystem::path &path, int value) {
  if (value < 1 || value > 3)
    throw std::invalid_argument("Invalid render scale");
  SaveSetting(path, "render_scale", value);
}

inline void SaveWindowMode(const std::filesystem::path &path, int mode) {
  if (mode != 1 && mode != 2)
    throw std::invalid_argument("Invalid window mode");
  SaveSetting(path, "window_mode", mode);
}

inline std::string PcAutosaveText(std::string_view localized) {
  std::string text(localized);
  for (const auto phrase :
       {"Xbox 360 console", "Xbox 360 Console", "Xbox 360", "Xbox360"}) {
    std::size_t position = 0;
    while ((position = text.find(phrase, position)) != std::string::npos) {
      text.replace(position, std::char_traits<char>::length(phrase), "PC");
      position += 2;
    }
  }
  return text;
}

} // namespace d3::features
