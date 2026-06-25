// Minimal, dependency-free PNG writer for headless render debugging.
//
// The SDK's trace_dump.cpp uses stb_image_write, but that header is absent from
// this tree and trace_dump is not built. To let the guest output (the final
// presented frame) be dumped to an image that can be inspected without a
// physical display, this encodes an 8-bit RGBA PNG using uncompressed
// ("stored") DEFLATE blocks, so no zlib/stb dependency is required.
//
// Used by D3D12CommandProcessor::IssueSwap (file-triggered screenshot). See
// WriteRawImageToPng().

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

namespace rex::graphics::d3d12 {

// ---------------------------------------------------------------------------
// [D3DIAG] On-demand per-frame render-target / resolve / draw logging.
// Armed via a file trigger from IssueSwap; consumed across the d3d12 command
// processor and render target cache to characterize a gameplay frame's
// structure (where the 3D scene draws and resolves to) without flooding logs.
// ---------------------------------------------------------------------------
namespace {
std::atomic<int> g_rtlog_frames{0};
std::atomic<uint64_t> g_rtlog_draws{0};
std::atomic<uint64_t> g_rtlog_resolves{0};
}  // namespace

void RtLogArm(int frames) { g_rtlog_frames.store(frames); }
bool RtLogActive() { return g_rtlog_frames.load() > 0; }
void RtLogCountDraw() {
  if (g_rtlog_frames.load() > 0) g_rtlog_draws.fetch_add(1);
}
void RtLogCountResolve() {
  if (g_rtlog_frames.load() > 0) g_rtlog_resolves.fetch_add(1);
}
uint64_t RtLogGetDraws() { return g_rtlog_draws.load(); }
uint64_t RtLogGetResolves() { return g_rtlog_resolves.load(); }
void RtLogEndFrameReset() {
  g_rtlog_draws.store(0);
  g_rtlog_resolves.store(0);
  int v = g_rtlog_frames.load();
  if (v > 0) g_rtlog_frames.store(v - 1);
}

namespace {

uint32_t Crc32(const uint8_t* data, size_t len) {
  static uint32_t table[256];
  static bool init = false;
  if (!init) {
    for (uint32_t i = 0; i < 256; ++i) {
      uint32_t c = i;
      for (int k = 0; k < 8; ++k) {
        c = (c & 1) ? (0xEDB88320u ^ (c >> 1)) : (c >> 1);
      }
      table[i] = c;
    }
    init = true;
  }
  uint32_t crc = 0xFFFFFFFFu;
  for (size_t i = 0; i < len; ++i) {
    crc = table[(crc ^ data[i]) & 0xFF] ^ (crc >> 8);
  }
  return ~crc;
}

uint32_t Adler32(const uint8_t* data, size_t len) {
  uint32_t a = 1, b = 0;
  for (size_t i = 0; i < len; ++i) {
    a = (a + data[i]) % 65521u;
    b = (b + a) % 65521u;
  }
  return (b << 16) | a;
}

void PutBE32(std::vector<uint8_t>& v, uint32_t x) {
  v.push_back(uint8_t((x >> 24) & 0xFF));
  v.push_back(uint8_t((x >> 16) & 0xFF));
  v.push_back(uint8_t((x >> 8) & 0xFF));
  v.push_back(uint8_t(x & 0xFF));
}

void WriteChunk(std::vector<uint8_t>& out, const char type[4],
                const std::vector<uint8_t>& data) {
  PutBE32(out, uint32_t(data.size()));
  size_t crc_start = out.size();
  out.push_back(uint8_t(type[0]));
  out.push_back(uint8_t(type[1]));
  out.push_back(uint8_t(type[2]));
  out.push_back(uint8_t(type[3]));
  out.insert(out.end(), data.begin(), data.end());
  uint32_t crc = Crc32(out.data() + crc_start, out.size() - crc_start);
  PutBE32(out, crc);
}

}  // namespace

// Encodes an 8-bit RGBA PNG. `rgbx` is R8 G8 B8 X8 (the X/alpha byte is ignored
// and written opaque), `stride` is the byte pitch of each source row.
bool WriteRawImageToPng(const std::string& path, uint32_t width, uint32_t height,
                        const uint8_t* rgbx, size_t stride) {
  if (!width || !height || !rgbx) {
    return false;
  }

  // Build PNG-filtered scanlines: each row is a filter byte (0 = none) followed
  // by width*4 RGBA bytes.
  std::vector<uint8_t> raw;
  raw.reserve(size_t(height) * (1 + size_t(width) * 4));
  for (uint32_t y = 0; y < height; ++y) {
    raw.push_back(0);
    const uint8_t* row = rgbx + stride * y;
    for (uint32_t x = 0; x < width; ++x) {
      raw.push_back(row[x * 4 + 0]);  // R
      raw.push_back(row[x * 4 + 1]);  // G
      raw.push_back(row[x * 4 + 2]);  // B
      raw.push_back(0xFF);            // A (ignore source X)
    }
  }

  // zlib stream wrapping uncompressed DEFLATE stored blocks.
  std::vector<uint8_t> zlib;
  zlib.push_back(0x78);  // CMF: 32K window, deflate
  zlib.push_back(0x01);  // FLG: no preset dict, fastest
  size_t pos = 0;
  while (pos < raw.size()) {
    size_t block = std::min<size_t>(65535, raw.size() - pos);
    bool last = (pos + block) >= raw.size();
    zlib.push_back(last ? 0x01 : 0x00);  // BFINAL + BTYPE=00 (stored)
    uint16_t len = uint16_t(block);
    uint16_t nlen = uint16_t(~len);
    zlib.push_back(uint8_t(len & 0xFF));
    zlib.push_back(uint8_t((len >> 8) & 0xFF));
    zlib.push_back(uint8_t(nlen & 0xFF));
    zlib.push_back(uint8_t((nlen >> 8) & 0xFF));
    zlib.insert(zlib.end(), raw.begin() + pos, raw.begin() + pos + block);
    pos += block;
  }
  PutBE32(zlib, Adler32(raw.data(), raw.size()));

  std::vector<uint8_t> out;
  const uint8_t sig[8] = {0x89, 'P', 'N', 'G', 0x0D, 0x0A, 0x1A, 0x0A};
  out.insert(out.end(), sig, sig + 8);

  std::vector<uint8_t> ihdr;
  PutBE32(ihdr, width);
  PutBE32(ihdr, height);
  ihdr.push_back(8);  // bit depth
  ihdr.push_back(6);  // color type: RGBA
  ihdr.push_back(0);  // compression
  ihdr.push_back(0);  // filter method
  ihdr.push_back(0);  // interlace
  WriteChunk(out, "IHDR", ihdr);
  WriteChunk(out, "IDAT", zlib);
  WriteChunk(out, "IEND", std::vector<uint8_t>());

  FILE* f = fopen(path.c_str(), "wb");
  if (!f) {
    return false;
  }
  fwrite(out.data(), 1, out.size(), f);
  fclose(f);
  return true;
}

}  // namespace rex::graphics::d3d12
