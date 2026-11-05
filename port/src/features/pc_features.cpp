// Optional PC hooks shared by the base disc and verified USA update.
// See port/extra-features.md for the executable and address audit.
#ifdef SOULS_TITLE_UPDATE
#include "generated/update/diablo3_pch.h"
#else
#include "generated/base/diablo3_pch.h"
#endif
#include "pc_features.h"
#include "pc_features_logic.h"
#include "pc_features_version.h"
#include "render_scale.h"

#include <rex/cvar.h>
#include <rex/runtime.h>

#include <algorithm>
#include <string>

namespace {
constexpr uint32_t kRenderOption = 100;
constexpr uint32_t kWindowOption = 101;
bool window_save_failed = false;
constexpr std::string_view kWindowKey = "D3PC:WindowMode";
constexpr std::string_view kWindowTooltipKey = "D3PC:WindowModeTooltip";
// Version-specific guest addresses and structure offsets come from the
// generated pc_features_version.h (src/features/versions/<id>.json).
namespace ver = d3::features::version;
constexpr uint32_t kOptionsOwner = ver::options_owner;
constexpr uint32_t kSelectorTextPath = ver::selector_text;
constexpr uint32_t kVersionCallReturn = ver::version_call_return;
constexpr uint32_t kVersionFormat = ver::version_format;
constexpr std::string_view kRenderKey = "D3PC:RenderResolution";
constexpr std::string_view kTooltipKey = "D3PC:RenderResolutionTooltip";
constexpr std::string_view kAutosaveKey =
    "ConsoleUI:AutosaveWarningScreenText_XBox360";

// Same masking as scripts/find_feature_addresses.py mask_word: branch targets
// and D/DS-form displacements and immediates vary between builds; li constants,
// the ld/ldu/lwa and std/stdu sub-opcodes and everything else must match.
constexpr uint32_t MaskWord(uint32_t word) {
  const uint32_t op = word >> 26;
  if (op == 18)
    return word & ~0x03FFFFFCu;
  if (op == 16)
    return word & ~0x0000FFFCu;
  if (op == 14 && ((word >> 16) & 31) == 0) // li rD,SIMM
    return word;
  if (op == 58 || op == 62) // DS-form: keep the low two sub-opcode bits
    return word & ~0x0000FFFCu;
  if (op == 7 || op == 8 || op == 10 || op == 11 || op == 12 || op == 13 ||
      op == 14 || op == 15 || (op >= 24 && op <= 29) || (op >= 32 && op <= 55))
    return word & ~0xFFFFu;
  return word;
}

// The profile's hooks are only meaningful if the loaded executable still has
// the code the audit saw at those addresses. Checked once, on first use. A
// signature whose code reads as all zero is treated as unreadable, not wrong.
bool CodeVerified(uint8_t *base) {
  static const bool verified = [&] {
    unsigned unreadable = 0;
    for (unsigned i = 0; i < ver::kCodeSignatureCount; ++i) {
      const auto &signature = ver::kCodeSignatures[i];
      uint32_t any = 0;
      bool match = true;
      for (uint32_t j = 0; j < signature.count; ++j) {
        const uint32_t word = REX_LOAD_U32(signature.address + j * 4);
        any |= word;
        match = match && MaskWord(word) == signature.words[j];
      }
      if (!any)
        ++unreadable;
      if (any && !match) {
        REXLOG_WARN("PC features: code at {:#x} does not match the "
                    "expected build; extra features disabled",
                    signature.address);
        return false;
      }
    }
    REXLOG_INFO("PC features: {} code signatures verified, {} unreadable",
                ver::kCodeSignatureCount - unreadable, unreadable);
    return true;
  }();
  return verified;
}

bool Active(uint8_t *base) {
  return d3::features::Enabled() && CodeVerified(base);
}

struct Settings {
  int active_x, active_y, selected;
  bool save_failed = false;
  std::filesystem::path path;

  Settings() {
    const auto active = d3::ConfiguredRenderScale();
    active_x = active.x;
    active_y = active.y;
    // Use the resolved directory when the executable is launched directly too.
    path = rex::Runtime::instance()->user_data_root() / d3::features::kSettingsFile;
    selected = d3::features::ReadRenderScale(path, std::clamp(active_x, 1, 3));
  }

  std::string title() const {
    return "Render resolution (restart required)";
  }

