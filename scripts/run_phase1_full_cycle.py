"""Run the repaired 0.9 mm Phase 1 cycle with resumable private ledgers.

Native Blender cycle frames are retained as the source of truth.  A frame can
enter CFD only after a private repair candidate passes Foundation surfaceCheck
and the complete shape-audit contract.  Existing verified candidate/audit
pairs may be supplied through a mapping file; all other frames are prepared in
the order repair -> audit -> CFD.  The campaign never changes a source frame,
never retries a failed CFD attempt automatically, and keeps scientific approval
separate from execution status.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from runflow import cfd
from runflow.cfd_cycle import FRAME_COUNT, _surface_override_info, execute_frame
from runflow.cfd_paths import reserve_reason
from runflow.core import digest, file_hash, read, write
from runflow.shape_fullbody import LIMITS

from run_phase1_cycle_campaign import validate_request


GIB = 1024 ** 3
DEFAULT_OUTPUT = Path("E:/RunFlowPrivate/phase1/cycle-phase1-full-001")
DEFAULT_REPAIR_ROOT = Path("E:/RunFlowPrivate/phase1/cycle-repair-campaign-001")


def _limits():
    return dict(LIMITS, resource_grace_s=5)


def _env():
    value = os.environ.copy()
    value.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="20", RUNFLOW_CPU_COUNT="20")
    return value


def _portable_private(value):
    path = cfd.private(value)
    return path


def _now():
    return datetime.now(timezone.utc).isoformat()


def _owned_process(command, root, name, timeout):
    """Run a campaign child and terminate its process group on timeout.

    Repair and CFD stages already use their own resource guards.  This outer
    guard is only for campaign accounting and stale-run prevention; it does
    not hide the child execution JSON written by the invoked command.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    log = root / (name + ".campaign.log")
    started = time.monotonic()
    if timeout <= 0:
        raise TimeoutError("Phase 1 campaign budget exhausted before " + name)
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = subprocess.Popen(
        [str(item) for item in command], cwd=REPO, env=_env(),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", creationflags=flags,
        start_new_session=(os.name != "nt"),
    )
    output = []
    try:
        text, _ = process.communicate(timeout=max(1.0, float(timeout)))
        output.append(text or "")
    except subprocess.TimeoutExpired as exc:
        output.append(exc.stdout or "")
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           check=False)
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            tail, _ = process.communicate(timeout=30)
            output.append(tail or "")
        except subprocess.TimeoutExpired:
            process.kill()
            tail, _ = process.communicate()
            output.append(tail or "")
        log.write_text("".join(output), encoding="utf-8")
        raise TimeoutError(name + " timed out")
    log.write_text("".join(output), encoding="utf-8")
    return dict(
        command=[str(item) for item in command],
        elapsed_s=time.monotonic() - started,
        returncode=process.returncode,
        log=str(log),
        termination_verified=process.poll() is not None,
    )


def _load_mapping(path, verified):
    if path is None:
        return {}
    mapping_path = _portable_private(path)
    value = read(mapping_path)
    if value.get("schema_version") != "phase1-repaired-cycle-mapping-1":
        raise ValueError("Wrong repaired cycle mapping schema")
    rows = value.get("frames")
    if not isinstance(rows, list):
        raise ValueError("Repaired cycle mapping frames must be a list")
    expected = {int(row["index"]): row for row in verified["frames"]}
    result = {}
    for row in rows:
        index = int(row.get("index", -1))
        if index not in expected or index in result:
            raise ValueError("Duplicate or unknown repaired mapping frame: " + str(index))
        candidate = _portable_private(row.get("surface", ""))
        audit = _portable_private(row.get("shape_audit", ""))
        if not candidate.is_file() or not audit.is_dir():
            raise ValueError("Repaired mapping input is missing for frame " + str(index))
        # This is the same gate used by prepare_frame.  It binds the candidate
        # to the source frame and verifies all six audit artifacts.
        info, records = _surface_override_info(
            candidate, audit, expected_source_sha256=expected[index]["sha256"]
        )
        if info is None or records is None:
            raise ValueError("Repaired mapping could not be validated for frame " + str(index))
        result[index] = dict(
            index=index,
            surface=str(candidate),
            shape_audit=str(audit),
            candidate_sha256=info["candidate_sha256"],
            repair_sha256=info["repair_sha256"],
            geometry_sha256=info["geometry_sha256"],
            shape_audit_sha256=info["shape_audit_sha256"],
            source_sha256=expected[index]["sha256"],
        )
    return dict(path=mapping_path, sha256=file_hash(mapping_path), rows=result)


