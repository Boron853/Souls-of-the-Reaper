#!/usr/bin/env python3
"""Validate locally dumped Vulkan guest shaders (requires spirv-val)."""
import argparse
import json
import pathlib
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=pathlib.Path)
    args = parser.parse_args()
    validator = shutil.which('spirv-val')
    if not validator:
        raise SystemExit('spirv-val is required')
    files = sorted(args.directory.glob('*.vulkan.bin.*'))
    if not files:
        raise SystemExit('No translated Vulkan shaders found')
    results = []
    for path in files:
        # The translator emits SPIR-V 1.5 with scalar block layout; check
        # against the corresponding enabled Vulkan device feature set.
        result = subprocess.run([validator, '--target-env', 'vulkan1.2',
                                 '--scalar-block-layout', str(path)],
                                capture_output=True, text=True)
        results.append(dict(file=path.name, valid=result.returncode == 0,
                            diagnostic=result.stderr.strip()))
    report = args.directory.parent / 'validation.json'
    report.write_text(json.dumps(results, indent=2) + '\n')
    failures = [r for r in results if not r['valid']]
    print(f'{len(results)} shader variants validated; {len(failures)} failed. Report: {report}')
    for result in failures:
        print(result['file'], result['diagnostic'])
    raise SystemExit(bool(failures))


if __name__ == '__main__':
    main()
