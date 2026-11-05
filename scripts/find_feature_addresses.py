#!/usr/bin/env python3
"""Generate a PC-feature version profile for a new game executable.

Takes a reference executable whose profile (port/src/features/versions/<id>.json)
is already verified and a target Default.xex, finds each profile function and
data address in the target by masked PPC instruction patterns, and writes a
candidate profile for the target. The result is only as good as its reported
confidence: review anything that is not "unique", and confirm with a build and
an in-game check before relying on it.

Matching: every instruction word has its relocatable fields masked (branch
targets and D/DS-form displacements and immediates, except `li` constants and the
ld/ldu/lwa, std/stdu sub-opcode), then the reference function body is searched
for in the target image. Functions with no unique body match are resolved from a
matched caller's call site; data addresses are re-derived from the lis/addi (or
lis/load) pair, or from the return address of a call to a profile function.

Needs the d3-image tool from scripts/d3-patch. build_client.py's patcher step
configures tools/d3-patch but builds only d3-patch; build d3-image there with
`cmake --build tools/d3-patch --target d3-image`.
"""
import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import struct
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
VERSIONS = ROOT / "port/src/features/versions"
BLR = 0x4E800020
MAX_BODY_WORDS = 256
MIN_BODY_WORDS = 8
CONTEXT_WORDS = 16
PAIR_REACH = 16
WINDOW_WORDS = 16
LOCALITY_NEAR = 0x2000
LOCALITY_FAR = 0x8000


class ProfileError(Exception):
    pass


def mask_word(word):
    """Zero the fields that change when code or data moves.

    port/src/features/pc_features.cpp MaskWord applies the same rules to the
    runtime check; change both together.
    """
    op = word >> 26
    if op == 18:                    # b/bl/ba: LI
        return word & ~0x03FFFFFC
    if op == 16:                    # bc: BD
        return word & ~0x0000FFFC
    if op == 14 and not (word >> 16) & 31:
        return word                 # li rD,SIMM: a constant, never half of an address
    if op in (58, 62):              # DS-form ld/ldu/lwa, std/stdu: keep the 2-bit sub-opcode
        return word & ~0xFFFC
    if op in (7, 8, 10, 11, 12, 13, 14, 15) or 24 <= op <= 29 or 32 <= op <= 55:
        return word & ~0xFFFF       # D-form immediates and displacements
    return word


# Extended opcodes (bits 1-10) of primary opcode 31, grouped by which GPR they write.
X_WRITES_RA = {24, 26, 27, 28, 58, 60, 124, 284, 316, 412, 444, 476, 536, 539, 792, 794, 824, 922, 954, 986}
X_WRITES_RT_RA = {53, 55, 119, 311, 373, 375}            # update-form integer loads
X_WRITES_ONLY_RA = {181, 183, 247, 439, 567, 631, 695, 759}  # update-form stores, FP update loads
X_WRITES_NONE = {0, 4, 32, 54, 68, 86, 144, 149, 150, 151, 199, 214, 215, 231, 246, 278, 407, 467,
                 535, 598, 599, 662, 663, 727, 854, 918, 982, 983, 1014}
VOLATILE_GPRS = {0} | set(range(3, 13))


def writes_gpr(word, reg):
    """Whether an instruction can change GPR `reg`; errs towards yes."""
    op = word >> 26
    rt, ra = (word >> 21) & 31, (word >> 16) & 31
    if op in (16, 18, 19):          # branches; a call (LK=1) clobbers the volatile registers
        return bool(word & 1) and reg in VOLATILE_GPRS
    if op in (7, 8, 12, 13, 14, 15, 32, 34, 40, 42):
        return rt == reg
    if op in (33, 35, 41, 43):      # lwzu lbzu lhzu lhau
        return reg in (rt, ra)
    if op == 46:                    # lmw rD..r31
        return reg >= rt
    if op in (20, 21, 23, 24, 25, 26, 27, 28, 29, 30, 37, 39, 45, 49, 51, 53, 55):
        return ra == reg            # rotates/logical immediates write RA; update stores/FP loads
    if op == 58:                    # ld, ldu, lwa
        return rt == reg or (word & 3 == 1 and ra == reg)
    if op == 62:                    # std, stdu
        return word & 3 == 1 and ra == reg
    if op == 31:
        xo = (word >> 1) & 0x3FF
        if xo in X_WRITES_RA or (word >> 2) & 0x1FF == 413:   # ... and sradi
            return ra == reg
        if xo in X_WRITES_RT_RA:
            return reg in (rt, ra)
        if xo in X_WRITES_ONLY_RA:
            return ra == reg
        if xo in X_WRITES_NONE:
            return False
        return rt == reg
    return False


