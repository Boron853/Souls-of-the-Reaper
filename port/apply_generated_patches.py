#!/usr/bin/env python3
"""Re-apply the hand patches to port/generated/default/*.cpp.

ReXGlue codegen rebuilds port/generated from scratch, so the two edits that
codegen cannot emit must be re-applied after every codegen run:

  1. setjmp/longjmp fix (sub_831583B0 / sub_83158680)
  2. main-menu "return to title screen" exit hook (sub_82632E00)

This is the Linux counterpart of apply_generated_patches.ps1 for the
ReXGlue 0.10 codegen output. It is idempotent and fails if a function is
missing or appears more than once.

Usage:
  python3 port/apply_generated_patches.py [--generated-dir DIR]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SETJMP_BODY = """DEFINE_REX_FUNC(sub_831583B0) {
\t// [D3 s9d] Guest setjmp(jmp_buf=r3): host ppc_setjmp plus the guest
\t// callee-saved registers (r1, r13..r31, lr, f14..f31), keyed by jmp_buf.
\t// Hand patch: reapply with port/apply_generated_patches.py after codegen.
\tconst uint32_t buf = ctx.r3.u32;
\td3_jmp_save(ctx, buf);
\tif (ppc_setjmp(buf) != 0)
\t\tctx.r3.u64 = d3_jmp_restore(ctx, buf);
\telse
\t\tctx.r3.u64 = 0;
}"""

LONGJMP_BODY = """DEFINE_REX_FUNC(sub_83158680) {
\t// [D3 s9d] Guest longjmp(jmp_buf=r3, val=r4): stash val and transfer to
\t// the ppc_setjmp in sub_831583B0, which restores the guest registers.
\t// [[noreturn]].
\tconst uint32_t buf = ctx.r3.u32;
\tconst int value = ctx.r4.s32 ? ctx.r4.s32 : 1;
\td3_jmp_regs()[buf].val = static_cast<uint32_t>(value);
\tppc_longjmp(buf, value);
}"""

MAIN_MENU_BODY = """extern "C" void D3RequestGameExit();

DEFINE_REX_FUNC(sub_82632E00) {
\t// [D3 main-menu-exit] Close the game like a PC "Exit" option instead of
\t// returning to the title screen. Hand patch: reapply after codegen.
\tD3RequestGameExit();
}"""

EXIT_DECL = 'extern "C" void D3RequestGameExit();'


def find_function_file(generated_dir: Path, symbol: str) -> Path:
    """Find the generated .cpp containing DEFINE_REX_FUNC(symbol)."""
    marker = f"DEFINE_REX_FUNC({symbol})"
    matches: list[Path] = []
    for candidate in sorted(generated_dir.glob("*_recomp.*.cpp")):
        try:
            if marker in candidate.read_text(encoding="utf-8"):
                matches.append(candidate)
        except OSError:
            continue
    if not matches:
        raise SystemExit(f"ERROR: no generated source contains {marker} in {generated_dir}")
    if len(matches) > 1:
        names = ", ".join(str(p) for p in matches)
        raise SystemExit(f"ERROR: {marker} found in multiple files: {names}")
    return matches[0]


def replace_function(path: Path, symbol: str, body: str, add_guest_include: bool) -> None:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"DEFINE_REX_FUNC\(" + re.escape(symbol) + r"\) \{.*?^\}",
        re.MULTILINE | re.DOTALL,
    )
    matches = pattern.findall(text)
    if len(matches) != 1:
        raise SystemExit(
            f"ERROR: expected one definition of {symbol} in {path.name}, found {len(matches)}"
        )

    # Drop a declaration left by an earlier run; the main-menu body re-adds it.
    text = text.replace(EXIT_DECL + "\n", "").replace(EXIT_DECL + "\r\n", "")
    text = pattern.sub(lambda _match: body, text, count=1)

    if add_guest_include and '#include "guest_jump.h"' not in text:
        text = '#include "guest_jump.h"\n' + text
    path.write_text(text, encoding="utf-8")
    print(f"{symbol}: patched in {path.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_dir = Path(__file__).resolve().parent / "generated" / "default"
    parser.add_argument("--generated-dir", type=Path, default=default_dir)
    args = parser.parse_args()

    generated_dir: Path = args.generated_dir
    if not generated_dir.is_dir():
        raise SystemExit(f"ERROR: generated directory not found: {generated_dir}")

    setjmp_file = find_function_file(generated_dir, "sub_831583B0")
    longjmp_file = find_function_file(generated_dir, "sub_83158680")
    main_menu_file = find_function_file(generated_dir, "sub_82632E00")

    replace_function(setjmp_file, "sub_831583B0", SETJMP_BODY, add_guest_include=True)
    replace_function(longjmp_file, "sub_83158680", LONGJMP_BODY, add_guest_include=True)
    replace_function(main_menu_file, "sub_82632E00", MAIN_MENU_BODY, add_guest_include=False)

    print("\nDone. Rebuild with port/build.sh (Linux) or port/build.ps1 (Windows).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
