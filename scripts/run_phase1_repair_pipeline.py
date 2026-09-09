"""Build and verify a private repaired candidate for one cycle frame.

The pipeline starts from a native Blender frame that failed Foundation's
surface check.  It performs the already-tested local component operation at
0.5 micrometre tolerance, then iterates a conservative contact-weld step
using only Foundation witness points.  Every candidate receives a fresh
Foundation probe; no solver is started here and no input is overwritten.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from repair_trial_support import guarded as resource_guarded
from runflow import cfd
from runflow.core import digest, file_hash, read, write
from runflow.shape_fullbody import LIMITS


GIB = 1024 ** 3
COMPONENT_TOLERANCE_M = 0.0000005
SEARCH_RADIUS_M = 0.002
MAX_WELD_M = 0.002


def _limits():
    return dict(LIMITS, resource_grace_s=5)


def _env():
    value = os.environ.copy()
    value.update(
        OPENBLAS_NUM_THREADS="1",
        OMP_NUM_THREADS="20",
        RUNFLOW_CPU_COUNT="20",
    )
    return value


def _run_stage(root, name, command, timeout, allow_failure=False):
    record = resource_guarded(
        command,
        root=root,
        log=root / (name + ".log"),
        timeout=float(timeout),
        limits=_limits(),
        cwd=REPO,
        env=_env(),
    )
    write(root / (name + ".execution.json"), record)
    if not allow_failure and (record.get("reason") or record.get("returncode") != 0):
        raise RuntimeError(name + " failed: " + str(record.get("reason") or record.get("returncode")))
    return record


def _extract_points(archive_path, destination):
    archive_path = Path(archive_path).resolve()
    destination = Path(destination).resolve()
    if not archive_path.is_file():
        raise ValueError("Foundation diagnostics archive is missing: " + str(archive_path))
    with tarfile.open(archive_path, mode="r:*") as archive:
        members = [item for item in archive.getmembers() if Path(item.name).name == "selfInterPoints.obj"]
        if len(members) != 1:
            raise ValueError("Expected exactly one selfInterPoints.obj in Foundation archive")
        member = members[0]
        if member.size <= 0 or member.size > 32 * 1024 * 1024:
            raise ValueError("Unexpected Foundation point file size")
        stream = archive.extractfile(member)
        if stream is None:
            raise ValueError("Foundation point file could not be read")
        data = stream.read()
    lines = data.decode("ascii").splitlines()
    points = []
    for line in lines:
        fields = line.split()
        if not fields:
            continue
        if fields[0] != "v" or len(fields) != 4:
            raise ValueError("Foundation point file is not a point OBJ")
        points.append([float(value) for value in fields[1:]])
    if not points:
        raise ValueError("Foundation point file is empty")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return dict(path=str(destination), sha256=file_hash(destination), count=len(points), bytes=len(data))


def _foundation_pass(probe_root):
    worker_path = Path(probe_root) / "surface-worker.json"
    log_path = Path(probe_root) / "surfaceCheck.log"
    if not worker_path.is_file() or not log_path.is_file():
        return False, dict(reason="Foundation result or log is missing")
    worker = read(worker_path)
    text = log_path.read_text(encoding="utf-8", errors="replace")
    closed = "Surface is closed" in text
    self_ok = "Surface is not self-intersecting" in text
    lower = text.lower().replace("\n", " ")
    illegal = "surface has no illegal triangles" in lower
    value = dict(
        worker=worker,
        closed=closed,
        self_intersection_free=self_ok,
        no_illegal_triangles=illegal,
        log_sha256=file_hash(log_path),
    )
    return bool(worker.get("execution_status") == "PASS" and closed and self_ok and illegal), value


def _native_geometry(native_root):
    native_root = Path(native_root).resolve()
    result_path = native_root / "result.json"
    geometry_path = native_root / "geometry" / "geometry.json"
    candidate_path = native_root / "geometry" / "candidate.obj"
    if not result_path.is_file() or not geometry_path.is_file() or not candidate_path.is_file():
        raise ValueError("Native frame is incomplete")
    result = read(result_path)
    geometry = read(geometry_path)
    if result.get("phase_index") is None or geometry.get("source_sha256") is None:
        raise ValueError("Native frame provenance is incomplete")
    if file_hash(candidate_path) != geometry.get("candidate_sha256"):
        raise ValueError("Native frame candidate hash mismatch")
    return dict(root=native_root, result=result, geometry=geometry, candidate=candidate_path,
                candidate_sha256=file_hash(candidate_path), source_sha256=geometry["source_sha256"])


def run(native_root, output_root, distro="Ubuntu", budget_s=86400, max_rounds=8,
        component_timeout_s=1800, probe_timeout_s=900, contact_timeout_s=900):
    native = _native_geometry(native_root)
    output = cfd.private(output_root)
    if output.exists():
        raise ValueError("Fresh repair pipeline output required")
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    write(output / "request.json", dict(
        schema_version="phase1-cycle-repair-pipeline-1",
        native_root=str(native["root"]),
        native_candidate_sha256=native["candidate_sha256"],
        source_sha256=native["source_sha256"],
        component_tolerance_m=COMPONENT_TOLERANCE_M,
        search_radius_m=SEARCH_RADIUS_M,
        max_weld_m=MAX_WELD_M,
        max_rounds=int(max_rounds),
        budget_s=float(budget_s),
        scientific_status="UNVALIDATED_PHASE1_CYCLE",
        ranking_eligible=False,
    ))
    records = []

    def remaining():
        value = float(budget_s) - (time.monotonic() - started)
        if value <= 0:
            raise TimeoutError("Repair pipeline budget exhausted")
        return value

    try:
        native_geometry = native["geometry"]
        if native_geometry.get("candidate_topology", {}).get("closed"):
            native_points = output / "native-self-points.obj"
            point_record = _extract_points(native["root"] / "surface-diagnostics.tar", native_points)
            write(output / "native-self-points.json", point_record)
            component_input = native["root"] / "geometry"
        else:
            # Blender's 0.9 mm output can leave a small open boundary around a
            # thin part.  One explicitly recorded same-voxel remesh is the
            # only fallback allowed here; no filling or smoothing is applied.
            second = output / "second-remesh"
            command = [
                str(REPO / ".tools/blender/blender-4.2.23-windows-x64/blender.exe"),
                "--background", "--factory-startup", "--threads", "20",
                "--python-exit-code", "2", "--python",
                str(REPO / "integrations/blender/repair_cycle_second_remesh.py"), "--",
                "--input", str(native["root"] / "geometry"), "--output", str(second),
            ]
            records.append(dict(stage="second_same_voxel_remesh", execution=_run_stage(
                output, "second-remesh", command, min(component_timeout_s, remaining()))))
            second_geometry = read(second / "geometry.json")
            if not second_geometry.get("candidate_topology", {}).get("closed"):
                raise RuntimeError("Same-voxel remesh did not produce a closed candidate")
            component_input = second

        native_points = output / "native-self-points.obj"
        final = None
        if not native_points.exists():
            # A closed second-remesh candidate has to be probed before its
            # witness points are known.
            first_probe = output / "foundation-initial"
            probe_command = [
                sys.executable, str(REPO / "scripts/run_foundation_surface_probe.py"),
                "--root", str(first_probe), "--candidate", str(component_input / "candidate.obj"),
                "--timeout", str(min(probe_timeout_s, remaining())), "--distro", distro,
            ]
            probe = _run_stage(output, "foundation-initial", probe_command,
                               min(probe_timeout_s, remaining()), allow_failure=True)
            passed, check = _foundation_pass(first_probe)
            initial_record = dict(stage="foundation_probe", round=-1, candidate=str(component_input),
                                  execution=probe, check=check, passed=passed)
            records.append(initial_record)
            write(output / "foundation-initial.json", initial_record)
            if passed:
                final = component_input
            else:
                _extract_points(first_probe / "surface-diagnostics.tar", native_points)
                write(output / "native-self-points.json", dict(
                    path=str(native_points), sha256=file_hash(native_points),
                    count=native_points.read_text(encoding="ascii").count("\nv ") +
                    (1 if native_points.read_text(encoding="ascii").startswith("v ") else 0),
                ))
        if final is not None:
            result = dict(
                schema_version="phase1-cycle-repair-pipeline-1",
                execution_status="PASS",
                candidate_root=str(final),
                candidate=str(final / "candidate.obj"),
                candidate_sha256=file_hash(final / "candidate.obj"),
                geometry_sha256=file_hash(final / "geometry.json"),
                repair_sha256=None,
                source_sha256=native["source_sha256"],
                candidate_counts=read(final / "geometry.json").get("candidate_counts"),
                foundation_pass=True,
                stages=records,
                elapsed_s=time.monotonic() - started,
                scientific_status="UNVALIDATED_PHASE1_CYCLE",
                ranking_eligible=False,
            )
            write(output / "repair-pipeline.json", result)
            print("PHASE1_REPAIR_PIPELINE_FINISHED", json.dumps(result, ensure_ascii=False), flush=True)
            return result

        component = output / "component-tol-0005"
        command = [
            sys.executable, str(REPO / "scripts/repair_cycle_local_component_union.py"),
            "--input", str(component_input),
            "--points", str(native_points),
            "--output", str(component),
            "--padding", "0.000001",
            "--tolerance", str(COMPONENT_TOLERANCE_M),
            "--point-index", "0",
        ]
        records.append(dict(stage="component_union", execution=_run_stage(output, "component-union", command, min(component_timeout_s, remaining()))))
        current = component

        final = None
        for round_index in range(int(max_rounds) + 1):
            probe_root = output / f"foundation-{round_index:03d}"
            probe_command = [
                sys.executable, str(REPO / "scripts/run_foundation_surface_probe.py"),
                "--root", str(probe_root),
                "--candidate", str(current / "candidate.obj"),
                "--timeout", str(min(probe_timeout_s, remaining())),
                "--distro", distro,
            ]
            probe = _run_stage(output, f"foundation-{round_index:03d}", probe_command,
                               min(probe_timeout_s, remaining()), allow_failure=True)
            passed, check = _foundation_pass(probe_root)
            probe_record = dict(stage="foundation_probe", round=round_index, candidate=str(current),
                                execution=probe, check=check, passed=passed)
            records.append(probe_record)
            write(output / f"foundation-{round_index:03d}.json", probe_record)
            if passed:
                final = current
                break
            if round_index >= int(max_rounds):
                break
            points_path = output / f"points-{round_index + 1:03d}.obj"
            point_info = _extract_points(probe_root / "surface-diagnostics.tar", points_path)
            write(output / f"points-{round_index + 1:03d}.json", point_info)
            contact = output / f"contact-{round_index + 1:03d}"
            contact_command = [
                sys.executable, str(REPO / "scripts/repair_cycle_contact_weld_safe.py"),
                "--input", str(current),
                "--points-file", str(points_path),
                "--output", str(contact),
                "--search-radius", str(SEARCH_RADIUS_M),
                "--max-weld", str(MAX_WELD_M),
            ]
            records.append(dict(stage="safe_contact_weld", round=round_index + 1,
                                execution=_run_stage(output, f"contact-{round_index + 1:03d}", contact_command,
                                                      min(contact_timeout_s, remaining()))))
            current = contact

        if final is None:
            raise RuntimeError("No Foundation-accepted candidate was produced")
        final_geometry = read(final / "geometry.json")
        result = dict(
            schema_version="phase1-cycle-repair-pipeline-1",
            execution_status="PASS",
            candidate_root=str(final),
            candidate=str(final / "candidate.obj"),
            candidate_sha256=file_hash(final / "candidate.obj"),
            geometry_sha256=file_hash(final / "geometry.json"),
            repair_sha256=file_hash(final / "repair.json"),
            source_sha256=native["source_sha256"],
            candidate_counts=final_geometry.get("candidate_counts"),
            foundation_pass=True,
            stages=records,
            elapsed_s=time.monotonic() - started,
            scientific_status="UNVALIDATED_PHASE1_CYCLE",
            ranking_eligible=False,
        )
    except BaseException as exc:
        result = dict(
            schema_version="phase1-cycle-repair-pipeline-1",
            execution_status="FAIL",
            reason=str(exc),
            stages=records,
            elapsed_s=time.monotonic() - started,
            scientific_status="UNVALIDATED_PHASE1_CYCLE",
            ranking_eligible=False,
        )
        write(output / "repair-pipeline.json", result)
        raise
    write(output / "repair-pipeline.json", result)
    print("PHASE1_REPAIR_PIPELINE_FINISHED", json.dumps(result, ensure_ascii=False), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--native-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--distro", default="Ubuntu")
    parser.add_argument("--budget-s", type=float, default=86400)
    parser.add_argument("--max-rounds", type=int, default=8)
    parser.add_argument("--component-timeout-s", type=float, default=1800)
    parser.add_argument("--probe-timeout-s", type=float, default=900)
    parser.add_argument("--contact-timeout-s", type=float, default=900)
    args = parser.parse_args()
    result = run(args.native_root, args.output_root, args.distro, args.budget_s, args.max_rounds,
                 args.component_timeout_s, args.probe_timeout_s, args.contact_timeout_s)
    return 0 if result["execution_status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
