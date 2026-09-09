"""Prepare native Blender geometry for selected Phase 1 cycle frames.

This lane intentionally stops at the native Foundation surface gate.  It is
used to build a private, resumable inventory before any repair candidate is
audited or sent to CFD.  A frame that fails surfaceCheck keeps its native
candidate and diagnostics and does not block later frame preparation.
"""

import argparse
from datetime import datetime, timezone
from pathlib import Path
from copy import deepcopy
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from runflow import cfd
from runflow.cfd_cycle import FRAME_COUNT, prepare_frame
from runflow.cfd_guard import directory_bytes
from runflow.core import digest, file_hash, read, write

from run_phase1_cycle_campaign import validate_request


def run(request, frames):
    verified, authority, prior = validate_request(request)
    output = cfd.private(request["output_root"])
    run_request = deepcopy(request)
    run_request["output_root"] = str(output)
    if output.exists():
        if not output.is_dir():
            raise ValueError("Native geometry discovery output is not a directory")
        request_path = output / "request.json"
        if not request_path.is_file() or read(request_path) != run_request:
            raise ValueError("Existing native geometry discovery request differs")
    else:
        output.mkdir(parents=True, exist_ok=False)
        write(output / "request.json", run_request)
        write(output / "authorization.json", authority)
        write(output / "source-manifest.json", verified["manifest"])
        write(output / "prior-campaign-reference.json", dict(
            root=str(request["prior_campaign_root"]),
            sha256=request["prior_campaign_sha256"],
            consumed_compute_s=prior["consumed_compute_s"],
        ))
    rows = {int(row["index"]): row for row in verified["frames"]}
    selected = list(range(FRAME_COUNT)) if frames is None else list(frames)
    if not selected or len(set(selected)) != len(selected) or any(frame not in rows for frame in selected):
        raise ValueError("Frame selection must be unique and between 0 and 31")
    ledger_path = output / "campaign.json"
    if ledger_path.exists():
        ledger = read(ledger_path)
        if ledger.get("request_sha256") != digest(run_request):
            raise ValueError("Existing native geometry discovery request differs")
        attempts = list(ledger.get("attempts", []))
    else:
        attempts = []
    started = time.time()
    for frame in selected:
        frame_root = output / f"frame-{frame:02d}-001"
        if any(int(row.get("phase_index", -1)) == frame for row in attempts):
            continue
        if frame_root.exists():
            result_path = frame_root / "result.json"
            if not result_path.is_file():
                raise ValueError("Existing native frame output is incomplete: " + frame_root.name)
            result = read(result_path)
            if result.get("phase_index") != frame or result.get("execution_status") not in {"PASS", "FAIL"}:
                raise ValueError("Existing native frame result is not terminal: " + frame_root.name)
            record = dict(
                phase_index=frame,
                label=frame_root.name,
                status=result["execution_status"],
                reason=result.get("reason"),
                result_sha256=file_hash(result_path),
                source_sha256=rows[frame]["sha256"],
                elapsed_s=float(result.get("evidence", {}).get("blender", {}).get("elapsed_s", 0.0)),
                output_bytes=directory_bytes(frame_root),
                recovered=True,
            )
            attempts.append(record)
            write(ledger_path, dict(
                schema_version="phase1-native-cycle-geometry-discovery-1",
                request_sha256=digest(run_request),
                started_utc=datetime.fromtimestamp(started, timezone.utc).isoformat(),
                attempts=attempts,
                scientific_approval=None,
                ranking_eligible=False,
            ))
            print("NATIVE_CYCLE_FRAME_RECOVERED", frame, record["status"], flush=True)
            continue
        frame_started = time.time()
        print("NATIVE_CYCLE_FRAME_BEGIN", frame, flush=True)
        try:
            result = prepare_frame(run_request, rows[frame], output,
                                   distro=run_request.get("distro", "Ubuntu"))
            result_path = frame_root / "result.json"
            if not result_path.is_file():
                raise RuntimeError("Native frame returned without result.json")
            record = dict(
                phase_index=frame,
                label=frame_root.name,
                status=result["execution_status"],
                reason=result.get("reason"),
                result_sha256=file_hash(result_path),
                source_sha256=rows[frame]["sha256"],
                elapsed_s=time.time() - frame_started,
                output_bytes=directory_bytes(frame_root),
            )
            attempts.append(record)
            write(output / "campaign.json", dict(
                schema_version="phase1-native-cycle-geometry-discovery-1",
                request_sha256=digest(run_request),
                started_utc=datetime.fromtimestamp(started, timezone.utc).isoformat(),
                attempts=attempts,
                scientific_approval=None,
                ranking_eligible=False,
            ))
            print("NATIVE_CYCLE_FRAME_END", frame, record["status"], flush=True)
        except BaseException:
            # A partial frame must remain visible for inspection.  Do not
            # continue after an exception that could indicate an unverified
            # child process or a broken preparation contract.
            raise
    ledger = read(output / "campaign.json")
    ledger["completion_status"] = "COMPLETE_REQUESTED_FRAMES"
    write(output / "campaign.json", ledger)
    print("NATIVE_CYCLE_GEOMETRY_FINISHED", len(attempts), flush=True)
    return ledger


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--frame", type=int, action="append")
    args = parser.parse_args()
    request = read(args.request)
    request["output_root"] = str(args.output_root)
    run(request, args.frame)


if __name__ == "__main__":
    main()
