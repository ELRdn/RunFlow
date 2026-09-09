"""Apply the pinned CGAL triangle-soup autorefinement to one private probe.

Autorefinement is a diagnostic repair candidate.  It splits intersecting
triangles and applies CGAL's iterative snap rounding, but it does not itself
prove a usable solid; Foundation 14 surfaceCheck remains mandatory.
"""

import argparse
from pathlib import Path
import json
import subprocess
import sys
import time

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from repair_cycle_candidate import _validate_arrays, _write_obj
from repair_trial_support import manifold_backend
from runflow.cfd import private
from runflow.core import file_hash, read, write
from runflow.local_geometry import binary_read, binary_write, ROOT, tools_manifest
from runflow.shape_fullbody import finish_cache
from runflow.shape_audit import file_sha


METHOD = "cgal_autorefine_iterative_snap_round_v1"
SOURCE_COMMIT = "28811b671a12b5caa9e3688569dadbc6b3728fe6"


def repair(source_root, output, grid, iterations, timeout):
    source_root = Path(source_root).resolve()
    output = private(output)
    if output.exists():
        raise ValueError("Fresh autorefine geometry output required")
    source_geometry = read(source_root / "geometry.json")
    if source_geometry.get("unit") != "m" or source_geometry.get("coordinate_system") != "RF_X_FORWARD_Z_UP":
        raise ValueError("Autorefine input must use metres and RF coordinates")
    vertices = np.load(source_root / "arrays/vertices.npy", mmap_mode="r")
    triangles = np.load(source_root / "arrays/triangles.npy", mmap_mode="r")
    _validate_arrays(vertices, triangles)
    manifest = tools_manifest()
    input_hashes = {
        "source_geometry.json": file_hash(source_root / "geometry.json"),
        "source_candidate.obj": file_hash(source_root / "candidate.obj"),
        "source_arrays/vertices.npy": file_hash(source_root / "arrays/vertices.npy"),
        "source_arrays/triangles.npy": file_hash(source_root / "arrays/triangles.npy"),
        "repair_script": file_hash(Path(__file__)),
        "local_geometry_source": file_hash(REPO / "integrations/geometry/autorefine.cpp"),
    }
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    input_mesh = output / "input.rfmesh"
    refined_mesh = output / "refined.rfmesh"
    try:
        input_exchange = binary_write(input_mesh, vertices, triangles)
        binary = ROOT / "native-build/Release/runflow_autorefine.exe"
        log_path = output / "autorefine.log"
        command = [str(binary), str(input_mesh), str(refined_mesh), str(int(grid)), str(int(iterations))]
        with log_path.open("wb") as log:
            process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                     cwd=REPO, timeout=float(timeout), check=False)
        if process.returncode != 0:
            raise ValueError("Pinned CGAL autorefine failed; inspect autorefine.log")
        refined_v, refined_f = binary_read(refined_mesh)
        _validate_arrays(refined_v, refined_f)
        out_v = np.asarray(refined_v, dtype=np.float64)
        out_f = np.asarray(refined_f, dtype=np.int32)
        arrays = output / "arrays"
        arrays.mkdir(parents=True, exist_ok=False)
        np.save(arrays / "vertices.npy", out_v)
        np.save(arrays / "triangles.npy", out_f)
        cache = finish_cache(arrays, source_sha256=input_hashes["source_candidate.obj"], method=METHOD)
        candidate = output / "candidate.obj"
        _write_obj(candidate, out_v, out_f)
        output_hashes = {
            "candidate.obj": file_hash(candidate),
            "arrays/vertices.npy": file_hash(arrays / "vertices.npy"),
            "arrays/triangles.npy": file_hash(arrays / "triangles.npy"),
            "input.rfmesh": file_hash(input_mesh),
            "refined.rfmesh": file_hash(refined_mesh),
            "autorefine.log": file_hash(log_path),
        }
        record = dict(
            schema_version="phase1-cycle-autorefine-1",
            status="PASS",
            method=METHOD,
            backend="CGAL 6.2.1 Polygon_mesh_processing::autorefine_triangle_soup",
            source_commit=SOURCE_COMMIT,
            grid_exponent=int(grid),
            iterations=int(iterations),
            input_hashes=input_hashes,
            output_hashes=output_hashes,
            input_counts={"vertices": int(len(vertices)), "triangles": int(len(triangles))},
            output_counts={"vertices": int(len(out_v)), "triangles": int(len(out_f))},
            input_exchange=input_exchange,
            output_cache=cache,
            native_binary_sha256=file_sha(binary),
            source_geometry_sha256=input_hashes["source_geometry.json"],
            may_change_external_surface=True,
            smoothing=False,
            part_deletion=False,
            added_thickness=False,
            surface_check="PENDING_FOUNDATION_SURFACECHECK",
            external_shape_audit="PENDING",
            scientific_status="UNVALIDATED_PHASE1_CYCLE",
            elapsed_s=time.monotonic() - started,
        )
        write(output / "repair.json", record)
        write(output / "geometry.json", dict(
            schema_version="phase1-cycle-geometry-autorefine-1",
            repair_method=METHOD,
            source_sha256=source_geometry.get("source_sha256"),
            native_geometry_sha256=input_hashes["source_geometry.json"],
            voxel_m=source_geometry.get("voxel_m"),
            whole_input=True,
            coordinate_system=source_geometry.get("coordinate_system"),
            unit=source_geometry.get("unit"),
            candidate_sha256=output_hashes["candidate.obj"],
            candidate_obj_bytes=candidate.stat().st_size,
            candidate_counts=record["output_counts"],
            candidate_arrays=output_hashes,
            candidate_topology=dict(closed=False, self_intersection_verified=False,
                                    note="Autorefinement output requires Foundation surfaceCheck."),
            repair=record,
            human_review=None,
            scientific_status="UNVALIDATED_PHASE1_CYCLE",
        ))
        print("CGAL_AUTOREFINE_SAVED", json.dumps(record["output_counts"]), flush=True)
        return record
    except BaseException as exc:
        write(output / "repair-failure.json", dict(
            schema_version="phase1-cycle-autorefine-1", status="FAIL", method=METHOD,
            input_hashes=input_hashes, grid_exponent=int(grid), iterations=int(iterations),
            error=str(exc), elapsed_s=time.monotonic() - started))
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--grid", type=int, default=30)
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=1800)
    args = parser.parse_args()
    if not 23 <= args.grid < 52 or not 1 <= args.iterations <= 5:
        raise ValueError("CGAL grid exponent must be 23..51 and iterations 1..5")
    repair(args.input, args.output, args.grid, args.iterations, args.timeout)


if __name__ == "__main__":
    main()
