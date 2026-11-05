#!/usr/bin/env python3
"""Apply Souls of the Reaper guest fixes by symbol, independent of codegen shard numbers."""
import argparse
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]


def read_source(path):
    """Text of a generated file with "\\n" line endings, whatever the generator wrote."""
    with open(path, encoding="utf-8") as stream:
        return stream.read()


def write_source(path, text):
    """Replace a generated file atomically (so an interrupted run never leaves half a shard),
    with the same LF line endings on every host."""
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "w", encoding="utf-8", newline="") as stream:
        stream.write(text)
    temporary.replace(path)


def patch_generated(directory, title_update=None):
    replacements = {
        "sub_831583B0": (ROOT / "port/title_updates/setjmp.cpp.in").read_text().strip(),
        "sub_83158680": """DEFINE_REX_FUNC(sub_83158680) {
    const uint32_t buf = ctx.r3.u32;
    const int value = ctx.r4.s32 ? ctx.r4.s32 : 1;
    d3_jmp_regs()[buf].val = static_cast<uint32_t>(value);
    ppc_longjmp(buf, value);
}""",
        "sub_82632E00": """extern "C" void D3RequestGameExit();
DEFINE_REX_FUNC(sub_82632E00) {
    D3RequestGameExit();
}""",
    }
    if title_update == "usa":
        relocated = {"sub_831583B0": "sub_83161AD0",
                     "sub_83158680": "sub_83161DA0",
                     "sub_82632E00": "sub_826374E8"}
        replacements = {relocated[symbol]: body.replace(symbol, relocated[symbol]).replace("D3RequestGameExit", "D3RequestTitleUpdateExit")
                        for symbol, body in replacements.items()}
    elif title_update is not None:
        raise ValueError(f"Unsupported title update: {title_update}")
    exit_symbol = "sub_826374E8" if title_update == "usa" else "sub_82632E00"
    edits = {}
    for symbol, replacement in replacements.items():
        pattern = re.compile(r"DEFINE_REX_FUNC\(" + symbol + r"\) \{.*?^\}", re.S | re.M)
        matches = []
        for path in directory.glob("*_recomp.*.cpp"):
            text = edits.get(path)
            if text is None:
                text = read_source(path)
            matches.extend((path, text) for _ in pattern.finditer(text))
        if len(matches) != 1:
            raise ValueError(f"Expected one definition of {symbol}, found {len(matches)}")
        path, text = matches[0]
        # Remove our declaration on repeat runs, then replace the whole body.
        text = text.replace('extern "C" void D3RequestGameExit();\n', '')
        text = text.replace('extern "C" void D3RequestTitleUpdateExit();\n', '')
        text = pattern.sub(lambda _: replacement, text, count=1)
        if symbol != exit_symbol and '#include "guest_jump.h"' not in text:
            text = '#include "guest_jump.h"\n' + text
        edits[path] = text
    # Run the host setjmp in each caller's frame (see D3_GUEST_SETJMP): a
    # longjmp into the returned replacement function corrupts the host stack.
    setjmp_symbol = "sub_83161AD0" if title_update == "usa" else "sub_831583B0"
    call = re.compile(r"\b" + setjmp_symbol + r"\(ctx, base\);")
    uses = 0
    for path in directory.glob("*_recomp.*.cpp"):
        text = edits.get(path) or read_source(path)
        text, count = call.subn("D3_GUEST_SETJMP(ctx);", text)
        if count:
            if '#include "guest_jump.h"' not in text:
                text = '#include "guest_jump.h"\n' + text
            edits[path] = text
        uses += text.count("D3_GUEST_SETJMP(ctx);")
    # One use is the replacement body itself; the rest are rewritten callers.
    sites = uses - 1
    if sites < 1:
        raise ValueError(f"Expected at least one call to {setjmp_symbol}")
    # Validate every anchor before modifying any file.
    for path, text in edits.items():
        if read_source(path) != text:
            write_source(path, text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=pathlib.Path,
                        default=ROOT / "port/generated/base")
    parser.add_argument("--title-update", choices=["usa"])
    args = parser.parse_args()
    try:
        patch_generated(args.directory, args.title_update)
    except ValueError as error:
        parser.exit(1, f"Guest patches failed: {error}\n")


if __name__ == "__main__":
    main()
