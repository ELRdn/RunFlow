"""Locate local triangle and edge contacts for Foundation self-intersection points.

Foundation surfaceCheck writes rounded witness points, so this diagnostic uses
small metric tolerances and reports the exact indexed triangles/edges nearby.
It never edits the source arrays or chooses a repair automatically.
"""

import argparse
import json
from pathlib import Path

import numpy as np


def array_path(root, name):
    nested = Path(root) / "arrays" / name
    flat = Path(root) / name
    if nested.is_file():
        return nested
    if flat.is_file():
        return flat
    raise FileNotFoundError(f"Missing array: {name}")


def read_points(path):
    points = []
    for line in Path(path).read_text(encoding="ascii").splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0] != "v" or len(fields) != 4:
            raise ValueError("Point OBJ must contain only vertices")
        point = np.asarray([float(value) for value in fields[1:]], dtype=np.float64)
        if not np.isfinite(point).all():
            raise ValueError("Point OBJ contains nonfinite coordinates")
        points.append(point)
    if not points:
        raise ValueError("Point OBJ is empty")
    return points


def barycentric(point, triangle):
    a, b, c = triangle
    ab = b - a
    ac = c - a
    normal = np.cross(ab, ac)
    normal_length = float(np.linalg.norm(normal))
    if normal_length == 0.0:
        return None
    plane_distance = abs(float(np.dot(point - a, normal))) / normal_length
    d00 = float(np.dot(ab, ab))
    d01 = float(np.dot(ab, ac))
    d11 = float(np.dot(ac, ac))
    ap = point - a
    d20 = float(np.dot(ap, ab))
    d21 = float(np.dot(ap, ac))
    denominator = d00 * d11 - d01 * d01
    if denominator <= 0.0:
        return None
    v = (d11 * d20 - d01 * d21) / denominator
    w = (d00 * d21 - d01 * d20) / denominator
    return [1.0 - v - w, v, w], plane_distance


def segment_distance(point, first, second):
    direction = second - first
    denominator = float(np.dot(direction, direction))
    if denominator == 0.0:
        return float(np.linalg.norm(point - first))
    t = float(np.dot(point - first, direction) / denominator)
    t = min(1.0, max(0.0, t))
    return float(np.linalg.norm(point - (first + t * direction)))


def locate(vertices, triangles, point, bbox_pad, plane_tol, edge_tol, chunk_size, max_hits):
    hits = []
    point_min = point - bbox_pad
    point_max = point + bbox_pad
    for start in range(0, len(triangles), chunk_size):
        stop = min(len(triangles), start + chunk_size)
        indexed = np.asarray(triangles[start:stop], dtype=np.int64)
        coords = np.asarray(vertices[indexed], dtype=np.float64)
        lower = coords.min(axis=1)
        upper = coords.max(axis=1)
        mask = np.all(lower <= point_max, axis=1) & np.all(upper >= point_min, axis=1)
        for local in np.flatnonzero(mask):
            triangle = coords[local]
            result = barycentric(point, triangle)
            if result is None:
                continue
            weights, plane_distance = result
            if plane_distance > plane_tol:
                continue
            edges = []
            for edge_index, (first, second) in enumerate(((0, 1), (1, 2), (2, 0))):
                distance = segment_distance(point, triangle[first], triangle[second])
                if distance <= edge_tol:
                    edges.append({"edge": edge_index, "distance_m": distance})
            if min(weights) < -1e-5 and not edges:
                continue
            hits.append(
                {
                    "triangle": int(start + local),
                    "vertices": [int(value) for value in indexed[local]],
                    "barycentric": [float(value) for value in weights],
                    "plane_distance_m": plane_distance,
                    "near_edges": edges,
                    "inside_or_boundary": min(weights) >= -1e-5,
                }
            )
            if len(hits) >= max_hits:
                return hits
    return hits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--points", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bbox-pad", type=float, default=2e-6)
    parser.add_argument("--plane-tol", type=float, default=2e-6)
    parser.add_argument("--edge-tol", type=float, default=2e-6)
    parser.add_argument("--chunk-size", type=int, default=250_000)
    parser.add_argument("--max-hits", type=int, default=200)
    args = parser.parse_args()
    for value in (args.bbox_pad, args.plane_tol, args.edge_tol):
        if value <= 0.0:
            raise ValueError("Diagnostic tolerances must be positive")
    if args.chunk_size <= 0 or args.max_hits <= 0:
        raise ValueError("Chunk size and hit limit must be positive")
    vertices = np.load(array_path(args.input, "vertices.npy"), mmap_mode="r")
    triangles = np.load(array_path(args.input, "triangles.npy"), mmap_mode="r")
    if vertices.ndim != 2 or vertices.shape[1] != 3:
        raise ValueError("Vertices must be Nx3")
    if triangles.ndim != 2 or triangles.shape[1] != 3:
        raise ValueError("Triangles must be Nx3")
    points = read_points(args.points)
    records = []
    for index, point in enumerate(points):
        hits = locate(
            vertices,
            triangles,
            point,
            args.bbox_pad,
            args.plane_tol,
            args.edge_tol,
            args.chunk_size,
            args.max_hits,
        )
        records.append({"index": index, "point": point.tolist(), "hits": hits})
        print(
            "FOUNDATION_CONTACT",
            json.dumps(
                {"index": index, "point": point.tolist(), "hit_count": len(hits)},
                separators=(",", ":"),
            ),
            flush=True,
        )
    value = {
        "schema_version": "runflow-foundation-contact-location-1",
        "input": str(args.input),
        "points": str(args.points),
        "tolerances_m": {
            "bbox_pad": args.bbox_pad,
            "plane": args.plane_tol,
            "edge": args.edge_tol,
        },
        "records": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    print("FOUNDATION_CONTACTS_SAVED", args.output, flush=True)


if __name__ == "__main__":
    main()
