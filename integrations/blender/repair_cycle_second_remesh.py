"""Diagnostic second-pass voxel repair for one saved cycle surface.

This is a separate repair trial.  The first Blender output is never replaced;
the second pass is accepted only after the independent Foundation check and
the existing shape audits have been run.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import bpy
import bmesh
import numpy as np


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "integrations/blender"))

from fullbody_voxel_compare import mesh_from_arrays


METHOD = "blender_second_voxel_remesh_same_0.9mm_v1"


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, allow_nan=False, indent=2), encoding="utf-8")


def recalculate_normals(mesh):
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(mesh)
        mesh.update()
    finally:
        bm.free()


def export_arrays(mesh, folder):
    mesh.calc_loop_triangles()
    vertices = np.empty((len(mesh.vertices), 3), dtype=np.float64)
    mesh.vertices.foreach_get("co", vertices.reshape(-1))
    triangles = np.empty((len(mesh.loop_triangles), 3), dtype=np.int32)
    mesh.loop_triangles.foreach_get("vertices", triangles.reshape(-1))
    folder.mkdir(parents=True, exist_ok=False)
    np.save(folder / "vertices.npy", vertices)
    np.save(folder / "triangles.npy", triangles)
    return vertices, triangles


def obj(path, vertices, triangles):
    with Path(path).open("w", encoding="ascii", newline="\n") as stream:
        stream.write("g oguri\n")
        for x, y, z in vertices:
            # Keep the double-precision coordinates used by the Foundation
            # checker; the diagnostic must measure the remesh, not OBJ rounding.
            stream.write(f"v {float(x):.17g} {float(y):.17g} {float(z):.17g}\n")
        for a, b, c in triangles:
            stream.write(f"f {int(a) + 1} {int(b) + 1} {int(c) + 1}\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if bpy.app.version != (4, 2, 23):
        raise ValueError("Pinned Blender 4.2.23 is required")
    source = args.input.resolve()
    output = args.output.resolve()
    if output.exists():
        raise ValueError("Fresh second-remesh output required")
    native_record = json.loads((source / "geometry.json").read_text(encoding="utf-8-sig"))
    if native_record.get("unit") != "m" or native_record.get("coordinate_system") != "RF_X_FORWARD_Z_UP":
        raise ValueError("Native cycle geometry must use metres and RF coordinates")
    vertices = np.load(source / "arrays/vertices.npy", mmap_mode="r")
    triangles = np.load(source / "arrays/triangles.npy", mmap_mode="r")
    if vertices.ndim != 2 or vertices.shape[1] != 3 or triangles.ndim != 2 or triangles.shape[1] != 3:
        raise ValueError("Native arrays must be Nx3")
    if not len(triangles) or not np.isfinite(vertices).all():
        raise ValueError("Native arrays are empty or nonfinite")
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    try:
        data = mesh_from_arrays(vertices, triangles, "cycle second-remesh input")
        for item in list(bpy.data.objects):
            bpy.data.objects.remove(item, do_unlink=True)
        ob = bpy.data.objects.new("cycle second-remesh", data)
        bpy.context.collection.objects.link(ob)
        bpy.context.view_layer.objects.active = ob
        ob.select_set(True)
        data.remesh_voxel_size = 0.0009
        data.remesh_voxel_adaptivity = 0
        data.use_remesh_preserve_volume = False
        print("CYCLE_SECOND_REMESH_BEGIN", 0.0009, len(vertices), len(triangles), flush=True)
        bpy.ops.object.voxel_remesh()
        recalculate_normals(ob.data)
        print("CYCLE_SECOND_REMESH_GENERATED", len(ob.data.vertices), len(ob.data.polygons), flush=True)
        result_vertices, result_triangles = export_arrays(ob.data, output / "arrays")
        obj_path = output / "candidate.obj"
        obj(obj_path, result_vertices, result_triangles)
        output_hashes = {
            "candidate.obj": sha(obj_path),
            "arrays/vertices.npy": sha(output / "arrays/vertices.npy"),
            "arrays/triangles.npy": sha(output / "arrays/triangles.npy"),
        }
        repair = dict(
            schema_version="phase1-cycle-second-remesh-1",
            status="PASS",
            method=METHOD,
            voxel_m=0.0009,
            passes=1,
            adaptivity=0,
            preserve_volume=False,
            input_geometry_sha256=sha(source / "geometry.json"),
            input_array_hashes={
                "vertices.npy": sha(source / "arrays/vertices.npy"),
                "triangles.npy": sha(source / "arrays/triangles.npy"),
            },
            output_hashes=output_hashes,
            input_counts={"vertices": int(len(vertices)), "triangles": int(len(triangles))},
            output_counts={"vertices": int(len(result_vertices)), "triangles": int(len(result_triangles))},
            whole_input=True,
            smoothing=False,
            part_deletion=False,
            volume_correction=False,
            external_shape_audit="PENDING",
            surface_check="PENDING_FOUNDATION_SURFACECHECK",
            scientific_status="UNVALIDATED_PHASE1_CYCLE",
            elapsed_s=time.monotonic() - started,
        )
        save(output / "repair.json", repair)
        save(output / "geometry.json", {
            "schema_version": "phase1-cycle-geometry-3",
            "repair_method": METHOD,
            "source_sha256": native_record.get("source_sha256"),
            "native_geometry_sha256": sha(source / "geometry.json"),
            "voxel_m": 0.0009,
            "whole_input": True,
            "coordinate_system": native_record["coordinate_system"],
            "unit": native_record["unit"],
            "candidate_sha256": output_hashes["candidate.obj"],
            "candidate_obj_bytes": obj_path.stat().st_size,
            "candidate_counts": repair["output_counts"],
            "candidate_arrays": output_hashes,
            "repair": repair,
            "self_intersection_verified": False,
            "scientific_status": "UNVALIDATED_PHASE1_CYCLE",
            "human_review": None,
        })
        print("CYCLE_SECOND_REMESH_SAVED", json.dumps(repair["output_counts"]), flush=True)
    except BaseException as exc:
        save(output / "repair-failure.json", {
            "schema_version": "phase1-cycle-second-remesh-1",
            "status": "FAIL",
            "method": METHOD,
            "input_geometry_sha256": sha(source / "geometry.json"),
            "error": str(exc),
            "elapsed_s": time.monotonic() - started,
        })
        raise


if __name__ == "__main__":
    main()
