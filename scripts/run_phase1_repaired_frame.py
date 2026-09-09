"""Run one Phase 1 cycle frame with a verified private repair candidate.

The ordinary cycle campaign remains unchanged.  This entry point is for a
frame whose native voxel surface failed Foundation surfaceCheck but whose
separate repair and shape-audit evidence passed all gates.
"""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from runflow import cfd
from runflow.cfd_cycle import prepare_frame, run_frame
from runflow.core import digest, file_hash, read, write

from run_phase1_cycle_campaign import validate_request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--frame", type=int, required=True)
    parser.add_argument("--surface", type=Path, required=True)
    parser.add_argument("--shape-audit", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    request = read(args.request)
    verified, authority, prior = validate_request(request)
    rows = {int(row["index"]): row for row in verified["frames"]}
    if args.frame not in rows:
        raise ValueError("Requested frame is not in the verified cycle intake")
    output = cfd.private(args.output_root)
    if output.exists():
        raise ValueError("Fresh repaired-frame output root required")
    candidate = cfd.private(args.surface)
    audit_root = cfd.private(args.shape_audit)
    if not candidate.is_file() or not audit_root.is_dir():
        raise ValueError("Repair candidate or shape-audit root is missing")

    run_request = deepcopy(request)
    run_request["output_root"] = str(output)
    output.mkdir(parents=True, exist_ok=False)
    write(output / "request.json", run_request)
    write(output / "authorization.json", authority)
    write(output / "source-manifest.json", verified["manifest"])
    write(output / "prior-campaign-reference.json", dict(
        root=str(request["prior_campaign_root"]),
        sha256=request["prior_campaign_sha256"],
        consumed_compute_s=prior["consumed_compute_s"],
    ))
    started = time.time()
    frame_root = output / f"frame-{args.frame:02d}-001"
    result = prepare_frame(
        run_request,
        rows[args.frame],
        output,
        distro=run_request.get("distro", "Ubuntu"),
        surface_override=candidate,
        shape_audit_root=audit_root,
    )
    if result.get("execution_status") == "PREPARED":
        result = run_frame(frame_root, distro=run_request.get("distro", "Ubuntu"))
    summary = dict(
        schema_version="phase1-repaired-frame-run-1",
        request_sha256=digest(run_request),
        frame=args.frame,
        result_sha256=file_hash(frame_root / "result.json"),
        candidate_sha256=file_hash(candidate),
        status=result.get("execution_status"),
        started_utc=datetime.fromtimestamp(started, timezone.utc).isoformat(),
        elapsed_s=time.time() - started,
        scientific_approval=None,
        ranking_eligible=False,
    )
    write(output / "repair-run.json", summary)
    print("PHASE1_REPAIRED_FRAME_FINISHED", summary, flush=True)
    return 0 if result.get("execution_status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
