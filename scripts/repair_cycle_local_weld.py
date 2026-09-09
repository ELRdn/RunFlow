"""Apply a bounded, point-directed weld to a saved cycle surface.

This diagnostic is deliberately local.  It selects the two closest vertices
to each Foundation ``selfInterPoints.obj`` point, welds only those pairs, and
removes only faces that became degenerate because of that weld.  It does not
smooth, fill holes, delete parts, or change the global tolerance.
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


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "integrations/blender"))

from fullbody_voxel_compare import mesh_from_arrays


METHOD = "blender_foundation_point_direct_weld_v1"


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, allow_nan=False, indent=2), encoding="utf-8")


def array_path(root, name):
    nested = Path(root) / "arrays" / name
    flat = Path(root) / name
    if nested.is_file():
        return nested
    if flat.is_file():
        return flat
    raise FileNotFoundError(f"Missing array: {name}")


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


def nearest_pair(vertices, point, search_radius, max_weld):
    delta = vertices - np.asarray(point, dtype=np.float64)
    distance2 = np.einsum("ij,ij->i", delta, delta)
    candidates = np.flatnonzero(distance2 <= float(search_radius) ** 2)
    if len(candidates) < 2:
        raise ValueError("Fewer than two vertices in local search radius")
    order = candidates[np.argsort(distance2[candidates], kind="mergesort")]
    first, second = int(order[0]), int(order[1])
    pair_distance = float(np.linalg.norm(vertices[first] - vertices[second]))
    if pair_distance > max_weld:
        raise ValueError(f"Nearest local pair exceeds weld limit: {pair_distance}")
    return first, second, pair_distance, float(np.sqrt(distance2[first])), float(np.sqrt(distance2[second]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--point", type=float, nargs=3, action="append", required=True)
    parser.add_argument("--search-radius", type=float, default=5e-6)
    parser.add_argument("--max-weld", type=float, default=1e-6)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if bpy.app.version != (4, 2, 23):
        raise ValueError("Pinned Blender 4.2.23 is required")
    if not 0 < args.max_weld <= 1e-6 or not 0 < args.search_radius:
        raise ValueError("Invalid local weld limits")
    source = args.input.resolve()
    output = args.output.resolve()
    if output.exists():
        raise ValueError("Fresh local-weld output required")
    source_record = json.loads((source / "geometry.json").read_text(encoding="utf-8-sig"))
    if source_record.get("unit") != "m" or source_record.get("coordinate_system") != "RF_X_FORWARD_Z_UP":
        raise ValueError("Local-weld input must use metres and RF coordinates")
    vertex_path = array_path(source, "vertices.npy")
    triangle_path = array_path(source, "triangles.npy")
    vertices = np.load(vertex_path, mmap_mode="r")
    triangles = np.load(triangle_path, mmap_mode="r")
    if vertices.ndim != 2 or vertices.shape[1] != 3 or triangles.ndim != 2 or triangles.shape[1] != 3:
        raise ValueError("Local-weld arrays must be Nx3")
    if not len(triangles) or not np.isfinite(vertices).all():
        raise ValueError("Local-weld arrays are empty or nonfinite")
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    points = [[float(value) for value in point] for point in args.point]
    pairs = {}
    selections = []
    for point in points:
        first, second, distance, first_distance, second_distance = nearest_pair(
            vertices, point, args.search_radius, args.max_weld
        )
        key = tuple(sorted((first, second)))
        pairs[key] = key
        selections.append(dict(
            point=point,
            vertices=[first, second],
            vertex_distance_m=distance,
            point_distances_m=[first_distance, second_distance],
        ))
    if not pairs:
        raise ValueError("No local vertex pairs selected")

    try:
        data = mesh_from_arrays(vertices, triangles, "Foundation point-weld input")
        for item in list(bpy.data.objects):
            bpy.data.objects.remove(item, do_unlink=True)
        ob = bpy.data.objects.new("cycle Foundation point weld", data)
        bpy.context.collection.objects.link(ob)
        bpy.context.view_layer.objects.active = ob
        ob.select_set(True)
        bm = bmesh.new()
        bm.from_mesh(data)
        bm.verts.ensure_lookup_table()
        targetmap = {}
        for first, second in sorted(pairs.values()):
            targetmap[bm.verts[second]] = bm.verts[first]
        bmesh.ops.weld_verts(bm, targetmap=targetmap)
        collapsed = [face for face in bm.faces if len({vertex.index for vertex in face.verts}) < 3 or face.calc_area() < 1e-16]
        if collapsed:
            bmesh.ops.delete(bm, geom=collapsed, context="FACES_ONLY")
        loose_vertices = [vertex for vertex in bm.verts if not vertex.link_faces]
        if loose_vertices:
            bmesh.ops.delete(bm, geom=loose_vertices, context="VERTS")
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        boundary_edges = sum(len(edge.link_faces) == 1 for edge in bm.edges)
        nonmanifold_edges = sum(len(edge.link_faces) != 2 for edge in bm.edges)
        bm.to_mesh(data)
        bm.free()
        data.update()
        result_vertices, result_triangles = arrays(data)
        arrays_dir = output / "arrays"
        arrays_dir.mkdir(exist_ok=False)
        np.save(arrays_dir / "vertices.npy", result_vertices)
        np.save(arrays_dir / "triangles.npy", result_triangles)
        obj_path = output / "candidate.obj"
        write_obj(obj_path, result_vertices, result_triangles)
        output_hashes = {
            "candidate.obj": sha(obj_path),
            "arrays/vertices.npy": sha(arrays_dir / "vertices.npy"),
            "arrays/triangles.npy": sha(arrays_dir / "triangles.npy"),
        }
        repair = dict(
            schema_version="phase1-cycle-local-weld-1",
            status="PASS",
            method=METHOD,
            input_geometry_sha256=sha(source / "geometry.json"),
            input_array_hashes={
                "arrays/vertices.npy": sha(vertex_path),
                "arrays/triangles.npy": sha(triangle_path),
            },
            diagnostic_points=points,
            search_radius_m=float(args.search_radius),
            max_weld_m=float(args.max_weld),
            selected_pairs=selections,
            unique_pair_count=len(pairs),
            input_counts={"vertices": int(len(vertices)), "triangles": int(len(triangles))},
            output_counts={"vertices": int(len(result_vertices)), "triangles": int(len(result_triangles))},
            removed_faces=int(len(collapsed)),
            removed_loose_vertices=int(len(loose_vertices)),
            boundary_edges=int(boundary_edges),
            nonmanifold_edges=int(nonmanifold_edges),
            smoothing=False,
            hole_filling=False,
            part_deletion=False,
            external_shape_audit="PENDING",
            surface_check="PENDING_FOUNDATION_SURFACECHECK",
            scientific_status="UNVALIDATED_PHASE1_CYCLE",
            output_hashes=output_hashes,
            elapsed_s=time.monotonic() - started,
        )
        save(output / "repair.json", repair)
        save(output / "geometry.json", dict(
            schema_version="phase1-cycle-geometry-local-weld-1",
            repair_method=METHOD,
            source_sha256=source_record.get("source_sha256"),
            native_geometry_sha256=sha(source / "geometry.json"),
            voxel_m=source_record.get("voxel_m"),
            whole_input=True,
            coordinate_system=source_record["coordinate_system"],
            unit=source_record["unit"],
            candidate_sha256=output_hashes["candidate.obj"],
            candidate_obj_bytes=obj_path.stat().st_size,
            candidate_counts=repair["output_counts"],
            candidate_topology=dict(
                closed=boundary_edges == 0 and nonmanifold_edges == 0,
                boundary_edges=int(boundary_edges),
                nonmanifold_edges=int(nonmanifold_edges),
                self_intersection_verified=False,
            ),
            candidate_arrays=output_hashes,
            repair=repair,
            self_intersection_verified=False,
            scientific_status="UNVALIDATED_PHASE1_CYCLE",
            human_review=None,
        ))
        print("FOUNDATION_POINT_WELD_SAVED", json.dumps(repair["output_counts"]), flush=True)
    except BaseException as exc:
        save(output / "repair-failure.json", dict(
            schema_version="phase1-cycle-local-weld-1",
            status="FAIL",
            method=METHOD,
            input_geometry_sha256=sha(source / "geometry.json"),
            error=str(exc),
            elapsed_s=time.monotonic() - started,
        ))
        raise


if __name__ == "__main__":
    main()
