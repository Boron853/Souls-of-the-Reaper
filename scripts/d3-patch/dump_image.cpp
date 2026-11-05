// d3-image: writes the decrypted, decompressed PPC image of an XEX so address
// tooling (scripts/find_feature_addresses.py) can read guest code.
//
// Usage: d3-image Default.xex OUTPUT.bin
// Prints "base=0xXXXXXXXX size=N" for the image; OUTPUT.bin holds `size` bytes
// that start at guest address `base`.
#include <file.h>
#include <image.h>
#include <cinttypes>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>

int main(int argc, char** argv) {
    if (argc != 3) {
        std::cerr << "Usage: d3-image BASE.xex OUTPUT.bin\n";
        return 1;
    }
    if (std::filesystem::exists(argv[2])) {
        std::cerr << "Output already exists; refusing to overwrite\n";
        return 2;
    }
    const auto xex = LoadFile(argv[1]);
    if (xex.empty()) {
        std::cerr << "Cannot read " << argv[1] << "\n";
        return 3;
    }
    const Image image = Image::ParseImage(xex.data(), xex.size());
    if (!image.data || !image.size) {
        std::cerr << "Not a loadable XEX image\n";
        return 4;
    }
    std::ofstream out(argv[2], std::ios::binary);
    out.write(reinterpret_cast<const char*>(image.data.get()), image.size);
    if (!out) {
        std::cerr << "Failed to write " << argv[2] << "\n";
        return 5;
    }
    std::printf("base=0x%08" PRIx64 " size=%u\n", static_cast<uint64_t>(image.base), image.size);
    return 0;
}
