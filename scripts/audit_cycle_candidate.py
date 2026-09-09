"""Run the private full-body shape audit for one repaired cycle candidate.

The source is the native Blender 0.9 mm result for the same frame.  The
candidate is a repair output.  This command only measures the pair; it never
changes either input, runs CFD, or grants scientific approval.
"""

import argparse
import json
from pathlib import Path
import shutil
import sys
import time

from runflow import cfd_guard
from runflow.cfd_paths import is_private
from runflow.shape_audit import cache_surface, file_sha


REPO = Path(__file__).resolve().parents[1]
BLENDER = REPO / ".tools/blender/blender-4.2.23-windows-x64/blender.exe"


def save(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, allow_nan=False, indent=2), encoding="utf-8")


def private(path):
    path = Path(path).resolve()
    if not is_private(path, REPO):
        raise ValueError("Cycle shape audit input/output must stay private")
    return path


def pins(root, name, command):
    sources = [
        Path(__file__).resolve(),
        REPO / "src/runflow/shape_audit.py",
        REPO / "src/runflow/shape_projection.py",
        REPO / "src/runflow/shape_sections.py",
        REPO / "src/runflow/cfd_guard.py",
    ]
    for argument in command:
        path = Path(argument)
        if path.suffix == ".py" and path.is_file():
            sources.append(path)
    record = {str(path.relative_to(REPO)).replace("\\", "/"): file_sha(path) for path in set(sources)}
    record["runtime"] = file_sha(command[0])
    save(root / (name + ".tool-pins.json"), record)


def prepare(args):
    root = private(args.output)
    source = private(args.source)
    candidate = private(args.candidate)
    if root.exists():
        raise ValueError("Fresh cycle shape audit output required")
    if not source.is_file() or not candidate.is_file():
        raise ValueError("Cycle shape audit OBJ input is missing")
    root.mkdir(parents=True, exist_ok=False)
    source_sha = file_sha(source)
    candidate_sha = file_sha(candidate)
    source_info = cache_surface(source, root / "source", source_sha)
    candidate_info = cache_surface(candidate, root / "candidate", candidate_sha)
    request = dict(
        schema_version="phase1-cycle-shape-audit-1",
        source=dict(path=str(source), sha256=source_sha, role="native_blender_0.9mm_frame0"),
        candidate=dict(path=str(candidate), sha256=candidate_sha, role="repair_candidate"),
        cover_m=float(args.cover_m),
        projection_grid_m=float(args.projection_grid_m),
        memory_bytes=int(args.memory_gib * 1024**3),
        output_bytes=int(args.output_gib * 1024**3),
        scientific_status="UNVALIDATED_PHASE1_CYCLE",
        ranking_eligible=False,
        source_cache=source_info,
        candidate_cache=candidate_info,
    )
    save(root / "request.json", request)
    save(root / "state.json", dict(status="PREPARED", started_epoch=time.time(), updated_epoch=time.time()))
    print("CYCLE_SHAPE_AUDIT_PREPARED", root, flush=True)


def run_stage(args):
    root = private(args.output)
    request = json.loads((root / "request.json").read_text(encoding="utf-8"))
    if request["source"]["sha256"] != file_sha(request["source"]["path"]):
        raise ValueError("Native source changed after audit preparation")
    if request["candidate"]["sha256"] != file_sha(request["candidate"]["path"]):
        raise ValueError("Repair candidate changed after audit preparation")
    memory = request["memory_bytes"]
    output = request["output_bytes"]
    timeout = float(args.timeout)
    jobs = []
    if args.stage == "distance":
        for direction in ("source-to-candidate", "candidate-to-source"):
            jobs.append((direction, [
                str(BLENDER), "--background", "--factory-startup", "--threads", "20",
                "--python-exit-code", "2", "--python", str(REPO / "integrations/blender/audit_surface_distance.py"),
                "--", "--root", str(root), "--direction", direction,
                "--cover-m", str(request["cover_m"]), "--timeout", str(timeout),
            ]))
    elif args.stage == "projection":
        jobs.append(("projection", [
            sys.executable, str(REPO / "scripts/audit_shape_projection.py"),
            "--root", str(root), "--grid-m", str(request["projection_grid_m"]),
        ]))
    elif args.stage == "views":
        jobs.append(("views", [
            str(BLENDER), "--background", "--factory-startup", "--threads", "20",
            "--python-exit-code", "2", "--python", str(REPO / "integrations/blender/audit_surface_views.py"),
            "--", "--root", str(root),
        ]))
    elif args.stage == "sections":
        jobs.append(("sections", [
            sys.executable, str(REPO / "scripts/audit_shape_sections.py"), "--root", str(root),
        ]))
    else:
        raise ValueError("Unknown shape audit stage")
    results = []
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    state.update(status="RUNNING", stage=args.stage, updated_epoch=time.time())
    save(root / "state.json", state)
    try:
        for name, command in jobs:
            record_name = name + ("-" + args.attempt if args.attempt else "")
            log = root / (record_name + ".log")
            execution = root / (record_name + ".execution.json")
            if execution.exists():
                raise ValueError("Stage already attempted: " + record_name)
            pins(root, record_name, command)
            record = cfd_guard.run(
                command, root=root, log=log, timeout=timeout + 60,
                memory_bytes=memory, output_bytes=output, cwd=REPO,
            )
            save(execution, record)
            results.append(dict(name=record_name, **record))
            if record["returncode"] != 0 or record["reason"]:
                raise RuntimeError(str(record))
        state.update(status="PASS", updated_epoch=time.time())
        save(root / "state.json", state)
        print("CYCLE_SHAPE_AUDIT_STAGE_DONE", args.stage, flush=True)
    except BaseException as exc:
        state.update(status="FAIL", error=str(exc), updated_epoch=time.time())
        save(root / "state.json", state)
        raise
    finally:
        save(root / (args.stage + ".run.json"), dict(stage=args.stage, results=results, complete=bool(results), elapsed_s=None))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stage", choices=("distance", "projection", "views", "sections"))
    parser.add_argument("--attempt", default="")
    parser.add_argument("--cover-m", type=float, default=0.001)
    parser.add_argument("--projection-grid-m", type=float, default=1e-9)
    parser.add_argument("--timeout", type=float, default=3600)
    parser.add_argument("--memory-gib", type=float, default=80)
    parser.add_argument("--output-gib", type=float, default=300)
    args = parser.parse_args()
    if args.prepare:
        if args.source is None or args.candidate is None:
            raise ValueError("--source and --candidate are required with --prepare")
        if not 0 < args.cover_m <= 0.001 or not 0 < args.projection_grid_m <= 1e-8:
            raise ValueError("Invalid shape audit precision")
        prepare(args)
    elif args.stage:
        run_stage(args)
    else:
        raise ValueError("Choose --prepare or --stage")


if __name__ == "__main__":
    main()
