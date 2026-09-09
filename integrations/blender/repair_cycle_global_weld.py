"""Globally weld only near-duplicate vertices in a saved cycle candidate.

This is a diagnostic post-process for voxel/CGAL outputs.  It is bounded to
the existing 1 micrometre vertex-cleanup allowance and does not smooth, fill
holes, change parts, or change the voxel scale.  Independent Foundation and
shape audits remain mandatory.
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
sys.path.insert(0, str(REPO / "integrations/blender"))

from fullbody_voxel_compare import mesh_from_arrays


METHOD = "blender_global_near_duplicate_weld_1um_v1"


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def array_path(root, name):
    nested = Path(root) / "arrays" / name
    flat = Path(root) / name
    if nested.is_file():
        return nested
    if flat.is_file():
        return flat
    raise FileNotFoundError("Missing array: " + name)


def topology(triangles):
    edges = np.concatenate((triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]), axis=0)
    edges.sort(axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return dict(
        edges=int(len(counts)),
        boundary_edges=int(np.count_nonzero(counts == 1)),
        nonmanifold_edges=int(np.count_nonzero(counts != 2)),
        max_edge_incidence=int(counts.max()) if len(counts) else 0,
    )


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


def save(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, allow_nan=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--distance", type=float, default=1e-6)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if bpy.app.version != (4, 2, 23):
        raise ValueError("Pinned Blender 4.2.23 is required")
    if not 0.0 < args.distance <= 1e-6:
        raise ValueError("Global weld distance must be in (0, 1um]")
    source = args.input.resolve()
    output = args.output.resolve()
    if output.exists():
        raise ValueError("Fresh global-weld output required")
    source_record = json.loads((source / "geometry.json").read_text(encoding="utf-8-sig"))
    if source_record.get("unit") != "m" or source_record.get("coordinate_system") != "RF_X_FORWARD_Z_UP":
        raise ValueError("Global-weld input must use metres and RF coordinates")
    vertices = np.load(array_path(source, "vertices.npy"), mmap_mode="r")
    triangles = np.load(array_path(source, "triangles.npy"), mmap_mode="r")
    if vertices.ndim != 2 or vertices.shape[1] != 3 or triangles.ndim != 2 or triangles.shape[1] != 3:
        raise ValueError("Global-weld arrays must be Nx3")
    if not len(triangles) or not np.isfinite(vertices).all():
        raise ValueError("Global-weld arrays are empty or nonfinite")
    initial_topology = topology(np.asarray(triangles, dtype=np.int64))
    started = time.monotonic()
    output.mkdir(parents=True, exist_ok=False)
    try:
        data = mesh_from_arrays(vertices, triangles, "cycle global weld input")
        for item in list(bpy.data.objects):
            bpy.data.objects.remove(item, do_unlink=True)
        ob = bpy.data.objects.new("cycle global near duplicate weld", data)
        bpy.context.collection.objects.link(ob)
        bpy.context.view_layer.objects.active = ob
        ob.select_set(True)
        bm = bmesh.new()
        bm.from_mesh(data)
        bm.verts.ensure_lookup_table()
        print("CYCLE_GLOBAL_WELD_BEGIN", args.distance, len(vertices), len(triangles), flush=True)
        result = bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=float(args.distance))
        collapsed = [
            face for face in bm.faces
            if len({vertex.index for vertex in face.verts}) < 3 or face.calc_area() < 1e-16
        ]
        if collapsed:
            bmesh.ops.delete(bm, geom=collapsed, context="FACES_ONLY")
        loose = [vertex for vertex in bm.verts if not vertex.link_faces]
        if loose:
            bmesh.ops.delete(bm, geom=loose, context="VERTS")
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(data)
        bm.free()
        data.update()
        out_vertices, out_triangles = arrays(data)
        final_topology = topology(out_triangles.astype(np.int64, copy=False))
        print("CYCLE_GLOBAL_WELD_GENERATED", len(out_vertices), len(out_triangles), flush=True)
        arrays_dir = output / "arrays"
        arrays_dir.mkdir(parents=True, exist_ok=False)
        np.save(arrays_dir / "vertices.npy", out_vertices)
        np.save(arrays_dir / "triangles.npy", out_triangles)
        candidate = output / "candidate.obj"
        write_obj(candidate, out_vertices, out_triangles)
        output_hashes = {
            "candidate.obj": sha(candidate),
            "arrays/vertices.npy": sha(arrays_dir / "vertices.npy"),
            "arrays/triangles.npy": sha(arrays_dir / "triangles.npy"),
        }
        weld_count = len(result.get("targetmap", {})) if isinstance(result, dict) else None
        repair = dict(
            schema_version="phase1-cycle-global-weld-1",
            status="PASS",
            method=METHOD,
            distance_m=float(args.distance),
            input_geometry_sha256=sha(source / "geometry.json"),
            input_array_hashes={
                "vertices.npy": sha(array_path(source, "vertices.npy")),
                "triangles.npy": sha(array_path(source, "triangles.npy")),
            },
            output_hashes=output_hashes,
            input_counts={"vertices": int(len(vertices)), "triangles": int(len(triangles))},
            output_counts={"vertices": int(len(out_vertices)), "triangles": int(len(out_triangles))},
            bmesh_targetmap_count=weld_count,
            removed_collapsed_faces=int(len(collapsed)),
            removed_loose_vertices=int(len(loose)),
            initial_topology=initial_topology,
            final_topology=final_topology,
            whole_input=True,
            smoothing=False,
            hole_filling=False,
            part_deletion=False,
            surface_check="PENDING_FOUNDATION_SURFACECHECK",
            external_shape_audit="PENDING",
            scientific_status="UNVALIDATED_PHASE1_CYCLE",
            elapsed_s=time.monotonic() - started,
        )
        save(output / "repair.json", repair)
        save(output / "geometry.json", dict(
            schema_version="phase1-cycle-geometry-global-weld-1",
            repair_method=METHOD,
            source_sha256=source_record.get("source_sha256"),
            native_geometry_sha256=sha(source / "geometry.json"),
            voxel_m=source_record.get("voxel_m"),
            whole_input=True,
            coordinate_system=source_record["coordinate_system"],
            unit=source_record["unit"],
            candidate_sha256=output_hashes["candidate.obj"],
            candidate_obj_bytes=candidate.stat().st_size,
            candidate_counts=repair["output_counts"],
            candidate_arrays=output_hashes,
            candidate_topology=dict(final_topology, closed=not final_topology["boundary_edges"] and not final_topology["nonmanifold_edges"], self_intersection_verified=False),
            repair=repair,
            self_intersection_verified=False,
            scientific_status="UNVALIDATED_PHASE1_CYCLE",
            human_review=None,
        ))
        print("CYCLE_GLOBAL_WELD_SAVED", json.dumps(repair["output_counts"]), flush=True)
    except BaseException as exc:
        save(output / "repair-failure.json", {
            "schema_version": "phase1-cycle-global-weld-1",
            "status": "FAIL",
            "method": METHOD,
            "input_geometry_sha256": sha(source / "geometry.json"),
            "error": str(exc),
            "elapsed_s": time.monotonic() - started,
        })
        raise


if __name__ == "__main__":
    main()
