"""Quantize a saved cycle surface within the existing 1 micrometre allowance.

This is a diagnostic repair for floating point noise in near-coplanar voxel
patches.  It changes coordinates only by the requested rounding grid, removes
faces collapsed by that rounding, and keeps Foundation surfaceCheck as the
acceptance gate.  It does not smooth, fill, thicken, or delete semantic parts.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

REPO = Path(__file__).resolve().parents[1]


METHOD = "numpy_coordinate_quantize_1um_v1"


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


def write_obj(path, vertices, triangles):
    with Path(path).open("w", encoding="ascii", newline="\n") as stream:
        stream.write("g oguri\n")
        for x, y, z in vertices:
            stream.write(f"v {float(x):.17g} {float(y):.17g} {float(z):.17g}\n")
        for a, b, c in triangles:
            stream.write(f"f {int(a) + 1} {int(b) + 1} {int(c) + 1}\n")


def run(source_root, output_root, grid_m):
    source_root = Path(source_root).resolve()
    output_root = Path(output_root).resolve()
    if output_root.exists():
        raise ValueError("Fresh coordinate-quantize output required")
    if not np.isfinite(grid_m) or not 0.0 < grid_m <= 1e-6:
        raise ValueError("Quantization grid must be in (0, 1um]")
    source_geometry_path = source_root / "geometry.json"
    source_geometry = json.loads(source_geometry_path.read_text(encoding="utf-8-sig"))
    if source_geometry.get("unit") != "m" or source_geometry.get("coordinate_system") != "RF_X_FORWARD_Z_UP":
        raise ValueError("Coordinate-quantize input must use metres and RF coordinates")
    vertices = np.asarray(np.load(array_path(source_root, "vertices.npy"), mmap_mode="r"), dtype=np.float64)
    triangles = np.asarray(np.load(array_path(source_root, "triangles.npy"), mmap_mode="r"), dtype=np.int64)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or triangles.ndim != 2 or triangles.shape[1] != 3:
        raise ValueError("Coordinate-quantize arrays must be Nx3")
    if not len(triangles) or not np.isfinite(vertices).all():
        raise ValueError("Coordinate-quantize arrays are empty or nonfinite")
    if int(triangles.min()) < 0 or int(triangles.max()) >= len(vertices):
        raise ValueError("Coordinate-quantize triangle index is out of range")

    started = time.monotonic()
    initial_topology = topology(triangles)
    quantized = np.rint(vertices / float(grid_m)) * float(grid_m)
    shifts = np.linalg.norm(quantized - vertices, axis=1)
    maximum_shift = float(shifts.max(initial=0.0))
    if maximum_shift > 1e-6 + 1e-12:
        raise ValueError("Coordinate quantization exceeded 1um allowance")

    unique_vertices, inverse = np.unique(quantized, axis=0, return_inverse=True)
    mapped = inverse[triangles]
    degenerate = (
        (mapped[:, 0] == mapped[:, 1])
        | (mapped[:, 1] == mapped[:, 2])
        | (mapped[:, 2] == mapped[:, 0])
    )
    kept = mapped[~degenerate]
    used = np.unique(kept.reshape(-1))
    remap = np.full(len(unique_vertices), -1, dtype=np.int64)
    remap[used] = np.arange(len(used), dtype=np.int64)
    out_vertices = np.asarray(unique_vertices[used], dtype=np.float64)
    out_triangles = remap[kept].astype(np.int32, copy=False)
    final_topology = topology(out_triangles)

    output_root.mkdir(parents=True, exist_ok=False)
    arrays = output_root / "arrays"
    arrays.mkdir(parents=True, exist_ok=False)
    np.save(arrays / "vertices.npy", out_vertices)
    np.save(arrays / "triangles.npy", out_triangles)
    candidate = output_root / "candidate.obj"
    write_obj(candidate, out_vertices, out_triangles)
    hashes = {
        "candidate.obj": sha(candidate),
        "arrays/vertices.npy": sha(arrays / "vertices.npy"),
        "arrays/triangles.npy": sha(arrays / "triangles.npy"),
    }
    repair = {
        "schema_version": "phase1-cycle-coordinate-quantize-1",
        "status": "PASS",
        "method": METHOD,
        "grid_m": float(grid_m),
        "input_hashes": {
            "geometry.json": sha(source_geometry_path),
            "candidate.obj": sha(source_root / "candidate.obj"),
            "arrays/vertices.npy": sha(array_path(source_root, "vertices.npy")),
            "arrays/triangles.npy": sha(array_path(source_root, "triangles.npy")),
            "repair_script": sha(Path(__file__)),
        },
        "output_hashes": hashes,
        "input_counts": {"vertices": int(len(vertices)), "triangles": int(len(triangles))},
        "output_counts": {"vertices": int(len(out_vertices)), "triangles": int(len(out_triangles))},
        "initial_topology": initial_topology,
        "final_topology": final_topology,
        "unique_coordinate_count": int(len(unique_vertices)),
        "merged_vertices": int(len(vertices) - len(unique_vertices)),
        "removed_collapsed_faces": int(degenerate.sum()),
        "removed_loose_vertices": int(len(unique_vertices) - len(used)),
        "maximum_vertex_shift_m": maximum_shift,
        "whole_input": True,
        "smoothing": False,
        "hole_filling": False,
        "part_deletion": False,
        "surface_check": "PENDING_FOUNDATION_SURFACECHECK",
        "external_shape_audit": "PENDING",
        "scientific_status": "UNVALIDATED_PHASE1_CYCLE",
        "elapsed_s": time.monotonic() - started,
    }
    (output_root / "repair.json").write_text(json.dumps(repair, sort_keys=True, indent=2), encoding="utf-8")
    geometry = {
        "schema_version": "phase1-cycle-geometry-coordinate-quantize-1",
        "repair_method": METHOD,
        "source_sha256": source_geometry.get("source_sha256"),
        "native_geometry_sha256": sha(source_geometry_path),
        "voxel_m": source_geometry.get("voxel_m"),
        "whole_input": True,
        "coordinate_system": source_geometry["coordinate_system"],
        "unit": source_geometry["unit"],
        "candidate_sha256": hashes["candidate.obj"],
        "candidate_obj_bytes": candidate.stat().st_size,
        "candidate_counts": repair["output_counts"],
        "candidate_arrays": hashes,
        "candidate_topology": dict(
            final_topology,
            closed=not final_topology["boundary_edges"] and not final_topology["nonmanifold_edges"],
            self_intersection_verified=False,
        ),
        "repair": repair,
        "self_intersection_verified": False,
        "scientific_status": "UNVALIDATED_PHASE1_CYCLE",
        "human_review": None,
    }
    (output_root / "geometry.json").write_text(json.dumps(geometry, sort_keys=True, indent=2), encoding="utf-8")
    print("COORDINATE_QUANTIZE_SAVED", json.dumps(repair["output_counts"], separators=(",", ":")), flush=True)
    return repair


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--grid-m", type=float, default=1e-6)
    args = parser.parse_args()
    run(args.input, args.output, args.grid_m)


if __name__ == "__main__":
    main()
