"""A7: frame-parallel Phase 1 cycle campaign with isolated worker ledgers.

Each worker owns a private campaign root with its own campaign.json and
active.json, so no two processes ever write the same ledger.  The parent owns
only parallel-request.json and the aggregated parallel-campaign.json.

Deterministic assignment: frame index modulo worker count.  The parent refuses
to aggregate results whose numerical families differ.
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

from runflow import cfd_paths
from runflow.core import read, write
from runflow.execution_profile import resolve, resolve_pair
from runflow.scratch import copy_back_frame, preflight

FULL_CYCLE = REPO / "scripts" / "run_phase1_full_cycle.py"
AGGREGATE_SCHEMA = "phase1-cycle-parallel-aggregate-1"
REQUEST_SCHEMA = "phase1-cycle-parallel-request-1"
DEFAULT_PARENT = Path("E:/RunFlowPrivate/phase1/cycle-phase1-parallel-001")


def assign(frames, workers):
    """Deterministic round-robin frame assignment."""
    workers = int(workers)
    if workers < 1:
        raise ValueError("Worker count must be positive")
    groups = {index: [] for index in range(workers)}
    for frame in sorted(int(item) for item in frames):
        groups[frame % workers].append(frame)
    return groups


def worker_root(parent, index):
    return Path(parent) / ("worker-%02d" % index)


def _env(profile):
    value = os.environ.copy()
    value.update(OPENBLAS_NUM_THREADS="1",
                 OMP_NUM_THREADS=str(profile["omp_threads"]),
                 RUNFLOW_CPU_COUNT=str(profile["threads_per_worker"]))
    return value


def marker_process_alive(worker):
    """Return (has_marker, alive) for a worker's active.json."""
    marker = Path(worker) / "active.json"
    if not marker.is_file():
        return False, False
    try:
        pid = int(read(marker).get("pid"))
    except (TypeError, ValueError, AttributeError):
        return True, True
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True, True
    except OSError:
        return True, False
    return True, True


def worker_command(request, native, output, mapping, frames, recover):
    command = [sys.executable, str(FULL_CYCLE),
               "--request", str(request), "--native-root", str(native),
               "--output-root", str(output)]
    if mapping is not None:
        command += ["--mapping", str(mapping)]
    for frame in frames:
        command += ["--frame", str(frame)]
    if recover:
        command.append("--recover-interrupted")
    return command


