"""A0: record the pre-optimization baseline for Phase A.

Collects code revision, dirty state, relevant config hashes, current
projection grid and process count, working/output paths, existing stage
timings, and the frame result summaries already present in the private
ledger.  Writes nothing outside the Phase A evidence root.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from runflow import cfd_paths
from runflow.core import read, write


def _git(*arguments):
    try:
        result = subprocess.run(["git", *arguments], cwd=REPO, capture_output=True,
                                text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return "unavailable: " + str(exc)
    return result.stdout.strip()


def _sha256(path):
    path = Path(path)
    if not path.is_file():
        return None
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _timings(root):
    """Collect every recorded stage timing below one campaign root."""
    root = Path(root)
    records = []
    if not root.is_dir():
        return records
    for path in sorted(root.rglob("*.execution.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        elapsed = value.get("elapsed_s")
        if not isinstance(elapsed, (int, float)):
            continue
        records.append(dict(file=str(path.relative_to(root)), elapsed_s=float(elapsed),
                            returncode=value.get("returncode"), reason=value.get("reason")))
    return records


def _ledger_summary(root):
    path = Path(root) / "campaign.json"
    if not path.is_file():
        return None
    value = read(path)
    return dict(
        schema_version=value.get("schema_version"),
        completion_status=value.get("completion_status"),
        execution_budget_s=value.get("execution_budget_s"),
        consumed_compute_s=value.get("consumed_compute_s"),
        repair_audit_compute_s=value.get("repair_audit_compute_s"),
        cycle_compute_s=value.get("cycle_compute_s"),
        recovered_interrupted_frame=value.get("recovered_interrupted_frame"),
        attempts=[dict(phase_index=row.get("phase_index"), status=row.get("status"),
                       label=row.get("label"), drag_N=row.get("drag_N"), Cd=row.get("Cd"),
                       execution_elapsed_s=row.get("execution_elapsed_s"),
                       reason=row.get("reason"))
                  for row in value.get("attempts", [])],
    )


def collect(campaign_root, native_root, repair_root=None):
    configs = {}
    for name in ("configs/cfd.phase1-provisional.json", "configs/cfd.phase1-smoke.json"):
        configs[name] = _sha256(REPO / name)
    provisional = read(REPO / "configs/cfd.phase1-provisional.json")
    smoke = read(REPO / "configs/cfd.phase1-smoke.json")
    frame_root = Path(campaign_root) / "frame-00-001"
    mesh = None
    if (frame_root / "mesh-worker.json").is_file():
        mesh = read(frame_root / "mesh-worker.json")
    solver = None
    if (frame_root / "solver-worker.json").is_file():
        solver = read(frame_root / "solver-worker.json")
    return dict(
        schema_version="phase-a-baseline-1",
        generated_utc=datetime.now(timezone.utc).isoformat(),
        host=dict(platform=platform.platform(), processor=platform.processor(),
                  logical_cpu=os.cpu_count()),
        git=dict(revision=_git("rev-parse", "HEAD"), branch=_git("rev-parse", "--abbrev-ref", "HEAD"),
                 status_porcelain=_git("status", "--porcelain=v1", "--untracked-files=all").splitlines(),
                 remote=_git("remote", "-v").splitlines()),
        configs=configs,
        projection=dict(current_grid_m=1e-9, legacy_max_grid_m=1e-8,
                        guard="scripts/audit_shape_projection.py rejects grids coarser than 10nm"),
        cfd=dict(processes=int(provisional["limits"]["processes"]),
                 memory_bytes=int(provisional["limits"]["memory_bytes"]),
                 output_bytes=int(provisional["limits"]["output_bytes"]),
                 smoke_processes=int(smoke["limits"]["processes"])),
        paths=dict(archive=[str(item) for item in cfd_paths.archive_roots()],
                   scratch=[str(item) for item in cfd_paths.scratch_roots()],
                   phase_a=str(cfd_paths.phase_a_root()),
                   campaign=str(campaign_root), native=str(native_root)),
        frame_00=dict(mesh=mesh, solver=solver),
        ledger=_ledger_summary(campaign_root),
        timings=_timings(campaign_root),
        timings_native=_timings(native_root),
        timings_repair=_timings(repair_root) if repair_root else [],
        repair_ledger=_ledger_summary(
            Path("E:/RunFlowPrivate/phase1/cycle-repair-campaign-001")),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-root", type=Path,
                        default=Path("E:/RunFlowPrivate/phase1/cycle-phase1-full-001"))
    parser.add_argument("--native-root", type=Path,
                        default=Path("E:/RunFlowPrivate/phase1/cycle-native-discovery-001"))
    parser.add_argument("--output", type=Path,
                        default=cfd_paths.phase_a_root() / "phase-a-baseline.json")
    args = parser.parse_args()
    value = collect(args.campaign_root, args.native_root)
    output = Path(args.output)
    if not cfd_paths.is_private(output, REPO):
        raise ValueError("Baseline output must stay private")
    output.parent.mkdir(parents=True, exist_ok=True)
    write(output, value)
    total = sum(item["elapsed_s"] for item in value["timings"])
    print("PHASE_A_BASELINE", output)
    print("stage records:", len(value["timings"]), "total measured s:", round(total, 1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
