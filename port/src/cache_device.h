// Synthetic FATX cache device for Diablo III ("A2" cache volume).
//
// Diablo mounts cache:\ as a FATX volume by reading the raw device
// \Device\Harddisk0\Partition0 and looking for a "Josh" superblock at
// offset 0x800. The SDK's NullDevice returns zeros, causing validation to
// fail; the game then tries to format FATX (no driver) and deadlocks via
// IoDismountVolume. This device serves the synthetic "Josh" superblock,
// accepts writes (formatting), and reports the volume geometry that the
// FATX mount validation requires:
//   SectorsPerAllocationUnit(128) * BytesPerSector(512) == 0x10000

#pragma once

#include <cstring>
#include <memory>
#include <string>
#include <vector>

#include <rex/filesystem/device.h>
#include <rex/filesystem/entry.h>
#include <rex/filesystem/file.h>
#include <rex/string.h>

namespace d3 {

using rex::X_STATUS;

class CacheFile : public rex::filesystem::File {
 public:
  CacheFile(uint32_t access, rex::filesystem::Entry* entry, bool is_partition0)
      : File(access, entry), is_partition0_(is_partition0) {}

  void Destroy() override { delete this; }

  X_STATUS ReadSync(std::span<uint8_t> buffer, size_t byte_offset,
                    size_t* out_bytes_read) override {
    std::memset(buffer.data(), 0, buffer.size());
    if (is_partition0_ && byte_offset == 0x800 && buffer.size() >= 4) {
      // magic "Josh"
      buffer[0] = 0x4A;
      buffer[1] = 0x6F;
      buffer[2] = 0x73;
      buffer[3] = 0x68;
      // version = 1 at +628 (big-endian u32)
      if (buffer.size() > 631) {
        buffer[628] = 0x00;
        buffer[629] = 0x00;
        buffer[630] = 0x00;
        buffer[631] = 0x01;
      }
    }
    if (out_bytes_read) {
      *out_bytes_read = buffer.size();
    }
    return X_STATUS_SUCCESS;
  }

  X_STATUS WriteSync(std::span<const uint8_t> buffer, size_t,
                     size_t* out_bytes_written) override {
    // Accept and discard (game writes boot sector + FAT during format).
    if (out_bytes_written) {
      *out_bytes_written = buffer.size();
    }
    return X_STATUS_SUCCESS;
  }

  X_STATUS SetLength(size_t) override { return X_STATUS_SUCCESS; }

 private:
  bool is_partition0_;
};

class CacheEntry : public rex::filesystem::Entry {
 public:
  CacheEntry(rex::filesystem::Device* device, rex::filesystem::Entry* parent,
             const std::string& path)
      : Entry(device, parent, path) {
    attributes_ = rex::filesystem::kFileAttributeNormal;
    // Non-zero size so size queries don't cache 0.
    size_ = 0x40000000ull;
    allocation_size_ = size_;
    is_partition0_ = path.find("artition0") != std::string::npos;
  }

  X_STATUS Open(uint32_t desired_access,
                rex::filesystem::File** out_file) override {
    *out_file = new CacheFile(desired_access, this, is_partition0_);
    return X_STATUS_SUCCESS;
  }

  // Children live in Entry::children_ so VFS::OpenFile can resolve them
  // (resolves parent, then calls GetChild).
  void AddChild(std::unique_ptr<rex::filesystem::Entry> child) {
    children_.push_back(std::move(child));
  }

  bool can_map() const override { return false; }

 private:
  bool is_partition0_ = false;
};

class CacheDevice : public rex::filesystem::Device {
 public:
  explicit CacheDevice(const std::string& mount_path) : Device(mount_path) {}

  bool Initialize() override {
    root_ = std::make_unique<CacheEntry>(this, nullptr, "");
    for (const char* p : {"\\Partition0", "\\Cache0", "\\Cache1"}) {
      root_->AddChild(std::make_unique<CacheEntry>(this, root_.get(), p));
    }
    return true;
  }

  void Dump(rex::string::StringBuffer*) override {}

  rex::filesystem::Entry* ResolvePath(const std::string_view path) override {
    if (path.empty()) {
      return root_.get();
    }
    return root_->ResolvePath(path);
  }

  const std::string& name() const override { return name_; }
  uint32_t attributes() const override { return 0; }
  uint32_t component_name_max_length() const override { return 255; }

  // FATX mount validation (sub_82D8C5D0) requires
  // SectorsPerAllocationUnit(128) * BytesPerSector(512) == 0x10000.
  uint32_t total_allocation_units() const override { return 0x10000; }
  uint32_t available_allocation_units() const override { return 0x10000; }
  uint32_t sectors_per_allocation_unit() const override { return 128; }
  uint32_t bytes_per_sector() const override { return 512; }

  bool is_read_only() const override { return false; }

 private:
  std::string name_ = "CacheDevice";
  std::unique_ptr<CacheEntry> root_;
};

}  // namespace d3