class Image:
    def __init__(self, path, base):
        data = pathlib.Path(path).read_bytes()
        if len(data) % 4:
            data = data[:len(data) - len(data) % 4]
        self.base = base
        self.words = struct.unpack(f">{len(data) // 4}I", data)
        self.masked = struct.pack(f">{len(self.words)}I", *map(mask_word, self.words))

    def contains(self, address):
        return address % 4 == 0 and 0 <= (address - self.base) // 4 < len(self.words)

    def index(self, address):
        if address % 4:
            raise ProfileError(f"address 0x{address:08X} is not word-aligned")
        if not self.contains(address):
            raise ProfileError(f"address 0x{address:08X} is outside the image "
                               f"(0x{self.base:08X}-0x{self.address(len(self.words)):08X})")
        return (address - self.base) // 4

    def address(self, index):
        return self.base + index * 4

    def body_length(self, index):
        """Words from `index` through the first blr, capped."""
        for n in range(min(MAX_BODY_WORDS, len(self.words) - index)):
            if self.words[index + n] == BLR:
                return n + 1
        return min(MAX_BODY_WORDS, len(self.words) - index)

    def find_all(self, sequence_words):
        needle = struct.pack(f">{len(sequence_words)}I", *sequence_words)
        hits, start = [], 0
        while True:
            pos = self.masked.find(needle, start)
            if pos < 0:
                return hits
            if pos % 4 == 0:
                hits.append(pos // 4)
            start = pos + 1


def load_image(d3_image, xex, scratch, name):
    out = scratch / f"{name}.bin"
    result = subprocess.run([str(d3_image), str(xex), str(out)], capture_output=True, text=True)
    if result.returncode:
        raise ProfileError(f"d3-image failed for {xex}: {result.stderr.strip() or result.stdout.strip()}")
    fields = dict(part.split("=") for part in result.stdout.split())
    return Image(out, int(fields["base"], 16))


# Runtime-check window, at most the 12 words load_version.cmake allows.
SIGNATURE_WORDS = 12


def signature(image, address):
    """Masked words of the fixed window at a function, as stored in profiles and checked at runtime.

    The window does not stop at the first blr, which is not always the end of a
    function (selector_count returns from three places). Functions shorter than
    the window (one-instruction thunks, `li; b` stub-table entries, two-word
    accessors) are followed by padding and adjacent code, which the window also
    covers: their own words are rarely distinctive (string_destroy's `b` and
    padding word match 12,671 places), and the check is only ever made at this
    exact address of the profile's executable.
    """
    start = image.index(address)
    return [f"{mask_word(w):08X}" for w in image.words[start:start + SIGNATURE_WORDS]]


def masked_sequence(image, start, count):
    return [mask_word(w) for w in image.words[start:start + count]]


def match_function(ref, tgt, address):
    """Return (method, target_index) for a reference function, or (reason, candidates)."""
    start = ref.index(address)
    body = ref.body_length(start)
    if body < MIN_BODY_WORDS:
        return "too-short", []
    attempts = (("body", start, body, 0),
                ("body+before", start - CONTEXT_WORDS, body + CONTEXT_WORDS, CONTEXT_WORDS),
                ("body+after", start, body + CONTEXT_WORDS, 0))
    candidates = []
    for method, first, count, skip in attempts:
        if first < 0 or first + count > len(ref.words):
            continue
        hits = [h + skip for h in tgt.find_all(masked_sequence(ref, first, count))]
        if len(hits) == 1:
            return method, hits[0]
        candidates = candidates or hits
    return ("ambiguous" if candidates else "unmatched"), candidates


def bl_target(image, index):
    """Target of a `bl` at word `index`, or None (not a bl, or index outside the image)."""
    if not 0 <= index < len(image.words):
        return None
    word = image.words[index]
    if word >> 26 != 18 or not word & 1 or word & 2:
        return None
    offset = word & 0x03FFFFFC
    if offset & 0x02000000:
        offset -= 0x04000000
    return image.address(index) + offset


def resolve_from_caller(ref, tgt, profile_ref, matched, name, address):
    """Resolve `address` from a matched caller's `bl` at the same word offset."""
    for other, entry in profile_ref["functions"].items():
        if other == name or other not in matched:
            continue
        start = ref.index(int(entry["address"], 16))
        for k in range(ref.body_length(start)):
            if bl_target(ref, start + k) == address:
                target = bl_target(tgt, matched[other][1] + k)
                if target is not None and tgt.contains(target):
                    return f"call-site in {other}+{k * 4:#x}", target
    return None


PAIR_LOW_OPS = (14, 32, 34, 36, 38, 40, 42, 44)    # addi lwz lbz stw stb lhz lha sth


def lis_pair_offsets(image, region_start, length, value):
    """Yield (offset, kind) of lis/{addi,load} pairs producing `value` inside a region.

    The scan for the low half stops once the lis register is overwritten.
    """
    for k in range(length):
        word = image.words[region_start + k]
        if word >> 26 != 15:        # addis (lis when RA=0)
            continue
        if (word >> 16) & 31:
            continue
        reg, high = (word >> 21) & 31, word & 0xFFFF
        for j in range(1, PAIR_REACH):
            if region_start + k + j >= len(image.words):
                break
            nxt = image.words[region_start + k + j]
            if (nxt >> 16) & 31 == reg and nxt >> 26 in PAIR_LOW_OPS:
                low = nxt & 0xFFFF
                if low & 0x8000:
                    low -= 0x10000
                if ((high << 16) + low) & 0xFFFFFFFF == value:
                    yield k, (k + j, nxt >> 26)
            if writes_gpr(nxt, reg):
                break


def derive_pair(tgt, region_start, k_hi, k_lo, op):
    if not (0 <= region_start + k_hi < len(tgt.words) and 0 <= region_start + k_lo < len(tgt.words)):
        return None
    hi_word, lo_word = tgt.words[region_start + k_hi], tgt.words[region_start + k_lo]
    if hi_word >> 26 != 15 or lo_word >> 26 != op or (lo_word >> 16) & 31 != (hi_word >> 21) & 31:
        return None
    low = lo_word & 0xFFFF
    if low & 0x8000:
        low -= 0x10000
    return (((hi_word & 0xFFFF) << 16) + low) & 0xFFFFFFFF


def resolve_data(ref, tgt, profile_ref, matched, resolved_returns, value):
    """Re-derive a data address from a pair in a matched function or caller window."""
    regions = [(name, ref.index(int(profile_ref["functions"][name]["address"], 16)), idx, ref.body_length(
        ref.index(int(profile_ref["functions"][name]["address"], 16)))) for name, (_, idx) in matched.items()]
    regions += [(f"call-window {label}", ref_index - WINDOW_WORDS, tgt_index - WINDOW_WORDS, WINDOW_WORDS)
                for label, (ref_index, tgt_index) in resolved_returns.items()]
    for label, ref_start, tgt_start, length in regions:
        if ref_start < 0 or tgt_start < 0:
            continue
        for k_hi, (k_lo, op) in lis_pair_offsets(ref, ref_start, length, value):
            derived = derive_pair(tgt, tgt_start, k_hi, k_lo, op)
            if derived is not None:
                return f"{label}+{k_hi * 4:#x}", derived
    return None


def resolve_return(ref, tgt, address, callee_targets, anchors):
    """Return address of a call to a matched profile function.

    The window around the `bl` at address-4 is searched in the target, widest
    first. Only hits that call the callee's matched target address count, so a
    short window is enough when it is unique under that filter. A data address
    that cannot follow a call in the reference image is not resolved this way.
    """
    if not ref.contains(address - 4):
        return None
    call = ref.index(address - 4)
    callee = bl_target(ref, call)
    if callee not in callee_targets:
        return None
    expected = callee_targets[callee]
    for before, after in ((WINDOW_WORDS, WINDOW_WORDS), (12, 4), (8, 2), (6, 0), (4, 0)):
        if call - before < 0:
            continue
        hits = [h + before for h in tgt.find_all(masked_sequence(ref, call - before, before + 1 + after))
                if bl_target(tgt, h + before) == expected]
        if len(hits) == 1:
            return call + 1, hits[0] + 1, (before, after, False)
        if hits:
            # Several identical call sequences: code keeps its order between
            # builds, so prefer the site whose shift matches the nearest matched
            # function's shift, and only accept a clear winner.
            site_address = ref.address(call)
            nearest = min(anchors, key=lambda pair: abs(pair[0] - site_address))
            shift = nearest[1] - nearest[0]
            ranked = sorted((abs((tgt.address(site) - site_address) - shift), site) for site in hits)
            if ranked[0][0] <= LOCALITY_NEAR and (len(ranked) == 1 or ranked[1][0] >= LOCALITY_FAR):
                return call + 1, ranked[0][1] + 1, (before, after, True)
            return None
    return None


def sign_profile(profile_id, xex, d3_image):
    """Add runtime-check signatures to an existing profile from its executable."""
    path = VERSIONS / f"{profile_id}.json"
    profile = json.loads(path.read_text())
    digest = hashlib.sha256(pathlib.Path(xex).read_bytes()).hexdigest()
    if digest != profile["executable_sha256"]:
        raise ProfileError(f"{xex} does not match profile '{profile_id}' (sha256 {digest[:12]}...)")
    with tempfile.TemporaryDirectory() as scratch:
        image = load_image(d3_image, xex, pathlib.Path(scratch), "image")
        for entry in profile["functions"].values():
            entry["signature"] = signature(image, int(entry["address"], 16))
    path.write_text(json.dumps(profile, indent=2) + "\n")
    return path


def generate(reference_id, reference_xex, target_xex, d3_image):
    profile_ref = json.loads((VERSIONS / f"{reference_id}.json").read_text())
    report = {"functions": {}, "data": {}}
    with tempfile.TemporaryDirectory() as scratch:
        scratch = pathlib.Path(scratch)
        ref = load_image(d3_image, reference_xex, scratch, "reference")
        tgt = load_image(d3_image, target_xex, scratch, "target")
        if ref.base != tgt.base:
            raise ProfileError("Images load at different bases; this generator assumes the same base")
        digest = hashlib.sha256(pathlib.Path(reference_xex).read_bytes()).hexdigest()
        if digest != profile_ref["executable_sha256"]:
            raise ProfileError(f"Reference executable does not match profile '{reference_id}' "
                               f"(sha256 {digest[:12]}...)")
        matched = {}
        pending = {}
        for name, entry in profile_ref["functions"].items():
            address = int(entry["address"], 16)
            method, found = match_function(ref, tgt, address)
            if method in ("body", "body+before", "body+after"):
                matched[name] = (method, found)
                report["functions"][name] = {"address": tgt.address(found), "method": method}
            else:
                pending[name] = (method, found, address)
        for name, (method, found, address) in pending.items():
            via = resolve_from_caller(ref, tgt, profile_ref, matched, name, address)
            if via:
                report["functions"][name] = {"address": via[1], "method": via[0], "weak": True}
            else:
                report["functions"][name] = {"address": None, "method": method, "candidates": len(found)}
        callee_targets = {int(profile_ref["functions"][n]["address"], 16): tgt.address(found)
                          for n, (_, found) in matched.items()}
        # Pairs are searched in function bodies matched by signature only.
        matched_addresses = {n: (m, i) for n, (m, i) in matched.items()}
        resolved_returns = {}
        for name, entry in profile_ref["data"].items():
            value = int(entry["address"], 16)
            via = resolve_data(ref, tgt, profile_ref, matched_addresses, resolved_returns, value)
            if via is None:
                pair = resolve_return(ref, tgt, value, callee_targets, sorted(callee_targets.items()))
                if pair:
                    resolved_returns[name] = pair[:2]
                    via = (f"return address, window {pair[2][0]}+{pair[2][1]} words"
                           + (", chosen by code locality" if pair[2][2] else ""), tgt.address(pair[1]))
            report["data"][name] = {"address": via[1] if via else None, "method": via[0] if via else "unresolved"}
        # Second pass: pairs that live in a call window discovered above.
        for name, entry in profile_ref["data"].items():
            if report["data"][name]["address"] is None:
                value = int(entry["address"], 16)
                via = resolve_data(ref, tgt, profile_ref, matched_addresses, resolved_returns, value)
                if via:
                    report["data"][name] = {"address": via[1], "method": via[0]}
        for entry in report["functions"].values():
            if entry["address"] is not None:
                entry["signature"] = signature(tgt, entry["address"])
    return profile_ref, report, hashlib.sha256(pathlib.Path(target_xex).read_bytes()).hexdigest()


def build_profile(profile_ref, report, new_id, target_digest):
    profile = {"id": new_id, "description": f"Generated from '{profile_ref['id']}' by find_feature_addresses.py; review before use",
               "executable_sha256": target_digest, "functions": {}, "data": {}, "layout": profile_ref["layout"]}
    for name, entry in profile_ref["functions"].items():
        found = report["functions"][name]["address"]
        profile["functions"][name] = {"address": f"{found:08X}" if found is not None else None, "hook": entry["hook"]}
        if "signature" in report["functions"][name]:
            profile["functions"][name]["signature"] = report["functions"][name]["signature"]
    for name in profile_ref["data"]:
        found = report["data"][name]["address"]
        profile["data"][name] = {"address": f"{found:08X}" if found is not None else None}
    return profile


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reference", help="Existing profile id to match from (e.g. base, update-usa)")
    parser.add_argument("--reference-xex", type=pathlib.Path, help="Executable that profile describes")
    parser.add_argument("--target-xex", type=pathlib.Path, help="New executable to find addresses in")
    parser.add_argument("--id", help="Id for the new profile (file name without .json)")
    parser.add_argument("--sign", metavar="PROFILE", help="Instead of generating, (re)write the runtime-check "
                        "signatures of an existing profile from --target-xex")
    parser.add_argument("--output", type=pathlib.Path, help="Profile path (default: versions/<id>.json)")
    parser.add_argument("--d3-image", type=pathlib.Path,
                        default=ROOT / "tools/d3-patch" / ("d3-image.exe" if os.name == "nt" else "d3-image"))
    parser.add_argument("--allow-partial", action="store_true", help="Write the profile even if entries are unresolved (null addresses)")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing output file")
    args = parser.parse_args()
    if args.sign and not args.target_xex:
        parser.error("--sign needs --target-xex (the executable the profile describes)")
    for name in () if args.sign else ("reference", "reference_xex", "target_xex", "id"):
        if not getattr(args, name):
            parser.error(f"--{name.replace('_', '-')} is required when generating a profile")
    if not args.d3_image.is_file():
        print(f"find_feature_addresses: d3-image not found at {args.d3_image}; pass --d3-image, or build it "
              "with `cmake --build tools/d3-patch --target d3-image` once build_client.py has configured "
              "tools/d3-patch", file=sys.stderr)
        return 1
    if args.sign:
        try:
            print(f"Wrote signatures to {sign_profile(args.sign, args.target_xex, args.d3_image)}")
            return 0
        except (ProfileError, OSError) as error:
            print(f"find_feature_addresses: {error}", file=sys.stderr)
            return 1
    output = args.output or VERSIONS / f"{args.id}.json"
    try:
        if output.exists() and not args.force:
            raise ProfileError(f"{output} exists; use --force to overwrite")
        profile_ref, report, digest = generate(args.reference, args.reference_xex, args.target_xex, args.d3_image)
    except (ProfileError, OSError) as error:
        print(f"find_feature_addresses: {error}", file=sys.stderr)
        return 1
    unresolved = [f"function {n}" for n, e in report["functions"].items() if e["address"] is None]
    unresolved += [f"data {n}" for n, e in report["data"].items() if e["address"] is None]
    weak = [n for n, e in report["functions"].items() if e.get("weak")]
    for section in ("functions", "data"):
        for name, entry in report[section].items():
            shown = f"{entry['address']:08X}" if entry["address"] is not None else "--------"
            print(f"{section[:-1]:8} {name:28} {shown}  {entry['method']}"
                  + (f" ({entry['candidates']} candidates)" if entry.get("candidates") else "")
                  + ("  [weak: single call site]" if entry.get("weak") else ""))
    if unresolved and not args.allow_partial:
        print(f"\nUnresolved: {', '.join(unresolved)}. Nothing written (use --allow-partial to keep a partial profile).",
              file=sys.stderr)
        return 2
    profile = build_profile(profile_ref, report, args.id, digest)
    output.write_text(json.dumps(profile, indent=2) + "\n")
    print(f"\nWrote {output}" + (f"; unresolved: {', '.join(unresolved)}" if unresolved else "")
          + (f"; weak matches to review: {', '.join(weak)}" if weak else ""))
    return 2 if unresolved else 0


if __name__ == "__main__":
    sys.exit(main())
