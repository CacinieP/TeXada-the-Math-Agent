#!/usr/bin/env python3
"""Reject packaged ELF requirements newer than the Ubuntu 22.04 glibc baseline."""
import argparse
import re
import subprocess
from pathlib import Path


def check_tree(root: Path, baseline=(2, 35)) -> int:
    checked = 0
    failures = []
    for path in sorted(root.rglob('*')):
        if not path.is_file():
            continue
        with path.open('rb') as stream:
            if stream.read(4) != b'\x7fELF':
                continue
        checked += 1
        # Only undefined imports impose requirements on the host. Definitions
        # inside a bundled library must not be mistaken for imported versions.
        symbols = subprocess.check_output(['objdump', '-T', str(path)], text=True)
        for line in symbols.splitlines():
            if '*UND*' not in line:
                continue
            for version in re.findall(r'GLIBC_(\d+(?:\.\d+)+)', line):
                if tuple(map(int, version.split('.'))) > baseline:
                    failures.append(f'{path.relative_to(root)}: GLIBC_{version}')
    if not checked:
        raise RuntimeError('No packaged ELF objects found')
    if failures:
        raise RuntimeError('Packaged glibc requirements exceed 2.35:\n' + '\n'.join(failures))
    return checked


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    print(f'glibc <= 2.35: checked {check_tree(args.root)} ELF objects')
