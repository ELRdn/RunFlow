"""Run the approved 32-pose Phase 1 cycle sequentially with checkpoints."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import os
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from runflow.core import digest, file_hash, read, write
from runflow import cfd_guard
from runflow.cfd_cycle import FRAME_COUNT, execute_frame, validate_cycle_manifest
from runflow.cfd_paths import reserve_reason
from runflow.cfd_study import verify_authorization


def _top_level_executions(root):
    records = []
    for path in sorted(root.glob("*.execution.json")):
        try:
            records.append(dict(file=path.name, **read(path)))
        except (OSError, ValueError):
            records.append(dict(file=path.name, readable=False))
    return records


def _frame_execution(root, started_epoch):
    state = read(root / "state.json") if (root / "state.json").exists() else {}
    ended = state.get("completed_epoch") or time.time()
    top = _top_level_executions(root)
    rss = [item.get("peak_rss_bytes") for item in top if isinstance(item.get("peak_rss_bytes"), (int, float))]
    return dict(elapsed_s=max(0.0, float(ended) - float(started_epoch)),
                output_bytes=cfd_guard.directory_bytes(root),
                peak_rss_bytes=max(rss, default=0), termination_verified=all(
                    item.get("termination_verified", True) for item in top), stages=top)


def validate_request(request):
    if request.get("schema_version") != "phase1-cycle-campaign-1":
        raise ValueError("Wrong cycle campaign request schema")
    if request.get("frame_count") != FRAME_COUNT or request.get("scientific_approval") is not None or request.get("ranking_eligible") is not False:
        raise ValueError("Cycle request must remain 32-frame, unapproved, and ranking-ineligible")
    authority_path = Path(request["authorization_path"]).resolve()
    authority = read(authority_path)
    verify_authorization(authority)
    if digest(authority) != request.get("authorization_sha256"):
        raise ValueError("Cycle authorization changed")
    adoption_path = Path(request["adoption_path"]).resolve()
    if file_hash(adoption_path) != request.get("adoption_sha256"):
        raise ValueError("Cycle adoption record changed")
    manifest_path = Path(request["manifest_path"]).resolve()
    if file_hash(manifest_path) != request.get("source_manifest_sha256"):
        raise ValueError("Cycle source manifest changed")
    verified = validate_cycle_manifest(manifest_path, Path(request["source_root"]))
    if verified["manifest"]["config_sha256"] != request.get("intake_config_sha256"):
        raise ValueError("Cycle intake config changed")
    expected = [(row["index"], row["sha256"], row["time_s"]) for row in verified["frames"]]
    actual = [(row.get("index"), row.get("sha256"), row.get("time_s")) for row in request.get("frames", [])]
    if expected != actual:
        raise ValueError("Cycle request frames do not match the verified intake")
    prior_root = Path(request["prior_campaign_root"]).resolve()
    prior_ledger = prior_root / "campaign.json"
    if file_hash(prior_ledger) != request.get("prior_campaign_sha256"):
        raise ValueError("Prior sensitivity ledger changed")
    prior = read(prior_ledger)
    if float(prior.get("consumed_compute_s")) != float(request.get("prior_consumed_compute_s")):
        raise ValueError("Prior sensitivity compute accounting changed")
    if request.get("execution_budget_s") != 86400 or request.get("trial_limit_s") != 3600:
        raise ValueError("Cycle campaign budget must remain the approved 24-hour/1-hour limit")
    return verified, authority, prior


def _load_ledger(root, request):
    path = root / "campaign.json"
    if path.exists():
        ledger = read(path)
        if ledger.get("request_sha256") != digest(request):
            raise ValueError("Existing cycle campaign request differs")
        return ledger
    return dict(schema_version="phase1-cycle-campaign-execution-1", request_sha256=digest(request),
                started_utc=datetime.now(timezone.utc).isoformat(), attempts=[], skipped=[],
                scientific_approval=None, ranking_eligible=False,
                prior_consumed_compute_s=float(request["prior_consumed_compute_s"]), cycle_compute_s=0.0,
                consumed_compute_s=float(request["prior_consumed_compute_s"]),
                auxiliary_reserved_s=int(request["auxiliary_reserved_s"]),
                remaining_budget_s=max(0.0, float(request["execution_budget_s"]) - float(request["prior_consumed_compute_s"]) - float(request["auxiliary_reserved_s"])))


def run(request, selected=None):
    verified, authority, prior = validate_request(request)
    root = Path(request["output_root"]).resolve()
    # cfd.private rejects arbitrary output locations before anything is written.
    from runflow import cfd
    root = cfd.private(root)
    if root.exists() and not root.is_dir():
        raise ValueError("Cycle output root is not a directory")
    root.mkdir(parents=True, exist_ok=True)
    request_path = root / "request.json"
    if request_path.exists() and read(request_path) != request:
        raise ValueError("Cycle output root request differs")
    if not request_path.exists():
        write(request_path, request)
        write(root / "authorization.json", authority)
        write(root / "source-manifest.json", verified["manifest"])
        write(root / "prior-campaign-reference.json", dict(root=str(request["prior_campaign_root"]),
                                                            sha256=request["prior_campaign_sha256"],
                                                            consumed_compute_s=prior["consumed_compute_s"]))
    ledger_path = root / "campaign.json"
    ledger = _load_ledger(root, request)
    if (root / "active.json").exists():
        raise ValueError("Cycle campaign has an active/interrupted frame; inspect before continuing")
    write(ledger_path, ledger)
    requested = list(range(FRAME_COUNT)) if selected is None else selected
    if any(frame not in range(FRAME_COUNT) for frame in requested):
        raise ValueError("Frame selection must be between 0 and 31")
    if len(set(requested)) != len(requested):
        raise ValueError("Duplicate frame selection")
    done = {int(row["phase_index"]) for row in ledger["attempts"]}
    done.update(int(row["phase_index"]) for row in ledger["skipped"])
    frames = {row["index"]: row for row in verified["frames"]}
    failures = []
    for frame in requested:
        if frame in done:
            continue
        current_cycle = float(ledger.get("cycle_compute_s", 0.0))
        remaining = float(request["execution_budget_s"]) - float(request["auxiliary_reserved_s"])
        if float(request["prior_consumed_compute_s"]) + current_cycle + float(request["trial_limit_s"]) > remaining:
            record = dict(phase_index=frame, status="NOT_RUN_BUDGET", reason="Predicted trial would exceed the 24-hour campaign budget",
                          prediction=dict(trial_limit_s=request["trial_limit_s"], remaining_s=remaining - float(request["prior_consumed_compute_s"]) - current_cycle))
            ledger["skipped"].append(record)
            write(ledger_path, ledger)
            print("CYCLE_FRAME_SKIPPED", frame, record["reason"], flush=True)
            continue
        reserve = reserve_reason(root)
        if reserve:
            record = dict(phase_index=frame, status="NOT_RUN_RESOURCE", reason=reserve)
            ledger["skipped"].append(record)
            write(ledger_path, ledger)
            print("CYCLE_FRAME_SKIPPED", frame, reserve, flush=True)
            break
        frame_record = frames[frame]
        label = f"frame-{frame:02d}-001"
        frame_root = root / label
        if frame_root.exists():
            raise ValueError("Untracked existing cycle frame output: " + label)
        started_epoch = time.time()
        write(root / "active.json", dict(phase_index=frame, label=label, pid=os.getpid(), started_epoch=started_epoch))
        print("CYCLE_FRAME_BEGIN", frame, flush=True)
        try:
            result = execute_frame(request, frame_record, root, distro=request.get("distro", "Ubuntu"))
            if not (frame_root / "result.json").exists():
                raise RuntimeError("Cycle frame returned without result.json")
            execution = _frame_execution(frame_root, started_epoch)
            status = result["execution_status"]
            record = dict(phase_index=frame, label=label, status=status,
                          result_sha256=file_hash(frame_root / "result.json"), execution=execution,
                          output_bytes=execution["output_bytes"], source_sha256=frame_record["sha256"],
                          comparison_family_sha256=result.get("comparison_family_sha256"))
            ledger["attempts"].append(record)
            ledger["cycle_compute_s"] = sum(float(row["execution"]["elapsed_s"]) for row in ledger["attempts"])
            ledger["consumed_compute_s"] = float(request["prior_consumed_compute_s"]) + ledger["cycle_compute_s"]
            ledger["remaining_budget_s"] = max(0.0, float(request["execution_budget_s"]) - float(request["auxiliary_reserved_s"]) - ledger["consumed_compute_s"])
            write(ledger_path, ledger)
            (root / "active.json").unlink()
            if status != "PASS":
                failures.append(frame)
            print("CYCLE_FRAME_END", frame, status, round(execution["elapsed_s"], 2), flush=True)
        except Exception:
            # Preserve active.json so a partial/unverified process is never treated as a completed frame.
            raise
    ledger["completion_status"] = "COMPLETE_REQUESTED_FRAMES" if all(frame in {int(row["phase_index"]) for row in ledger["attempts"] + ledger["skipped"]} for frame in requested) else "PAUSED"
    ledger["scientific_approval"] = None
    ledger["ranking_eligible"] = False
    write(ledger_path, ledger)
    print("CYCLE_CAMPAIGN_FINISHED", ledger["completion_status"], "failed_or_unconverged", failures, flush=True)
    return ledger, failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--frame", type=int, action="append", help="Run only selected frame(s); default is all remaining")
    args = parser.parse_args()
    ledger, failures = run(read(args.request), args.frame)
    return 0 if not failures and ledger.get("completion_status") == "COMPLETE_REQUESTED_FRAMES" else 2


if __name__ == "__main__":
    raise SystemExit(main())
