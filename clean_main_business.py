#!/usr/bin/env python3
"""Remove detail/inactive suffixes from main_business in a JSON array."""

import argparse
import json
import os
import re
import tempfile
from pathlib import Path


REMOVABLE_SUFFIX = re.compile(
    r"\s*(?:(?:\(|-)?chi tiết:|\(?cụ thể:|\(không hoạt động|\(trừ tái chế phế|\(trừ sản xuất xốp|\(Ngoài)|\(trừ hóa lỏng.*$",
    flags=re.IGNORECASE,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Clean detail/inactive suffixes from main_business."
    )
    parser.add_argument("input", type=Path, help="Source JSON array file")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Destination file (defaults to replacing the input safely)",
    )
    return parser.parse_args()


def clean_main_business(data):
    if not isinstance(data, list):
        raise ValueError("The top-level JSON value must be an array.")

    changed = 0
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Array item {index} must be an object.")

        value = item.get("main_business")
        if not isinstance(value, str):
            continue

        cleaned = REMOVABLE_SUFFIX.sub("", value).rstrip()
        if cleaned != value:
            item["main_business"] = cleaned
            changed += 1

    return data, changed


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def replace_safely(path, data):
    path = path.resolve()
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
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

    with args.input.open("r", encoding="utf-8-sig") as file:
        data, changed = clean_main_business(json.load(file))

    if args.output:
        write_json(args.output, data)
        destination = args.output
    else:
        replace_safely(args.input, data)
        destination = args.input

    print(f"Cleaned main_business in {changed} objects in {destination}.")


if __name__ == "__main__":
    main()
