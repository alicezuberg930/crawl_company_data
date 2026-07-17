#!/usr/bin/env python3
"""Remove other_businesses from every object in a JSON array."""

import argparse
import json
import os
import tempfile
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description='Remove other_businesses from every object in a JSON array.'
    )
    parser.add_argument(
        'input',
        nargs='?',
        type=Path,
        default=Path('doanh_nghiep_chi_tiet.json'),
        help='Source JSON file (default: doanh_nghiep_chi_tiet.json)',
    )
    parser.add_argument(
        '-o', '--output',
        type=Path,
        help='Destination file (defaults to replacing the input safely)',
    )
    return parser.parse_args()


def remove_other_businesses(data):
    if not isinstance(data, list):
        raise ValueError('The top-level JSON value must be an array.')

    removed = 0
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f'Array item {index} must be an object.')
        if 'other_businesses' in item:
            del item['other_businesses']
            removed += 1

    return data, removed


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='\n') as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write('\n')


def replace_safely(path, data):
    path = path.resolve()
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)

    try:
        write_json(temporary_path, data)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def main():
    args = parse_args()

    with args.input.open('r', encoding='utf-8-sig') as file:
        data, removed = remove_other_businesses(json.load(file))

    if args.output:
        write_json(args.output, data)
        destination = args.output
    else:
        replace_safely(args.input, data)
        destination = args.input

    print(
        f'Removed other_businesses from {removed} objects in {destination}.'
    )


if __name__ == '__main__':
    main()
