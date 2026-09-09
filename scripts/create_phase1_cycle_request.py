"""Create a hash-bound private request for the 32-pose Phase 1 cycle lane."""

import argparse
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from runflow.core import digest, file_hash, read, write
from runflow.cfd_cycle import FRAME_COUNT, validate_cycle_manifest
from runflow.cfd_study import verify_authorization


def create(manifest_path, source_root, prior_root, authorization_path, adoption_path, output, output_root):
    manifest_path = Path(manifest_path).resolve()
    source_root = Path(source_root).resolve()
    prior_root = Path(prior_root).resolve()
    authorization_path = Path(authorization_path).resolve()
    adoption_path = Path(adoption_path).resolve()
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("Fresh cycle request output required")
    authority = read(authorization_path)
    verify_authorization(authority)
    verified = validate_cycle_manifest(manifest_path, source_root)
    prior_ledger = prior_root / "campaign.json"
    if not prior_ledger.is_file():
        raise ValueError("Prior sensitivity campaign ledger is required")
    prior = read(prior_ledger)
    if not isinstance(prior.get("consumed_compute_s"), (int, float)):
        raise ValueError("Prior campaign compute accounting is missing")
    adoption = read(adoption_path)
    phase = adoption.get("decision", {}).get("phase", {})
    if not phase.get("research_reference_accepted") or not isinstance(phase.get("phase_s"), (int, float)):
        raise ValueError("Adopted clip phase is missing")
    config = verified["manifest"]["config"]
    request = dict(
        schema_version="phase1-cycle-campaign-1",
        source_root=str(source_root),
        manifest_path=str(manifest_path),
        source_manifest_sha256=verified["manifest_sha256"],
        intake_config_sha256=verified["manifest"]["config_sha256"],
        authorization_path=str(authorization_path),
        authorization_sha256=digest(authority),
        adoption_path=str(adoption_path),
        adoption_sha256=file_hash(adoption_path),
        prior_campaign_root=str(prior_root),
        prior_campaign_sha256=file_hash(prior_ledger),
        prior_consumed_compute_s=float(prior["consumed_compute_s"]),
        execution_budget_s=86400,
        auxiliary_reserved_s=3600,
        trial_limit_s=3600,
        max_output_bytes=300 * 1024**3,
        output_root=str(Path(output_root).resolve()),
        distro="Ubuntu",
        source_period_s=float(config["source_period_s"]),
        clip_start_phase_s=float(phase["phase_s"]),
        frame_count=FRAME_COUNT,
        frames=[dict(index=row["index"], phase_fraction=row["phase_fraction"], time_s=row["time_s"],
                     weight=row["weight"], snapshot=row["relative_path"], sha256=row["sha256"],
                     repeat_sha256=row.get("repeat_sha256")) for row in verified["frames"]],
        protocol_family="OpenFOAM Foundation 14 / incompressibleFluid / SIMPLE / kOmegaSST / upwind / 0.9mm full-body",
        scientific_approval=None,
        ranking_eligible=False,
    )
    write(output, request)
    print("PHASE1_CYCLE_REQUEST_CREATED", output, digest(request), flush=True)
    return request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--prior-root", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--adoption", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    create(args.manifest, args.source_root, args.prior_root, args.authorization,
           args.adoption, args.output, args.output_root)


if __name__ == "__main__":
    main()
