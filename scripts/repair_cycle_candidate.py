"""Repair one Blender cycle surface with a pinned Manifold self-union.

The Blender result is kept as the immutable native input.  This command writes
the Boolean result into a new directory and records both inputs, tool pins, and
the fact that external-shape fidelity still needs an independent audit.
"""

import argparse
from pathlib import Path
import json
import os
import shutil
import sys
import time

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from repair_trial_support import manifold_backend
from runflow.cfd import private
from runflow.core import file_hash, read, write
from runflow.shape_fullbody import finish_cache


REPAIR_VERSION = "manifold_self_union_v1"
BACKEND_COMMIT = "11235e6b8ebea2dbed8aec4285685aafd3d95667"


def _validate_arrays(vertices, triangles):
    if vertices.ndim != 2 or vertices.shape[1] != 3 or vertices.dtype != np.float64:
        raise ValueError("Native vertices must be a float64 Nx3 array")
    if triangles.ndim != 2 or triangles.shape[1] != 3:
        raise ValueError("Native triangles must be an Nx3 array")
    if not len(triangles) or not np.isfinite(vertices).all():
        raise ValueError("Native surface is empty or contains nonfinite vertices")
    if int(triangles.min()) < 0 or int(triangles.max()) >= len(vertices):
        raise ValueError("Native triangle index is out of range")


def _write_obj(path, vertices, triangles):
    """Write a triangular OBJ without material or per-face metadata."""
    path = Path(path)
    with path.open("w", encoding="ascii", newline="\n") as stream:
        stream.write("g oguri\n")
        for x, y, z in vertices:
            stream.write(f"v {float(x):.17g} {float(y):.17g} {float(z):.17g}\n")
        for a, b, c in triangles:
            stream.write(f"f {int(a) + 1} {int(b) + 1} {int(c) + 1}\n")


def _geometry_record(native_root, output, native, repaired, input_hashes, output_hashes,
                     status, elapsed_s, error=None):
    native_geometry = read(native_root / "geometry.json")
    value = dict(
        schema_version="phase1-cycle-geometry-2",
        repair_version=REPAIR_VERSION,
        blender_version=native_geometry.get("blender_version"),
        source_sha256=native_geometry.get("source_sha256"),
        voxel_m=native_geometry.get("voxel_m"),
        whole_input=True,
        coordinate_system=native_geometry.get("coordinate_system"),
        unit=native_geometry.get("unit"),
        native_geometry_sha256=file_hash(native_root / "geometry.json"),
        native_candidate=dict(
            obj_sha256=native_geometry.get("candidate_sha256"),
            obj_bytes=native_geometry.get("candidate_obj_bytes"),
            counts=native_geometry.get("candidate_counts"),
            topology=native_geometry.get("candidate_topology"),
        ),
        candidate_sha256=output_hashes.get("candidate.obj"),
        candidate_obj_bytes=(output / "candidate.obj").stat().st_size
        if (output / "candidate.obj").exists() else None,
        candidate_counts=repaired,
        candidate_topology=dict(
            closed=status == "PASS",
            manifold_backend_verified=status == "PASS",
            vertex_fans_verified=status == "PASS",
            self_intersection_verified=False,
            note="Boolean backend result; Foundation surfaceCheck remains the external acceptance gate.",
        ),
        candidate_arrays=dict(
            dtype_vertices="float64",
            dtype_triangles="int32",
            hashes=output_hashes,
        ) if status == "PASS" else None,
        input_hashes=input_hashes,
        preprocessing=[
            "Native Blender 0.9 mm full-body result retained as the input surface.",
            "No part cutout, smoothing, scaling, thickness addition, or volume correction.",
            "Manifold boolean self-union applied once to the complete native surface.",
        ],
        repair=dict(
            method=REPAIR_VERSION,
            backend="manifold3d 3.5.2",
            backend_commit=BACKEND_COMMIT,
            operand="native full-body surface union with itself",
            may_remove_internal_overlaps=True,
            may_change_external_surface=True,
            external_shape_audit="PENDING",
            exact_self_intersection_audit="PENDING_FOUNDATION_SURFACECHECK",
            smoothing=False,
            part_deletion=False,
            added_thickness=False,
        ),
        self_intersection_verified=False,
        scientific_status="UNVALIDATED_PHASE1_CYCLE",
        human_review=None,
        status=status,
        elapsed_s=elapsed_s,
    )
    if error is not None:
        value["error"] = str(error)
    return value


