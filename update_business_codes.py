#!/usr/bin/env python3
"""Set business_code to each object's one-based index in a JSON array."""

import argparse
import json
import os
import tempfile
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description='Replace business_code with 1..n in a JSON array.'
    )
    parser.add_argument('input', type=Path, help='Source JSON file')
    parser.add_argument(
        '-o', '--output', type=Path,
        help='Destination JSON file (defaults to replacing the input safely)',
    )
    return parser.parse_args()


def update_business_codes(data):
    if not isinstance(data, list):
        raise ValueError('The top-level JSON value must be an array.')

    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f'Array item {index} must be an object.')
        item['business_code'] = index

    return data


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
        data = update_business_codes(json.load(file))

    if args.output:
        write_json(args.output, data)
        destination = args.output
    else:
        replace_safely(args.input, data)
        destination = args.input

    print(f'Updated {len(data)} objects in {destination}.')


if __name__ == '__main__':
    main()
