"""Stitch only sub-micrometre boundary duplicate vertices in a cycle mesh.

This is a diagnostic repair for triangle-soup outputs that contain tiny
duplicate-coordinate seams.  It never moves a representative vertex, fills a
hole, smooths, or removes a non-collapsed face.  Foundation surfaceCheck and
the shape audit remain mandatory after a candidate is written.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from runflow.cfd import private


METHOD = "numpy_boundary_cluster_stitch_v1"


def array_path(root, name):
    nested = Path(root) / "arrays" / name
    flat = Path(root) / name
    if nested.is_file():
        return nested
    if flat.is_file():
        return flat
    raise FileNotFoundError("Missing array: " + name)


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def topology(triangles):
    edges = np.concatenate(
        (triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]),
        axis=0,
    )
    edges.sort(axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return {
        "edges": int(len(counts)),
        "boundary_edges": int(np.count_nonzero(counts == 1)),
        "nonmanifold_edges": int(np.count_nonzero(counts != 2)),
        "max_edge_incidence": int(counts.max()) if len(counts) else 0,
    }


def boundary_vertices(triangles):
    edges = np.concatenate(
        (triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]),
        axis=0,
    )
    edges.sort(axis=1)
    _, first, counts = np.unique(
        edges, axis=0, return_index=True, return_counts=True
    )
    return np.unique(edges[first[counts == 1]].reshape(-1)).astype(np.int64)


def clusters(vertices, ids, radius):
    """Return a deterministic root vertex for each boundary vertex."""
    parent = np.arange(len(ids), dtype=np.int64)

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left, right):
        left = find(left)
        right = find(right)
        if left == right:
            return
        parent[max(left, right)] = min(left, right)

    radius2 = float(radius) ** 2
    cell_size = float(radius)
    buckets = {}
    for local_index, vertex_index in enumerate(ids):
        cell = tuple(np.floor(vertices[vertex_index] / cell_size).astype(np.int64))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for other in buckets.get((cell[0] + dx, cell[1] + dy, cell[2] + dz), ()):
                        delta = vertices[vertex_index] - vertices[ids[other]]
                        if float(np.dot(delta, delta)) <= radius2:
                            union(local_index, other)
        buckets.setdefault(cell, []).append(local_index)

    groups = {}
    for local_index, vertex_index in enumerate(ids):
        root = find(local_index)
        groups.setdefault(root, []).append(int(vertex_index))
    result = []
    for members in groups.values():
        members.sort()
        result.append(members)
    return sorted(result, key=lambda members: members[0])


def write_obj(path, vertices, triangles):
    with Path(path).open("w", encoding="ascii", newline="\n") as stream:
        stream.write("g oguri\n")
        for x, y, z in vertices:
            stream.write(f"v {float(x):.17g} {float(y):.17g} {float(z):.17g}\n")
        for a, b, c in triangles:
            stream.write(f"f {int(a) + 1} {int(b) + 1} {int(c) + 1}\n")


def run(source_root, output_root, max_weld):
    source_root = Path(source_root).resolve()
    output_root = private(output_root)
    if output_root.exists():
        raise ValueError("Fresh boundary-stitch output required")
    if not np.isfinite(max_weld) or not 0.0 < max_weld <= 1e-6:
        raise ValueError("Boundary stitch limit must be in (0, 1um]")

    source_geometry_path = source_root / "geometry.json"
    source_geometry = json.loads(source_geometry_path.read_text(encoding="utf-8-sig"))
    if source_geometry.get("unit") != "m" or source_geometry.get("coordinate_system") != "RF_X_FORWARD_Z_UP":
        raise ValueError("Boundary-stitch input must use metres and RF coordinates")
    vertices = np.asarray(np.load(array_path(source_root, "vertices.npy"), mmap_mode="r"), dtype=np.float64)
    triangles = np.asarray(np.load(array_path(source_root, "triangles.npy"), mmap_mode="r"), dtype=np.int64)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or triangles.ndim != 2 or triangles.shape[1] != 3:
        raise ValueError("Boundary-stitch arrays must be Nx3")
    if not len(triangles) or not np.isfinite(vertices).all():
        raise ValueError("Boundary-stitch arrays are empty or nonfinite")

    started = time.monotonic()
    initial_topology = topology(triangles)
    ids = boundary_vertices(triangles)
    if not len(ids):
        raise ValueError("Boundary-stitch input has no boundary vertices")
    groups = clusters(vertices, ids, max_weld)
    changed = [members for members in groups if len(members) > 1]
    if not changed:
        raise ValueError("No boundary vertex cluster within weld limit")

    mapping = np.arange(len(vertices), dtype=np.int64)
    max_shift = 0.0
    for members in changed:
        root = members[0]
        for vertex_index in members[1:]:
            mapping[vertex_index] = root
            max_shift = max(max_shift, float(np.linalg.norm(vertices[vertex_index] - vertices[root])))
    welded = mapping[triangles]
    degenerate = (
        (welded[:, 0] == welded[:, 1])
        | (welded[:, 1] == welded[:, 2])
        | (welded[:, 2] == welded[:, 0])
    )
    welded = welded[~degenerate]
    used = np.unique(welded.reshape(-1))
    remap = np.full(len(vertices), -1, dtype=np.int64)
    remap[used] = np.arange(len(used), dtype=np.int64)
    out_vertices = np.asarray(vertices[used], dtype=np.float64)
    out_triangles = remap[welded].astype(np.int32, copy=False)
    final_topology = topology(out_triangles)

    output_root.mkdir(parents=True, exist_ok=False)
    arrays = output_root / "arrays"
    arrays.mkdir(parents=True, exist_ok=False)
    np.save(arrays / "vertices.npy", out_vertices)
    np.save(arrays / "triangles.npy", out_triangles)
    candidate = output_root / "candidate.obj"
    write_obj(candidate, out_vertices, out_triangles)
    hashes = {
        "candidate.obj": file_hash(candidate),
        "arrays/vertices.npy": file_hash(arrays / "vertices.npy"),
        "arrays/triangles.npy": file_hash(arrays / "triangles.npy"),
    }
    repair = {
        "schema_version": "phase1-cycle-boundary-stitch-1",
        "status": "PASS",
        "method": METHOD,
        "scientific_status": "UNVALIDATED_PHASE1_CYCLE",
        "input_hashes": {
            "geometry.json": file_hash(source_geometry_path),
            "candidate.obj": file_hash(source_root / "candidate.obj"),
            "arrays/vertices.npy": file_hash(array_path(source_root, "vertices.npy")),
            "arrays/triangles.npy": file_hash(array_path(source_root, "triangles.npy")),
            "repair_script": file_hash(Path(__file__)),
        },
        "output_hashes": hashes,
        "input_counts": {"vertices": int(len(vertices)), "triangles": int(len(triangles))},
        "output_counts": {"vertices": int(len(out_vertices)), "triangles": int(len(out_triangles))},
        "initial_topology": initial_topology,
        "final_topology": final_topology,
        "boundary_vertex_count": int(len(ids)),
        "cluster_count": int(len(groups)),
        "changed_cluster_count": int(len(changed)),
        "cluster_sizes": [len(members) for members in changed],
        "max_weld_m": float(max_weld),
        "max_vertex_shift_m": max_shift,
        "removed_collapsed_faces": int(degenerate.sum()),
        "removed_loose_vertices": int(len(vertices) - len(used)),
        "whole_input": True,
        "smoothing": False,
        "hole_filling": False,
        "part_deletion": False,
        "surface_check": "PENDING_FOUNDATION_SURFACECHECK",
        "external_shape_audit": "PENDING",
        "elapsed_s": time.monotonic() - started,
    }
    (output_root / "repair.json").write_text(json.dumps(repair, sort_keys=True, indent=2), encoding="utf-8")
    geometry = {
        "schema_version": "phase1-cycle-geometry-boundary-stitch-1",
        "repair_method": METHOD,
        "source_sha256": source_geometry.get("source_sha256"),
        "native_geometry_sha256": file_hash(source_geometry_path),
        "voxel_m": source_geometry.get("voxel_m"),
        "whole_input": True,
        "coordinate_system": source_geometry["coordinate_system"],
        "unit": source_geometry["unit"],
        "candidate_sha256": hashes["candidate.obj"],
        "candidate_obj_bytes": candidate.stat().st_size,
        "candidate_counts": repair["output_counts"],
        "candidate_arrays": hashes,
        "candidate_topology": dict(final_topology, closed=not final_topology["boundary_edges"] and not final_topology["nonmanifold_edges"], self_intersection_verified=False),
        "repair": repair,
        "self_intersection_verified": False,
        "scientific_status": "UNVALIDATED_PHASE1_CYCLE",
        "human_review": None,
    }
    (output_root / "geometry.json").write_text(json.dumps(geometry, sort_keys=True, indent=2), encoding="utf-8")
    print("BOUNDARY_STITCH_SAVED", json.dumps(repair["output_counts"], separators=(",", ":")), flush=True)
    return repair


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-weld", type=float, default=1e-6)
    args = parser.parse_args()
    run(args.input, args.output, args.max_weld)


if __name__ == "__main__":
    main()
