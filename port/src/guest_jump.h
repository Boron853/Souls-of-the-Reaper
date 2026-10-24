#pragma once
#include <cstdint>
#include <unordered_map>
// Guest setjmp/longjmp state (see apply_generated_patches.ps1). It must be
// shared because codegen may put the two functions in different files.

struct D3JmpState {
  uint64_t r1;
  uint64_t r13, r14, r15, r16, r17, r18, r19, r20, r21, r22, r23, r24, r25, r26,
      r27, r28, r29, r30, r31;
  uint64_t lr;
  uint64_t f14, f15, f16, f17, f18, f19, f20, f21, f22, f23, f24, f25, f26, f27,
      f28, f29, f30, f31;
  uint32_t val;
};
inline std::unordered_map<uint32_t, D3JmpState> &d3_jmp_regs() {
  static thread_local std::unordered_map<uint32_t, D3JmpState> m;
  return m;
}

template <typename Context> void d3_jmp_save(Context &ctx, uint32_t buf) {
  D3JmpState &s = d3_jmp_regs()[buf];
  s.r1 = ctx.r1.u64;
  s.r13 = ctx.r13.u64; s.r14 = ctx.r14.u64; s.r15 = ctx.r15.u64; s.r16 = ctx.r16.u64;
  s.r17 = ctx.r17.u64; s.r18 = ctx.r18.u64; s.r19 = ctx.r19.u64; s.r20 = ctx.r20.u64;
  s.r21 = ctx.r21.u64; s.r22 = ctx.r22.u64; s.r23 = ctx.r23.u64; s.r24 = ctx.r24.u64;
  s.r25 = ctx.r25.u64; s.r26 = ctx.r26.u64; s.r27 = ctx.r27.u64; s.r28 = ctx.r28.u64;
  s.r29 = ctx.r29.u64; s.r30 = ctx.r30.u64; s.r31 = ctx.r31.u64;
  s.lr = ctx.lr;
  s.f14 = ctx.f14.u64; s.f15 = ctx.f15.u64; s.f16 = ctx.f16.u64; s.f17 = ctx.f17.u64;
  s.f18 = ctx.f18.u64; s.f19 = ctx.f19.u64; s.f20 = ctx.f20.u64; s.f21 = ctx.f21.u64;
  s.f22 = ctx.f22.u64; s.f23 = ctx.f23.u64; s.f24 = ctx.f24.u64; s.f25 = ctx.f25.u64;
  s.f26 = ctx.f26.u64; s.f27 = ctx.f27.u64; s.f28 = ctx.f28.u64; s.f29 = ctx.f29.u64;
  s.f30 = ctx.f30.u64; s.f31 = ctx.f31.u64;
}

// Restores the registers saved by d3_jmp_save and returns the longjmp value.
template <typename Context> uint32_t d3_jmp_restore(Context &ctx, uint32_t buf) {
  const D3JmpState &r = d3_jmp_regs()[buf];
  ctx.r1.u64 = r.r1;
  ctx.r13.u64 = r.r13; ctx.r14.u64 = r.r14; ctx.r15.u64 = r.r15; ctx.r16.u64 = r.r16;
  ctx.r17.u64 = r.r17; ctx.r18.u64 = r.r18; ctx.r19.u64 = r.r19; ctx.r20.u64 = r.r20;
  ctx.r21.u64 = r.r21; ctx.r22.u64 = r.r22; ctx.r23.u64 = r.r23; ctx.r24.u64 = r.r24;
  ctx.r25.u64 = r.r25; ctx.r26.u64 = r.r26; ctx.r27.u64 = r.r27; ctx.r28.u64 = r.r28;
  ctx.r29.u64 = r.r29; ctx.r30.u64 = r.r30; ctx.r31.u64 = r.r31;
  ctx.lr = r.lr;
  ctx.f14.u64 = r.f14; ctx.f15.u64 = r.f15; ctx.f16.u64 = r.f16; ctx.f17.u64 = r.f17;
  ctx.f18.u64 = r.f18; ctx.f19.u64 = r.f19; ctx.f20.u64 = r.f20; ctx.f21.u64 = r.f21;
  ctx.f22.u64 = r.f22; ctx.f23.u64 = r.f23; ctx.f24.u64 = r.f24; ctx.f25.u64 = r.f25;
  ctx.f26.u64 = r.f26; ctx.f27.u64 = r.f27; ctx.f28.u64 = r.f28; ctx.f29.u64 = r.f29;
  ctx.f30.u64 = r.f30; ctx.f31.u64 = r.f31;
  return r.val;
}
