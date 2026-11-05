#!/usr/bin/env python3
"""Extract an XDVDFS game partition; retain a SHA-256 inventory of every file."""
import argparse
import hashlib
import json
import struct
from pathlib import Path

CHUNK = 4 * 1024 * 1024
# Names Windows maps to devices, with or without an extension ("NUL", "con.txt").
RESERVED_NAMES = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{n}' for n in range(1, 10)), *(f'LPT{n}' for n in range(1, 10))}


def check_name(name):
    """Return `name` if it is one plain file name on every host, else raise ValueError.

    On Windows a name like "C:x" (drive-relative), "a:b" (alternate data stream),
    "NUL" (device) or "x." (trailing dot is dropped) would write somewhere other
    than the extraction folder, so disc and package names must avoid them.
    """
    if (not name or name in ('.', '..') or name[-1] in '. '
            or any(c in '<>:"/\\|?*' or ord(c) < 32 or ord(c) == 127 for c in name)
            or name.split('.')[0].rstrip(' ').upper() in RESERVED_NAMES):
        raise ValueError(f'Unsafe filename: {name!r}')
    return name


def inside(destination, relative):
    """destination / relative, refusing anything that resolves outside destination."""
    target = destination / relative
    if not target.resolve().is_relative_to(destination.resolve()):
        raise ValueError(f'Unsafe path: {relative}')
    return target


def store(target, chunks, label):
    """Write `chunks` to `target` and return their SHA-256, resuming what an interrupted run left.

    New data goes to `<name>.part` and is renamed when complete, so a finished name
    always holds a whole file. Data already present (a `.part` file, or a file that
    older versions left truncated in place) is kept while it matches the source byte
    for byte and the rest is appended; content that differs is reported, never replaced.
    """
    partial = target.with_name(target.name + '.part')
    path = target if target.exists() else partial
    existing = path.exists()
    digest = hashlib.sha256()
    with path.open('r+b' if existing else 'xb') as stream:
        appending = not existing
        for data in chunks:
            digest.update(data)
            if not appending:
                have = stream.read(len(data))
                if have != data[:len(have)]:
                    raise ValueError(f'Existing file differs: {label}; move it aside and run again')
                if len(have) == len(data):
                    continue
                appending = True
                stream.seek(0, 2)
                data = data[len(have):]
            stream.write(data)
        if not appending and stream.read(1):
            raise ValueError(f'Existing file too long: {label}; move it aside and run again')
    if path == partial:
        partial.replace(target)
    else:
        partial.unlink(missing_ok=True)
    return digest.hexdigest()


class Disc:
    """Read-only view of an Xbox 360 ISO's XDVDFS game partition."""

    def __init__(self, source):
        self.source = source
        source.seek(0, 2)
        self.size = source.tell()
        bases = (0, 0x2080000, 0xFD90000)
        matches = [b for b in bases if b + 32 * 2048 + 20 <= self.size
                   and self.read(b + 32 * 2048, 20) == b'MICROSOFT*XBOX*MEDIA']
        if len(matches) != 1:
            raise ValueError(f'Expected one game partition, found {matches}')
        self.base = matches[0]
        self.root = struct.unpack_from('<II', self.read(self.base + 32 * 2048, 2048), 20)

    def read(self, offset, length):
        if offset < 0 or length < 0 or offset + length > self.size:
            raise ValueError('Read outside ISO')
        self.source.seek(offset)
        data = self.source.read(length)
        if len(data) != length:
            raise ValueError('Truncated ISO')
        return data

    def entries(self):
        """Yield (relative path, is_directory, sector, length) in disc order."""
        visited = set()

        def directory(sector, size, relative):
            if sector in visited or size > 16 * 1024 * 1024:
                raise ValueError('Invalid or cyclic directory')
            visited.add(sector)
            table = self.read(self.base + sector * 2048, size)
            nodes = set()

            def node(offset):
                if offset in nodes or offset + 14 > len(table):
                    raise ValueError('Invalid directory entry')
                nodes.add(offset)
                left, right, sec, length, attr, count = struct.unpack_from('<HHIIBB', table, offset)
                if offset + 14 + count > len(table):
                    raise ValueError('Truncated name')
                name = check_name(table[offset + 14:offset + 14 + count].decode('ascii'))
                if left:
                    yield from node(left * 4)
                path = relative / name
                if attr & 0x10:
                    yield path, True, sec, length
                    if length:
                        yield from directory(sec, length, path)
                else:
                    yield path, False, sec, length
                if right:
                    yield from node(right * 4)

            yield from node(0)

        yield from directory(*self.root, Path())

    def chunks(self, sector, length):
        remaining, position = length, self.base + sector * 2048
        while remaining:
            data = self.read(position, min(remaining, CHUNK))
            yield data
            remaining -= len(data)
            position += len(data)


def file_sha256(iso, name):
    """SHA-256 of one top-level file, without extracting the disc."""
    with iso.open('rb') as source:
        disc = Disc(source)
        for path, is_dir, sector, length in disc.entries():
            if not is_dir and path.as_posix().lower() == name.lower():
                digest = hashlib.sha256()
                for data in disc.chunks(sector, length):
                    digest.update(data)
                return digest.hexdigest()
    raise ValueError(f'{name} not found on disc')


def bytes_to_extract(iso, destination):
    """Bytes extract() still has to write: data already present (complete or partial) counts as written."""
    remaining = 0
    with iso.open('rb') as source:
        for path, is_dir, _, length in Disc(source).entries():
            if is_dir:
                continue
            target = destination / path
            present = max((p.stat().st_size for p in (target, target.with_name(target.name + '.part'))
                           if p.is_file()), default=0)
            remaining += length - min(present, length)
    return remaining


def extract(iso, destination):
    """Extract the game partition into `destination`; rerunning resumes an interrupted extraction."""
    records = []
    with iso.open('rb') as source:
        disc = Disc(source)
        destination.mkdir(parents=True, exist_ok=True)
        for path, is_dir, sector, length in disc.entries():
            target = inside(destination, path)
            if is_dir:
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = store(target, disc.chunks(sector, length), path)
            records.append(dict(path=path.as_posix(), size=length, sector=sector, sha256=digest))
            print(f'{path}: {length:,} bytes', flush=True)
        manifest = dict(source=iso.name, source_size=disc.size, partition_offset=disc.base, files=records)
    # Written last (and atomically): its presence marks a complete extraction.
    write_json(destination / 'disc-manifest.json', manifest)


def write_json(path, value):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('iso', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    extract(args.iso, args.destination)
