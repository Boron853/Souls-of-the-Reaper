#include <xex_patcher.h>
#include <file.h>
#include <xex.h>
#include <cstring>
#include <filesystem>
#include <iostream>
#include <TinySHA1.hpp>

int main(int argc, char** argv) {
    const bool experimental = argc == 5 && std::strcmp(argv[4], "--allow-source-mismatch") == 0;
    if (argc != 4 && !experimental) {
        std::cerr << "Usage: d3-patch BASE.xex PATCH.xexp OUTPUT.xex [--allow-source-mismatch]\n";
        return 1;
    }
    if (std::filesystem::exists(argv[3])) {
        std::cerr << "Output already exists; refusing to overwrite\n";
        return 2;
    }
    const auto base = LoadFile(argv[1]);
    const auto patch = LoadFile(argv[2]);
    auto valid = [](const auto& bytes) {
        if (bytes.size() < sizeof(Xex2Header) || std::memcmp(bytes.data(), "XEX2", 4)) return false;
        const auto* header = reinterpret_cast<const Xex2Header*>(bytes.data());
        if (header->headerSize > bytes.size() || header->headerSize < sizeof(Xex2Header) ||
            header->securityOffset > bytes.size() ||
            bytes.size() - header->securityOffset < sizeof(Xex2SecurityInfo) ||
            header->headerCount > (bytes.size() - sizeof(Xex2Header)) / sizeof(Xex2OptHeader)) return false;
        const auto* options = reinterpret_cast<const Xex2OptHeader*>(header + 1);
        for (unsigned i = 0; i < header->headerCount; ++i) {
            auto key = options[i].key.get();
            if ((key & 255) > 1 && (options[i].offset > bytes.size() ||
                bytes.size() - options[i].offset < ((key & 255) == 255 ? 4 : (key & 255) * 4))) return false;
        }
        return true;
    };
    if (!valid(base) || !valid(patch)) return 4;
    const auto* execution = static_cast<const be<uint32_t>*>(getOptHeaderPtr(base.data(), XEX_HEADER_EXECUTION_INFO));
    const auto* descriptor = static_cast<const Xex2OptDeltaPatchDescriptor*>(getOptHeaderPtr(patch.data(), XEX_HEADER_DELTA_PATCH_DESCRIPTOR));
    if (!execution || !descriptor || reinterpret_cast<const uint8_t*>(descriptor) + sizeof(*descriptor) > patch.data() + patch.size()) return 4;
    const auto* header = reinterpret_cast<const Xex2Header*>(base.data());
    const auto* security = reinterpret_cast<const Xex2SecurityInfo*>(base.data() + header->securityOffset);
    bool version_match = execution[1].get() == descriptor->sourceVersionValue.get();
    // digestSource identifies the source RSA signature, not headerDigest.
    uint8_t signature_digest[20];
    sha1::SHA1 signature_hash;
    signature_hash.processBytes(security->rsaSignature, sizeof(security->rsaSignature));
    signature_hash.finalize(signature_digest);
    bool digest_match = std::memcmp(signature_digest, descriptor->digestSource, 20) == 0;
    std::cout << std::hex << "Base version: 0x" << execution[1].get()
              << "\nRequired source version: 0x" << descriptor->sourceVersionValue.get()
              << "\nTarget version: 0x" << descriptor->targetVersionValue.get()
              << "\nSource signature digest match: " << (digest_match ? "yes" : "no") << '\n';
    if ((!version_match || !digest_match) && !experimental) {
        std::cerr << "PatchIncompatible: source version/signature digest mismatch; no output written\n";
        return 3;
    }
    if ((!version_match || !digest_match) && experimental)
        std::cerr << "EXPERIMENTAL: applying delta against a mismatched source; output is unverified\n";
    auto result = XexPatcher::apply(argv[1], argv[2], argv[3]);
    const char* names[] = {"Success", "FileOpenFailed", "FileWriteFailed",
        "XexFileUnsupported", "XexFileInvalid", "PatchFileInvalid",
        "PatchIncompatible", "PatchFailed", "PatchUnsupported"};
    std::cout << "Patch result: " << names[static_cast<unsigned>(result)] << '\n';
    return result == XexPatcher::Result::Success ? 0 : 3;
}
