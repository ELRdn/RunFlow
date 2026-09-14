"""Automatic coplanar-fan repair loop for one cycle frame.

The native Blender 0.9 mm surface of every cycle frame is closed or nearly
closed, but Foundation surfaceCheck still reports self-intersections.  The
accepted remedy is the local coplanar-fan retriangulation already validated on
frame 3: it removes only an interior planar fan vertex, keeps every ring
coordinate exactly, and never smooths, fills, thickens, or deletes a semantic
part.

This script automates that loop: probe with Foundation, take the witness
points, reduce each witness point to the nearest input vertex whose incident
fan is planar enough to retriangulate, apply the operation, and probe again.
Every round is recorded.  Nothing is deleted and no tolerance is relaxed; a
candidate is only accepted when Foundation itself reports a closed,
self-intersection-free surface with no illegal triangles.
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

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from repair_cycle_coplanar_fan import cycle_for_center, plane_residual
from repair_trial_support import guarded as resource_guarded
from runflow import cfd
from runflow.core import file_hash, read, write
from runflow.shape_fullbody import LIMITS


# Foundation reports a representative point inside an offending triangle, not
# the fan centre.  The ladder therefore has to reach the local triangle scale:
# at a 0.9 mm voxel a witness point sits up to roughly one edge length
# (1.3 mm measured) from any of that triangle's vertices.
DEFAULT_SEARCH_RADII_M = (5e-6, 5e-5, 5e-4, 1.5e-3)
MAX_POINT_ARCHIVE_BYTES = 32 * 1024 * 1024


def _now():
    return datetime.now(timezone.utc).isoformat()


def _archive_usable(path):
    """Return whether a diagnostics archive is present and fully readable.

    A probe that is interrupted leaves a truncated tar.  The file exists but its
    member list cannot be read, so it must not be selected as the record of a
    completed probe.
    """
    path = Path(path)
    if not path.is_file() or path.stat().st_size <= 0:
        return False
    try:
        with tarfile.open(path, mode="r:*") as archive:
            archive.getmembers()
    except (tarfile.TarError, OSError, EOFError, ValueError):
        return False
    return True


def _unique_root(path):
    """Return a path that does not exist yet, so a probe root is never reused."""
    path = Path(path)
    if not path.exists():
        return path
    serial = 1
    while True:
        candidate = path.with_name(path.name + "-retry-%03d" % serial)
        if not candidate.exists():
            return candidate
        serial += 1


def _limits():
    return dict(LIMITS, resource_grace_s=5)


def _env():
    value = os.environ.copy()
    value.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="20", RUNFLOW_CPU_COUNT="20")
    return value


def array_path(root, name):
    nested = Path(root) / "arrays" / name
    flat = Path(root) / name
    if nested.is_file():
        return nested
    if flat.is_file():
        return flat
    raise FileNotFoundError("Missing array: " + name)


def topology(triangles):
    edges = np.concatenate((triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]))
    edges.sort(axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return {
        "edges": int(len(counts)),
        "boundary_edges": int(np.count_nonzero(counts == 1)),
        "nonmanifold_edges": int(np.count_nonzero(counts != 2)),
    }


def _run_stage(root, name, command, timeout, allow_failure=False):
    record = resource_guarded(
        command, root=Path(root), log=Path(root) / (name + ".log"),
        timeout=float(timeout), limits=_limits(), cwd=REPO, env=_env(),
    )
    write(Path(root) / (name + ".execution.json"), record)
    # Foundation surfaceCheck exits nonzero when it finds a defect.  That is a
    # diagnostic result, not a failed stage, so probes are read from their log.
    if not allow_failure and (record.get("reason") or record.get("returncode") != 0):
        raise RuntimeError(name + " failed: " + str(record.get("reason") or record.get("returncode")))
    return record


def _foundation_pass(probe_root):
    worker_path = Path(probe_root) / "surface-worker.json"
    log_path = Path(probe_root) / "surfaceCheck.log"
    if not worker_path.is_file() or not log_path.is_file():
        return False, dict(reason="Foundation result or log is missing")
    worker = read(worker_path)
    text = log_path.read_text(encoding="utf-8", errors="replace")
    closed = "Surface is closed" in text
    self_ok = "Surface is not self-intersecting" in text
    illegal = "surface has no illegal triangles" in text.lower().replace("\n", " ")
    value = dict(worker=worker, closed=closed, self_intersection_free=self_ok,
                 no_illegal_triangles=illegal, log_sha256=file_hash(log_path))
    passed = bool(worker.get("execution_status") == "PASS" and closed and self_ok and illegal)
    return passed, value


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
        if member.size <= 0 or member.size > MAX_POINT_ARCHIVE_BYTES:
            raise ValueError("Unexpected Foundation point file size")
        stream = archive.extractfile(member)
        if stream is None:
            raise ValueError("Foundation point file could not be read")
        data = stream.read()
    points = []
    for line in data.decode("ascii").splitlines():
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
    return dict(path=str(destination), sha256=file_hash(destination), count=len(points))


def _probe(candidate_obj, probe_root, log_root, remaining, probe_timeout_s, distro, records, label):
    command = [sys.executable, str(REPO / "scripts/run_foundation_surface_probe.py"),
               "--root", str(probe_root), "--candidate", str(candidate_obj),
               "--timeout", str(min(probe_timeout_s, remaining())), "--distro", distro]
    execution = _run_stage(log_root, "foundation-probe-" + label, command,
                           min(probe_timeout_s, remaining()), allow_failure=True)
    passed, check = _foundation_pass(probe_root)
    records.append(dict(stage="foundation_probe", label=label, candidate=str(candidate_obj),
                        execution=execution, check=check, passed=passed))
    return passed, check


def _probe_fresh(output, candidate_obj, base_name, remaining, probe_timeout_s, distro, records, label):
    """Probe into a guaranteed-new root until one yields a diagnostics archive.

    A probe that is interrupted leaves a directory without its archive, and a
    later attempt must never reuse that directory.  The result is only accepted
    once the archive exists, so the witness points always describe this probe.
    """
    for attempt in range(1, 4):
        root = _unique_root(output / base_name)
        passed, check = _probe(candidate_obj, root, output, remaining, probe_timeout_s,
                               distro, records, label + ("-a%d" % attempt))
        if _archive_usable(root / "surface-diagnostics.tar"):
            return root, passed, check
        records.append(dict(stage="probe_retry", label=label, attempt=attempt, root=str(root),
                            reason="Foundation diagnostics archive missing"))
    raise RuntimeError("Foundation probe produced no diagnostics archive for " + str(candidate_obj))


def _nearest_vertices(vertices, points, radius):
    """Return the nearest input vertex index for each witness point.

    Foundation writes rounded witness coordinates, so the metric radius is a
    search window rather than an exact match.
    """
    rows = []
    total = len(vertices)
    chunk = 2_000_000
    for index, point in enumerate(points):
        best = None
        for start in range(0, total, chunk):
            stop = min(total, start + chunk)
            block = np.asarray(vertices[start:stop], dtype=np.float64)
            delta = block - point
            distance2 = np.einsum("ij,ij->i", delta, delta)
            local = int(np.argmin(distance2))
            value = float(distance2[local])
            if best is None or value < best[0]:
                best = (value, start + local)
        rows.append((index, best[1], float(np.sqrt(best[0]))))
    return [(index, vertex, distance) for index, vertex, distance in rows if distance <= radius]


def _select_centers(vertices, triangles, nearest, max_planarity_m, cap):
    """Keep only vertices whose incident fan can be retriangulated safely.

    A candidate must form a single directed fan cycle whose ring is planar
    within the diagnostic limit.  Two fans that share an incident face, or
    whose ring contains the other centre, would remove overlapping faces and
    break the closed topology, so only a face-disjoint set is offered in one
    call.  Everything else is reported, not guessed at.
    """
    accepted = []
    rejected = []
    used_faces = set()
    used_centers = set()
    seen = set()
    for index, vertex, distance in sorted(nearest, key=lambda row: (row[2], row[1])):
        if vertex in seen:
            continue
        seen.add(vertex)
        if len(accepted) >= cap:
            break
        try:
            incident, ring, _ = cycle_for_center(vertices, triangles, vertex)
            residual, _ = plane_residual(vertices, ring)
        except ValueError as exc:
            rejected.append(dict(point_index=index, vertex=vertex,
                                 distance_m=distance, reason=str(exc)))
            continue
        if residual > max_planarity_m:
            rejected.append(dict(point_index=index, vertex=vertex, distance_m=distance,
                                 reason="fan planarity exceeds limit", residual_m=residual))
            continue
        faces = set(int(value) for value in incident)
        if faces & used_faces:
            rejected.append(dict(point_index=index, vertex=vertex, distance_m=distance,
                                 reason="fan shares a face with an already selected fan"))
            continue
        if any(int(value) in used_centers for value in ring):
            rejected.append(dict(point_index=index, vertex=vertex, distance_m=distance,
                                 reason="fan ring contains an already selected fan centre"))
            continue
        accepted.append(dict(point_index=index, vertex=vertex, distance_m=distance,
                             ring_size=int(len(ring)), planarity_m=residual,
                             incident_faces=int(len(faces))))
        used_faces |= faces
        used_centers.add(vertex)
    return accepted, rejected


def _native_geometry(native_root):
    native_root = Path(native_root).resolve()
    result_path = native_root / "result.json"
    geometry_dir = native_root / "geometry"
    geometry_path = geometry_dir / "geometry.json"
    candidate_path = geometry_dir / "candidate.obj"
    if not result_path.is_file() or not geometry_path.is_file() or not candidate_path.is_file():
        raise ValueError("Native frame is incomplete: " + str(native_root))
    result = read(result_path)
    geometry = read(geometry_path)
    if result.get("phase_index") is None or geometry.get("source_sha256") is None:
        raise ValueError("Native frame provenance is incomplete")
    actual = file_hash(candidate_path)
    if geometry.get("candidate_sha256") != actual:
        raise ValueError("Native frame candidate hash mismatch")
    return dict(root=native_root, result=result, geometry=geometry, geometry_dir=geometry_dir,
                candidate=candidate_path, candidate_sha256=actual,
                source_sha256=geometry["source_sha256"])


def run(native_root, output_root, *, distro="Ubuntu", budget_s=7200.0, max_rounds=6,
        probe_timeout_s=900.0, fan_timeout_s=900.0, max_planarity_m=1e-4, max_centers=32,
        search_radii=DEFAULT_SEARCH_RADII_M, reuse_native_probe=True):
    native = _native_geometry(native_root)
    output = cfd.private(output_root)
    resumed = output.exists()
    if resumed:
        request_path = output / "request.json"
        if not request_path.is_file():
            raise ValueError("Existing automatic repair output has no request: " + str(output))
        if read(request_path).get("native_candidate_sha256") != native["candidate_sha256"]:
            raise ValueError("Existing automatic repair output belongs to another candidate")
    else:
        output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    records = []
    write(output / "request.json", dict(
        schema_version="phase1-cycle-repair-auto-1",
        native_root=str(native["root"]),
        native_candidate_sha256=native["candidate_sha256"],
        source_sha256=native["source_sha256"],
        method="coplanar_fan_retriangulate_v1",
        max_planarity_m=float(max_planarity_m),
        max_centers=int(max_centers),
        search_radii_m=[float(item) for item in search_radii],
        max_rounds=int(max_rounds),
        budget_s=float(budget_s),
        started_utc=_now(),
        scientific_status="UNVALIDATED_PHASE1_CYCLE",
        ranking_eligible=False,
    ))

    def remaining():
        value = float(budget_s) - (time.monotonic() - started)
        if value <= 0:
            raise TimeoutError("Automatic repair budget exhausted")
        return value

    start_round = 1
    probe_root = None
    if resumed:
        serial = 0
        for item in output.glob("fan-*"):
            if not (item / "geometry.json").is_file():
                continue
            head = item.name.split("-")[1]
            if head.isdigit():
                serial = max(serial, int(head))
        if serial:
            # Both the plain fan-NNN and the fan-NNN-AA attempt naming are
            # accepted, so a run started by an earlier revision still resumes.
            fans = sorted(item for item in output.glob(f"fan-{serial:03d}*")
                          if (item / "geometry.json").is_file())
            if not fans:
                raise ValueError("Resumed repair is missing the fan output for round " + str(serial))
            current = fans[-1]
            probes = sorted((item for item in output.glob(f"foundation-{serial:03d}*")
                             if _archive_usable(item / "surface-diagnostics.tar")
                             and (item / "surface-worker.json").is_file()),
                            key=lambda item: item.name)
            if probes:
                probe_root = probes[-1]
                # The completed round may already be accepted; Foundation only
                # writes a witness-point file when a defect remains.
                passed, check = _foundation_pass(probe_root)
                if passed:
                    return _finish(output, current, native, records, started, True,
                                   probe_root=probe_root, check=check)
            else:
                probe_root, passed, check = _probe_fresh(
                    output, current / "candidate.obj", f"foundation-{serial:03d}", remaining,
                    probe_timeout_s, distro, records, f"resume-{serial:03d}")
                if passed:
                    return _finish(output, current, native, records, started, True,
                                   probe_root=probe_root, check=check)
            start_round = serial + 1
        elif (output / "boundary-stitch" / "geometry.json").is_file():
            current = output / "boundary-stitch"
        elif (output / "manifold-roundtrip" / "geometry.json").is_file():
            current = output / "manifold-roundtrip"
        else:
            current = native["geometry_dir"]
        if probe_root is None:
            probe_root = _native_probe_reuse(native, current, reuse_native_probe)
            if probe_root is not None:
                records.append(dict(stage="foundation_probe", label="native-reuse",
                                    candidate=str(current / "candidate.obj"),
                                    execution=dict(reused=True, archive=str(
                                        native["root"] / "surface-diagnostics.tar"))))
        if probe_root is None:
            probe_root, passed, check = _probe_fresh(
                output, current / "candidate.obj", "foundation-resume-001", remaining,
                probe_timeout_s, distro, records, "resume")
            if passed:
                return _finish(output, current, native, records, started, True,
                               probe_root=probe_root, check=check)
        records.append(dict(stage="resume", round=serial, candidate=str(current),
                            probe=str(probe_root)))
    else:
        current = native["geometry_dir"]
        current_topology = topology(np.asarray(
            np.load(array_path(current, "triangles.npy"), mmap_mode="r"), dtype=np.int64))

    # Only a not-closed native surface needs a closure step.  The closure
    # backends are the already-recorded stitch and manifold round trip; both
    # keep every ring coordinate and delete nothing semantic.
    if not resumed and current_topology["boundary_edges"]:
        stitched = output / "boundary-stitch"
        command = [sys.executable, str(REPO / "scripts/repair_cycle_boundary_stitch.py"),
                   "--input", str(current), "--output", str(stitched), "--max-weld", "0.000001"]
        try:
            execution = _run_stage(output, "boundary-stitch", command, min(fan_timeout_s, remaining()))
        except RuntimeError as exc:
            execution = dict(command=command, failed=str(exc))
        records.append(dict(stage="boundary_stitch", execution=execution))
        if stitched.is_dir():
            current = stitched
        else:
            roundtrip = output / "manifold-roundtrip"
            command = [sys.executable, str(REPO / "scripts/repair_cycle_manifold_roundtrip.py"),
                       "--input", str(current), "--output", str(roundtrip)]
            execution = _run_stage(output, "manifold-roundtrip", command, min(fan_timeout_s, remaining()))
            records.append(dict(stage="manifold_roundtrip", execution=execution))
            current = roundtrip
        current_topology = topology(np.asarray(
            np.load(array_path(current, "triangles.npy"), mmap_mode="r"), dtype=np.int64))
        if current_topology["boundary_edges"]:
            result = dict(schema_version="phase1-cycle-repair-auto-1", execution_status="BLOCKED",
                          reason="Closure repair did not produce a closed surface",
                          topology=current_topology, stages=records,
                          elapsed_s=time.monotonic() - started,
                          scientific_status="UNVALIDATED_PHASE1_CYCLE", ranking_eligible=False)
            write(output / "repair-auto.json", result)
            return result

    # Reuse the probe Foundation already recorded for this exact native
    # candidate; it is the same diagnostic on the same bytes.
    if not resumed:
        probe_root = _native_probe_reuse(native, current, reuse_native_probe)
        if probe_root is not None:
            records.append(dict(stage="foundation_probe", label="native-reuse",
                                candidate=str(current / "candidate.obj"),
                                execution=dict(reused=True, archive=str(
                                    native["root"] / "surface-diagnostics.tar"))))
    if not resumed and probe_root is None:
        probe_root, passed, check = _probe_fresh(
            output, current / "candidate.obj", "foundation-000", remaining,
            probe_timeout_s, distro, records, "initial")
        if passed:
            result = _finish(output, current, native, records, started, True)
            return result

    for round_index in range(start_round, start_round + int(max_rounds)):
        # A completed probe that Foundation already accepted ends the repair,
        # even when the surface carries no witness points to read.
        already, already_check = _foundation_pass(probe_root)
        if already:
            return _finish(output, current, native, records, started, True,
                           probe_root=probe_root, check=already_check)
        points_path = output / f"points-{round_index:03d}.obj"
        point_info = _extract_points(probe_root / "surface-diagnostics.tar", points_path)
        write(output / f"points-{round_index:03d}.json", point_info)
        points = [np.asarray([float(value) for value in line.split()[1:]], dtype=np.float64)
                  for line in points_path.read_text(encoding="ascii").splitlines() if line.split()]
        vertices = np.load(array_path(current, "vertices.npy"), mmap_mode="r")
        triangles = np.asarray(np.load(array_path(current, "triangles.npy"), mmap_mode="r"), dtype=np.int64)

        accepted = []
        rejected = []
        used_radius = None
        for radius in search_radii:
            nearest = _nearest_vertices(vertices, points, float(radius))
            accepted, rejected = _select_centers(vertices, triangles, nearest,
                                                float(max_planarity_m), int(max_centers))
            used_radius = float(radius)
            if accepted:
                break
        round_record = dict(round=round_index, probe=str(probe_root),
                            witness_points=int(len(points)), search_radius_m=used_radius,
                            accepted_centers=len(accepted), rejected_candidates=len(rejected),
                            accepted=[row["vertex"] for row in accepted],
                            accepted_detail=accepted, rejected_detail=rejected[:32])
        if not accepted:
            # Record why: the distance from each witness point to its nearest
            # input vertex, measured without a search window.
            nearest_any = _nearest_vertices(vertices, points[:8], float("inf"))
            round_record["nearest_vertex_m"] = [
                dict(point_index=index, vertex=vertex, distance_m=distance)
                for index, vertex, distance in nearest_any]
        records.append(dict(stage="center_selection", **round_record))
        write(output / f"centers-{round_index:03d}.json", round_record)
        if not accepted:
            result = dict(schema_version="phase1-cycle-repair-auto-1", execution_status="BLOCKED",
                          reason="No retriangulatable coplanar fan was found for the witness points",
                          stages=records, elapsed_s=time.monotonic() - started,
                          scientific_status="UNVALIDATED_PHASE1_CYCLE", ranking_eligible=False)
            write(output / "repair-auto.json", result)
            return result

        fan_root, applied = _apply_fans(output, current, accepted, round_index,
                                        min(fan_timeout_s, remaining()), max_planarity_m, records)
        if fan_root is None:
            result = dict(schema_version="phase1-cycle-repair-auto-1", execution_status="BLOCKED",
                          reason="Coplanar fan could not be applied without breaking the closed topology",
                          stages=records, elapsed_s=time.monotonic() - started,
                          scientific_status="UNVALIDATED_PHASE1_CYCLE", ranking_eligible=False)
            write(output / "repair-auto.json", result)
            return result
        round_record["applied_centers"] = len(applied)
        write(output / f"centers-{round_index:03d}.json", round_record)
        current = fan_root
        probe_root, passed, check = _probe_fresh(
            output, current / "candidate.obj", f"foundation-{round_index:03d}", remaining,
            probe_timeout_s, distro, records, f"round-{round_index:03d}")
        if passed:
            result = _finish(output, current, native, records, started, True, probe_root=probe_root, check=check)
            return result

    result = dict(schema_version="phase1-cycle-repair-auto-1", execution_status="FAIL",
                  reason="Round limit reached without a Foundation-accepted candidate",
                  stages=records, elapsed_s=time.monotonic() - started,
                  scientific_status="UNVALIDATED_PHASE1_CYCLE", ranking_eligible=False)
    write(output / "repair-auto.json", result)
    return result


def _native_probe_reuse(native, current, enabled):
    """Return the native frame's own probe root when it describes these bytes.

    The probe hard-links the candidate into its own geometry directory, so the
    probe root must sit on the same volume as the candidate.  Reusing the probe
    the native frame already recorded satisfies that and repeats nothing.
    """
    if not enabled or current != native["geometry_dir"]:
        return None
    if not (native["root"] / "surface-diagnostics.tar").is_file():
        return None
    if not (native["root"] / "surface-worker.json").is_file():
        return None
    return native["root"]


def _apply_fans(output, current, centers, round_index, timeout, max_planarity_m, records):
    """Apply the largest prefix of centres that keeps the closed topology.

    A single call must leave a closed surface; the coplanar-fan script refuses
    anything else.  If the preferred set is refused, the prefix is halved until
    it is accepted.  Centres left out are simply re-derived from the next
    Foundation probe, so nothing is silently dropped.
    """
    size = len(centers)
    attempt = 0
    while size >= 1:
        attempt += 1
        target = output / f"fan-{round_index:03d}-{attempt:02d}"
        subset = centers[:size]
        command = [sys.executable, str(REPO / "scripts/repair_cycle_coplanar_fan.py"),
                   "--input", str(current), "--output", str(target),
                   "--max-planarity-m", str(float(max_planarity_m))]
        for row in subset:
            command += ["--center-vertex", str(row["vertex"])]
        try:
            execution = _run_stage(output, f"fan-{round_index:03d}-{attempt:02d}", command, timeout)
        except RuntimeError as exc:
            execution = dict(command=command, failed=str(exc))
        records.append(dict(stage="coplanar_fan", round=round_index, attempt=attempt,
                            centers=int(size), execution=execution))
        if target.is_dir() and not execution.get("failed"):
            return target, subset
        if size == 1:
            return None, []
        size = max(1, size // 2)
    return None, []


def _finish(output, current, native, records, started, passed, probe_root=None, check=None):
    result = dict(
        schema_version="phase1-cycle-repair-auto-1",
        execution_status="PASS" if passed else "FAIL",
        candidate_root=str(current),
        candidate=str(current / "candidate.obj"),
        candidate_sha256=file_hash(current / "candidate.obj"),
        geometry_sha256=file_hash(current / "geometry.json"),
        repair_sha256=file_hash(current / "repair.json"),
        source_sha256=native["source_sha256"],
        candidate_counts=read(current / "geometry.json").get("candidate_counts"),
        foundation_pass=bool(passed),
        probe_root=str(probe_root) if probe_root else None,
        probe_check=check,
        stages=records,
        elapsed_s=time.monotonic() - started,
        finished_utc=_now(),
        scientific_status="UNVALIDATED_PHASE1_CYCLE",
        ranking_eligible=False,
    )
    write(output / "repair-auto.json", result)
    print("PHASE1_REPAIR_AUTO_FINISHED", json.dumps({k: result[k] for k in (
        "execution_status", "candidate_root", "elapsed_s")}, ensure_ascii=False), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--native-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--distro", default="Ubuntu")
    parser.add_argument("--budget-s", type=float, default=7200.0)
    parser.add_argument("--max-rounds", type=int, default=6)
    parser.add_argument("--probe-timeout-s", type=float, default=900.0)
    parser.add_argument("--fan-timeout-s", type=float, default=900.0)
    parser.add_argument("--max-planarity-m", type=float, default=1e-4)
    parser.add_argument("--max-centers", type=int, default=32)
    parser.add_argument("--no-reuse-native-probe", action="store_true")
    args = parser.parse_args()
    result = run(args.native_root, args.output_root, distro=args.distro,
                 budget_s=args.budget_s, max_rounds=args.max_rounds,
                 probe_timeout_s=args.probe_timeout_s, fan_timeout_s=args.fan_timeout_s,
                 max_planarity_m=args.max_planarity_m, max_centers=args.max_centers,
                 reuse_native_probe=not args.no_reuse_native_probe)
    return 0 if result["execution_status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