def launch(command, profile, log):
    started = time.monotonic()
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("wb") as stream:
        process = subprocess.Popen([str(item) for item in command], cwd=REPO,
                                   env=_env(profile), stdout=stream,
                                   stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        code = process.wait()
    return dict(command=[str(item) for item in command], returncode=code,
                elapsed_s=round(time.monotonic() - started, 3), log=str(log),
                termination_verified=process.poll() is not None)


def aggregate(parent, roots):
    """Aggregate isolated worker ledgers; refuse mixed numerical families."""
    parent = Path(parent)
    workers = []
    frames = {}
    families = {}
    for index, root in enumerate(roots):
        record = dict(worker=index, root=str(root), status=None, completion_status=None)
        ledger_path = root / "campaign.json"
        if not ledger_path.is_file():
            record["status"] = "MISSING_LEDGER"
            workers.append(record)
            continue
        ledger = read(ledger_path)
        record["completion_status"] = ledger.get("completion_status")
        record["consumed_compute_s"] = ledger.get("consumed_compute_s")
        record["status"] = "READ"
        for row in ledger.get("attempts", []):
            frame = int(row["phase_index"])
            label = row.get("label") or ("frame-%02d-001" % frame)
            result_path = root / label / "result.json"
            family = read(result_path).get("comparison_family_sha256") if result_path.is_file() else None
            item = dict(worker=index, phase_index=frame, status=row.get("status"),
                        drag_N=row.get("drag_N"), Cd=row.get("Cd"),
                        execution_elapsed_s=row.get("execution_elapsed_s"),
                        comparison_family_sha256=family)
            frames[frame] = item
            if row.get("status") == "PASS" and family:
                families.setdefault(family, []).append(frame)
        workers.append(record)
    if len(families) > 1:
        raise ValueError("Parallel campaign mixes numerical families: "
                         + json.dumps({key: sorted(value) for key, value in families.items()}))
    order = sorted(frames)
    values = [frames[frame] for frame in order]
    passed = [item for item in values if item["status"] == "PASS"]
    mean_drag = (sum(item["drag_N"] for item in passed) / len(passed)) if passed else None
    summary = dict(schema_version=AGGREGATE_SCHEMA,
                   generated_utc=datetime.now(timezone.utc).isoformat(),
                   workers=workers, frames=values,
                   families=sorted(families),
                   pass_count=len(passed), frame_count=len(values),
                   mean_drag_N=mean_drag,
                   ranking_eligible=False, scientific_approval=None)
    write(parent / "parallel-campaign.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--native-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_PARENT)
    parser.add_argument("--mapping", type=Path)
    parser.add_argument("--frame", type=int, action="append")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--ranks", type=int)
    parser.add_argument("--profile", default="batch")
    parser.add_argument("--scratch", action="store_true",
                        help="run worker roots under the NVMe scratch and copy canonical artifacts back")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--aggregate-only", action="store_true",
                        help="re-aggregate existing isolated worker ledgers without running workers")
    args = parser.parse_args()
    if args.workers or args.ranks:
        profile = resolve_pair(args.workers or 1, args.ranks or 4)
    else:
        profile = resolve(args.profile)
    frames = args.frame if args.frame else list(range(32))
    groups = assign(frames, profile["workers"])
    parent = Path(args.output_root).resolve()
    if not cfd_paths.is_private(parent, REPO):
        raise ValueError("Parallel campaign root must stay private")
    parent.mkdir(parents=True, exist_ok=True)
    if args.scratch:
        reason = preflight(parent)
        if reason:
            raise ValueError("Scratch preflight refused: " + reason)
    plan = dict(schema_version=REQUEST_SCHEMA,
                request=str(args.request), native_root=str(args.native_root),
                output_root=str(parent), mapping=(str(args.mapping) if args.mapping else None),
                frames=frames, profile=profile, groups={str(k): v for k, v in groups.items()},
                scratch=bool(args.scratch), generated_utc=datetime.now(timezone.utc).isoformat())
    write(parent / "parallel-request.json", plan)
    if args.dry_run:
        print(json.dumps(plan, indent=2))
        return 0
    runs = []
    started = time.monotonic()
    for index in sorted(groups):
        assigned = groups[index]
        if not assigned:
            continue
        root = worker_root(parent, index)
        has_marker, alive = marker_process_alive(root)
        if has_marker and alive:
            raise RuntimeError("Worker %02d has a live campaign marker; refusing to duplicate" % index)
        runs.append(dict(worker=index, frames=assigned, root=str(root), recover=has_marker))
    if args.aggregate_only:
        summary = aggregate(parent, [Path(item["root"]) for item in runs])
        summary["aggregate_only"] = True
        summary["frame_selection"] = frames
        write(parent / "parallel-campaign.json", summary)
        print(json.dumps(dict(pass_count=summary["pass_count"], frame_count=summary["frame_count"],
                              families=summary["families"]), indent=2))
        return 0 if summary["pass_count"] == len(frames) else 2
    started_utc = datetime.now(timezone.utc).isoformat()
    processes = []
    for item in runs:
        command = worker_command(args.request, args.native_root, Path(item["root"]), args.mapping,
                                item["frames"], recover=item["recover"])
        log = Path(item["root"]) / "parallel-worker.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        stream = log.open("wb")
        processes.append(dict(item=item, log=log, stream=stream,
                              process=subprocess.Popen([str(x) for x in command], cwd=REPO,
                                                       env=_env(profile), stdout=stream,
                                                       stderr=subprocess.STDOUT,
                                                       stdin=subprocess.DEVNULL)))
        print("PARALLEL_WORKER_START", item["worker"], item["frames"], flush=True)
    for entry in processes:
        code = entry["process"].wait()
        entry["stream"].close()
        entry["item"]["execution"] = dict(returncode=code, log=str(entry["log"]),
                                          termination_verified=entry["process"].poll() is not None)
        print("PARALLEL_WORKER_END", entry["item"]["worker"], code, flush=True)
    summary = aggregate(parent, [Path(item["root"]) for item in runs])
    summary["wall_elapsed_s"] = round(time.monotonic() - started, 3)
    summary["started_utc"] = started_utc
    summary["worker_runs"] = runs
    write(parent / "parallel-campaign.json", summary)
    if args.scratch:
        copied = []
        for item in runs:
            scratch_frame_root = Path(item["root"])
            for frame in item["frames"]:
                label = "frame-%02d-001" % frame
                source = scratch_frame_root / label
                if source.is_dir():
                    archive_frame = parent / label
                    manifest = copy_back_frame(source, archive_frame)
                    copied.append(dict(frame=frame, manifest=manifest["files"],
                                       scratch_only=manifest["scratch_only"]))
        write(parent / "scratch-copyback.json", dict(
            schema_version="phase1-scratch-copyback-report-1", frames=copied,
            generated_utc=datetime.now(timezone.utc).isoformat()))
    return 0 if summary["pass_count"] == len(frames) else 2


if __name__ == "__main__":
    raise SystemExit(main())
