#!/usr/bin/env python3
"""Extract the Diablo III Xbox 360 disc data from an ISO on Linux.

Linux counterpart of setup.ps1's extraction step (which uses extract-xiso on
Windows). Reads the XDVDFS filesystem directly, so no external tools are
needed, and lays the files out the way port/diablo3_manifest.toml expects:

    game/default.xex       the game executable (ReXGlue decrypts it itself)
    game/CPKs/*.cpk        all CPK archives from the disc
    game/CommonTOC.dat     if the disc has one

Usage:
  python3 port/extract_iso.py path/to/diablo.iso
  python3 port/extract_iso.py path/to/diablo.iso --out /path/to/game --force

Re-running is cheap: files that already exist with the right size are skipped
unless --force is given. The ISO can also be a .xiso.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
from pathlib import Path

SECTOR = 2048
MAGIC = b"MICROSOFT*XBOX*MEDIA"

# Partition bases seen in Xbox/Xbox 360 images (same list as the MW2 tooling).
BASE_CANDIDATES = (
    0x0,
    0xFD90000,
    0x2080000,
    0x18300000,
    0x18310000,
)

LANGUAGES = {
    "enUS": ("English", 1, 103),
    "enGB": ("English (UK)", 1, 35),
    "esES": ("Spanish", 5, 31),
    "esMX": ("Spanish (LatAm)", 5, 71),
    "frFR": ("French", 4, 34),
    "deDE": ("German", 3, 24),
    "itIT": ("Italian", 6, 50),
    "ptBR": ("Portuguese", 9, 13),
    "ptPT": ("Portuguese (Portugal)", 9, 84),
    "ruRU": ("Russian", 12, 88),
    "plPL": ("Polish", 11, 82),
    "frCA": ("French (Canada)", 4, 16),
    "jaJP": ("Japanese", 2, 53),
    "koKR": ("Korean", 7, 56),
    "zhCN": ("Chinese (Simplified)", 8, 20),
    "zhTW": ("Chinese (Traditional)", 8, 101),
    "trTR": ("Turkish", 14, 99),
    "enSG": ("English (SG)", 1, 91),
}


class XDvdFs:
    def __init__(self, path: Path):
        self.f = open(path, "rb")
        self.base = self._find_base()
        self.f.seek(self.base + 32 * SECTOR)
        vd = self.f.read(SECTOR)
        if vd[:20] != MAGIC or vd[0x7EC:0x800] != MAGIC:
            raise RuntimeError("not an XDVDFS image (bad volume descriptor)")
        self.root_sector, self.root_size = struct.unpack_from("<II", vd, 0x14)

    def _find_base(self) -> int:
        for off in BASE_CANDIDATES:
            self.f.seek(off + 32 * SECTOR)
            if self.f.read(20) == MAGIC:
                return off
        raise RuntimeError("XDVDFS volume descriptor not found; is this an Xbox 360 ISO?")

    def _read(self, sector: int, size: int) -> bytes:
        self.f.seek(self.base + sector * SECTOR)
        data = self.f.read(size)
        if len(data) != size:
            raise RuntimeError(f"short read at sector {sector} (wanted {size}, got {len(data)})")
        return data

    def _walk_dir(self, sector: int, size: int, prefix: str = ""):
        if size == 0:
            return
        data = self._read(sector, size)
        stack = [0]
        seen: set[int] = set()
        while stack:
            off = stack.pop()
            if off in seen or off * 4 + 14 > len(data):
                continue
            seen.add(off)
            p = off * 4
            left, right, start, fsize, attr, nlen = struct.unpack_from("<HHIIBB", data, p)
            if left == 0xFFFF:
                continue
            name = data[p + 14 : p + 14 + nlen].decode("latin-1")
            if left:
                stack.append(left)
            if right:
                stack.append(right)
            full = prefix + name
            if attr & 0x10:
                yield full + "/", start, fsize, attr, True
                yield from self._walk_dir(start, fsize, full + "/")
            else:
                yield full, start, fsize, attr, False

    def walk(self):
        yield from self._walk_dir(self.root_sector, self.root_size)

    def extract(self, sector: int, size: int, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        self.f.seek(self.base + sector * SECTOR)
        written = 0
        try:
            with open(tmp, "wb") as out:
                while written < size:
                    chunk = self.f.read(min(4 << 20, size - written))
                    if not chunk:
                        raise RuntimeError(f"unexpected end of ISO while reading {dest.name}")
                    out.write(chunk)
                    written += len(chunk)
            if written != size:
                raise RuntimeError(f"size mismatch for {dest.name}: {written} != {size}")
            tmp.replace(dest)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise


def human(size: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GiB"


def detect_language(cpk_names: list[str]) -> tuple[str, int, int] | None:
    for name in cpk_names:
        stem = Path(name).name
        if stem.endswith("_Common.cpk") and len(stem) == len("enUS_Common.cpk"):
            row = LANGUAGES.get(stem[:4])
            if row:
                return row
    return None


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("iso", type=Path, help="Xbox 360 Diablo III ISO/XISO")
    parser.add_argument("--out", type=Path, default=repo / "game", help="game data directory (default: <repo>/game)")
    parser.add_argument("--force", action="store_true", help="re-extract files that already exist")
    args = parser.parse_args()

    iso = args.iso.expanduser()
    if not iso.is_file():
        print(f"error: ISO not found: {iso}", file=sys.stderr)
        return 1

    out: Path = args.out.expanduser().resolve()
    try:
        fs = XDvdFs(iso)
        entries = list(fs.walk())
    except (OSError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    xex = next((e for e in entries if not e[4] and e[0].lower() in ("default.xex", "default_decrypted.exe")), None)
    if xex is None:
        xex = next(
            (e for e in entries if not e[4] and Path(e[0]).name.lower() in ("default.xex", "default_decrypted.exe")),
            None,
        )
    cpks = [e for e in entries if not e[4] and e[0].lower().endswith(".cpk")]
    toc = next((e for e in entries if not e[4] and e[0].lower().endswith("commontoc.dat")), None)

    if xex is None:
        print("error: Default.xex not found; is this an Xbox 360 Diablo III disc?", file=sys.stderr)
        return 1
    if not cpks:
        print("error: no CPK archives found; is this an Xbox 360 Diablo III disc?", file=sys.stderr)
        return 1

    cpk_dir = out / "CPKs"
    cpk_dir.mkdir(parents=True, exist_ok=True)

    jobs: list[tuple[str, int, int, Path]] = [(xex[0], xex[1], xex[2], out / "default.xex")]
    jobs += [(name, sector, size, cpk_dir / Path(name).name) for name, sector, size, _, _ in cpks]
    if toc is not None:
        jobs.append((toc[0], toc[1], toc[2], out / Path(toc[0]).name))

    total = sum(job[2] for job in jobs)
    print(f"Game data: {out}")
    print(f"Extracting {len(jobs)} files ({human(total)}) from {iso.name}")

    for index, (name, sector, size, dest) in enumerate(jobs, 1):
        label = f"[{index}/{len(jobs)}] {Path(name).name}"
        if dest.exists() and dest.stat().st_size == size and not args.force:
            print(f"{label}: already extracted ({human(size)})")
            continue
        print(f"{label}: {human(size)}")
        fs.extract(sector, size, dest)
        if dest.stat().st_size != size:
            print(f"error: {dest} has the wrong size after extraction", file=sys.stderr)
            return 1

    cpk_names = [Path(job[3]).name for job in jobs[1:]]
    language = detect_language(cpk_names)
    if language:
        name, lang_id, country_id = language
        print(f"Detected language: {name} (user_language={lang_id}, user_country={country_id})")

    print()
    print("Done. Next steps:")
    print("  ./port/codegen.sh")
    print("  ./port/build.sh -c RelWithDebInfo")
    print(f'  python3 apply_config.py --game-data-root "{out}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