  std::string tooltip() const {
    return std::string(save_failed ? "Could not save setting. " : "") +
           "Use left/right to select 1x, 2x, or 3x internal rendering scale. "
           "Current: " +
           std::to_string(active_x) + "x" + std::to_string(active_y) +
           ". Saved: " + std::to_string(selected) +
           "x. Close and relaunch the game to apply. Higher scales use more "
           "GPU memory and processing.";
  }

  void select(int next) {
    if (next < 1 || next > 3 || next == selected)
      return;
    try {
      d3::features::SaveRenderScale(path, next);
      selected = next;
      save_failed = false;
      REXLOG_INFO("PC settings: saved render resolution {}x; restart required",
                  selected);
    } catch (const std::exception &error) {
      save_failed = true;
      REXLOG_ERROR("PC settings: {}", error.what());
    }
  }
};

Settings &settings() {
  static Settings value;
  return value;
}

// Guest strings own their storage. Use the guest API for
// construction/assignment.
void ConstructText(PPCContext &ctx, uint8_t *base, uint32_t destination,
                   std::string_view text, bool assign) {
  const auto previous = ctx.r1.u64;
  const auto frame =
      ctx.r1.u32 - ((static_cast<uint32_t>(text.size()) + 96) & ~15u);
  REX_STORE_U32(frame, ctx.r1.u32);
  for (uint32_t i = 0; i <= text.size(); ++i) {
    REX_STORE_U8(frame + 80 + i, i == text.size() ? 0 : text[i]);
  }
  ctx.r1.u64 = frame;
  ctx.r3.u64 = destination;
  ctx.r4.u64 = frame + 80;
  if (assign)
    D3_FN_string_assign(ctx, base);
  else
    D3_FN_string_construct(ctx, base);
  ctx.r1.u64 = previous;
}

std::string ReadText(uint8_t *base, uint32_t address, unsigned limit) {
  if (!address)
    return {};
  std::string result;
  for (unsigned i = 0; i < limit; ++i) {
    const auto byte = REX_LOAD_U8(address + i);
    if (!byte)
      return result;
    result.push_back(static_cast<char>(byte));
  }
  return {}; // Leave unterminated text untouched.
}

// The selector label hook feeds kSelectorTextPath to the game as a node name.
// Confirm the guest string is what we expect so an unrecognised build loses
// only the custom selector labels instead of misbehaving.
bool SelectorPathValid(uint8_t *base) {
  static const bool valid = [&] {
    const bool ok = ReadText(base, kSelectorTextPath, 32) == "SelectorTemplateText";
    if (!ok)
      REXLOG_WARN("PC features: unexpected guest data at {:#x}; custom "
                  "selector labels disabled for this build",
                  kSelectorTextPath);
    return ok;
  }();
  return valid;
}

// The start-screen hook only appends " + Extras" after a "%s" format call.
bool VersionFormatValid(uint8_t *base) {
  static const bool valid = [&] {
    const bool ok = ReadText(base, kVersionFormat, 8) == "%s";
    if (!ok)
      REXLOG_WARN("PC features: unexpected guest data at {:#x}; version label "
                  "suffix disabled for this build",
                  kVersionFormat);
    return ok;
  }();
  return valid;
}

uint32_t CurrentDescriptor(uint8_t *base) {
  const auto owner = REX_LOAD_U32(kOptionsOwner);
  if (!owner)
    return 0;
  const auto vector = REX_LOAD_U32(owner + ver::active_descriptor_vector);
  const auto index = REX_LOAD_U32(owner + ver::active_descriptor_index);
  if (!vector || index >= REX_LOAD_U32(vector + 8))
    return 0;
  // The vector stores its big-endian data pointer in the low word of a u64.
  const auto data = static_cast<uint32_t>(REX_LOAD_U64(vector));
  return data ? data + index * ver::descriptor_stride : 0;
}
} // namespace