def _load_or_create(root, request, mapping, verified, authority, prior):
    path = root / "campaign.json"
    if path.exists():
        ledger = read(path)
        if ledger.get("request_sha256") != digest(request):
            raise ValueError("Existing repaired cycle request differs")
        if ledger.get("mapping_sha256") != mapping.get("sha256"):
            raise ValueError("Existing repaired cycle mapping differs")
        return ledger
    ledger = dict(
        schema_version="phase1-repaired-cycle-campaign-1",
        request_sha256=digest(request),
        mapping_sha256=mapping.get("sha256"),
        started_utc=_now(),
        attempts=[], skipped=[],
        scientific_approval=None,
        ranking_eligible=False,
        prior_consumed_compute_s=float(request["prior_consumed_compute_s"]),
        auxiliary_reserved_s=int(request["auxiliary_reserved_s"]),
        repair_audit_compute_s=0.0,
        cycle_compute_s=0.0,
        consumed_compute_s=float(request["prior_consumed_compute_s"]),
        execution_budget_s=float(request["execution_budget_s"]),
        completion_status="NOT_STARTED",
    )
    write(path, ledger)
    return ledger


def _remaining(request, ledger):
    return max(0.0, float(request["execution_budget_s"]) -
               float(request["auxiliary_reserved_s"]) -
               float(request["prior_consumed_compute_s"]) -
               float(ledger.get("repair_audit_compute_s", 0.0)) -
               float(ledger.get("cycle_compute_s", 0.0)))


def _done(ledger):
    # A failed attempt is evidence to retain, not a completed frame.  This
    # lets an explicit recovery run retry a failed frame while keeping every
    # previous attempt in the private ledger.
    successful = {
        int(row["phase_index"])
        for row in ledger.get("attempts", [])
        if row.get("status") == "PASS"
    }
    return successful | {int(row["phase_index"]) for row in ledger.get("skipped", [])}


