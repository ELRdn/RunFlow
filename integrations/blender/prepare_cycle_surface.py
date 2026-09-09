"""Generate one private full-body CFD surface for a captured gait frame.

This script is intentionally separate from the Phase 1.0 single-pose
preparation script.  It always performs exactly one pinned Blender voxel
remesh, including when the cleaned input happens to be closed, so every gait
frame uses the same surface-generation route.  It writes an ASCII OBJ because
Foundation OpenFOAM consumes that format and binary NumPy arrays for later
shape inspection without duplicating the large mesh in JSON.

The generated surface is an execution input, not a scientific approval.  The
cycle runner performs the authoritative Foundation 14 surface check before it
can create or run a case.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import bpy
import bmesh
import numpy as np


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, allow_nan=False), encoding="utf-8")


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def arrays(mesh):
    mesh.calc_loop_triangles()
    vertices = np.empty((len(mesh.vertices), 3), dtype=np.float64)
    mesh.vertices.foreach_get("co", vertices.reshape(-1))
    triangles = np.empty((len(mesh.loop_triangles), 3), dtype=np.int32)
    mesh.loop_triangles.foreach_get("vertices", triangles.reshape(-1))
    return vertices, triangles


def mesh_from_snapshot(snapshot, name):
    mesh = bpy.data.meshes.new(name)
    vertices = np.asarray(snapshot["vertices"], dtype=np.float64)
    triangles = np.asarray(snapshot["triangles"], dtype=np.int32)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not np.isfinite(vertices).all():
        raise ValueError("Source vertex buffer is not finite XYZ data")
    if triangles.ndim != 2 or triangles.shape[1] != 3 or not len(triangles):
        raise ValueError("Source triangle buffer is empty or malformed")
    if triangles.min() < 0 or triangles.max() >= len(vertices):
        raise ValueError("Source triangle index is outside the vertex buffer")
    mesh.from_pydata(vertices.tolist(), [], triangles.tolist())
    mesh.update()
    return mesh


def clean_mesh(mesh, weld_m):
    """Apply the Phase 0 one-micrometre cleanup to the source mesh."""
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=weld_m)
    bm.verts.index_update()
    seen = set()
    remove = []
    for face in bm.faces:
        key = tuple(sorted(vertex.index for vertex in face.verts))
        if key in seen or face.calc_area() < 1e-16:
            remove.append(face)
        else:
            seen.add(key)
    if remove:
        bmesh.ops.delete(bm, geom=remove, context="FACES_ONLY")
    unused_edges = [edge for edge in bm.edges if not edge.link_faces]
    if unused_edges:
        bmesh.ops.delete(bm, geom=unused_edges, context="EDGES")
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def degenerate_summary(vertices, triangles):
    count = 0
    affected = set()
    for start in range(0, len(triangles), 250_000):
        faces = triangles[start:start + 250_000]
        points = vertices[faces]
        twice_area = np.linalg.norm(
            np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0]), axis=1
        )
        bad = twice_area * 0.5 < 1e-16
        count += int(bad.sum())
        if bad.any():
            affected.update(np.unique(faces[bad]).tolist())
    return count, sorted(affected)


def repair_degenerate_mesh(mesh, weld_m, bad_ids):
    """Perform only the permitted direct weld around emitted degenerate faces."""
    record = dict(method="local_degenerate_direct_weld_v1", weld_m=weld_m,
                  degenerate_triangles_before=len(bad_ids), affected_vertices=len(bad_ids),
                  merged_vertices=0, max_vertex_shift_m=0.0, removed_collapsed_faces=0)
    if not bad_ids:
        return record
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    retained = []
    target_map = {}
    replacements = []
    for index in bad_ids:
        vertex = bm.verts[index]
        target = next((candidate for candidate in retained
                       if (bm.verts[candidate].co - vertex.co).length <= weld_m), None)
        if target is None:
            retained.append(index)
            continue
        distance = float((bm.verts[target].co - vertex.co).length)
        target_map[vertex] = bm.verts[target]
        replacements.append(dict(vertex_index=index, target_index=target,
                                  distance_m=distance))
        record["max_vertex_shift_m"] = max(record["max_vertex_shift_m"], distance)
    if target_map:
        bmesh.ops.weld_verts(bm, targetmap=target_map)
        collapsed = [face for face in bm.faces if face.calc_area() < 1e-16]
        record["removed_collapsed_faces"] = len(collapsed)
        if collapsed:
            bmesh.ops.delete(bm, geom=collapsed, context="FACES_ONLY")
        record["merged_vertices"] = len(target_map)
        record["replacements"] = replacements
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(mesh)
        mesh.update()
    bm.free()
    return record


def edge_topology(vertices, triangles, degenerate_faces):
    """Check edge incidence and orientation with bounded NumPy buffers."""
    if not len(triangles):
        raise ValueError("Candidate surface has no triangles")
    directed = np.concatenate((triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]), axis=0)
    lower = np.minimum(directed[:, 0], directed[:, 1]).astype(np.uint64)
    upper = np.maximum(directed[:, 0], directed[:, 1]).astype(np.uint64)
    keys = (lower << np.uint64(32)) | upper
    direction = np.where(directed[:, 0] < directed[:, 1], 1, -1).astype(np.int8)
    order = np.argsort(keys, kind="mergesort")
    sorted_keys = keys[order]
    starts = np.r_[0, np.flatnonzero(sorted_keys[1:] != sorted_keys[:-1]) + 1]
    ends = np.r_[starts[1:], len(sorted_keys)]
    counts = ends - starts
    sums = np.add.reduceat(direction[order].astype(np.int32), starts)
    boundary = int(np.count_nonzero(counts == 1))
    nonmanifold = int(np.count_nonzero(counts != 2))
    inconsistent = int(np.count_nonzero((counts == 2) & (sums != 0)))
    return dict(vertices=int(len(vertices)), triangles=int(len(triangles)), edges=int(len(starts)),
                boundary_edges=boundary, nonmanifold_edges=nonmanifold,
                inconsistent_edges=inconsistent, nonmanifold_vertices=None,
                degenerate_faces=int(degenerate_faces), vertex_fans_verified=False,
                closed=bool(len(triangles) and boundary == 0 and nonmanifold == 0
                        and inconsistent == 0 and degenerate_faces == 0),
            method="numpy_edge_incidence_v1",
            note="Vertex fan and self-intersection checks remain delegated to Foundation surfaceCheck.")


def recalculate_normals(mesh):
    """Reorient all emitted voxel faces once, without changing their vertices."""
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(mesh)
        mesh.update()
    finally:
        bm.free()


def write_binary_arrays(folder, vertices, triangles):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    np.save(folder / "vertices.npy", vertices)
    np.save(folder / "triangles.npy", triangles)
    return dict(vertices=int(len(vertices)), triangles=int(len(triangles)), dtype_vertices="float64",
                dtype_triangles="int32", hashes={name: file_sha(folder / name)
                                                  for name in ("vertices.npy", "triangles.npy")})


def write_obj(path, vertices, triangles):
    path = Path(path)
    with path.open("w", encoding="ascii", newline="\n") as stream:
        stream.write("g oguri\n")
        for x, y, z in vertices:
            stream.write(f"v {float(x):.9g} {float(y):.9g} {float(z):.9g}\n")
        for a, b, c in triangles:
            stream.write(f"f {int(a) + 1} {int(b) + 1} {int(c) + 1}\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    request = json.loads(args.request.read_text(encoding="utf-8-sig"))
    source = Path(request["source"]).resolve()
    output = Path(request["output"]).resolve()
    settings = request["geometry"]
    if bpy.app.version != (4, 2, 23):
        raise ValueError("Pinned Blender 4.2.23 is required")
    if output.exists():
        raise ValueError("Fresh cycle geometry output required")
    if file_sha(source) != request["source_sha256"]:
        raise ValueError("Cycle source snapshot hash mismatch")
    snapshot = json.loads(source.read_text(encoding="utf-8-sig"))
    if snapshot.get("unit") != "m" or snapshot.get("coordinate_system") != "RF_X_FORWARD_Z_UP":
        raise ValueError("Cycle snapshot must use metres and RF coordinates")
    started = time.monotonic()
    output.mkdir(parents=True, exist_ok=False)
    original = mesh_from_snapshot(snapshot, "cycle source")
    cleaned = original.copy()
    clean_mesh(cleaned, settings["weld_m"])
    clean_vertices, clean_triangles = arrays(cleaned)
    clean_degenerate, _ = degenerate_summary(clean_vertices, clean_triangles)

    # Always remesh once.  A closed source is not used as a silent raw-mesh fallback.
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    obj = bpy.data.objects.new("cycle voxel candidate", cleaned)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    obj.data.remesh_voxel_size = settings["voxel_m"]
    obj.data.remesh_voxel_adaptivity = 0
    obj.data.use_remesh_preserve_volume = False
    print("CYCLE_VOXEL_BEGIN", settings["voxel_m"], flush=True)
    bpy.ops.object.voxel_remesh()
    candidate = obj.data
    candidate.update()
    print("CYCLE_VOXEL_GENERATED", len(candidate.vertices), len(candidate.polygons), flush=True)

    # Blender's voxel output can contain disconnected components with mixed
    # winding.  Correct winding is a topology-preserving postprocess; it is
    # still the single requested voxel remesh and does not smooth or fill.
    recalculate_normals(candidate)
    print("CYCLE_NORMALS_RECALCULATED", len(candidate.polygons), flush=True)

    candidate_vertices, candidate_triangles = arrays(candidate)
    emitted_degenerate, bad_ids = degenerate_summary(candidate_vertices, candidate_triangles)
    repair = repair_degenerate_mesh(candidate, settings["weld_m"], bad_ids)
    if bad_ids:
        candidate_vertices, candidate_triangles = arrays(candidate)
    final_degenerate, _ = degenerate_summary(candidate_vertices, candidate_triangles)
    topology = edge_topology(candidate_vertices, candidate_triangles, final_degenerate)

    arrays_info = write_binary_arrays(output / "arrays", candidate_vertices, candidate_triangles)
    obj_path = output / "candidate.obj"
    write_obj(obj_path, candidate_vertices, candidate_triangles)
    candidate_hash = file_sha(obj_path)
    geometry = dict(
        schema_version="phase1-cycle-geometry-1",
        blender_version=bpy.app.version_string,
        source_sha256=request["source_sha256"],
        candidate_sha256=candidate_hash,
        candidate_obj_bytes=obj_path.stat().st_size,
        voxel_m=settings["voxel_m"],
        whole_input=True,
        coordinate_system=snapshot["coordinate_system"],
        unit=snapshot["unit"],
        source_counts=dict(vertices=len(snapshot["vertices"]), triangles=len(snapshot["triangles"]),
                           parts=len(snapshot.get("parts", []))),
        cleaned_counts=dict(vertices=len(clean_vertices), triangles=len(clean_triangles),
                            degenerate_faces=clean_degenerate),
        candidate_counts=dict(vertices=len(candidate_vertices), triangles=len(candidate_triangles),
                              emitted_degenerate_faces=emitted_degenerate,
                              final_degenerate_faces=final_degenerate),
        candidate_bbox_m=[candidate_vertices.min(axis=0).tolist(), candidate_vertices.max(axis=0).tolist()],
        candidate_topology=topology,
        candidate_arrays=arrays_info,
        preprocessing=[
            "Whole captured mesh retained; no part cutout or part deletion.",
            "1 micrometre source weld, duplicate/degenerate face removal, and normal recalculation.",
            "Exactly one Blender voxel remesh; adaptivity disabled; preserve-volume correction disabled.",
            "Voxel-output face winding recalculated once; vertices and triangles are otherwise retained.",
            "Only emitted degenerate faces received the direct 1 micrometre local weld when required.",
        ],
        repair=repair,
        distance_verification="NOT_RUN_FOR_CYCLE_BATCH",
        distance_passed=None,
        self_intersection_verified=False,
        scientific_status="UNVALIDATED_PHASE1_CYCLE",
        human_review=None,
        elapsed_s=time.monotonic() - started,
    )
    save(output / "geometry.json", geometry)
    print("CYCLE_GEOMETRY_SAVED", json.dumps({"closed": topology["closed"], "triangles": len(candidate_triangles)}), flush=True)


if __name__ == "__main__":
    main()
