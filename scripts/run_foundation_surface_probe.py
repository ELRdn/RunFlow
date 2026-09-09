"""Run a bounded Foundation 14 surfaceCheck against a private candidate.

This is a diagnostic entry point for repair probes.  It creates only a hard
link inside the probe's ``geometry`` directory, so the candidate itself is
never rewritten or copied.  The external checker remains the acceptance gate.
"""

import argparse
from pathlib import Path
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from runflow import cfd
from runflow.core import read, write


def probe(root, candidate, timeout, distro):
    root = cfd.private(root)
    candidate = Path(candidate).resolve()
    if not candidate.is_file():
        raise ValueError("Surface candidate is missing: " + str(candidate))
    geometry = root / "geometry"
    geometry.mkdir(parents=True, exist_ok=False)
    link = geometry / "candidate.obj"
    link.hardlink_to(candidate)
    protocol = dict(
        schema_version="phase1-foundation-surface-probe-1",
        limits=dict(
            surface_s=float(timeout),
            total_s=float(timeout),
            memory_bytes=12 * 1024**3,
            output_bytes=10 * 1024**3,
            processes=4,
        ),
    )
    write(root / "protocol.json", protocol)
    started = time.time()
    write(root / "state.json", dict(
        started_epoch=started,
        started_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
        status="PROBING",
        stage="surface",
    ))
    try:
        result = cfd.worker(root, "surface", float(timeout), distro)
    except BaseException as exc:
        write(root / "probe-result.json", dict(
            execution_status="FAIL",
            error=str(exc),
            elapsed_s=time.time() - started,
            candidate_sha256=None,
        ))
        raise
    value = dict(
        execution_status="PASS",
        elapsed_s=time.time() - started,
        candidate=str(candidate),
        surface_worker=result,
        surface_check=read(root / "surface-worker.json"),
    )
    write(root / "probe-result.json", value)
    print("FOUNDATION_SURFACE_PROBE", value, flush=True)
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--distro", default="Ubuntu")
    args = parser.parse_args()
    probe(args.root, args.candidate, args.timeout, args.distro)


if __name__ == "__main__":
    main()
