"""Round-trip one cycle candidate through pinned Manifold without Boolean ops."""

import argparse
import json
from pathlib import Path
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
from runflow.shape_fullbody import finish_cache


METHOD = "manifold_roundtrip_no_boolean_v1"
BACKEND_COMMIT = "11235e6b8ebea2dbed8aec4285685aafd3d95667"


def repair(source_root, output_root):
    source_root = Path(source_root).resolve()
    output_root = private(output_root)
    if output_root.exists():
        raise ValueError("Fresh Manifold roundtrip output required")
    source_geometry_path = source_root / "geometry.json"
    source_geometry = read(source_geometry_path)
    if source_geometry.get("unit") != "m" or source_geometry.get("coordinate_system") != "RF_X_FORWARD_Z_UP":
        raise ValueError("Manifold roundtrip input must use metres and RF coordinates")
    vertices = np.asarray(np.load(source_root / "arrays/vertices.npy", mmap_mode="r"), dtype=np.float64)
    triangles = np.asarray(np.load(source_root / "arrays/triangles.npy", mmap_mode="r"), dtype=np.uint64)
    _validate_arrays(vertices, triangles)
    input_hashes = {
        "geometry.json": file_hash(source_geometry_path),
        "candidate.obj": file_hash(source_root / "candidate.obj"),
        "arrays/vertices.npy": file_hash(source_root / "arrays/vertices.npy"),
        "arrays/triangles.npy": file_hash(source_root / "arrays/triangles.npy"),
        "repair_script": file_hash(Path(__file__)),
    }
    output_root.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    try:
        manifold = manifold_backend(REPO)
        body = manifold.Manifold(manifold.Mesh64(np.array(vertices, copy=True, order="C"),
                                                  np.array(triangles, copy=True, order="C"),
                                                  tolerance=0.0))
        status = str(body.status())
        if body.status() != manifold.Error.NoError or not body.num_tri():
            raise ValueError("Manifold did not accept input: " + status)
        exported = body.to_mesh64()
        out_vertices = np.asarray(exported.vert_properties, dtype=np.float64)[:, :3]
        out_triangles = np.asarray(exported.tri_verts, dtype=np.int32)
        _validate_arrays(out_vertices, out_triangles)
        arrays = output_root / "arrays"
        arrays.mkdir(parents=True, exist_ok=False)
        np.save(arrays / "vertices.npy", out_vertices)
        np.save(arrays / "triangles.npy", out_triangles)
        candidate = output_root / "candidate.obj"
        _write_obj(candidate, out_vertices, out_triangles)
        hashes = {
            "candidate.obj": file_hash(candidate),
            "arrays/vertices.npy": file_hash(arrays / "vertices.npy"),
            "arrays/triangles.npy": file_hash(arrays / "triangles.npy"),
        }
        cache = finish_cache(arrays, source_sha256=input_hashes["candidate.obj"], method=METHOD)
        repair_record = {
            "schema_version": "phase1-cycle-manifold-roundtrip-1",
            "status": "PASS",
            "method": METHOD,
            "backend": "manifold3d 3.5.2",
            "backend_commit": BACKEND_COMMIT,
            "boolean_operations": 0,
            "input_hashes": input_hashes,
            "output_hashes": hashes,
            "input_counts": {"vertices": int(len(vertices)), "triangles": int(len(triangles))},
            "output_counts": {"vertices": int(len(out_vertices)), "triangles": int(len(out_triangles))},
            "input_status": status,
            "imported_triangles": int(body.num_tri()),
            "tolerance_m": float(body.get_tolerance()),
            "whole_input": True,
            "smoothing": False,
            "hole_filling": False,
            "part_deletion": False,
            "surface_check": "PENDING_FOUNDATION_SURFACECHECK",
            "external_shape_audit": "PENDING",
            "scientific_status": "UNVALIDATED_PHASE1_CYCLE",
            "cache": cache,
            "elapsed_s": time.monotonic() - started,
        }
        write(output_root / "repair.json", repair_record)
        write(output_root / "geometry.json", {
            "schema_version": "phase1-cycle-geometry-manifold-roundtrip-1",
            "repair_method": METHOD,
            "source_sha256": source_geometry.get("source_sha256"),
            "native_geometry_sha256": input_hashes["geometry.json"],
            "voxel_m": source_geometry.get("voxel_m"),
            "whole_input": True,
            "coordinate_system": source_geometry["coordinate_system"],
            "unit": source_geometry["unit"],
            "candidate_sha256": hashes["candidate.obj"],
            "candidate_obj_bytes": candidate.stat().st_size,
            "candidate_counts": repair_record["output_counts"],
            "candidate_arrays": hashes,
            "candidate_topology": {
                "closed": True,
                "self_intersection_verified": False,
                "note": "Manifold import/export only; Foundation surfaceCheck remains mandatory.",
            },
            "repair": repair_record,
            "self_intersection_verified": False,
            "scientific_status": "UNVALIDATED_PHASE1_CYCLE",
            "human_review": None,
        })
        print("MANIFOLD_ROUNDTRIP_SAVED", json.dumps(repair_record["output_counts"], separators=(",", ":")), flush=True)
        return repair_record
    except BaseException as exc:
        write(output_root / "repair-failure.json", {
            "schema_version": "phase1-cycle-manifold-roundtrip-1",
            "status": "FAIL",
            "method": METHOD,
            "input_hashes": input_hashes,
            "error": str(exc),
            "elapsed_s": time.monotonic() - started,
        })
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repair(args.input, args.output)


if __name__ == "__main__":
    main()