def _pid_is_running(pid):
    """Return whether a process still owns the interrupted campaign marker."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        # The process exists but this user cannot query it.  Fail closed.
        return True
    except (OSError, ProcessLookupError):
        return False
    return True


def _recover_interrupted(output, ledger):
    """Archive a stopped frame and its marker before a deliberate rerun.

    Recovery is explicit so a live campaign can never be silently duplicated.
    The incomplete frame directory is renamed in place and remains available
    for forensic inspection; the next attempt may then recreate the canonical
    frame directory without overwriting the partial evidence.
    """
    active = output / "active.json"
    marker = read(active)
    try:
        frame = int(marker["phase_index"])
        pid = int(marker["pid"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Malformed interrupted campaign marker") from exc
    if frame not in range(FRAME_COUNT):
        raise ValueError("Interrupted campaign marker has an invalid frame")
    if _pid_is_running(pid):
        raise RuntimeError("Cannot recover while campaign PID is still running: " + str(pid))

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    frame_root = output / f"frame-{frame:02d}-001"
    archived_frame = output / f"frame-{frame:02d}-001.interrupted-{stamp}"
    archived_active = output / f"active.interrupted-{stamp}.json"
    if archived_frame.exists() or archived_active.exists():
        raise FileExistsError("Recovery archive target already exists")
    if frame_root.exists():
        frame_root.replace(archived_frame)
    active.replace(archived_active)

    recovery = dict(
        phase_index=frame,
        marker_pid=pid,
        marker_started_utc=marker.get("started_utc"),
        archived_frame=str(archived_frame) if archived_frame.exists() else None,
        archived_active=str(archived_active),
        recovered_utc=_now(),
    )
    ledger.setdefault("recoveries", []).append(recovery)
    ledger["completion_status"] = "RESUMING"
    ledger["recovered_interrupted_frame"] = frame
    write(output / "campaign.json", ledger)
    return recovery


def _run_repair(native_root, repair_root, frame, remaining, *, retry=False):
    output = repair_root / f"frame-{frame:02d}-001"
    if output.exists():
        if not retry:
            raise ValueError("Existing incomplete repair output requires manual inspection: " + str(output))
        serial = 1
        while True:
            candidate = repair_root / f"frame-{frame:02d}-retry-{serial:03d}"
            if not candidate.exists():
                output = candidate
                break
            serial += 1
    command = [
        sys.executable, str(REPO / "scripts/run_phase1_repair_pipeline.py"),
        "--native-root", str(native_root / f"frame-{frame:02d}-001"),
        "--output-root", str(output), "--distro", "Ubuntu",
        "--budget-s", str(max(1.0, remaining)),
    ]
    execution = _owned_process(command, repair_root, f"repair-frame-{frame:02d}", remaining)
    result_path = output / "repair-pipeline.json"
    result = read(result_path) if result_path.is_file() else {}
    if execution["returncode"] != 0 or result.get("execution_status") != "PASS":
        raise RuntimeError("Repair pipeline did not produce a PASS candidate for frame " + str(frame))
    return output, result, execution


def _audit_command(audit_root, stage, timeout):
    return [
        sys.executable, str(REPO / "scripts/audit_cycle_candidate.py"),
        "--output", str(audit_root), "--stage", stage,
        "--timeout", str(max(1.0, timeout)),
    ]


def _audit_complete(root):
    required = ["request.json", "source-to-candidate.json", "candidate-to-source.json",
                "projections.json", "views.json", "sections.json"]
    if any(not (root / name).is_file() for name in required):
        return False
    return all(read(root / name).get("complete") is True
               for name in required[1:])


def _run_audit(native_root, candidate, audit_root, frame, remaining):
    if audit_root.exists():
        if not _audit_complete(audit_root):
            raise ValueError("Existing incomplete shape audit requires manual inspection: " + str(audit_root))
    else:
        source = native_root / f"frame-{frame:02d}-001/geometry/candidate.obj"
        prepare = [
            sys.executable, str(REPO / "scripts/audit_cycle_candidate.py"), "--prepare",
            "--source", str(source), "--candidate", str(candidate),
            "--output", str(audit_root), "--cover-m", "0.001",
            "--projection-grid-m", "0.000000001", "--memory-gib", "80", "--output-gib", "300",
        ]
        _owned_process(prepare, audit_root.parent, f"audit-prepare-frame-{frame:02d}", remaining)
    for stage in ("distance", "projection", "views", "sections"):
        if stage == "distance":
            complete = (audit_root / "source-to-candidate.json").is_file() and (audit_root / "candidate-to-source.json").is_file()
        elif stage == "projection":
            complete = (audit_root / "projections.json").is_file() and read(audit_root / "projections.json").get("complete") is True
        else:
            complete = (audit_root / (stage + ".json")).is_file() and read(audit_root / (stage + ".json")).get("complete") is True
        if complete:
            continue
        if remaining <= 0:
            raise TimeoutError("Shape audit budget exhausted before frame " + str(frame))
        _owned_process(_audit_command(audit_root, stage, min(3600.0, remaining)),
                       audit_root, f"audit-{stage}-frame-{frame:02d}", min(3600.0, remaining))
    if not _audit_complete(audit_root):
        raise RuntimeError("Shape audit did not complete for frame " + str(frame))
    return audit_root


def run(request, *, output_root, native_root, mapping_path=None, selected=None,
        recover_interrupted=False):
    verified, authority, prior = validate_request(request)
    output = _portable_private(output_root)
    native_root = _portable_private(native_root)
    if not native_root.is_dir():
        raise ValueError("Native cycle discovery root is missing")
    mapping = _load_mapping(mapping_path, verified)
    if output.exists() and not output.is_dir():
        raise ValueError("Repaired cycle output root is not a directory")
    output.mkdir(parents=True, exist_ok=True)
    run_request = dict(request, output_root=str(output),
                       repaired_mapping_sha256=mapping.get("sha256"))
    request_path = output / "request.json"
    if request_path.exists() and read(request_path) != run_request:
        raise ValueError("Existing repaired cycle request differs")
    if not request_path.exists():
        write(request_path, run_request)
        write(output / "authorization.json", authority)
        write(output / "source-manifest.json", verified["manifest"])
        write(output / "mapping-reference.json", dict(
            path=str(mapping.get("path")) if mapping.get("path") else None,
            sha256=mapping.get("sha256"),
            rows={str(key): value for key, value in mapping.get("rows", {}).items()},
        ))
        write(output / "prior-campaign-reference.json", dict(
            root=str(request["prior_campaign_root"]),
            sha256=request["prior_campaign_sha256"],
            consumed_compute_s=prior["consumed_compute_s"],
        ))
    ledger = _load_or_create(output, run_request, mapping, verified, authority, prior)
    active = output / "active.json"
    recovered_frame = None
    if active.exists():
        if not recover_interrupted:
            raise ValueError("Repaired cycle has an active/interrupted frame; inspect before continuing")
        recovery = _recover_interrupted(output, ledger)
        recovered_frame = recovery["phase_index"]
    write(output / "campaign.json", ledger)
    requested = list(range(FRAME_COUNT)) if selected is None else [int(item) for item in selected]
    if any(item not in range(FRAME_COUNT) for item in requested) or len(set(requested)) != len(requested):
        raise ValueError("Frame selection must be unique and between 0 and 31")
    frames = {row["index"]: row for row in verified["frames"]}
    failures = []
    for frame in requested:
        if frame in _done(ledger):
            continue
        reserve = reserve_reason(output)
        if reserve:
            record = dict(phase_index=frame, status="NOT_RUN_RESOURCE", reason=reserve)
            ledger["skipped"].append(record)
            write(output / "campaign.json", ledger)
            break
        remaining = _remaining(run_request, ledger)
        if remaining <= 0:
            record = dict(phase_index=frame, status="NOT_RUN_BUDGET", reason="24-hour repaired cycle budget exhausted")
            ledger["skipped"].append(record)
            write(output / "campaign.json", ledger)
            break
        frame_root = output / f"frame-{frame:02d}-001"
        if frame_root.exists():
            raise ValueError("Untracked existing repaired CFD frame output: " + str(frame_root))
        write(active, dict(phase_index=frame, started_utc=_now(), pid=os.getpid()))
        frame_started = time.monotonic()
        repair_output = audit_root = None
        try:
            if frame in mapping.get("rows", {}):
                row = mapping["rows"][frame]
                candidate = Path(row["surface"])
                audit_root = Path(row["shape_audit"])
                repair_output = candidate.parent
                repair_info = dict(source="mapping", candidate_sha256=row["candidate_sha256"],
                                   repair_sha256=row["repair_sha256"],
                                   geometry_sha256=row["geometry_sha256"])
                audit_info = dict(source="mapping", shape_audit_sha256=row["shape_audit_sha256"])
                repair_execution = None
            else:
                repair_output, repair_info, repair_execution = _run_repair(
                    native_root, _portable_private(DEFAULT_REPAIR_ROOT), frame,
                    _remaining(run_request, ledger), retry=(recovered_frame == frame))
                repair_elapsed = float(repair_info.get("elapsed_s", repair_execution.get("elapsed_s", 0.0)))
                ledger["repair_audit_compute_s"] += repair_elapsed
                candidate = Path(repair_info["candidate"])
                audit_info = None
            audit_started = time.monotonic()
            if audit_root is None:
                audit_root = _portable_private(DEFAULT_REPAIR_ROOT) / f"shape-audit-frame-{frame:02d}-001"
                _run_audit(native_root, candidate, audit_root, frame,
                           _remaining(run_request, ledger))
                audit_info = dict(source="generated", shape_audit_sha256=digest({
                    name: file_hash(audit_root / name) for name in (
                        "request.json", "source-to-candidate.json", "candidate-to-source.json",
                        "projections.json", "views.json", "sections.json")
                }))
            audit_elapsed = time.monotonic() - audit_started
            if repair_execution is not None:
                ledger["repair_audit_compute_s"] += audit_elapsed
            candidate_info, _ = _surface_override_info(
                candidate, audit_root, expected_source_sha256=frames[frame]["sha256"])
            if candidate_info is None:
                raise ValueError("Candidate validation returned no candidate info")
            result = execute_frame(run_request, frames[frame], output,
                                   distro=run_request.get("distro", "Ubuntu"),
                                   surface_override=candidate, shape_audit_root=audit_root)
            if not (frame_root / "result.json").is_file():
                raise RuntimeError("Repaired frame returned without result.json")
            execution_s = time.monotonic() - frame_started
            result_record = dict(
                phase_index=frame,
                label=frame_root.name,
                status=result.get("execution_status"),
                result_sha256=file_hash(frame_root / "result.json"),
                candidate_sha256=candidate_info["candidate_sha256"],
                repair_sha256=candidate_info["repair_sha256"],
                shape_audit_sha256=candidate_info["shape_audit_sha256"],
                execution_elapsed_s=execution_s,
                repair_output=str(repair_output) if repair_output else None,
                audit_root=str(audit_root),
                drag_N=result.get("drag_N"), Cd=result.get("Cd"), CdA_m2=result.get("CdA_m2"),
                scientific_status="UNVALIDATED_PHASE1_CYCLE", ranking_eligible=False,
            )
            ledger["attempts"].append(result_record)
            ledger["cycle_compute_s"] += execution_s
            ledger["consumed_compute_s"] = (float(run_request["prior_consumed_compute_s"]) +
                                             float(ledger["repair_audit_compute_s"]) +
                                             float(ledger["cycle_compute_s"]))
            write(output / "campaign.json", ledger)
            active.unlink(missing_ok=True)
            if result.get("execution_status") != "PASS":
                failures.append(frame)
            print("REPAIRED_CYCLE_FRAME_END", frame, result.get("execution_status"), flush=True)
        except BaseException as exc:
            # Keep active.json so a partial frame cannot be mistaken for a
            # finished result.  The per-stage outputs remain available for
            # manual inspection and a new campaign root.
            if isinstance(exc, KeyboardInterrupt):
                ledger["completion_status"] = "PAUSED"
                ledger["interrupted_frame"] = frame
                ledger["interrupted_utc"] = _now()
                write(output / "campaign.json", ledger)
                raise
            record = dict(phase_index=frame, label=frame_root.name,
                          status="FAIL", reason=str(exc),
                          repair_output=str(repair_output) if repair_output else None,
                          audit_root=str(audit_root) if audit_root else None,
                          scientific_status="UNVALIDATED_PHASE1_CYCLE", ranking_eligible=False)
            ledger["attempts"].append(record)
            write(output / "campaign.json", ledger)
            failures.append(frame)
            raise
    completed = _done(ledger)
    ledger["completion_status"] = "COMPLETE_REQUESTED_FRAMES" if all(item in completed for item in requested) else "PAUSED"
    ledger["scientific_approval"] = None
    ledger["ranking_eligible"] = False
    write(output / "campaign.json", ledger)
    print("REPAIRED_CYCLE_CAMPAIGN_FINISHED", ledger["completion_status"], failures, flush=True)
    return ledger, failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--native-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--mapping", type=Path)
    parser.add_argument("--frame", type=int, action="append")
    parser.add_argument(
        "--recover-interrupted", action="store_true",
        help="archive a stopped frame after its marker PID is confirmed dead, then resume",
    )
    args = parser.parse_args()
    ledger, failures = run(read(args.request), output_root=args.output_root,
                           native_root=args.native_root, mapping_path=args.mapping,
                           selected=args.frame, recover_interrupted=args.recover_interrupted)
    return 0 if not failures and ledger.get("completion_status") == "COMPLETE_REQUESTED_FRAMES" else 2


if __name__ == "__main__":
    raise SystemExit(main())
