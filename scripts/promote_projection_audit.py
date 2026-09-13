"""Promote already-valid projection evidence into the canonical artifact.

This never recomputes a projection and never deletes previous bytes: the
earlier canonical file is archived as projections-prior.json.
"""
import argparse
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from runflow.audit_contract import load_authoritative_projections, promote
from runflow.cfd_paths import is_private


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--check", action="store_true",
                        help="report the authoritative artifact without rewriting anything")
    args = parser.parse_args()
    root = args.root.resolve()
    if not is_private(root, REPO):
        raise ValueError("Audit root must stay private")
    if args.check:
        document, source = load_authoritative_projections(root)
        print(json.dumps(dict(authoritative=source, complete=document.get("complete"),
                              views=sorted(document["views"])), indent=2))
        return 0
    print(json.dumps(promote(root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
