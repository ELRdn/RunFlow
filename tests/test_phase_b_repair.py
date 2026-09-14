"""Phase B tests: automatic repair centre selection, resume, and pilot lanes."""
import json
from pathlib import Path
import sys

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from run_phase1_repair_auto import (_nearest_vertices, _select_centers, _unique_root,
                                    topology)
from collect_phase1_pilot import collect


def _fan_surface(centres):
    """Build a flat hexagon fan around each centre on the z = 0 plane.

    Each centre gets six ring vertices and six triangles, so a centre is a
    legitimate coplanar fan and two centres never share a face unless they are
    deliberately placed next to each other.
    """
    vertices = []
    triangles = []
    for index, (cx, cy) in enumerate(centres):
        centre = len(vertices)
        vertices.append([cx, cy, 0.0])
        ring = []
        for step in range(6):
            angle = step * (np.pi / 3.0)
            ring.append(len(vertices))
            vertices.append([cx + 0.5 * np.cos(angle), cy + 0.5 * np.sin(angle), 0.0])
        for step in range(6):
            triangles.append([centre, ring[step], ring[(step + 1) % 6]])
    return (np.asarray(vertices, dtype=np.float64),
            np.asarray(triangles, dtype=np.int64))


def test_select_centers_accepts_a_planar_fan():
    vertices, triangles = _fan_surface([(0.0, 0.0)])
    nearest = [(0, 0, 0.0)]
    accepted, rejected = _select_centers(vertices, triangles, nearest, 1e-4, 8)
    assert [row["vertex"] for row in accepted] == [0]
    assert rejected == []
    assert accepted[0]["ring_size"] == 6


def test_select_centers_never_returns_two_fans_that_share_a_face():
    # Two fans may share a ring vertex without sharing a face.  Removing both is
    # still topology safe, so the selection keeps both; what it must never do is
    # hand the repair two fans that both claim the same incident face.
    vertices, triangles = _fan_surface([(0.0, 0.0)])
    centre = len(vertices)
    vertices = np.vstack([vertices, [[0.5, 0.0, 0.0]]])
    ring = [1, 2, 3, 4, 5, 6]
    for step in range(6):
        triangles = np.vstack([triangles, [[centre, ring[step], ring[(step + 1) % 6]]]])
    nearest = [(0, centre, 0.0), (1, 0, 0.0)]
    accepted, _ = _select_centers(vertices, triangles, nearest, 1e-4, 8)
    assert len(accepted) >= 1
    used = set()
    for row in accepted:
        faces = {int(value) for value in np.flatnonzero(
            np.any(triangles == row["vertex"], axis=1))}
        assert not (faces & used), "selected fans must not claim the same face"
        used |= faces


def test_select_centers_keeps_disjoint_fans():
    vertices, triangles = _fan_surface([(0.0, 0.0), (5.0, 0.0)])
    nearest = [(0, 0, 0.0), (1, 7, 0.0)]
    accepted, _ = _select_centers(vertices, triangles, nearest, 1e-4, 8)
    assert sorted(row["vertex"] for row in accepted) == [0, 7]


def test_select_centers_rejects_a_non_planar_ring():
    vertices, triangles = _fan_surface([(0.0, 0.0)])
    vertices = np.asarray(vertices, dtype=np.float64).copy()
    vertices[1, 2] = 0.01  # lift one ring vertex well past the diagnostic limit
    accepted, rejected = _select_centers(vertices, triangles, [(0, 0, 0.0)], 1e-4, 8)
    assert accepted == []
    assert rejected and "planarity" in rejected[0]["reason"]


def test_nearest_vertices_respects_the_search_radius():
    vertices = np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=np.float64)
    points = [np.asarray([0.0001, 0.0, 0.0]), np.asarray([0.5, 0.0, 0.0])]
    assert _nearest_vertices(vertices, points, 1e-3) == [(0, 0, pytest.approx(0.0001))]
    assert len(_nearest_vertices(vertices, points, 1.0)) == 2


def test_unique_root_never_returns_an_existing_path(tmp_path):
    target = tmp_path / "foundation-001"
    assert _unique_root(target) == target
    target.mkdir()
    assert _unique_root(target) != target
    assert not _unique_root(target).exists()


def test_topology_counts_boundary_edges():
    closed = np.asarray([[0, 1, 2], [0, 2, 3], [0, 3, 1], [1, 3, 2]], dtype=np.int64)
    open_mesh = np.asarray([[0, 1, 2]], dtype=np.int64)
    assert topology(closed)["boundary_edges"] == 0
    assert topology(open_mesh)["boundary_edges"] == 3


def _lane(tmp_path, name, frames, family="family-a"):
    worker = tmp_path / name / "worker-00"
    worker.mkdir(parents=True)
    attempts = []
    for frame in frames:
        label = "frame-%02d-001" % frame
        root = worker / label
        root.mkdir()
        (root / "result.json").write_text(json.dumps(dict(
            phase_index=frame, execution_status="PASS", drag_N=80.0 + frame,
            Cd=0.7, CdA_m2=0.35, source_area_m2=0.45,
            comparison_family_sha256=family)), encoding="utf-8")
        attempts.append(dict(phase_index=frame, label=label, status="PASS",
                             drag_N=80.0 + frame, execution_elapsed_s=700.0))
    (worker / "campaign.json").write_text(json.dumps(
        dict(completion_status="COMPLETE_REQUESTED_FRAMES", attempts=attempts)), encoding="utf-8")
    return tmp_path / name


def test_collect_reads_lanes_and_builds_incomplete_schedules(tmp_path):
    lanes = [_lane(tmp_path, "lane-00", [0, 4]), _lane(tmp_path, "lane-01", [8, 12])]
    records, rows = collect(lanes)
    assert [row["phase_index"] for row in rows] == [0, 4, 8, 12]
    assert all(row["execution_status"] == "PASS" for row in rows)
    assert [record["status"] for record in records] == ["READ", "READ"]


def test_collect_reports_a_missing_ledger(tmp_path):
    (tmp_path / "lane-00").mkdir()
    records, rows = collect([tmp_path / "lane-00"])
    assert rows == []
    assert records[0]["status"] == "MISSING_LEDGER"
