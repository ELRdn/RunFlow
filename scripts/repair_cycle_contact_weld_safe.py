"""Apply only topology-preserving contact welds selected by Foundation points.

The input is a closed candidate and a Foundation ``selfInterPoints.obj``
diagnostic.  A point is actionable only when its nearest two vertices are
within the diagnostic search/weld limits and replacing one with the other
removes at least one degenerate face while keeping the complete surface
closed.  Coordinates are never edited; only collapsed faces and now-unused
vertices are removed.  The Foundation check remains the acceptance gate.
"""

import argparse
import gc
import math
from pathlib import Path
import sys
import time

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from runflow.cfd import private
from runflow.core import digest, file_hash, read, write


METHOD = "numpy_foundation_contact_weld_safe_v1"


def array_path(root, name):
    nested = Path(root) / "arrays" / name
    flat = Path(root) / name
    if nested.is_file():
        return nested
    if flat.is_file():
        return flat
    raise FileNotFoundError("Missing array: " + name)


def read_points(path):
    points = []
    for line in Path(path).read_text(encoding="ascii").splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0] != "v" or len(fields) != 4:
            raise ValueError("Foundation point file must contain only v x y z lines")
        point = np.asarray([float(value) for value in fields[1:]], dtype=np.float64)
        if not np.isfinite(point).all():
            raise ValueError("Foundation point file contains nonfinite coordinates")
        points.append(point)
    if not points:
        raise ValueError("Foundation point file is empty")
    return points


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


def nearest_pair(vertices, point, search_radius, max_weld):
    delta = vertices - np.asarray(point, dtype=np.float64)
    distance2 = np.einsum("ij,ij->i", delta, delta)
    candidates = np.flatnonzero(distance2 <= float(search_radius) ** 2)
    if len(candidates) < 2:
        raise ValueError("Fewer than two vertices in local search radius")
    order = candidates[np.argpartition(distance2[candidates], 1)[:2]]
    order = order[np.argsort(distance2[order], kind="mergesort")]
    first, second = int(order[0]), int(order[1])
    distance = float(np.linalg.norm(vertices[first] - vertices[second]))
    if distance > max_weld:
        raise ValueError("Nearest local pair exceeds weld limit: " + repr(distance))
    return first, second, distance, float(math.sqrt(distance2[first])), float(math.sqrt(distance2[second]))


def apply_pair(vertices, triangles, first, second):
    if first == second:
        return None, "same vertex"
    welded = np.array(triangles, dtype=np.int64, copy=True)
    welded[welded == int(second)] = int(first)
    degenerate = (
        (welded[:, 0] == welded[:, 1])
        | (welded[:, 1] == welded[:, 2])
        | (welded[:, 2] == welded[:, 0])
    )
    removed = int(degenerate.sum())
    if not removed:
        return None, "pair creates no degenerate face"
    welded = welded[~degenerate]
    used = np.unique(welded.reshape(-1))
    remap = np.full(len(vertices), -1, dtype=np.int64)
    remap[used] = np.arange(len(used), dtype=np.int64)
    out_vertices = np.asarray(vertices[used], dtype=np.float64)
    out_triangles = remap[welded].astype(np.int32, copy=False)
    topo = topology(out_triangles)
    if topo["boundary_edges"] or topo["nonmanifold_edges"]:
        return None, "pair breaks closed 2-manifold: " + repr(topo)
    return (out_vertices, out_triangles, removed, int(len(vertices) - len(used)), topo), None


def write_obj(path, vertices, triangles):
    with Path(path).open("w", encoding="ascii", newline="\n") as stream:
        stream.write("g oguri\n")
        for x, y, z in vertices:
            stream.write(f"v {float(x):.17g} {float(y):.17g} {float(z):.17g}\n")
        for a, b, c in triangles:
            stream.write(f"f {int(a) + 1} {int(b) + 1} {int(c) + 1}\n")


