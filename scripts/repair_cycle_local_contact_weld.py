"""Diagnostic local contact weld for Foundation witness points.

This is deliberately separate from the 1um cleanup tool.  It tests whether a
small number of voxel-grid contact vertices can be identified without changing
the rest of the surface.  The output is never accepted by this script; the
Foundation surface check and the external shape audit remain mandatory.
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
from runflow.core import digest, file_hash, read, write
from repair_cycle_local_array_weld import (
    array_path,
    nearest_pair,
    read_points_file,
    topology,
    write_obj,
)


METHOD = "numpy_foundation_contact_weld_diagnostic_v1"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--points-file", type=Path, required=True)
    parser.add_argument("--search-radius", type=float, default=0.002)
    parser.add_argument("--max-weld", type=float, default=0.001)
    args = parser.parse_args()
    if not 0.0 < args.max_weld <= 0.002:
        raise ValueError("Diagnostic contact weld must be in (0, 2mm]")
    if not 0.0 < args.search_radius:
        raise ValueError("Search radius must be positive")

    source = args.input.resolve()
    output = private(args.output)
    points_path = private(args.points_file)
    if output.exists():
        raise ValueError("Fresh contact-weld output required")
    source_geometry = read(source / "geometry.json")
    if source_geometry.get("unit") != "m" or source_geometry.get("coordinate_system") != "RF_X_FORWARD_Z_UP":
        raise ValueError("Contact-weld input must use metres and RF coordinates")
    vertices = np.load(array_path(source, "vertices.npy"), mmap_mode="r")
    triangles = np.asarray(np.load(array_path(source, "triangles.npy"), mmap_mode="r"), dtype=np.int64)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or triangles.ndim != 2 or triangles.shape[1] != 3:
        raise ValueError("Contact-weld arrays must be Nx3")
    if not len(triangles) or not np.isfinite(vertices).all():
        raise ValueError("Contact-weld arrays are empty or nonfinite")
    if topology(triangles)["boundary_edges"] or topology(triangles)["nonmanifold_edges"]:
        raise ValueError("Contact-weld input must already be closed")

    points = read_points_file(points_path)
    pairs = {}
    selections = []
    for point in points:
        first, second, distance, first_distance, second_distance = nearest_pair(
            vertices, point, args.search_radius, args.max_weld
        )
        pair = tuple(sorted((first, second)))
        pairs[pair] = pair
        selections.append(
            dict(
                point=point,
                vertices=[first, second],
                vertex_distance_m=distance,
                point_distances_m=[first_distance, second_distance],
            )
        )
    if not pairs:
        raise ValueError("No contact pairs selected")

    started = time.monotonic()
    before_degenerate = np.any(
        (triangles[:, 0] == triangles[:, 1])
        | (triangles[:, 1] == triangles[:, 2])
        | (triangles[:, 2] == triangles[:, 0])
    )
    if before_degenerate:
        raise ValueError("Input already contains degenerate triangles")
    mapping = {second: first for first, second in pairs.values()}
    welded = triangles.copy()
    for second, first in sorted(mapping.items()):
        welded[welded == second] = first
    degenerate = (
        (welded[:, 0] == welded[:, 1])
        | (welded[:, 1] == welded[:, 2])
        | (welded[:, 2] == welded[:, 0])
    )
    degenerate_count = int(degenerate.sum())
    if not degenerate_count:
        raise ValueError("Contact weld did not create a face to remove")
    welded = welded[~degenerate]
    used = np.unique(welded.reshape(-1))
    remap = np.full(len(vertices), -1, dtype=np.int64)
    remap[used] = np.arange(len(used), dtype=np.int64)
    out_vertices = np.asarray(vertices[used], dtype=np.float64)
    out_triangles = remap[welded].astype(np.int32, copy=False)
    topo = topology(out_triangles)
    if topo["boundary_edges"] or topo["nonmanifold_edges"]:
        raise ValueError("Contact weld did not preserve a closed 2-manifold")

    output.mkdir(parents=True, exist_ok=False)
    arrays = output / "arrays"
    arrays.mkdir(exist_ok=False)
    np.save(arrays / "vertices.npy", out_vertices)
    np.save(arrays / "triangles.npy", out_triangles)
    obj = output / "candidate.obj"
    write_obj(obj, out_vertices, out_triangles)

    source_hashes = {
        "arrays/vertices.npy": file_hash(array_path(source, "vertices.npy")),
        "arrays/triangles.npy": file_hash(array_path(source, "triangles.npy")),
        "geometry.json": file_hash(source / "geometry.json"),
        "points_file": file_hash(points_path),
    }
    repair = dict(
        schema_version="phase1-cycle-local-contact-weld-1",
        method=METHOD,
        scientific_status="UNVALIDATED_PHASE1_CYCLE",
        status="PASS",
        input_geometry_sha256=source_geometry.get("native_geometry_sha256"),
        input_array_hashes=source_hashes,
        input_counts={"vertices": int(len(vertices)), "triangles": int(len(triangles))},
        output_counts={"vertices": int(len(out_vertices)), "triangles": int(len(out_triangles))},
        diagnostic_points=points,
        selected_pairs=selections,
        unique_pair_count=len(pairs),
        search_radius_m=args.search_radius,
        max_weld_m=args.max_weld,
        removed_faces=degenerate_count,
        removed_loose_vertices=int(len(vertices) - len(used)),
        displacement_upper_bound_m=max(
            (row["vertex_distance_m"] for row in selections), default=0.0
        ),
        topology=topo,
        smoothing=False,
        hole_filling=False,
        part_deletion=False,
        surface_check="PENDING_FOUNDATION_SURFACECHECK",
        external_shape_audit="PENDING",
        elapsed_s=time.monotonic() - started,
    )
    repair["repair_sha256"] = digest(repair)
    write(output / "repair.json", repair)
    geometry = dict(
        schema_version="phase1-cycle-geometry-local-contact-weld-1",
        scientific_status="UNVALIDATED_PHASE1_CYCLE",
        unit="m",
        coordinate_system="RF_X_FORWARD_Z_UP",
        whole_input=True,
        native_geometry_sha256=source_geometry.get("native_geometry_sha256"),
        source_sha256=source_geometry.get("source_sha256"),
        voxel_m=source_geometry.get("voxel_m"),
        repair_method=METHOD,
        candidate_counts=repair["output_counts"],
        candidate_sha256=file_hash(obj),
        candidate_obj_bytes=obj.stat().st_size,
        candidate_arrays={
            "arrays/vertices.npy": file_hash(arrays / "vertices.npy"),
            "arrays/triangles.npy": file_hash(arrays / "triangles.npy"),
            "candidate.obj": file_hash(obj),
        },
        candidate_topology=dict(topo, closed=not topo["boundary_edges"] and not topo["nonmanifold_edges"], self_intersection_verified=False),
        human_review=None,
    )
    write(output / "geometry.json", geometry)
    print(
        "FOUNDATION_CONTACT_WELD_SAVED",
        json.dumps(
            {"vertices": int(len(out_vertices)), "triangles": int(len(out_triangles)), "pairs": len(pairs), "max_weld_m": args.max_weld},
            separators=(",", ":"),
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
