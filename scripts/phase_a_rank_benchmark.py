"""A6 step 1: numerical independence of frame-00 across MPI rank counts.

Prepares and executes the already-audited frame-00 geometry at two or more
rank counts into fresh Phase A roots, then compares the physics.  No repair or
audit is recomputed, and the scientific protocol is unchanged: only the
execution-resource limits differ.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from runflow import cfd_paths
from runflow.core import read, write
from runflow.cfd_cycle import execute_frame
from run_phase1_cycle_campaign import validate_request
from run_phase1_full_cycle import _load_mapping

# Existing protocol tolerance for the force-derived coefficients.
AREA_RELATIVE_TOLERANCE = 0.01
# Engineering sanity bound only.  The protocol does not constrain the cell
# count across rank counts, and parallel snappyHexMesh legitimately produces a
# slightly different count at partition boundaries.  A larger difference is
# reported as a regime change needing review, not silently accepted.
MESH_CELL_SANITY_RELATIVE = 0.01


def _iterations(path):
    if not Path(path).is_file():
        return None
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return len(re.findall(r"(?m)^Time = ", text))


def _frame_record(root):
    result = read(Path(root) / "result.json")
    mesh = read(Path(root) / "mesh-evidence.json") if (Path(root) / "mesh-evidence.json").is_file() else None
    state = read(Path(root) / "state.json")
    mesh_run = (read(Path(root) / "mesh-launcher.log.execution.json")
                if (Path(root) / "mesh-launcher.log.execution.json").is_file() else None)
    solver_run = (read(Path(root) / "solver-launcher.log.execution.json")
                  if (Path(root) / "solver-launcher.log.execution.json").is_file() else None)
    return dict(
        execution_status=result.get("execution_status"),
        drag_N=result.get("drag_N"), Cd=result.get("Cd"), CdA_m2=result.get("CdA_m2"),
        reason=result.get("reason"),
        comparison_family_sha256=result.get("comparison_family_sha256"),
        cells=(mesh or {}).get("cells"),
        refinement_reached=(mesh or {}).get("refinement_reached"),
        solver_iterations=_iterations(Path(root) / "foamRun.log"),
        mesh_elapsed_s=(mesh_run or {}).get("elapsed_s"),
        solver_elapsed_s=(solver_run or {}).get("elapsed_s"),
        frame_elapsed_s=(None if "started_epoch" not in state or "completed_epoch" not in state
                         else round(state["completed_epoch"] - state["started_epoch"], 3)),
    )


def compare(reference, candidate):
    """Per-field deltas against the reference rank count."""
    rows = {}
    for key in ("drag_N", "Cd", "CdA_m2"):
        a, b = reference.get(key), candidate.get(key)
        relative = (abs(b - a) / abs(a)) if (a and b and a != 0) else None
        rows[key] = dict(reference=a, candidate=b, relative_delta=relative)
    a, b = reference.get("cells"), candidate.get("cells")
    rows["cells"] = dict(reference=a, candidate=b,
                         relative_delta=(abs(b - a) / a) if (a and b) else None)
    rows["solver_iterations"] = dict(reference=reference.get("solver_iterations"),
                                     candidate=candidate.get("solver_iterations"))
    peak = max((value["relative_delta"] or 0.0) for key, value in rows.items()
               if key in ("drag_N", "Cd", "CdA_m2") and isinstance(value, dict))
    mesh_gates = bool(
        reference.get("execution_status") == "PASS" and candidate.get("execution_status") == "PASS"
        and reference.get("refinement_reached") and candidate.get("refinement_reached"))
    rows["mesh_gates_pass"] = mesh_gates
    rows["cells_sanity_ok"] = bool(rows["cells"]["relative_delta"] is not None
                                   and rows["cells"]["relative_delta"] <= MESH_CELL_SANITY_RELATIVE)
    rows["equivalent"] = bool(mesh_gates
                              and peak <= AREA_RELATIVE_TOLERANCE
                              and rows["cells_sanity_ok"])
    rows["max_physics_relative_delta"] = peak
    return rows


def reuse(output_root, ranks, frame):
    """Re-read completed rank runs so the comparison can be recomputed."""
    records = {}
    for rank in ranks:
        root = Path(output_root) / ("rank-%02d" % rank)
        label = "frame-%02d-001" % frame
        if not (root / label).is_dir():
            raise ValueError("Rank run is missing: " + str(root))
        summary = _frame_record(root / label)
        summary["ranks"] = int(rank)
        records[str(rank)] = summary
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--frame", type=int, default=0)
    parser.add_argument("--ranks", type=int, nargs="+", default=[4, 8])
    parser.add_argument("--output-root", type=Path,
                        default=cfd_paths.phase_a_root() / "rank-independence-001")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reuse", action="store_true",
                        help="recompute the comparison from completed rank runs without executing")
    args = parser.parse_args()
    request = read(args.request)
    verified, authority, prior = validate_request(request)
    mapping = _load_mapping(args.mapping, verified)
    frames = {row["index"]: row for row in verified["frames"]}
    frame = int(args.frame)
    if frame not in mapping["rows"]:
        raise ValueError("Frame " + str(frame) + " has no audited candidate in the mapping")
    row = mapping["rows"][frame]
    root = Path(args.output_root)
    if not cfd_paths.is_private(root, REPO):
        raise ValueError("Rank benchmark root must stay private")
    if args.dry_run:
        print(json.dumps(dict(frame=frame, ranks=args.ranks, output_root=str(root),
                              candidate=row["surface"], shape_audit=row["shape_audit"]), indent=2))
        return 0
    root.mkdir(parents=True, exist_ok=True)
    records = {}
    if args.reuse:
        records = reuse(root, args.ranks, frame)
    for ranks in (() if args.reuse else args.ranks):
        campaign = root / ("rank-%02d" % ranks)
        started = time.monotonic()
        result = execute_frame(request, frames[frame], campaign, distro="Ubuntu",
                               surface_override=Path(row["surface"]),
                               shape_audit_root=Path(row["shape_audit"]),
                               execution={"processes": int(ranks)})
        label = "frame-%02d-001" % frame
        summary = _frame_record(campaign / label) if (campaign / label).is_dir() else {}
        summary["ranks"] = int(ranks)
        summary["execution_status"] = result.get("execution_status")
        summary["stage_reason"] = result.get("reason")
        summary["wall_elapsed_s"] = round(time.monotonic() - started, 3)
        records[str(ranks)] = summary
        print("RANK_RUN", ranks, summary["execution_status"], summary.get("frame_elapsed_s"), flush=True)
    reference_key = str(args.ranks[0])
    comparisons = {key: compare(records[reference_key], value)
                   for key, value in records.items() if key != reference_key}
    value = dict(schema_version="phase-a-rank-independence-1",
                 generated_utc=datetime.now(timezone.utc).isoformat(),
                 frame=frame, output_root=str(root),
                 tolerance=dict(physics_relative=AREA_RELATIVE_TOLERANCE),
                 records=records, comparisons=comparisons,
                 all_equivalent=all(item["equivalent"] for item in comparisons.values()))
    write(root / "rank-independence.json", value)
    print("PHASE_A_RANK_BENCHMARK", root / "rank-independence.json", flush=True)
    print(json.dumps({key: item["equivalent"] for key, item in comparisons.items()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
