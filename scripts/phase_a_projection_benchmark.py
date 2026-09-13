"""A1/A2/A3: measure projection grid, source cache, and view parallelism.

Every step copies the already-cached audit surfaces into its own benchmark
sub-root under the scratch root, then runs the same audit CLI.  Nothing here
touches an existing audit root, and nothing recomputes a repair.

The grid A/B can compare against an already-archived 1e-9 result through
--reference-json, so the definitive reference does not have to be recomputed
before the coarse grids are answered.  Results are written after every grid.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from runflow import cfd_paths
from runflow.audit_contract import REQUIRED_VIEWS, merge_views
from runflow.core import write

AUDIT = REPO / "scripts" / "audit_shape_projection.py"
RELATIVE_TOLERANCE = 1e-3
IOU_FLOOR = 0.999
CONTRACT_AREA_TOLERANCE = 0.01


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _stage(audit_root, target):
    """Copy the cached surfaces so the sub-root is self-contained."""
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for name in ("source", "candidate"):
        shutil.copytree(Path(audit_root) / name, target / name)
    return target


def _run(root, *, grid, benchmark=True, cache=True, cache_root=None, view=None, timeout=14400):
    command = [sys.executable, str(AUDIT), "--root", str(root)]
    if view:
        command += ["--view", view]
    command += ["--grid-m", repr(float(grid))]
    if benchmark:
        command.append("--benchmark")
    if not cache:
        command.append("--no-projection-cache")
    if cache_root is not None:
        command += ["--cache-root", str(cache_root)]
    started = time.monotonic()
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=timeout, check=False)
    elapsed = time.monotonic() - started
    return dict(command=command, elapsed_s=round(elapsed, 3), returncode=result.returncode,
                tail=(result.stdout or "")[-2000:], stderr=(result.stderr or "")[-2000:])


def _views(root, name="projections.json"):
    path = Path(root) / name
    if not path.is_file():
        return None
    return _read(path)


def _compare(reference, candidate):
    """Return per-view deltas between two projection documents."""
    rows = {}
    for view in REQUIRED_VIEWS:
        if view not in reference["views"] or view not in candidate["views"]:
            continue
        a = reference["views"][view]
        b = candidate["views"][view]
        source_delta = abs(b["source_m2"] - a["source_m2"]) / a["source_m2"]
        candidate_delta = abs(b["candidate_m2"] - a["candidate_m2"]) / a["candidate_m2"]
        change_delta = abs(float(b["relative_change_abs"]) - float(a["relative_change_abs"]))
        rows[view] = dict(source_area_relative_delta=source_delta,
                          candidate_area_relative_delta=candidate_delta,
                          relative_change_abs_delta=change_delta,
                          iou=float(b["iou"]),
                          contract_pass=bool(float(b["relative_change_abs"]) <= CONTRACT_AREA_TOLERANCE),
                          equivalent=bool(source_delta <= RELATIVE_TOLERANCE
                                          and candidate_delta <= RELATIVE_TOLERANCE
                                          and float(b["iou"]) >= IOU_FLOOR
                                          and float(b["relative_change_abs"]) <= CONTRACT_AREA_TOLERANCE))
    return rows


def step_grids(audit_root, root, grids, into, reference=None, emit=None):
    current = reference
    for grid in grids:
        label = ("%g" % grid)
        target = _stage(audit_root, root / ("grid-" + label))
        run = _run(target, grid=grid, cache=False)
        document = _views(target)
        entry = dict(grid_m=grid, root=str(target), run=run)
        if document is None:
            entry["status"] = "NO_OUTPUT"
        else:
            entry["views"] = {view: document["views"][view] for view in REQUIRED_VIEWS}
            entry["elapsed_s"] = run["elapsed_s"]
            if current is None:
                entry["status"] = "REFERENCE"
                current = document
            else:
                entry["comparison"] = _compare(current, document)
                entry["status"] = ("EQUIVALENT"
                                   if all(row["equivalent"] for row in entry["comparison"].values())
                                   else "DIVERGENT")
            if reference is not None:
                entry["vs_external_reference"] = _compare(reference, document)
        into[label] = entry
        if emit is not None:
            emit()
        print("GRID", label, entry["status"], run["elapsed_s"], flush=True)
    return into


def step_cache(audit_root, root, grid):
    shared = root / "cache-store"
    cold = _stage(audit_root, root / "cache-cold")
    warm = _stage(audit_root, root / "cache-warm")
    first = _run(cold, grid=grid, cache=True, cache_root=shared)
    second = _run(warm, grid=grid, cache=True, cache_root=shared)
    a = _views(cold)
    b = _views(warm)
    equivalent = False
    if a is not None and b is not None:
        equivalent = all(abs(a["views"][v]["source_m2"] - b["views"][v]["source_m2"])
                         / a["views"][v]["source_m2"] <= RELATIVE_TOLERANCE
                         and abs(a["views"][v]["candidate_m2"] - b["views"][v]["candidate_m2"])
                         / a["views"][v]["candidate_m2"] <= RELATIVE_TOLERANCE
                         and float(a["views"][v]["iou"]) == float(b["views"][v]["iou"])
                         for v in REQUIRED_VIEWS)
    statuses = {}
    for label, document in (("cold", a), ("warm", b)):
        statuses[label] = (None if document is None
                           else {v: document.get("cache", {}).get(v, {}).get("status")
                                 for v in REQUIRED_VIEWS})
    return dict(cold=first, warm=second, equivalent=equivalent, cache_status=statuses,
                saved_s=round(first["elapsed_s"] - second["elapsed_s"], 3))


def step_focused(audit_root, root, legacy=1e-9, coarse=1e-7):
    """Front view only: does the precision grid change the cost or the result?

    A full three-view A/B costs roughly 40 minutes per grid.  One view answers
    the grid question directly because the same union code dominates every
    view, and the reference values come from the archived 1e-9 audit.
    """
    rows = {}
    for label, grid in (("legacy", legacy), ("coarse", coarse)):
        target = _stage(audit_root, root / ("view-" + label))
        run = _run(target, grid=grid, view="front", cache=False)
        document = _views(target, "projection-front.json")
        rows[label] = dict(grid_m=grid, run=run,
                           views=(document["views"] if document else None))
    if rows["legacy"]["views"] and rows["coarse"]["views"]:
        comparison = _compare({"views": rows["legacy"]["views"]},
                              {"views": rows["coarse"]["views"]})
        rows["comparison"] = comparison
        rows["equivalent"] = all(item["equivalent"] for item in comparison.values())
        rows["elapsed_ratio"] = (rows["coarse"]["run"]["elapsed_s"]
                                 / rows["legacy"]["run"]["elapsed_s"])
    return rows


def step_parallel(audit_root, root, grid, reference=None, workers=3):
    target = _stage(audit_root, root / "views-parallel")
    started = time.monotonic()
    processes = []
    for view in REQUIRED_VIEWS[:workers]:
        command = [sys.executable, str(AUDIT), "--root", str(target), "--view", view,
                   "--grid-m", repr(float(grid)), "--benchmark", "--no-projection-cache"]
        processes.append((view, subprocess.Popen(command, stdout=subprocess.PIPE,
                                                 stderr=subprocess.STDOUT, text=True,
                                                 encoding="utf-8", errors="replace")))
    logs = {}
    failures = []
    for view, process in processes:
        out, _ = process.communicate()
        logs[view] = dict(returncode=process.returncode, tail=(out or "")[-2000:])
        if process.returncode != 0:
            failures.append(view)
    elapsed = round(time.monotonic() - started, 3)
    merged = None
    if not failures:
        rows = {}
        for view in REQUIRED_VIEWS[:workers]:
            document = _views(target, "projection-" + view + ".json")
            if document is None or document.get("complete") is not True:
                failures.append(view)
            else:
                rows[view] = document["views"][view]
        if not failures and set(rows) == set(REQUIRED_VIEWS):
            document = merge_views(rows)
            document["parallel"] = dict(workers=workers, elapsed_s=elapsed,
                                        order=list(REQUIRED_VIEWS))
            path = target / "projections.json"
            path.write_text(json.dumps(document, indent=2), encoding="utf-8")
            merged = document
    result = dict(root=str(target), workers=workers, elapsed_s=elapsed, logs=logs,
                  failures=failures)
    if merged is not None and reference is not None:
        result["comparison"] = _compare(reference, merged)
    result["equivalent"] = bool(merged is not None and reference is not None
                                and all(row["equivalent"] for row in result["comparison"].values()))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-root", type=Path, required=True,
                        help="existing audit root holding cached source/ and candidate/ surfaces")
    parser.add_argument("--benchmark-root", type=Path,
                        default=cfd_paths.scratch_win() / "phase-a" / "projection-ab-001")
    parser.add_argument("--steps", default="grids")
    parser.add_argument("--grids", type=float, nargs="+", default=[1e-7, 1e-6, 1e-9])
    parser.add_argument("--reference-json", type=Path,
                        help="already-archived 1e-9 projection document used as the A/B reference")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    root = Path(args.benchmark_root)
    if not cfd_paths.is_private(root, REPO):
        raise ValueError("Benchmark root must stay private")
    root.mkdir(parents=True, exist_ok=True)
    output = args.json_out or (cfd_paths.phase_a_root() / "projection-grid-ab.json")
    reference = _read(args.reference_json) if args.reference_json is not None else None
    grid_results = {}
    value = dict(schema_version="phase-a-projection-ab-1",
                 generated_utc=datetime.now(timezone.utc).isoformat(),
                 audit_root=str(args.audit_root), benchmark_root=str(root),
                 reference=(str(args.reference_json) if args.reference_json else None),
                 tolerance=dict(relative=RELATIVE_TOLERANCE, iou_floor=IOU_FLOOR,
                                contract_area=CONTRACT_AREA_TOLERANCE),
                 grids=grid_results)
    steps = [item.strip() for item in args.steps.split(",") if item.strip()]

    def emit():
        write(output, value)
        print("PHASE_A_PARTIAL_WRITE", output, flush=True)

    if "grids" in steps:
        step_grids(args.audit_root, root, args.grids, grid_results,
                   reference=reference, emit=emit)
    if "cache" in steps:
        value["cache"] = step_cache(args.audit_root, root, args.grids[0])
        emit()
    if "focused" in steps:
        value["focused"] = step_focused(args.audit_root, root)
        emit()
    if "parallel" in steps:
        serial = reference
        if serial is None and grid_results:
            first = grid_results.get("%g" % args.grids[0], {})
            if "views" in first:
                serial = {"views": first["views"]}
        value["parallel"] = step_parallel(args.audit_root, root, args.grids[0], reference=serial)
        emit()
    write(output, value)
    print("PHASE_A_PROJECTION_BENCHMARK", output, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