// The start screen formats the original build string into a 1024-byte buffer
// before passing it to Root.NormalLayer.ConsoleStart_main.LayoutRoot.Version.
// Match that call site and its "%s" format; all other formatting stays intact.
extern "C" void D3_FN_version_format_call(PPCContext &ctx, uint8_t *base) {
  if (!Active(base)) {
    D3_IMP_version_format_call(ctx, base);
    return;
  }
  const bool start_version = ctx.lr == kVersionCallReturn &&
                             ctx.r4.u32 == kVersionFormat &&
                             VersionFormatValid(base);
  const auto destination = ctx.r3.u32;
  D3_IMP_version_format_call(ctx, base);
  if (!start_version)
    return;
  constexpr std::string_view suffix = " + Extras";
  const auto text = ReadText(base, destination, 1024);
  if (text.empty() || text.ends_with(suffix) ||
      text.size() + suffix.size() >= 1024)
    return;
  for (uint32_t i = 0; i < suffix.size(); ++i)
    REX_STORE_U8(destination + static_cast<uint32_t>(text.size()) + i, suffix[i]);
  REX_STORE_U8(destination + static_cast<uint32_t>(text.size() + suffix.size()), 0);
}

// Strong definitions override only these weak generated aliases when linked.
// Each hook hands straight back to the original function unless the
// `extra_features` cvar is set, so one binary serves both modes.
extern "C" void D3_FN_video_options_build(PPCContext &ctx, uint8_t *base) {
  if (!Active(base)) {
    D3_IMP_video_options_build(ctx, base);
    return;
  }
  const auto owner = ctx.r3.u32;
  D3_IMP_video_options_build(ctx, base);
  const auto saved = ctx;
  const auto frame = ctx.r1.u32 - 512;
  REX_STORE_U32(frame, ctx.r1.u32);
  ctx.r1.u64 = frame;
  for (const auto option : {kRenderOption, kWindowOption}) {
    ctx.r3.u64 = frame + 96;
    D3_FN_option_descriptor_init(ctx, base);
    ConstructText(ctx, base, frame + 160,
                  option == kRenderOption ? kRenderKey : kWindowKey, false);
    ConstructText(ctx, base, frame + 176,
                  option == kRenderOption ? kTooltipKey : kWindowTooltipKey, false);
    ctx.r3.u64 = frame + 96;
    ctx.r4.u64 = 1; // Native left/right selector.
    ctx.r5.u64 = frame + 160;
    ctx.r6.u64 = frame + 176;
    ctx.r7.u64 = option;
    D3_FN_option_descriptor_selector(ctx, base);
    ctx.r3.u64 = owner + ver::video_vector;
    ctx.r4.u64 = frame + 96;
    D3_FN_options_insert(ctx, base);
  }
  // The constructor consumes both key strings, and insertion consumes the
  // temporary descriptor. Do not destroy those temporaries a second time.
  ctx = saved;
  REXLOG_INFO("PC settings: render resolution and window mode added to Video options");
}

// Selector model: option ID at +4, count in vtable slot 0.
extern "C" void D3_FN_selector_count(PPCContext &ctx, uint8_t *base) {
  if (!Active(base)) {
    D3_IMP_selector_count(ctx, base);
    return;
  }
  const auto option = REX_LOAD_U32(ctx.r3.u32 + ver::selector_option_id);
  if (option == kRenderOption || option == kWindowOption) {
    ctx.r3.u64 = option == kRenderOption ? 3 : 2;
    return;
  }
  D3_IMP_selector_count(ctx, base);
}

extern "C" void D3_FN_selector_init(PPCContext &ctx, uint8_t *base) {
  if (!Active(base)) {
    D3_IMP_selector_init(ctx, base);
    return;
  }
  const auto option = REX_LOAD_U32(ctx.r3.u32 + ver::selector_option_id);
  if (option != kRenderOption && option != kWindowOption) {
    D3_IMP_selector_init(ctx, base);
    return;
  }
  const auto saved = ctx;
  ctx.r3 = saved.r4; // Resolved native selector control.
  ctx.r4.u64 = (option == kRenderOption ? settings().selected
                  : d3::features::SelectedWindowMode()) - 1;
  ctx.r5.u64 = 0; // Initialize without firing the change callback.
  D3_FN_selector_set_index(ctx, base);
  ctx = saved;
}

