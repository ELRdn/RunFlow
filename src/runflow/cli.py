import argparse
import sys
from shapely.errors import GEOSException
from pathlib import Path

from .contracts import SCHEMAS, validate
from .core import read, write, sample, generate, validate_manifest


def main(argv=None):
    parser = argparse.ArgumentParser(prog="runflow")
    sub = parser.add_subparsers(dest="command", required=True)
    cfd = sub.add_parser('cfd').add_subparsers(dest='cfd_command', required=True)
    prep = cfd.add_parser('prepare')
    prep.add_argument('manifest',type=Path)
    prep.add_argument('--asset-root',type=Path,required=True)
    prep.add_argument('--protocol',type=Path,required=True)
    prep.add_argument('--output',type=Path,required=True)
    prep.add_argument('--frame',type=int,default=0)
    prep.add_argument('--distro',default='Ubuntu')
    pp=cfd.add_parser('prepare-provisional')
    pp.add_argument('--receipt',type=Path,required=True)
    pp.add_argument('--protocol',type=Path,required=True)
    pp.add_argument('--output',type=Path,required=True)
    pp.add_argument('--distro',default='Ubuntu')
    for name in ('run','report'):
        cfd.add_parser(name).add_argument('--output',type=Path,required=True)
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
        if args.command == 'cfd':
            from . import cfd
            if args.cfd_command == 'prepare':
                report=cfd.prepare(args.manifest,args.asset_root,args.protocol,args.output,args.frame,args.distro)
            elif args.cfd_command == 'prepare-provisional':
                from .cfd_provisional import prepare
                report=prepare(args.receipt,args.protocol,args.output,args.distro)
            elif args.cfd_command == 'run': report=cfd.run(args.output)
            else: report=cfd.report(args.output)
            print(report['execution_status'])
            return 0 if report['execution_status'] in ('PASS','PREPARED') else 2
        elif args.command in {"validate", "sample", "generate"}:
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
            from .cfd_contracts import PROTOCOL,RESULT,EXPERIMENT,PROVISIONAL_PROTOCOL,PROVISIONAL_RESULT,PROVISIONAL_EXPERIMENT
            for kind,schema in dict(protocol=PROTOCOL,result=RESULT,experiment=EXPERIMENT,
                **{'provisional-protocol':PROVISIONAL_PROTOCOL,'provisional-result':PROVISIONAL_RESULT,'provisional-experiment':PROVISIONAL_EXPERIMENT}).items():
                write(args.output / f"cfd-{kind}.schema.json", {"$schema":"https://json-schema.org/draft/2020-12/schema",**schema})
            from . import cfd_study_contracts as study
            for kind,schema in dict(protocol=study.PROTOCOL,result=study.RESULT,experiment=study.EXPERIMENT).items():
                write(args.output / f"cfd-study-{kind}.schema.json", {"$schema":"https://json-schema.org/draft/2020-12/schema",**schema})
        print("PASS")
        return 0
    except (ValueError, OSError, GEOSException) as error:
        print(f"BLOCKED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
