"""Prepare one repaired cycle frame: automatic repair, shape audit, mapping row.

The stages are the same ones the repaired cycle campaign already uses, with the
accepted Phase A change applied to the projection stage: the three canonical
views run concurrently and are merged in the fixed front, side, top order after
every view succeeds.  The serial three-view audit costs 2,500 s to 4,900 s per
frame and is the dominant per-frame cost.

Nothing here relaxes a threshold.  The audit writes the same evidence the CFD
admission gate already requires, and the 2 mm / 1 % contract is unchanged.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from runflow import cfd
from runflow.audit_contract import REQUIRED_VIEWS, merge_views
from runflow.cfd_paths import reserve_reason
from runflow.core import file_hash, read, write
from runflow.shape_fullbody import LIMITS

from repair_trial_support import guarded as resource_guarded


DEFAULT_NATIVE = Path("E:/RunFlowPrivate/phase1/cycle-native-discovery-001")
DEFAULT_REPAIR = Path("D:/RunFlowScratch/phase-b/repair")
DEFAULT_AUDIT = Path("D:/RunFlowScratch/phase-b/audit")
DEFAULT_STATE = Path("D:/RunFlowScratch/phase-b/state")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _limits():
    return dict(LIMITS, resource_grace_s=5)


def _env():
    value = os.environ.copy()
    value.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="20", RUNFLOW_CPU_COUNT="20")
    return value


def _run(root, name, command, timeout):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    record = resource_guarded(command, root=root, log=root / (name + ".log"),
                              timeout=float(timeout), limits=_limits(), cwd=REPO, env=_env())
    write(root / (name + ".execution.json"), record)
    if record.get("reason") or record.get("returncode") != 0:
        raise RuntimeError(name + " failed: " + str(record.get("reason") or record.get("returncode")))
    return record


def _launch(root, name, command, env=None):
    root = Path(root)
    stream = (root / (name + ".log")).open("wb")
    started = time.monotonic()
    process = subprocess.Popen([str(item) for item in command], cwd=REPO, env=env or _env(),
                               stdout=stream, stderr=subprocess.STDOUT)
    return dict(name=name, process=process, stream=stream, started=started, log=root / (name + ".log"))


def _projection_env(threads):
    """Keep each per-view process small so several frames can run at once.

    The projection result does not depend on the thread count; this only stops
    three concurrent views from each claiming twenty threads.
    """
    value = _env()
    value.update(OMP_NUM_THREADS=str(int(threads)), OPENBLAS_NUM_THREADS="1",
                 MKL_NUM_THREADS="1", RUNFLOW_CPU_COUNT=str(int(threads)))
    return value


def _wait(handles, timeout):
    deadline = time.monotonic() + float(timeout)
    records = []
    for handle in handles:
        remaining = max(1.0, deadline - time.monotonic())
        try:
            code = handle["process"].wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            handle["process"].kill()
            code = handle["process"].wait()
            code = code if code is not None else -9
        handle["stream"].close()
        records.append(dict(name=handle["name"], returncode=code,
                            elapsed_s=time.monotonic() - handle["started"],
                            log=str(handle["log"])))
    return records


def _audit_complete(root):
    required = ("source-to-candidate.json", "candidate-to-source.json", "views.json", "sections.json")
    if any(not (root / name).is_file() for name in required):
        return False
    if not all(read(root / name).get("complete") is True for name in required):
        return False
    return (root / "projections.json").is_file() and read(root / "projections.json").get("complete") is True


def prepare(frame, *, native_root=DEFAULT_NATIVE, repair_root=DEFAULT_REPAIR,
            audit_root=DEFAULT_AUDIT, state_root=DEFAULT_STATE, distro="Ubuntu",
            stage_timeout_s=5400.0, repair_budget_s=5400.0, max_rounds=6,
            projection_workers=3, overlap_distance_projection=True):
    frame = int(frame)
    native_root = cfd.private(native_root)
    repair_root = cfd.private(repair_root)
    audit_root = cfd.private(audit_root)
    state = cfd.private(state_root) / f"frame-{frame:02d}"
    state.mkdir(parents=True, exist_ok=True)
    native_frame = native_root / f"frame-{frame:02d}-001"
    if not native_frame.is_dir():
        raise ValueError("Native frame is missing: " + str(native_frame))
    native_geometry = native_frame / "geometry"
    native_candidate = native_geometry / "candidate.obj"
    if not native_candidate.is_file():
        raise ValueError("Native frame geometry is missing for frame " + str(frame))

    report = dict(schema_version="phase1-prepare-repair-frame-1", frame=frame,
                  started_utc=_now(), stages=[], scientific_status="UNVALIDATED_PHASE1_CYCLE",
                  ranking_eligible=False)
    started = time.monotonic()

    # 1. Automatic repair (skipped when a previous PASS already exists).
    repair_output = repair_root / f"frame-{frame:02d}-001"
    repair_record_path = repair_output / "repair-auto.json"
    if repair_record_path.is_file() and read(repair_record_path).get("execution_status") == "PASS":
        repair = read(repair_record_path)
        report["stages"].append(dict(stage="repair", reused=True, root=str(repair_output)))
    else:
        if repair_output.exists() and not (repair_output / "request.json").is_file():
            # The automatic repair resumes from its own records, so a partial
            # round is resumable; only an unrecognised directory is refused.
            raise ValueError("Existing unrecognised repair output requires inspection: " + str(repair_output))
        command = [sys.executable, str(REPO / "scripts/run_phase1_repair_auto.py"),
                   "--native-root", str(native_frame), "--output-root", str(repair_output),
                   "--distro", distro, "--budget-s", str(repair_budget_s),
                   "--max-rounds", str(max_rounds)]
        execution = _run(state, "repair-auto", command, repair_budget_s + 300.0)
        report["stages"].append(dict(stage="repair", execution=execution))
        if not repair_record_path.is_file():
            raise RuntimeError("Automatic repair wrote no record for frame " + str(frame))
        repair = read(repair_record_path)
        if repair.get("execution_status") != "PASS":
            report.update(execution_status=repair.get("execution_status", "FAIL"),
                          reason=repair.get("reason"), elapsed_s=time.monotonic() - started)
            write(state / "prepare-report.json", report)
            return report
    candidate = Path(repair["candidate"])
    if not candidate.is_file():
        raise ValueError("Repaired candidate is missing: " + str(candidate))

    # 2. Shape audit.
    audit = audit_root / f"shape-audit-frame-{frame:02d}-001"
    if not (audit / "request.json").is_file():
        if audit.exists() and any(audit.iterdir()):
            raise ValueError("Existing incomplete audit requires inspection: " + str(audit))
        command = [sys.executable, str(REPO / "scripts/audit_cycle_candidate.py"), "--prepare",
                   "--source", str(native_candidate), "--candidate", str(candidate),
                   "--output", str(audit), "--cover-m", "0.001",
                   "--projection-grid-m", "0.000000001", "--memory-gib", "80",
                   "--output-gib", "300"]
        report["stages"].append(dict(stage="audit_prepare",
                                     execution=_run(audit.parent, f"prepare-frame-{frame:02d}",
                                                    command, 1800.0)))

    reservation = reserve_reason(audit)
    if reservation:
        raise RuntimeError("Scratch reserve preflight failed: " + reservation)

    distance_done = all((audit / name).is_file() for name in
                        ("source-to-candidate.json", "candidate-to-source.json"))
    projection_done = (audit / "projections.json").is_file() and read(audit / "projections.json").get("complete") is True

    # Each distance direction is launched here rather than through the audit
    # stage, because that stage refuses to retry a direction whose execution
    # record already exists.  A direction is only skipped when its own result
    # document is present, so an interrupted direction is repeated exactly.
    cover_m = read(audit / "request.json")["cover_m"]
    distance_jobs = _distance_jobs(audit, cover_m, stage_timeout_s)
    projection_jobs = _projection_handles(
        audit, projection_workers, stage_timeout_s,
        threads=max(1, 22 // max(1, projection_workers) // 2))

    if distance_jobs and projection_jobs and overlap_distance_projection:
        handles = [_launch(audit, "audit-distance-" + direction, command)
                   for direction, command in distance_jobs]
        handles.extend(projection_jobs)
        records = _wait(handles, stage_timeout_s + 900.0)
        report["stages"].append(dict(stage="distance_and_projection", records=records))
        failed = [row["name"] for row in records
                  if row["returncode"] != 0 and row["name"].startswith("audit-distance-")]
        if failed:
            raise RuntimeError("Shape-audit distance failed for frame %d: %s" % (frame, ", ".join(failed)))
        _merge_projection(audit, projection_workers, records, report)
    else:
        for direction, command in distance_jobs:
            report["stages"].append(dict(stage="distance", direction=direction,
                                         execution=_run(audit, f"audit-distance-{direction}-frame-{frame:02d}",
                                                        command, stage_timeout_s + 600.0)))
        projection_records = []
        if projection_jobs:
            projection_records = _wait(projection_jobs, stage_timeout_s + 900.0)
            report["stages"].append(dict(stage="projection_parallel", records=projection_records))
        if not (audit / "projections.json").is_file():
            _merge_projection(audit, projection_workers, projection_records, report)

    for direction in ("source-to-candidate", "candidate-to-source"):
        if not (audit / (direction + ".json")).is_file():
            raise RuntimeError("Distance direction did not complete for frame %d: %s" % (frame, direction))

    for stage in ("views", "sections"):
        path = audit / (stage + ".json")
        if path.is_file() and read(path).get("complete") is True:
            continue
        command = [sys.executable, str(REPO / "scripts/audit_cycle_candidate.py"),
                   "--output", str(audit), "--stage", stage, "--timeout", str(stage_timeout_s)]
        report["stages"].append(dict(stage=stage,
                                     execution=_run(audit, f"audit-{stage}-frame-{frame:02d}",
                                                    command, stage_timeout_s + 600.0)))

    if not _audit_complete(audit):
        raise RuntimeError("Shape audit did not complete for frame " + str(frame))

    # 3. Candidate and audit validation through the existing admission gate.
    from runflow.cfd_cycle import _surface_override_info
    native_result = read(native_frame / "result.json")
    native_geometry_record = read(native_geometry / "geometry.json")
    info, _ = _surface_override_info(candidate, audit,
                                     expected_source_sha256=native_geometry_record["source_sha256"])
    if info is None:
        raise RuntimeError("Candidate admission gate rejected frame " + str(frame))
    entry = dict(index=frame, surface=str(candidate), shape_audit=str(audit),
                 candidate_sha256=info["candidate_sha256"],
                 repair_sha256=info["repair_sha256"],
                 geometry_sha256=info["geometry_sha256"],
                 shape_audit_sha256=info["shape_audit_sha256"],
                 source_sha256=native_geometry_record["source_sha256"],
                 phase_index=native_result.get("phase_index"))
    write(state / "mapping-entry.json", entry)
    report.update(execution_status="PASS", mapping_entry=entry,
                  elapsed_s=time.monotonic() - started, finished_utc=_now())
    write(state / "prepare-report.json", report)
    print("PREPARE_REPAIR_FRAME_PASS", frame, round(report["elapsed_s"], 1), flush=True)
    return report


BLENDER = REPO / ".tools/blender/blender-4.2.23-windows-x64/blender.exe"


def _distance_jobs(audit, cover_m, timeout):
    """Return the two surface-distance directions that have no result yet.

    The command is the one the shape-audit distance stage already uses, so the
    distance evidence is identical to the archived frame-02 and frame-03 arms.
    """
    jobs = []
    for direction in ("source-to-candidate", "candidate-to-source"):
        if (audit / (direction + ".json")).is_file():
            continue
        command = [str(BLENDER), "--background", "--factory-startup", "--threads", "20",
                   "--python-exit-code", "2", "--python",
                   str(REPO / "integrations/blender/audit_surface_distance.py"),
                   "--", "--root", str(audit), "--direction", direction,
                   "--cover-m", str(cover_m), "--timeout", str(timeout)]
        jobs.append((direction, command))
    return jobs


def _projection_handles(audit, workers, timeout, threads=4):
    handles = []
    for view in list(REQUIRED_VIEWS)[:int(workers)]:
        if (audit / ("projection-" + view + ".json")).is_file():
            continue
        handles.append(_launch(audit, "audit-projection-" + view,
                               [sys.executable, str(REPO / "scripts/audit_shape_projection.py"),
                                "--root", str(audit), "--view", view,
                                "--grid-m", "0.000000001"],
                               env=_projection_env(threads)))
    return handles


def _merge_projection(audit, workers, records, report):
    failures = [row["name"] for row in records if row["returncode"] != 0]
    if failures:
        raise RuntimeError("Projection view failed: " + ", ".join(failures))
    rows = {}
    for view in REQUIRED_VIEWS:
        path = audit / ("projection-" + view + ".json")
        if not path.is_file():
            raise RuntimeError("Projection view document is missing: " + str(path))
        document = read(path)
        if document.get("views", {}).get(view) is None:
            raise RuntimeError("Projection view document lacks its own view: " + view)
        rows[view] = document["views"][view]
    document = merge_views(rows)
    document["parallel"] = dict(workers=int(workers), order=list(REQUIRED_VIEWS),
                                mode="per-view processes merged in fixed order")
    document["view_elapsed_s"] = {row["name"]: round(row["elapsed_s"], 3) for row in records}
    (audit / "projections.json").write_text(json.dumps(document, indent=2), encoding="utf-8")
    report["stages"].append(dict(stage="projection_merge",
                                 views=list(rows), workers=int(workers),
                                 projection_sha256=file_hash(audit / "projections.json")))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", type=int, required=True)
    parser.add_argument("--native-root", type=Path, default=DEFAULT_NATIVE)
    parser.add_argument("--repair-root", type=Path, default=DEFAULT_REPAIR)
    parser.add_argument("--audit-root", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--distro", default="Ubuntu")
    parser.add_argument("--stage-timeout-s", type=float, default=5400.0)
    parser.add_argument("--repair-budget-s", type=float, default=5400.0)
    parser.add_argument("--max-rounds", type=int, default=6)
    parser.add_argument("--projection-workers", type=int, default=3)
    parser.add_argument("--no-overlap", action="store_true")
    args = parser.parse_args()
    report = prepare(args.frame, native_root=args.native_root, repair_root=args.repair_root,
                     audit_root=args.audit_root, state_root=args.state_root, distro=args.distro,
                     stage_timeout_s=args.stage_timeout_s, repair_budget_s=args.repair_budget_s,
                     max_rounds=args.max_rounds, projection_workers=args.projection_workers,
                     overlap_distance_projection=not args.no_overlap)
    return 0 if report.get("execution_status") == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
