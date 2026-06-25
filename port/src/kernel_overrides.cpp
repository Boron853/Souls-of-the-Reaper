// Game-specific kernel export overrides.
// Pattern: REX_HOOK_RAW defines a strong symbol; the linker resolves the
// recompiled code's call here instead of the runtime import lib.

#include <rex/hook.h>

// IoDismountVolume: SDK stub doesn't set r3; cache mount validation reads
// garbage and deadlocks. Diablo requires STATUS_SUCCESS here.
REX_HOOK_RAW(__imp__IoDismountVolume) {
  (void)base;
  ctx.r3.u64 = 0;  // X_STATUS_SUCCESS
}

// XeKeysConsoleSignatureVerification: Josh superblock signature bypass.
// Diablo's validator (sub_82D8BF80) accepts the signature only if r3 != 0
// AND *out != 0. The SDK stub returns 0 and doesn't write *out, so the cache
// device is rejected and the game falls through to the FATX format path.
// Args: r3=hash, r4=signature, r5=out (result, big-endian u32).
REX_HOOK_RAW(__imp__XeKeysConsoleSignatureVerification) {
  if (ctx.r5.u32) {
    uint8_t* out = base + ctx.r5.u32;
    out[0] = 0;
    out[1] = 0;
    out[2] = 0;
    out[3] = 1;
  }
  ctx.r3.u64 = 1;  // signature valid (nonzero)
}
