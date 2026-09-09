"""Apply the existing 1 micrometre vertex weld to a repaired cycle surface.

This is a diagnostic post-Boolean pass.  It performs no smoothing, scaling,
thickness, hole filling, or part selection; the Foundation checker still
decides whether the resulting surface is usable.
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


METHOD = "blender_post_boolean_direct_weld_1um_compact_v2"


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, allow_nan=False, indent=2), encoding="utf-8")


def arrays(mesh):
    mesh.calc_loop_triangles()
    vertices = np.empty((len(mesh.vertices), 3), dtype=np.float64)
    mesh.vertices.foreach_get("co", vertices.reshape(-1))
    triangles = np.empty((len(mesh.loop_triangles), 3), dtype=np.int32)
    mesh.loop_triangles.foreach_get("vertices", triangles.reshape(-1))
    return vertices, triangles


def write_obj(path, vertices, triangles):
    with Path(path).open("w", encoding="ascii", newline="\n") as stream:
        stream.write("g oguri\n")
        for x, y, z in vertices:
            stream.write(f"v {float(x):.17g} {float(y):.17g} {float(z):.17g}\n")
        for a, b, c in triangles:
            stream.write(f"f {int(a) + 1} {int(b) + 1} {int(c) + 1}\n")


def array_path(root, name):
    nested = Path(root) / "arrays" / name
    flat = Path(root) / name
    if nested.is_file():
        return nested
    if flat.is_file():
        return flat
    raise FileNotFoundError(f"Missing array: {name}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--weld", type=float, default=1e-6)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if bpy.app.version != (4, 2, 23):
        raise ValueError("Pinned Blender 4.2.23 is required")
    if not 0 < args.weld <= 1e-6:
        raise ValueError("Post-weld distance must be in (0, 1um]")
    source = args.input.resolve()
    output = args.output.resolve()
    if output.exists():
        raise ValueError("Fresh post-weld output required")
    record = json.loads((source / "geometry.json").read_text(encoding="utf-8-sig"))
    if record.get("unit") != "m" or record.get("coordinate_system") != "RF_X_FORWARD_Z_UP":
        raise ValueError("Post-weld input must use metres and RF coordinates")
    vertices = np.load(array_path(source, "vertices.npy"), mmap_mode="r")
    triangles = np.load(array_path(source, "triangles.npy"), mmap_mode="r")
    if vertices.ndim != 2 or vertices.shape[1] != 3 or triangles.ndim != 2 or triangles.shape[1] != 3:
        raise ValueError("Post-weld arrays must be Nx3")
    if not len(triangles) or not np.isfinite(vertices).all():
        raise ValueError("Post-weld arrays are empty or nonfinite")
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    try:
        data = mesh_from_arrays(vertices, triangles, "post-Boolean weld input")
        for item in list(bpy.data.objects):
            bpy.data.objects.remove(item, do_unlink=True)
        ob = bpy.data.objects.new("cycle post-Boolean weld", data)
        bpy.context.collection.objects.link(ob)
        bpy.context.view_layer.objects.active = ob
        ob.select_set(True)
        bm = bmesh.new()
        bm.from_mesh(data)
        before_vertices = len(bm.verts)
        before_faces = len(bm.faces)
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=float(args.weld))
        bm.verts.ensure_lookup_table()
        collapsed = [face for face in bm.faces if len({vertex.index for vertex in face.verts}) < 3 or face.calc_area() < 1e-16]
        if collapsed:
            bmesh.ops.delete(bm, geom=collapsed, context="FACES_ONLY")
        loose_vertices = [vertex for vertex in bm.verts if not vertex.link_faces]
        if loose_vertices:
            bmesh.ops.delete(bm, geom=loose_vertices, context="VERTS")
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(data)
        bm.free()
        data.update()
        result_vertices, result_triangles = arrays(data)
        obj_path = output / "candidate.obj"
        write_obj(obj_path, result_vertices, result_triangles)
        output_arrays = output / "arrays"
        output_arrays.mkdir(exist_ok=False)
        np.save(output_arrays / "vertices.npy", result_vertices)
        np.save(output_arrays / "triangles.npy", result_triangles)
        output_hashes = {
            "candidate.obj": sha(obj_path),
            "arrays/vertices.npy": sha(output_arrays / "vertices.npy"),
            "arrays/triangles.npy": sha(output_arrays / "triangles.npy"),
        }
        repair = dict(
            schema_version="phase1-cycle-post-weld-2",
            status="PASS",
            method=METHOD,
            weld_m=float(args.weld),
            input_geometry_sha256=sha(source / "geometry.json"),
            input_array_hashes={f"arrays/{name}": sha(array_path(source, name)) for name in ("vertices.npy", "triangles.npy")},
            output_hashes=output_hashes,
            input_counts={"vertices": int(before_vertices), "triangles": int(before_faces)},
            output_counts={"vertices": int(len(result_vertices)), "triangles": int(len(result_triangles))},
            removed_faces=int(len(collapsed)),
            removed_loose_vertices=int(len(loose_vertices)),
            smoothing=False,
            part_deletion=False,
            added_thickness=False,
            volume_correction=False,
            external_shape_audit="PENDING",
            surface_check="PENDING_FOUNDATION_SURFACECHECK",
            scientific_status="UNVALIDATED_PHASE1_CYCLE",
            elapsed_s=time.monotonic() - started,
        )
        save(output / "repair.json", repair)
        save(output / "geometry.json", dict(
            schema_version="phase1-cycle-geometry-post-weld-2",
            repair_method=METHOD,
            source_sha256=record.get("source_sha256"),
            native_geometry_sha256=sha(source / "geometry.json"),
            voxel_m=record.get("voxel_m"),
            whole_input=True,
            coordinate_system=record["coordinate_system"],
            unit=record["unit"],
            candidate_sha256=output_hashes["candidate.obj"],
            candidate_obj_bytes=obj_path.stat().st_size,
            candidate_counts=repair["output_counts"],
            candidate_arrays={name: digest for name, digest in output_hashes.items() if name.startswith("arrays/")},
            repair=repair,
            self_intersection_verified=False,
            scientific_status="UNVALIDATED_PHASE1_CYCLE",
            human_review=None,
        ))
        print("BLENDER_POST_WELD_SAVED", json.dumps(repair["output_counts"]), flush=True)
    except BaseException as exc:
        save(output / "repair-failure.json", dict(
            schema_version="phase1-cycle-post-weld-2", status="FAIL", method=METHOD,
            input_geometry_sha256=sha(source / "geometry.json"), error=str(exc),
            elapsed_s=time.monotonic() - started))
        raise


if __name__ == "__main__":
    main()
