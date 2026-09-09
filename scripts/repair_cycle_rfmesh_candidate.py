"""Materialize a private candidate from a validated RunFlow rfmesh stream.

The native geometry tools exchange a compact binary surface.  This command
creates the ordinary cycle-candidate layout without putting the binary mesh in
Git.  It preserves the source record and records the converter/tool hashes.
"""

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
from runflow.cfd import private
from runflow.core import file_hash, write
from runflow.local_geometry import binary_read
from runflow.shape_fullbody import finish_cache


METHOD = "rfmesh_materialize_candidate_v1"


def materialize(source_root, rfmesh, output_root, repair_record=None):
    source_root = Path(source_root).resolve()
    rfmesh = Path(rfmesh).resolve()
    output_root = private(output_root)
    if output_root.exists():
        raise ValueError("Fresh rfmesh candidate output required")
    source_geometry_path = source_root / "geometry.json"
    if not source_geometry_path.is_file():
        raise ValueError("Source geometry record is missing")
    source_geometry = json.loads(source_geometry_path.read_text(encoding="utf-8-sig"))
    if source_geometry.get("unit") != "m" or source_geometry.get("coordinate_system") != "RF_X_FORWARD_Z_UP":
        raise ValueError("Source geometry must use metres and RF coordinates")

    started = time.monotonic()
    vertices, triangles = binary_read(rfmesh)
    vertices = np.asarray(vertices, dtype=np.float64)
    triangles = np.asarray(triangles, dtype=np.int32)
    _validate_arrays(vertices, triangles)
    output_root.mkdir(parents=True, exist_ok=False)
    arrays = output_root / "arrays"
    arrays.mkdir(parents=True, exist_ok=False)
    np.save(arrays / "vertices.npy", vertices)
    np.save(arrays / "triangles.npy", triangles)
    candidate = output_root / "candidate.obj"
    _write_obj(candidate, vertices, triangles)
    hashes = {
        "candidate.obj": file_hash(candidate),
        "arrays/vertices.npy": file_hash(arrays / "vertices.npy"),
        "arrays/triangles.npy": file_hash(arrays / "triangles.npy"),
    }
    input_hashes = {
        "source_geometry.json": file_hash(source_geometry_path),
        "source_candidate.obj": file_hash(source_root / "candidate.obj"),
        "source_arrays/vertices.npy": file_hash(source_root / "arrays/vertices.npy"),
        "source_arrays/triangles.npy": file_hash(source_root / "arrays/triangles.npy"),
        "rfmesh": file_hash(rfmesh),
        "converter": file_hash(Path(__file__)),
    }
    cache = finish_cache(arrays, source_sha256=input_hashes["rfmesh"], method=METHOD)
    repair = dict(repair_record or {})
    repair.update({
        "schema_version": "phase1-cycle-rfmesh-materialize-1",
        "materialize_method": METHOD,
        "status": "PASS",
        "input_hashes": input_hashes,
        "output_hashes": hashes,
        "output_counts": {"vertices": int(len(vertices)), "triangles": int(len(triangles))},
        "whole_input": True,
        "smoothing": False,
        "hole_filling": False,
        "part_deletion": False,
        "surface_check": "PENDING_FOUNDATION_SURFACECHECK",
        "external_shape_audit": "PENDING",
        "scientific_status": "UNVALIDATED_PHASE1_CYCLE",
        "cache": cache,
        "elapsed_s": time.monotonic() - started,
    })
    geometry = {
        "schema_version": "phase1-cycle-geometry-rfmesh-materialize-1",
        "repair_method": repair.get("method", METHOD),
        "source_sha256": source_geometry.get("source_sha256"),
        "native_geometry_sha256": input_hashes["source_geometry.json"],
        "voxel_m": source_geometry.get("voxel_m"),
        "whole_input": True,
        "coordinate_system": source_geometry["coordinate_system"],
        "unit": source_geometry["unit"],
        "candidate_sha256": hashes["candidate.obj"],
        "candidate_obj_bytes": candidate.stat().st_size,
        "candidate_counts": repair["output_counts"],
        "candidate_arrays": hashes,
        "candidate_topology": {
            "closed": True,
            "self_intersection_verified": False,
            "note": "Materialized from native diagnostic output; Foundation surfaceCheck remains mandatory.",
        },
        "repair": repair,
        "self_intersection_verified": False,
        "scientific_status": "UNVALIDATED_PHASE1_CYCLE",
        "human_review": None,
    }
    write(output_root / "repair.json", repair)
    write(output_root / "geometry.json", geometry)
    print("RFMESH_CANDIDATE_SAVED", json.dumps({
        "vertices": int(len(vertices)),
        "triangles": int(len(triangles)),
        "candidate_sha256": hashes["candidate.obj"],
    }, separators=(",", ":")), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--rfmesh", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--method", default="cgal_repair_polygon_soup_noop_v1")
    parser.add_argument("--tool-status", default="PASS")
    args = parser.parse_args()
    materialize(args.source_root, args.rfmesh, args.output, {
        "method": args.method,
        "tool_status": args.tool_status,
    })


if __name__ == "__main__":
    main()