extern "C" void D3_FN_selector_row_label(PPCContext &ctx, uint8_t *base) {
  if (!Active(base)) {
    D3_IMP_selector_row_label(ctx, base);
    return;
  }
  const auto option = REX_LOAD_U32(ctx.r3.u32 + ver::selector_option_id);
  const bool render = option == kRenderOption;
  const bool window = option == kWindowOption;
  const auto row = ctx.r5.u32;
  const auto index = ctx.r6.u32;
  // Preserve the game's selection highlighting and normal row setup.
  D3_IMP_selector_row_label(ctx, base);
  if ((!render && !window) || index >= (render ? 3u : 2u))
    return;
  if (!SelectorPathValid(base))
    return;
  const auto saved = ctx;
  const auto frame = ctx.r1.u32 - 256;
  REX_STORE_U32(frame, ctx.r1.u32);
  ctx.r1.u64 = frame;
  ctx.r3.u64 = frame + 80;
  ctx.r4.u64 = row;
  ctx.r5.u64 = kSelectorTextPath; // "SelectorTemplateText".
  D3_FN_find_child_node(ctx, base);
  ctx.r3.u64 = frame + 80;
  D3_FN_resolve_label(ctx, base);
  const auto label = ctx.r3.u32;
  const auto setter = REX_LOAD_U32(REX_LOAD_U32(label) + ver::label_setter_vtable_slot);
  const std::string text = render ? std::to_string(index + 1) + "x"
      : std::string(d3::features::WindowModeLabel(index + 1));
  for (uint32_t i = 0; i <= text.size(); ++i)
    REX_STORE_U8(frame + 112 + i, i == text.size() ? 0 : text[i]);
  ctx.r3.u64 = label;
  ctx.r4.u64 = frame + 112;
  ctx.r5.u64 = 0;
  REX_CALL_INDIRECT_FUNC(setter);
  ctx = saved;
}

extern "C" void D3_FN_selector_changed(PPCContext &ctx, uint8_t *base) {
  if (!Active(base)) {
    D3_IMP_selector_changed(ctx, base);
    return;
  }
  const auto descriptor = CurrentDescriptor(base);
  const auto option = descriptor ? REX_LOAD_U32(descriptor + ver::descriptor_action_id) : 0;
  if (option != kRenderOption && option != kWindowOption) {
    D3_IMP_selector_changed(ctx, base);
    return;
  }
  const auto saved = ctx;
  D3_FN_selector_control(ctx, base);
  const auto control = ctx.r3.u32;
  const auto index = REX_LOAD_U32(control + ver::selector_selected_index);
  if (option == kRenderOption && index < 3)
    settings().select(static_cast<int>(index) + 1);
  else if (option == kWindowOption && index < 2)
    window_save_failed = !d3::features::SelectWindowMode(static_cast<int>(index) + 1);
  // Restore the last saved value if saving failed, without another callback.
  ctx.r3.u64 = control;
  ctx.r4.u64 = (option == kRenderOption ? settings().selected
                  : d3::features::SelectedWindowMode()) - 1;
  ctx.r5.u64 = 0;
  D3_FN_selector_set_index(ctx, base);
  const auto owner = REX_LOAD_U32(kOptionsOwner);
  if (owner)
    REX_STORE_U32(owner + ver::options_dirty_flag, 1); // Mark the options model dirty.
  ctx = saved;
}

extern "C" void D3_FN_localized_text(PPCContext &ctx, uint8_t *base) {
  if (!Active(base)) {
    D3_IMP_localized_text(ctx, base);
    return;
  }
  const auto name = ReadText(base, ctx.r4.u32, 64);
  const auto destination = ctx.r3.u32;
  if (name == kWindowKey || name == kWindowTooltipKey) {
    const auto saved = ctx;
    const std::string text = name == kWindowKey ? "Window mode"
        : std::string(window_save_failed ? "Could not save setting. " : "") +
          "Choose Windowed or Borderless fullscreen. Applies immediately. "
          "F11 toggles the current mode without changing the saved preference.";
    ConstructText(ctx, base, destination, text, false);
    ctx = saved;
    ctx.r3.u64 = destination;
    return;
  }
  if (name == kRenderKey || name == kTooltipKey) {
    const auto saved = ctx;
    ConstructText(
        ctx, base, destination,
        name == kRenderKey ? settings().title() : settings().tooltip(), false);
    ctx = saved;
    ctx.r3.u64 = destination;
    return;
  }
  D3_IMP_localized_text(ctx, base);
  if (name != kAutosaveKey)
    return;
  const auto saved = ctx;
  ctx.r3.u64 = destination;
  D3_FN_string_c_str(ctx, base);
  const auto localized = ReadText(base, ctx.r3.u32, 16384);
  const auto replacement = d3::features::PcAutosaveText(localized);
  if (replacement != localized) {
    ConstructText(ctx, base, destination, replacement, true);
    REXLOG_INFO("PC settings: autosave notice uses PC wording");
  }
  ctx = saved;
}
