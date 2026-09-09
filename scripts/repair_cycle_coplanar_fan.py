"""Remove only validated interior coplanar fan vertices from a cycle surface.

Some voxel surfaces contain a planar six-triangle fan whose interior vertex is
reported by Foundation surfaceCheck as a self-intersection.  This diagnostic
retriangulates the existing outer ring and keeps every ring coordinate exactly
unchanged.  It refuses non-coplanar or non-cyclic neighborhoods and never
smooths, fills, thickens, or deletes a semantic component.
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
sys.path.insert(0, str(REPO / "scripts"))

from repair_cycle_candidate import _validate_arrays, _write_obj
from runflow.cfd import private
from runflow.core import file_hash, write
from runflow.shape_fullbody import finish_cache


METHOD = "coplanar_fan_retriangulate_v1"


def sha(path):
    return file_hash(Path(path))


def topology(triangles):
    edges = np.concatenate((triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]))
    edges.sort(axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return {
        "edges": int(len(counts)),
        "boundary_edges": int(np.count_nonzero(counts == 1)),
        "nonmanifold_edges": int(np.count_nonzero(counts != 2)),
        "max_edge_incidence": int(counts.max()) if len(counts) else 0,
    }


def cycle_for_center(vertices, triangles, center):
    incident_ids = np.flatnonzero(np.any(triangles == center, axis=1))
    directed = []
    normal = np.zeros(3, dtype=np.float64)
    point = vertices[center]
    for face_id in incident_ids:
        tri = [int(value) for value in triangles[face_id]]
        if tri.count(center) != 1:
            raise ValueError(f"Center {center} has a degenerate incident face")
        center_position = tri.index(center)
        # The oriented edge opposite the center is the next two vertices in
        # the cyclic face order.  Simply filtering the center reverses every
        # fan edge whose center is in the middle of the face.
        directed.append((tri[(center_position + 1) % 3], tri[(center_position + 2) % 3]))
        normal += np.cross(vertices[tri[1]] - vertices[tri[0]], vertices[tri[2]] - vertices[tri[0]])
    if len(directed) < 3:
        raise ValueError(f"Center {center} does not have a polygonal fan")
    outgoing = {}
    incoming = {}
    for start, end in directed:
        if start in outgoing or end in incoming:
            raise ValueError(f"Center {center} fan is not a single directed cycle")
        outgoing[start] = end
        incoming[end] = start
    start = min(outgoing)
    ring = [start]
    while True:
        next_vertex = outgoing[ring[-1]]
        if next_vertex == start:
            break
        if next_vertex in ring or len(ring) > len(directed):
            raise ValueError(f"Center {center} fan cycle is not simple")
        ring.append(next_vertex)
    if len(ring) != len(directed):
        raise ValueError(f"Center {center} fan has disconnected incident faces")
    if np.linalg.norm(normal) <= 1e-20:
        raise ValueError(f"Center {center} fan normal is undefined")
    return incident_ids, np.asarray(ring, dtype=np.int64), normal


def plane_residual(vertices, ring):
    points = np.asarray(vertices[ring], dtype=np.float64)
    centroid = points.mean(axis=0)
    _, _, vh = np.linalg.svd(points - centroid, full_matrices=False)
    normal = vh[-1]
    distances = np.abs((points - centroid) @ normal)
    return float(distances.max(initial=0.0)), normal


def project(vertices, ring, normal):
    normal = normal / np.linalg.norm(normal)
    basis = np.cross(normal, np.array([1.0, 0.0, 0.0]))
    if np.linalg.norm(basis) < 1e-8:
        basis = np.cross(normal, np.array([0.0, 1.0, 0.0]))
    basis /= np.linalg.norm(basis)
    second = np.cross(normal, basis)
    origin = vertices[ring].mean(axis=0)
    points = vertices[ring] - origin
    return np.column_stack((points @ basis, points @ second))


def signed_area(points):
    return float(0.5 * np.sum(points[:, 0] * np.roll(points[:, 1], -1) -
                                 points[:, 1] * np.roll(points[:, 0], -1)))


def cross2(a, b, c):
    ab = b - a
    ac = c - a
    return float(ab[0] * ac[1] - ab[1] * ac[0])


def point_in_triangle(point, a, b, c, sign):
    values = [cross2(a, b, point), cross2(b, c, point), cross2(c, a, point)]
    return all(value * sign >= -1e-14 for value in values)


def triangulate(points):
    if len(points) < 3:
        raise ValueError("Fan boundary has fewer than three vertices")
    winding = 1.0 if signed_area(points) > 0 else -1.0
    if abs(signed_area(points)) <= 1e-18:
        raise ValueError("Fan boundary is numerically degenerate")
    remaining = list(range(len(points)))
    result = []
    guard = 0
    while len(remaining) > 3:
        found = False
        for pos in range(len(remaining)):
            previous = remaining[pos - 1]
            current = remaining[pos]
            following = remaining[(pos + 1) % len(remaining)]
            if cross2(points[previous], points[current], points[following]) * winding <= 1e-14:
                continue
            if any(point_in_triangle(points[index], points[previous], points[current], points[following], winding)
                   for index in remaining if index not in (previous, current, following)):
                continue
            result.append((previous, current, following))
            remaining.pop(pos)
            found = True
            break
        guard += 1
        if not found or guard > len(points) * len(points):
            raise ValueError("Fan boundary is not a simple polygon")
    result.append(tuple(remaining))
    return result


def run(source_root, output_root, centers, max_planarity_m=1e-6):
    source_root = Path(source_root).resolve()
    output_root = private(output_root)
    if output_root.exists():
        raise ValueError("Fresh coplanar fan output required")
    geometry_path = source_root / "geometry.json"
    if not geometry_path.is_file():
        raise ValueError("Source geometry record is missing")
    geometry = json.loads(geometry_path.read_text(encoding="utf-8-sig"))
    if geometry.get("unit") != "m" or geometry.get("coordinate_system") != "RF_X_FORWARD_Z_UP":
        raise ValueError("Coplanar fan input must use metres and RF coordinates")
    vertices = np.asarray(np.load(source_root / "arrays/vertices.npy", mmap_mode="r"), dtype=np.float64)
    triangles = np.asarray(np.load(source_root / "arrays/triangles.npy", mmap_mode="r"), dtype=np.int32)
    _validate_arrays(vertices, triangles)
    if len(set(centers)) != len(centers):
        raise ValueError("Center vertices must be unique")
    if any(center < 0 or center >= len(vertices) for center in centers):
        raise ValueError("Center vertex is out of range")

    started = time.monotonic()
    removals = []
    replacement_faces = []
    incident_union = []
    used_centers = set()
    for center in centers:
        incident, ring, face_normal = cycle_for_center(vertices, triangles, center)
        residual, plane_normal = plane_residual(vertices, ring)
        if residual > max_planarity_m:
            raise ValueError(f"Center {center} fan planarity exceeds limit: {residual} m")
        if np.dot(plane_normal, face_normal) < 0:
            plane_normal = -plane_normal
        points = project(vertices, ring, plane_normal)
        local_faces = triangulate(points)
        new_faces = np.asarray([[ring[a], ring[b], ring[c]] for a, b, c in local_faces], dtype=np.int32)
        reference_normal = np.sum(np.cross(vertices[new_faces[:, 1]] - vertices[new_faces[:, 0]],
                                           vertices[new_faces[:, 2]] - vertices[new_faces[:, 0]]), axis=0)
        if np.dot(reference_normal, face_normal) <= 0:
            new_faces = new_faces[:, [0, 2, 1]]
        if np.any(np.linalg.norm(np.cross(vertices[new_faces[:, 1]] - vertices[new_faces[:, 0]],
                                          vertices[new_faces[:, 2]] - vertices[new_faces[:, 0]]), axis=1) <= 1e-20):
            raise ValueError(f"Center {center} replacement contains a degenerate face")
        removals.extend(int(value) for value in incident)
        incident_union.extend(int(value) for value in incident)
        replacement_faces.append(new_faces)
        used_centers.add(center)
        removals.append(center)

    incident_union = np.unique(np.asarray(incident_union, dtype=np.int64))
    keep = np.ones(len(triangles), dtype=bool)
    keep[incident_union] = False
    out_triangles = np.concatenate([triangles[keep], *replacement_faces], axis=0).astype(np.int32, copy=False)
    referenced = np.unique(out_triangles.reshape(-1))
    remap = np.full(len(vertices), -1, dtype=np.int64)
    remap[referenced] = np.arange(len(referenced), dtype=np.int64)
    out_vertices = np.asarray(vertices[referenced], dtype=np.float64)
    out_triangles = remap[out_triangles].astype(np.int32, copy=False)
    _validate_arrays(out_vertices, out_triangles)
    out_topology = topology(out_triangles)
    if out_topology["boundary_edges"] or out_topology["nonmanifold_edges"]:
        raise ValueError("Coplanar fan retriangulation changed closed topology")

    output_root.mkdir(parents=True, exist_ok=False)
    arrays = output_root / "arrays"
    arrays.mkdir(parents=True, exist_ok=False)
    np.save(arrays / "vertices.npy", out_vertices)
    np.save(arrays / "triangles.npy", out_triangles)
    candidate = output_root / "candidate.obj"
    _write_obj(candidate, out_vertices, out_triangles)
    hashes = {
        "candidate.obj": sha(candidate),
        "arrays/vertices.npy": sha(arrays / "vertices.npy"),
        "arrays/triangles.npy": sha(arrays / "triangles.npy"),
    }
    input_hashes = {
        "geometry.json": sha(geometry_path),
        "candidate.obj": sha(source_root / "candidate.obj"),
        "arrays/vertices.npy": sha(source_root / "arrays/vertices.npy"),
        "arrays/triangles.npy": sha(source_root / "arrays/triangles.npy"),
        "repair_script": sha(Path(__file__)),
    }
    repair = {
        "schema_version": "phase1-cycle-coplanar-fan-1",
        "status": "PASS",
        "method": METHOD,
        "max_weld_m": 0.0,
        "input_geometry_sha256": input_hashes["geometry.json"],
        "center_vertices": centers,
        "removed_interior_vertices": sorted(used_centers),
        "removed_face_count": int(len(incident_union)),
        "replacement_face_count": int(sum(len(item) for item in replacement_faces)),
        "max_planarity_m": float(max_planarity_m),
        "input_hashes": input_hashes,
        "output_hashes": hashes,
        "input_counts": {"vertices": int(len(vertices)), "triangles": int(len(triangles))},
        "output_counts": {"vertices": int(len(out_vertices)), "triangles": int(len(out_triangles))},
        "output_topology": out_topology,
        "whole_input": True,
        "smoothing": False,
        "hole_filling": False,
        "part_deletion": False,
        "coordinate_shift_m": 0.0,
        "surface_check": "PENDING_FOUNDATION_SURFACECHECK",
        "external_shape_audit": "PENDING",
        "scientific_status": "UNVALIDATED_PHASE1_CYCLE",
        "elapsed_s": time.monotonic() - started,
    }
    repair["cache"] = finish_cache(arrays, source_sha256=input_hashes["candidate.obj"], method=METHOD)
    write(output_root / "repair.json", repair)
    write(output_root / "geometry.json", {
        "schema_version": "phase1-cycle-geometry-coplanar-fan-1",
        "repair_method": METHOD,
        "source_sha256": geometry.get("source_sha256"),
        "native_geometry_sha256": input_hashes["geometry.json"],
        "voxel_m": geometry.get("voxel_m"),
        "whole_input": True,
        "coordinate_system": geometry["coordinate_system"],
        "unit": geometry["unit"],
        "candidate_sha256": hashes["candidate.obj"],
        "candidate_obj_bytes": candidate.stat().st_size,
        "candidate_counts": repair["output_counts"],
        "candidate_arrays": hashes,
        "candidate_topology": dict(out_topology, closed=True, self_intersection_verified=False),
        "repair": repair,
        "self_intersection_verified": False,
        "scientific_status": "UNVALIDATED_PHASE1_CYCLE",
        "human_review": None,
    })
    print("COPLANAR_FAN_SAVED", json.dumps(repair["output_counts"], separators=(",", ":")), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--center-vertex", type=int, action="append", required=True)
    parser.add_argument("--max-planarity-m", type=float, default=1e-6)
    args = parser.parse_args()
    run(args.input, args.output, args.center_vertex, args.max_planarity_m)


if __name__ == "__main__":
    main()
