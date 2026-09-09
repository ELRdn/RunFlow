"""Apply a point-directed weld directly to the saved triangle arrays.

This is the array counterpart of the Blender local-weld diagnostic.  Direct
array editing is used here so Blender's BMesh conversion cannot introduce
additional face changes.  Only the selected vertex pairs and faces made
degenerate by those pairs may change; the output must remain closed before it
is sent to Foundation surfaceCheck.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np


REPO = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(REPO / "src"))

from runflow.cfd import private
from runflow.core import read, write


METHOD = "numpy_foundation_point_direct_weld_v1"


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
    raise FileNotFoundError(f"Missing array: {name}")


def write_obj(path, vertices, triangles):
    with Path(path).open("w", encoding="ascii", newline="\n") as stream:
        stream.write("g oguri\n")
        for x, y, z in vertices:
            stream.write(f"v {float(x):.17g} {float(y):.17g} {float(z):.17g}\n")
        for a, b, c in triangles:
            stream.write(f"f {int(a) + 1} {int(b) + 1} {int(c) + 1}\n")


def read_points_file(path):
    points = []
    for line in Path(path).read_text(encoding="ascii").splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0] != "v" or len(fields) != 4:
            raise ValueError("Point OBJ must contain only triangular point vertices")
        point = [float(value) for value in fields[1:]]
        if not np.isfinite(point).all():
            raise ValueError("Point OBJ contains nonfinite coordinates")
        points.append(point)
    if not points:
        raise ValueError("Point OBJ is empty")
    return points


def nearest_pair(vertices, point, search_radius, max_weld):
    delta = vertices - np.asarray(point, dtype=np.float64)
    distance2 = np.einsum("ij,ij->i", delta, delta)
    candidates = np.flatnonzero(distance2 <= float(search_radius) ** 2)
    if len(candidates) < 2:
        raise ValueError("Fewer than two vertices in local search radius")
    order = candidates[np.argsort(distance2[candidates], kind="mergesort")]
    first, second = int(order[0]), int(order[1])
    distance = float(np.linalg.norm(vertices[first] - vertices[second]))
    if distance > max_weld:
        raise ValueError(f"Nearest local pair exceeds weld limit: {distance}")
    return first, second, distance, float(np.sqrt(distance2[first])), float(np.sqrt(distance2[second]))


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--point", type=float, nargs=3, action="append")
    parser.add_argument("--points-file", type=Path)
    parser.add_argument("--search-radius", type=float, default=5e-6)
    parser.add_argument("--max-weld", type=float, default=1e-6)
    args = parser.parse_args()
    if not 0 < args.max_weld <= 1e-6 or not 0 < args.search_radius:
        raise ValueError("Invalid local weld limits")
    source = args.input.resolve()
    output = private(args.output)
    if output.exists():
        raise ValueError("Fresh local-array-weld output required")
    source_record = read(source / "geometry.json")
    if source_record.get("unit") != "m" or source_record.get("coordinate_system") != "RF_X_FORWARD_Z_UP":
        raise ValueError("Local-array-weld input must use metres and RF coordinates")
    vertices = np.load(array_path(source, "vertices.npy"), mmap_mode="r")
    triangles = np.asarray(np.load(array_path(source, "triangles.npy"), mmap_mode="r"), dtype=np.int64)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or triangles.ndim != 2 or triangles.shape[1] != 3:
        raise ValueError("Local-array-weld arrays must be Nx3")
    if not len(triangles) or not np.isfinite(vertices).all():
        raise ValueError("Local-array-weld arrays are empty or nonfinite")
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    if bool(args.point) == bool(args.points_file):
        raise ValueError("Choose exactly one of --point or --points-file")
    points_path = private(args.points_file) if args.points_file else None
    points = read_points_file(points_path) if points_path else [
        [float(value) for value in point] for point in args.point
    ]
    pairs = {}
    selections = []
    for point in points:
        first, second, distance, first_distance, second_distance = nearest_pair(
            vertices, point, args.search_radius, args.max_weld
        )
        pair = tuple(sorted((first, second)))
        pairs[pair] = pair
        selections.append(dict(
            point=point,
            vertices=[first, second],
            vertex_distance_m=distance,
            point_distances_m=[first_distance, second_distance],
        ))
    if not pairs:
        raise ValueError("No local vertex pairs selected")

    # The input is expected to have no degenerate faces.  This prevents the
    # local repair from silently hiding pre-existing defects.
    before_degenerate = np.any(
        (triangles[:, 0] == triangles[:, 1]) |
        (triangles[:, 1] == triangles[:, 2]) |
        (triangles[:, 2] == triangles[:, 0])
    )
    if before_degenerate:
        raise ValueError("Input already contains degenerate triangles")
    mapping = {}
    for first, second in pairs.values():
        mapping[second] = first
    welded = triangles.copy()
    for second, first in sorted(mapping.items()):
        welded[welded == second] = first
    degenerate = (
        (welded[:, 0] == welded[:, 1]) |
        (welded[:, 1] == welded[:, 2]) |
        (welded[:, 2] == welded[:, 0])
    )
    degenerate_count = int(degenerate.sum())
    if not degenerate_count:
        raise ValueError("Selected local weld did not create a face to remove")
    welded = welded[~degenerate]
    used = np.unique(welded.reshape(-1))
    remap = np.full(len(vertices), -1, dtype=np.int64)
    remap[used] = np.arange(len(used), dtype=np.int64)
    out_vertices = np.asarray(vertices[used], dtype=np.float64)
    out_triangles = remap[welded].astype(np.int32, copy=False)
    topo = topology(out_triangles)
    if topo["boundary_edges"] or topo["nonmanifold_edges"]:
        raise ValueError("Local array weld did not preserve a closed 2-manifold")
    arrays = output / "arrays"
    arrays.mkdir(exist_ok=False)
    np.save(arrays / "vertices.npy", out_vertices)
    np.save(arrays / "triangles.npy", out_triangles)
    candidate = output / "candidate.obj"
    write_obj(candidate, out_vertices, out_triangles)
    output_hashes = {
        "candidate.obj": sha(candidate),
        "arrays/vertices.npy": sha(arrays / "vertices.npy"),
        "arrays/triangles.npy": sha(arrays / "triangles.npy"),
    }
    repair = dict(
        schema_version="phase1-cycle-local-array-weld-1",
        status="PASS",
        method=METHOD,
        input_geometry_sha256=sha(source / "geometry.json"),
        input_array_hashes={
            "arrays/vertices.npy": sha(array_path(source, "vertices.npy")),
            "arrays/triangles.npy": sha(array_path(source, "triangles.npy")),
        },
        diagnostic_points=points,
        search_radius_m=float(args.search_radius),
        max_weld_m=float(args.max_weld),
        selected_pairs=selections,
        unique_pair_count=len(pairs),
        input_counts={"vertices": int(len(vertices)), "triangles": int(len(triangles))},
        output_counts={"vertices": int(len(out_vertices)), "triangles": int(len(out_triangles))},
        removed_faces=degenerate_count,
        removed_loose_vertices=int(len(vertices) - len(used)),
        topology=topo,
        smoothing=False,
        hole_filling=False,
        part_deletion=False,
        external_shape_audit="PENDING",
        surface_check="PENDING_FOUNDATION_SURFACECHECK",
        scientific_status="UNVALIDATED_PHASE1_CYCLE",
        output_hashes=output_hashes,
        elapsed_s=time.monotonic() - started,
    )
    write(output / "repair.json", repair)
    write(output / "geometry.json", dict(
        schema_version="phase1-cycle-geometry-local-array-weld-1",
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
        candidate_topology=dict(**topo, closed=True, self_intersection_verified=False),
        candidate_arrays=output_hashes,
        repair=repair,
        self_intersection_verified=False,
        scientific_status="UNVALIDATED_PHASE1_CYCLE",
        human_review=None,
    ))
    print("FOUNDATION_POINT_ARRAY_WELD_SAVED", json.dumps(repair["output_counts"]), flush=True)


if __name__ == "__main__":
    main()
