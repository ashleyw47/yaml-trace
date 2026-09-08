"""Command line entry point for yamltrace.

The tool answers exactly one question: for a dotted key, and a list of
YAML files applied in override order, what is the effective value and
which file actually set it.
"""

from __future__ import annotations

import argparse
import json
import sys

from .parser import YList, YMap, YamlError, parse


def resolve(tree, path):
    """Walk a dotted path through a parsed tree.

    Returns (value, lineno) if the path exists, None otherwise. lineno
    is the line where the final segment's key was defined; for list
    items it falls back to the line of the containing key, since list
    entries don't have a key of their own.
    """
    segments = path.split(".")
    node = tree
    lineno = None
    for seg in segments:
        if isinstance(node, YMap):
            if seg not in node:
                return None
            lineno = node.lines[seg]
            node = node[seg]
        elif isinstance(node, YList):
            if not seg.isdigit() or int(seg) >= len(node):
                return None
            node = node[int(seg)]
        else:
            return None
    return node, lineno


def build_argparser():
    parser = argparse.ArgumentParser(
        prog="yamltrace",
        description=(
            "Show the effective value of a dotted key across a stack of "
            "YAML files, and which file actually set it."
        ),
    )
    parser.add_argument("path", help="dotted key path, e.g. database.pool.max")
    parser.add_argument(
        "files",
        nargs="+",
        help="YAML files in override order (later files win)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="emit machine readable JSON instead of the human readable summary",
    )
    return parser


def main(argv=None):
    args = build_argparser().parse_args(argv)

    hits = []
    for filename in args.files:
        try:
            with open(filename, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            print(f"yamltrace: cannot read {filename}: {exc.strerror}", file=sys.stderr)
            return 2
        try:
            tree = parse(text, filename)
        except YamlError as exc:
            print(f"yamltrace: {exc}", file=sys.stderr)
            return 2
        found = resolve(tree, args.path)
        if found is not None:
            value, lineno = found
            hits.append({"file": filename, "line": lineno, "value": value})

    if not hits:
        if args.as_json:
            print(json.dumps({"path": args.path, "found": False}, indent=2))
        else:
            print(f"{args.path}: not set in any of the given files")
        return 1

    winner = hits[-1]
    shadowed = hits[:-1]

    if args.as_json:
        print(
            json.dumps(
                {
                    "path": args.path,
                    "found": True,
                    "value": winner["value"],
                    "type": type(winner["value"]).__name__,
                    "source": {"file": winner["file"], "line": winner["line"]},
                    "shadowed": [
                        {"file": h["file"], "line": h["line"], "value": h["value"]}
                        for h in shadowed
                    ],
                },
                indent=2,
            )
        )
    else:
        print(f"{args.path} = {winner['value']!r}")
        print(f"  from: {winner['file']} (line {winner['line']})")
        if shadowed:
            print("  shadows:")
            for h in shadowed:
                print(f"    {h['file']} (line {h['line']}): {h['value']!r}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
