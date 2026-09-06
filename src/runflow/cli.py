import argparse
import sys
from shapely.errors import GEOSException
from pathlib import Path

from .contracts import SCHEMAS, validate
from .core import read, write, sample, generate, validate_manifest


def main(argv=None):
    parser = argparse.ArgumentParser(prog="runflow")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "sample", "generate"):
        p = sub.add_parser(name)
        p.add_argument("manifest", type=Path)
        p.add_argument("--asset-root", required=True, type=Path)
        if name != "validate":
            p.add_argument("--output", required=True, type=Path)
        if name == "generate":
            p.add_argument("--cfd", type=Path)
    p = sub.add_parser("baseline")
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--distro", default="Ubuntu")
    p.add_argument("--timeout", type=int, default=1800)
    p = sub.add_parser("compare")
    p.add_argument("reference", type=Path)
    p.add_argument("candidate", type=Path)
    p.add_argument("--height-m", type=float, required=True)
    p.add_argument("--output", required=True, type=Path)
    p = sub.add_parser("publish")
    p.add_argument("result", type=Path)
    p.add_argument("--output", required=True, type=Path)
    p = sub.add_parser("verify-gait")
    p.add_argument("manifest", type=Path)
    p.add_argument("--asset-root", required=True, type=Path)
    for key in ("reference", "candidate", "repeat", "output"):
        p.add_argument("--"+key,required=True,type=Path)
    p = sub.add_parser("schemas")
    p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in {"validate", "sample", "generate"}:
            manifest = validate_manifest(read(args.manifest), args.asset_root)
            if args.command == "sample":
                write(args.output, sample(manifest))
            elif args.command == "generate":
                config, result = generate(manifest, args.asset_root, read(args.cfd) if args.cfd else None)
                args.output.mkdir(parents=True, exist_ok=False)
                write(args.output / "experiment.json", config)
                write(args.output / "result.json", result)
                print(config["config_sha256"])
        elif args.command == "baseline":
            from .baseline import run
            result = run(args.output, args.distro, args.timeout)
            print(result["execution_status"])
            return 0 if result["execution_status"] == "PASS" else 2
        elif args.command == "compare":
            from .geometry import compare
            report = compare(read(args.reference), read(args.candidate), args.height_m)
            write(args.output, report)
            print(report["execution_status"])
            return 0 if report["execution_status"] == "PASS" else 2
        elif args.command == "publish":
            from .publication import public_result
            public_result(read(args.result), args.output)
        elif args.command == "verify-gait":
            from .geometry import verify_gait
            manifest = validate_manifest(read(args.manifest),args.asset_root)
            report = verify_gait(manifest,args.reference,args.candidate,args.repeat)
            write(args.output,report)
            print(report["execution_status"])
            return 0 if report["execution_status"] == "PASS" else 2
        elif args.command == "schemas":
            for kind, schema in SCHEMAS.items():
                write(args.output / f"{kind}.schema.json", {"$schema": "https://json-schema.org/draft/2020-12/schema", **schema})
        print("PASS")
        return 0
    except (ValueError, OSError, GEOSException) as error:
        print(f"BLOCKED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
