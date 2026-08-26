#!/usr/bin/env python3
"""Remove trailing Ngoai ra sentences from legal_representative in a JSON array."""

import argparse
import json
import os
import re
import tempfile
from pathlib import Path

from crawl_paths import resolve_json_path


REMOVABLE_SENTENCE = re.compile(
    r"(?:^|\s+)Ngoài ra\b.*$",
    flags=re.IGNORECASE | re.DOTALL,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Clean Ngoai ra sentences from legal_representative."
    )
    parser.add_argument("input", type=Path, help="Source JSON array file")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Destination file (defaults to replacing the input safely)",
    )
    return parser.parse_args()


def clean_legal_representative(data):
    if not isinstance(data, list):
        raise ValueError("The top-level JSON value must be an array.")

    changed = 0
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Array item {index} must be an object.")

        value = item.get("legal_representative")
        if not isinstance(value, str):
            continue

        cleaned = REMOVABLE_SENTENCE.sub("", value).rstrip()
        if cleaned != value:
            item["legal_representative"] = cleaned
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
    args.input = resolve_json_path(args.input)
    args.output = resolve_json_path(args.output) if args.output else None

    with args.input.open("r", encoding="utf-8-sig") as file:
        data, changed = clean_legal_representative(json.load(file))

    if args.output:
        write_json(args.output, data)
        destination = args.output
    else:
        replace_safely(args.input, data)
        destination = args.input

    print(f"Cleaned legal_representative in {changed} objects in {destination}.")


if __name__ == "__main__":
    main()