def repair(native_root, output):
    native_root = Path(native_root).resolve()
    output = private(output)
    if output.exists():
        raise ValueError("Fresh repaired geometry output required")
    if not (native_root / "geometry.json").is_file():
        raise ValueError("Native Blender geometry record is missing")
    native_geometry = read(native_root / "geometry.json")
    if native_geometry.get("unit") != "m" or native_geometry.get("coordinate_system") != "RF_X_FORWARD_Z_UP":
        raise ValueError("Native geometry must use metres and RF coordinates")
    native_arrays = native_root / "arrays"
    vertices = np.load(native_arrays / "vertices.npy", mmap_mode="r")
    triangles = np.load(native_arrays / "triangles.npy", mmap_mode="r")
    _validate_arrays(vertices, triangles)
    input_hashes = {
        "native_geometry.json": file_hash(native_root / "geometry.json"),
        "native_candidate.obj": file_hash(native_root / "candidate.obj"),
        "native_arrays/vertices.npy": file_hash(native_arrays / "vertices.npy"),
        "native_arrays/triangles.npy": file_hash(native_arrays / "triangles.npy"),
        "repair_script": file_hash(Path(__file__)),
        "repair_support": file_hash(REPO / "scripts/repair_trial_support.py"),
    }
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    try:
        # Mesh64 is allowed to mutate its buffers, so do not pass read-only memmaps.
        input_vertices = np.array(vertices, dtype=np.float64, order="C", copy=True)
        input_triangles = np.array(triangles, dtype=np.uint64, order="C", copy=True)
        print("MANIFOLD_SELF_UNION_IMPORT_BEGIN", len(input_vertices), len(input_triangles), flush=True)
        manifold = manifold_backend(REPO)
        mesh = manifold.Mesh64(input_vertices, input_triangles, tolerance=0.0)
        body = manifold.Manifold(mesh)
        import_status = str(body.status())
        print("MANIFOLD_SELF_UNION_IMPORTED", import_status, body.num_tri(), flush=True)
        if body.status() != manifold.Error.NoError or body.num_tri() == 0:
            raise ValueError("Manifold did not accept the native full-body surface: " + import_status)
        print("MANIFOLD_SELF_UNION_BEGIN", flush=True)
        joined = body + body
        union_status = str(joined.status())
        print("MANIFOLD_SELF_UNION_RESULT", union_status, joined.num_tri(), flush=True)
        if joined.status() != manifold.Error.NoError or joined.num_tri() == 0:
            raise ValueError("Manifold self-union failed: " + union_status)
        exported = joined.to_mesh64()
        repaired_vertices = np.asarray(exported.vert_properties, dtype=np.float64)[:, :3]
        repaired_triangles = np.asarray(exported.tri_verts, dtype=np.int32)
        _validate_arrays(repaired_vertices, repaired_triangles)
        arrays = output / "arrays"
        arrays.mkdir(parents=True, exist_ok=False)
        np.save(arrays / "vertices.npy", repaired_vertices)
        np.save(arrays / "triangles.npy", repaired_triangles)
        cache = finish_cache(arrays, source_sha256=input_hashes["native_candidate.obj"],
                             method=REPAIR_VERSION)
        obj_path = output / "candidate.obj"
        print("MANIFOLD_SELF_UNION_WRITE_OBJ", len(repaired_vertices), len(repaired_triangles), flush=True)
        _write_obj(obj_path, repaired_vertices, repaired_triangles)
        output_hashes = {
            "candidate.obj": file_hash(obj_path),
            "arrays/vertices.npy": file_hash(arrays / "vertices.npy"),
            "arrays/triangles.npy": file_hash(arrays / "triangles.npy"),
        }
        repaired = dict(vertices=len(repaired_vertices), triangles=len(repaired_triangles),
                        bbox_m=[repaired_vertices.min(axis=0).tolist(), repaired_vertices.max(axis=0).tolist()],
                        volume_m3=float(joined.volume()),
                        imported_triangles=int(body.num_tri()),
                        output_triangles=int(joined.num_tri()),
                        import_status=import_status, union_status=union_status,
                        tolerance_m=float(joined.get_tolerance()))
        record = _geometry_record(native_root, output, native_geometry, repaired, input_hashes,
                                  output_hashes, "PASS", time.monotonic() - started)
        record["candidate_arrays"]["cache"] = cache
        write(output / "repair.json", record["repair"] | {
            "schema_version": "phase1-cycle-repair-1",
            "status": "PASS",
            "input_hashes": input_hashes,
            "output_hashes": output_hashes,
            "counts": repaired,
            "volume_m3": float(joined.volume()),
            "tolerance_m": float(joined.get_tolerance()),
            "surface_check_required": True,
        })
        write(output / "geometry.json", record)
        print("MANIFOLD_SELF_UNION_SAVED", json.dumps({"triangles": len(repaired_triangles),
                                                        "vertices": len(repaired_vertices),
                                                        "candidate_sha256": output_hashes["candidate.obj"]}), flush=True)
        return record
    except BaseException as exc:
        record = _geometry_record(native_root, output, native_geometry, {}, input_hashes, {},
                                  "FAIL", time.monotonic() - started, exc)
        write(output / "repair-failure.json", record)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repair(args.input, args.output)


if __name__ == "__main__":
    main()
