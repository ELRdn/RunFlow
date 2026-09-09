"""Classify Foundation self-intersection points by nearby input vertices."""

import argparse
from pathlib import Path
import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vertices", type=Path, required=True)
    parser.add_argument("--points", type=Path, required=True)
    parser.add_argument("--search-radius", type=float, default=5e-6)
    parser.add_argument("--max-weld", type=float, default=1e-6)
    args = parser.parse_args()
    vertices = np.load(args.vertices, mmap_mode="r")
    points = []
    for line in args.points.read_text(encoding="ascii").splitlines():
        fields = line.split()
        if fields and fields[0] == "v":
            points.append(np.asarray([float(value) for value in fields[1:]], dtype=np.float64))
    rows = []
    for index, point in enumerate(points):
        delta = vertices - point
        distance2 = np.einsum("ij,ij->i", delta, delta)
        nearest = np.argpartition(distance2, 1)[:2]
        nearest = nearest[np.argsort(distance2[nearest], kind="mergesort")]
        first, second = (int(nearest[0]), int(nearest[1]))
        first_distance = float(np.sqrt(distance2[first]))
        second_distance = float(np.sqrt(distance2[second]))
        pair_distance = float(np.linalg.norm(vertices[first] - vertices[second]))
        rows.append(dict(index=index, point=point.tolist(), vertices=[first, second],
                         point_distances_m=[first_distance, second_distance],
                         pair_distance_m=pair_distance,
                         weldable=second_distance <= args.search_radius and pair_distance <= args.max_weld))
    weldable = [row for row in rows if row["weldable"]]
    print("POINT_CLASSIFICATION", dict(total=len(rows), weldable=len(weldable),
                                        non_weldable=len(rows) - len(weldable)))
    for row in rows:
        if row["weldable"]:
            print(row)


if __name__ == "__main__":
    main()