def repair(source_root, points_path, output, search_radius, max_weld):
    source_root = Path(source_root).resolve()
    output = private(output)
    points_path = private(points_path)
    if output.exists():
        raise ValueError("Fresh safe contact-weld output required")
    if not 0.0 < search_radius or not np.isfinite(search_radius):
        raise ValueError("Search radius must be positive and finite")
    if not 0.0 < max_weld <= 0.002 or not np.isfinite(max_weld):
        raise ValueError("Safe contact weld must be in (0, 2mm]")
    source_geometry_path = source_root / "geometry.json"
    source_geometry = read(source_geometry_path)
    if source_geometry.get("unit") != "m" or source_geometry.get("coordinate_system") != "RF_X_FORWARD_Z_UP":
        raise ValueError("Safe contact input must use metres and RF coordinates")
    vertices = np.asarray(np.load(array_path(source_root, "vertices.npy"), mmap_mode="r"), dtype=np.float64)
    triangles = np.asarray(np.load(array_path(source_root, "triangles.npy"), mmap_mode="r"), dtype=np.int64)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or triangles.ndim != 2 or triangles.shape[1] != 3:
        raise ValueError("Safe contact arrays must be Nx3")
    if not len(triangles) or not np.isfinite(vertices).all():
        raise ValueError("Safe contact arrays are empty or nonfinite")
    initial_topology = topology(triangles)
    if initial_topology["boundary_edges"] or initial_topology["nonmanifold_edges"]:
        raise ValueError("Safe contact input must already be closed")

    points = read_points(points_path)
    source_hashes = {
        "geometry.json": file_hash(source_geometry_path),
        "arrays/vertices.npy": file_hash(array_path(source_root, "vertices.npy")),
        "arrays/triangles.npy": file_hash(array_path(source_root, "triangles.npy")),
        "candidate.obj": file_hash(source_root / "candidate.obj"),
        "foundation_points.obj": file_hash(points_path),
        "repair_script": file_hash(Path(__file__)),
    }
    started = time.monotonic()
    selected = []
    skipped = []
    current_vertices = np.array(vertices, dtype=np.float64, order="C", copy=True)
    current_triangles = np.array(triangles, dtype=np.int64, order="C", copy=True)
    seen_pairs = set()

    for index, point in enumerate(points):
        try:
            first, second, distance, first_distance, second_distance = nearest_pair(
                current_vertices, point, search_radius, max_weld
            )
        except ValueError as exc:
            skipped.append(dict(index=index, point=point.tolist(), reason=str(exc)))
            continue
        pair_key = tuple(sorted((first, second)))
        if pair_key in seen_pairs:
            skipped.append(dict(index=index, point=point.tolist(), vertices=[first, second],
                                vertex_distance_m=distance, reason="pair already tested"))
            continue
        seen_pairs.add(pair_key)
        result = None
        errors = []
        orientation = None
        for left, right in ((first, second), (second, first)):
            result, error = apply_pair(current_vertices, current_triangles, left, right)
            if result is not None:
                orientation = (left, right)
                break
            errors.append(error)
        if result is None:
            skipped.append(dict(index=index, point=point.tolist(), vertices=[first, second],
                                vertex_distance_m=distance, reason="; ".join(errors)))
            continue
        current_vertices, current_triangles, removed, loose, topo = result
        selected.append(dict(index=index, point=point.tolist(), vertices=[int(orientation[0]), int(orientation[1])],
                             vertex_distance_m=distance, point_distances_m=[first_distance, second_distance],
                             removed_faces=removed, removed_loose_vertices=loose, topology=topo))
        gc.collect()

    if not selected:
        raise ValueError("No contact pair both removed a face and preserved a closed 2-manifold")

    output.mkdir(parents=True, exist_ok=False)
    arrays = output / "arrays"
    arrays.mkdir(parents=True, exist_ok=False)
    np.save(arrays / "vertices.npy", current_vertices)
    np.save(arrays / "triangles.npy", current_triangles.astype(np.int32, copy=False))
    candidate = output / "candidate.obj"
    write_obj(candidate, current_vertices, current_triangles)
    output_hashes = {
        "candidate.obj": file_hash(candidate),
        "arrays/vertices.npy": file_hash(arrays / "vertices.npy"),
        "arrays/triangles.npy": file_hash(arrays / "triangles.npy"),
    }
    final_topology = topology(current_triangles)
    repair_record = dict(
        schema_version="phase1-cycle-contact-weld-safe-1",
        status="PASS",
        method=METHOD,
        scientific_status="UNVALIDATED_PHASE1_CYCLE",
        input_geometry_sha256=source_hashes["geometry.json"],
        native_geometry_sha256=source_geometry.get("native_geometry_sha256", source_hashes["geometry.json"]),
        source_sha256=source_geometry.get("source_sha256"),
        input_hashes=source_hashes,
        output_hashes=output_hashes,
        input_counts={"vertices": int(len(vertices)), "triangles": int(len(triangles))},
        output_counts={"vertices": int(len(current_vertices)), "triangles": int(len(current_triangles))},
        diagnostic_points=[point.tolist() for point in points],
        selected_pairs=selected,
        skipped_points=skipped,
        search_radius_m=float(search_radius),
        max_weld_m=float(max_weld),
        selected_pair_count=len(selected),
        removed_faces=int(sum(row["removed_faces"] for row in selected)),
        removed_loose_vertices=int(sum(row["removed_loose_vertices"] for row in selected)),
        max_vertex_shift_m=max((row["vertex_distance_m"] for row in selected), default=0.0),
        topology=final_topology,
        smoothing=False,
        hole_filling=False,
        part_deletion=False,
        surface_check="PENDING_FOUNDATION_SURFACECHECK",
        external_shape_audit="PENDING",
        elapsed_s=time.monotonic() - started,
    )
    repair_record["repair_sha256"] = digest(repair_record)
    write(output / "repair.json", repair_record)
    write(output / "geometry.json", dict(
        schema_version="phase1-cycle-geometry-contact-weld-safe-1",
        scientific_status="UNVALIDATED_PHASE1_CYCLE",
        unit=source_geometry.get("unit"),
        coordinate_system=source_geometry.get("coordinate_system"),
        whole_input=True,
        source_sha256=source_geometry.get("source_sha256"),
        native_geometry_sha256=source_geometry.get("native_geometry_sha256", source_hashes["geometry.json"]),
        voxel_m=source_geometry.get("voxel_m"),
        repair_method=METHOD,
        candidate_counts=repair_record["output_counts"],
        candidate_sha256=output_hashes["candidate.obj"],
        candidate_obj_bytes=candidate.stat().st_size,
        candidate_arrays=output_hashes,
        candidate_topology=dict(final_topology, closed=True, self_intersection_verified=False),
        repair=repair_record,
        human_review=None,
    ))
    print("SAFE_CONTACT_WELD_SAVED", dict(
        vertices=int(len(current_vertices)), triangles=int(len(current_triangles)),
        selected=len(selected), skipped=len(skipped), max_weld_m=max_weld,
    ), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--points-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--search-radius", type=float, default=0.002)
    parser.add_argument("--max-weld", type=float, default=0.002)
    args = parser.parse_args()
    repair(args.input, args.points_file, args.output, args.search_radius, args.max_weld)


if __name__ == "__main__":
    main()
