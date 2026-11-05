#!/usr/bin/env python3
"""Extract read-only STFS title updates, checking SHA-1 for each data block.

Format reference: xenia-project/xenia src/xenia/vfs/devices/stfs_xbox.h
and stfs_container_device.cc. Writable/dual-table packages are rejected.
"""
import argparse
import hashlib
from pathlib import Path

from extract_disc import check_name, inside, store, write_json


def extract(package, destination):
    data = package.read_bytes()
    def number(offset, size, endian='big'):
        return int.from_bytes(data[offset:offset + size], endian)
    if data[:4] not in (b'LIVE', b'PIRS') or len(data) < 0xA000:
        raise ValueError('Expected LIVE/PIRS package')
    if number(0x3A9, 4) != 0 or data[0x379] != 0x24 or not data[0x37B] & 1:
        raise ValueError('Only read-only STFS supported')
    header = (number(0x340, 4) + 4095) & ~4095
    count = number(0x395, 4)

    def block(index):
        if not 0 <= index < count:
            raise ValueError('Block index outside package')
        physical, level = index, 170
        for _ in range(3):
            physical += (index + level) // level
            if index < level:
                break
            level *= 170
        offset = header + physical * 4096
        payload = data[offset:offset + 4096]
        if len(payload) != 4096:
            raise ValueError('Truncated block')
        if index < 170:
            hash_block = 0
        else:
            hash_block = (index // 170) * 171 + index // 28900 + 1
            if index >= 28900:
                hash_block += 1
        entry = header + hash_block * 4096 + index % 170 * 24
        if hashlib.sha1(payload).digest() != data[entry:entry + 20]:
            raise ValueError(f'SHA-1 mismatch in block {index}')
        return payload, number(entry + 21, 3)

    paths, directories, files, tables = [], set(), [], set()
    table_index = number(0x37E, 3, 'little')
    for _ in range(number(0x37C, 2, 'little')):
        if table_index in tables:
            raise ValueError('Cyclic directory table')
        tables.add(table_index)
        table, table_index = block(table_index)
        for offset in range(0, 4096, 64):
            entry = table[offset:offset + 64]
            if not entry[0]:
                break
            if entry[40] & 63 > 40:  # the name field is 40 bytes
                raise ValueError('Invalid filename length')
            name = check_name(entry[:entry[40] & 63].decode('ascii'))
            parent = int.from_bytes(entry[50:52], 'big')
            if parent != 65535 and parent not in directories:
                raise ValueError('Invalid directory parent')
            relative = (Path() if parent == 65535 else paths[parent]) / name
            paths.append(relative)
            target = inside(destination, relative)
            if entry[40] & 128:
                directories.add(len(paths) - 1)
                target.mkdir(parents=True, exist_ok=True)
                continue
            length = int.from_bytes(entry[52:56], 'big')
            index = int.from_bytes(entry[47:50], 'little')
            payload, seen = bytearray(), set()
            while len(payload) < length:
                if index in seen:
                    raise ValueError('Cyclic file block chain')
                seen.add(index)
                part, index = block(index)
                payload.extend(part[:length - len(payload)])
            if len(seen) != int.from_bytes(entry[44:47], 'little'):
                raise ValueError('Allocated block count mismatch')
            target.parent.mkdir(parents=True, exist_ok=True)
            # Resumes a file an interrupted run left partly written; never replaces different content.
            digest = store(target, [bytes(payload)], relative)
            files.append(dict(path=relative.as_posix(), size=length, sha256=digest))
            print(f'{relative}: {length:,} bytes')
    manifest = dict(source=package.name, sha256=hashlib.sha256(data).hexdigest(),
                    title_id=f'{number(0x360, 4):08X}', media_id=f'{number(0x354, 4):08X}',
                    version=number(0x358, 4), base_version=number(0x35C, 4),
                    block_hashes_verified=True, files=files)
    destination.mkdir(parents=True, exist_ok=True)
    write_json(destination / 'update-manifest.json', manifest)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    extract(args.package, args.destination)
