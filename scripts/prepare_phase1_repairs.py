"""Prepare repaired cycle frames concurrently and emit a mapping document.

Runs the per-frame prepare step for several frames at once.  Each frame owns a
private repair root, audit root, and state directory, so no shared mutable file
is written.  A frame that fails leaves its own evidence in place and does not
stop the others; the assembler only emits rows that passed the existing CFD
admission gate.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from runflow import cfd
from runflow.core import file_hash, read, write


DEFAULT_STATE = Path("D:/RunFlowScratch/phase-b/state")
DEFAULT_MAPPING = Path("D:/RunFlowScratch/phase-b/repaired-mapping-001.json")
FRAME = str(REPO / "scripts/prepare_phase1_repair_frame.py")


def assemble(state_root, frames, destination):
    rows = []
    missing = []
    for frame in frames:
        entry_path = cfd.private(state_root) / f"frame-{frame:02d}" / "mapping-entry.json"
        if entry_path.is_file():
            entry = read(entry_path)
            rows.append(dict(index=int(entry["index"]), surface=entry["surface"],
                             shape_audit=entry["shape_audit"],
                             candidate_sha256=entry.get("candidate_sha256"),
                             repair_sha256=entry.get("repair_sha256"),
                             geometry_sha256=entry.get("geometry_sha256"),
                             shape_audit_sha256=entry.get("shape_audit_sha256"),
                             source_sha256=entry.get("source_sha256")))
        else:
            missing.append(int(frame))
    rows.sort(key=lambda row: row["index"])
    destination = cfd.private(destination)
    document = dict(schema_version="phase1-repaired-cycle-mapping-1",
                    generated_utc=datetime.now(timezone.utc).isoformat(),
                    frames=rows)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return document, missing


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=int, nargs="+", required=True)
    parser.add_argument("--parallel", type=int, default=3)
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--mapping-out", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--distro", default="Ubuntu")
    parser.add_argument("--stage-timeout-s", type=float, default=5400.0)
    parser.add_argument("--repair-budget-s", type=float, default=5400.0)
    parser.add_argument("--max-rounds", type=int, default=6)
    parser.add_argument("--projection-workers", type=int, default=3)
    parser.add_argument("--no-overlap", action="store_true")
    parser.add_argument("--assemble-only", action="store_true")
    args = parser.parse_args()

    frames = [int(item) for item in args.frames]
    if len(set(frames)) != len(frames):
        raise ValueError("Frame list must be unique")
    state_root = cfd.private(args.state_root)
    state_root.mkdir(parents=True, exist_ok=True)

    results = []
    if not args.assemble_only:
        pending = list(frames)
        running = []
        limit = max(1, int(args.parallel))
        started = time.monotonic()
        while pending or running:
            while pending and len(running) < limit:
                frame = pending.pop(0)
                log = state_root / f"frame-{frame:02d}.prepare.log"
                stream = log.open("wb")
                command = [sys.executable, FRAME, "--frame", str(frame),
                           "--state-root", str(args.state_root), "--distro", args.distro,
                           "--stage-timeout-s", str(args.stage_timeout_s),
                           "--repair-budget-s", str(args.repair_budget_s),
                           "--max-rounds", str(args.max_rounds),
                           "--projection-workers", str(args.projection_workers)]
                if args.no_overlap:
                    command.append("--no-overlap")
                process = subprocess.Popen(command, cwd=REPO, stdout=stream, stderr=subprocess.STDOUT)
                running.append(dict(frame=frame, process=process, stream=stream, log=log,
                                    started=time.monotonic()))
                print("PREPARE_START", frame, flush=True)
            time.sleep(5)
            still = []
            for item in running:
                code = item["process"].poll()
                if code is None:
                    still.append(item)
                    continue
                item["stream"].close()
                elapsed = time.monotonic() - item["started"]
                results.append(dict(frame=item["frame"], returncode=code,
                                    elapsed_s=elapsed, log=str(item["log"])))
                print("PREPARE_END", item["frame"], code, round(elapsed, 1), flush=True)
            running = still

    document, missing = assemble(Path(args.state_root), frames, args.mapping_out)
    summary = dict(frames=frames, passed=[row["index"] for row in document["frames"]],
                   missing=missing, mapping=str(cfd.private(args.mapping_out)),
                   mapping_sha256=file_hash(cfd.private(args.mapping_out)),
                   results=results, total_elapsed_s=None)
    summary_path = state_root / "prepare-summary.json"
    write(summary_path, summary)
    print("PREPARE_SUMMARY", json.dumps({k: summary[k] for k in ("passed", "missing")}), flush=True)
    return 0 if not missing else 2


if __name__ == "__main__":
    raise SystemExit(main())
