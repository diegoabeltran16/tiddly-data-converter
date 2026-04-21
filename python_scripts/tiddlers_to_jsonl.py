#!/usr/bin/env python3
"""
Combine all .json files from a directory into a single JSON Lines file.
Usage: python python_scripts/tiddlers_to_jsonl.py --input-dir docs/tiddlers_esp --output docs/tiddlers_esp.jsonl
"""
import argparse
import json
import sys
from pathlib import Path


def compact_json(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def process_dir(input_dir, output_path, encoding="utf-8", skip_invalid=False):
    p = Path(input_dir)
    if not p.exists():
        print(f"Input directory not found: {input_dir}", file=sys.stderr)
        return 2
    files = sorted([f for f in p.iterdir() if f.is_file() and f.suffix.lower() == ".json"])
    total = 0
    skipped = 0
    with open(output_path, "w", encoding=encoding, newline="\n") as out:
        for f in files:
            total += 1
            try:
                text = f.read_text(encoding=encoding)
                if text.startswith("\ufeff"):
                    text = text.lstrip("\ufeff")
                obj = json.loads(text)
                out.write(compact_json(obj) + "\n")
            except Exception as e:
                skipped += 1
                print(f"Warning: could not parse {f}: {e}", file=sys.stderr)
                if not skip_invalid:
                    continue
    print(f"Wrote {total - skipped} records to {output_path} (skipped {skipped})")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Combine .json files into a .jsonl")
    parser.add_argument("--input-dir", "-i", default="docs/tiddlers_esp", help="Directory containing .json files")
    parser.add_argument("--output", "-o", default="docs/tiddlers_esp.jsonl", help="Output jsonl file path")
    parser.add_argument("--encoding", default="utf-8", help="File encoding")
    parser.add_argument("--skip-invalid", action="store_true", help="Skip invalid JSON files")
    args = parser.parse_args()
    return process_dir(args.input_dir, args.output, encoding=args.encoding, skip_invalid=args.skip_invalid)


if __name__ == "__main__":
    sys.exit(main())
