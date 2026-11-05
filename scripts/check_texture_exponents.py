#!/usr/bin/env python3
"""Check dumped SPIR-V texture exponent data flow against Xenos fetch words."""
import argparse
import pathlib
import subprocess


def inspect(path):
    text = subprocess.check_output(['spirv-dis', str(path)], text=True)
    definitions = {}
    constants = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[1] == '=':
            definitions[parts[0]] = parts[2:]
            if (parts[2] == 'OpConstant' and len(parts) == 5
                    and definitions.get(parts[3], [''])[0] == 'OpTypeInt'):
                constants[parts[0]] = int(parts[4], 0)
    checked = 0
    for op in definitions.values():
        if op[0] != 'OpExtInst' or len(op) < 6 or op[3] != 'Ldexp':
            continue
        exponent = definitions.get(op[5], [])
        if not exponent or exponent[0] != 'OpBitFieldSExtract':
            continue
        if (constants.get(exponent[3]), constants.get(exponent[4])) != (13, 6):
            continue
        signed = definitions[exponent[2]]
        assert signed[0] == 'OpBitcast', (path, signed)
        load = definitions[signed[2]]
        assert load[0] == 'OpLoad', (path, load)
        access = definitions[load[2]]
        assert access[0] == 'OpAccessChain' and 'fetch_constants' in access[2], (path, access)
        indices = [constants[x] for x in access[3:]]
        assert len(indices) == 3 and indices[0] == 0, (path, indices)
        word = indices[1] * 4 + indices[2]
        assert word % 6 == 3, f'{path.name}: exponent reads fetch word {word % 6}, expected word 3'
        checked += 1
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=pathlib.Path)
    args = parser.parse_args()
    files = sorted(args.path.glob('*.vulkan.bin.*')) if args.path.is_dir() else [args.path]
    try:
        checked = sum(inspect(path) for path in files)
    except AssertionError as error:
        raise SystemExit(str(error)) from None
    if not checked:
        raise SystemExit('No texture exponent operations found')
    print(f'Checked {checked} texture exponent operations across {len(files)} shader variants')


if __name__ == '__main__':
    main()
