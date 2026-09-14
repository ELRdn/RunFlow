"""Collect isolated Phase 1 lanes and aggregate the nested pilot schedules.

Four concurrent lanes each own a single-writer campaign ledger, so the parent
never shares a mutable file.  This collector reads every lane, refuses a mix of
numerical families, and reports the nested 8 / 16 / 32 schedules through the
protocol's own gait-cycle functions.  A schedule that is missing a phase stays
INCOMPLETE; no missing pose is imputed.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from runflow import cfd
from runflow.core import read, write
from runflow.gait_cycle import aggregate, nested_indices, sampling_comparison


def collect(lane_roots):
    rows = []
    lanes = []
    for index, lane in enumerate(lane_roots):
        lane = Path(lane).resolve()
        worker = lane / "worker-00"
        ledger_path = worker / "campaign.json"
        record = dict(lane=index, root=str(lane), worker=str(worker), status=None)
        if not ledger_path.is_file():
            record["status"] = "MISSING_LEDGER"
            lanes.append(record)
            continue
        ledger = read(ledger_path)
        record["completion_status"] = ledger.get("completion_status")
        record["consumed_compute_s"] = ledger.get("consumed_compute_s")
        record["status"] = "READ"
        for attempt in ledger.get("attempts", []):
            frame = int(attempt["phase_index"])
            label = attempt.get("label") or ("frame-%02d-001" % frame)
            result_path = worker / label / "result.json"
            if not result_path.is_file():
                rows.append(dict(phase_index=frame, execution_status="FAIL",
                                 reason="result.json missing", lane=index))
                continue
            result = read(result_path)
            rows.append(dict(
                phase_index=frame, lane=index, label=label,
                execution_status=result.get("execution_status"),
                drag_N=result.get("drag_N"), Cd=result.get("Cd"),
                CdA_m2=result.get("CdA_m2"), source_area_m2=result.get("source_area_m2"),
                comparison_family_sha256=result.get("comparison_family_sha256"),
                execution_elapsed_s=attempt.get("execution_elapsed_s"),
                result_sha256=attempt.get("result_sha256"),
                candidate_sha256=attempt.get("candidate_sha256"),
                shape_audit_sha256=attempt.get("shape_audit_sha256"),
            ))
        lanes.append(record)
    rows.sort(key=lambda row: row["phase_index"])
    return lanes, rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lane", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    lanes, rows = collect(args.lane)
    families = sorted({row["comparison_family_sha256"] for row in rows
                       if row.get("execution_status") == "PASS"
                       and row.get("comparison_family_sha256")})
    if len(families) > 1:
        raise ValueError("Pilot lanes mix numerical families: " + json.dumps(families))

    schedules = {}
    for count in (8, 16, 32):
        expected = nested_indices(count)
        present = [row for row in rows if row["phase_index"] in expected]
        schedules[str(count)] = aggregate(present, count) if present else dict(
            status="INCOMPLETE", samples=count, missing_or_failed=expected,
            mean_drag_N=None, mean_CdA_m2=None)
    comparison = sampling_comparison([row for row in rows
                                      if row.get("execution_status") == "PASS"])

    summary = dict(
        schema_version="phase1-pilot-aggregate-1",
        generated_utc=datetime.now(timezone.utc).isoformat(),
        lanes=lanes,
        frames=rows,
        families=families,
        passed=sorted(row["phase_index"] for row in rows
                      if row.get("execution_status") == "PASS"),
        failed=sorted(row["phase_index"] for row in rows
                      if row.get("execution_status") != "PASS"),
        mean_drag_N=(sum(row["drag_N"] for row in rows
                         if row.get("execution_status") == "PASS")
                     / max(1, len([row for row in rows
                                   if row.get("execution_status") == "PASS"]))
                     if any(row.get("execution_status") == "PASS" for row in rows) else None),
        schedules=schedules,
        sampling_comparison=comparison,
        scientific_approval=None,
        ranking_eligible=False,
    )
    destination = cfd.private(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("PILOT_COLLECTED", json.dumps(dict(
        passed=summary["passed"], failed=summary["failed"], families=families,
        schedule_8=schedules["8"].get("status"),
        schedule_16=schedules["16"].get("status"),
        schedule_32=schedules["32"].get("status")), ensure_ascii=False), flush=True)
    if args.report is not None:
        write(args.report, dict(source=str(destination), summary=summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
