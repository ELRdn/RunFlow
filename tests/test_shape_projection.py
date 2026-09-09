"""Tests for runflow.shape_projection (synthetic geometry only)."""
import math

import numpy as np
import pytest
import shapely

from runflow.shape_projection import compare_projections, project_mesh


def _quad_yz(y0, z0, y1, z1, x=0.0):
    verts = np.array([
        [x, y0, z0], [x, y1, z0], [x, y1, z1], [x, y0, z1],
    ], dtype=np.float64)
    tris = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
    return verts, tris


def _ring_with_hole_yz(outer, inner, x=0.0):
    (oy0, oz0, oy1, oz1) = outer
    (iy0, iz0, iy1, iz1) = inner
    verts = np.array([
        [x, oy0, oz0], [x, oy1, oz0], [x, oy1, oz1], [x, oy0, oz1],
        [x, iy0, iz0], [x, iy1, iz0], [x, iy1, iz1], [x, iy0, iz1],
    ], dtype=np.float64)
    # Ring triangulation: bottom/right/top/left strips, 2 tris each.
    tris = np.array([
        [0, 1, 5], [0, 5, 4],
        [1, 2, 6], [1, 6, 5],
        [2, 3, 7], [2, 7, 6],
        [3, 0, 4], [3, 4, 7],
    ], dtype=np.int64)
    return verts, tris


def test_disjoint_triangles_union_exact():
    verts = np.array([
        [0, 0, 0], [0, 1, 0], [0, 0, 1],
        [0, 10, 0], [0, 11, 0], [0, 10, 1],
    ], dtype=np.float64)
    tris = np.array([[0, 1, 2], [3, 4, 5]], dtype=np.int64)
    geom = project_mesh(verts, tris)
    assert geom.area == pytest.approx(1.0)


def test_overlapping_triangles_union_exact():
    # Identical squares built twice: union stays 1.0 (no double count).
    v1, t1 = _quad_yz(0, 0, 1, 1)
    verts = np.vstack([v1, v1])
    tris = np.vstack([t1, t1 + 4])
    assert project_mesh(verts, tris).area == pytest.approx(1.0)
    # Partial overlap: [0,1]^2 and [0.5,1.5]^2 -> 1 + 1 - 0.25 = 1.75.
    v2, t2 = _quad_yz(0.5, 0.5, 1.5, 1.5)
    verts = np.vstack([v1, v2])
    tris = np.vstack([t1, t2 + 4])
    assert project_mesh(verts, tris).area == pytest.approx(1.75)


def test_two_axes_differ():
    # Right triangle with legs on X and Y, flat at Z=0.
    verts = np.array([[0, 0, 0], [2, 0, 0], [0, 4, 0]], dtype=np.float64)
    tris = np.array([[0, 1, 2]], dtype=np.int64)
    assert project_mesh(verts, tris, axes=(0, 1)).area == pytest.approx(4.0)
    empty = project_mesh(verts, tris, axes=(1, 2))
    assert empty.area == pytest.approx(0.0)
    assert empty.is_empty


def test_square_hole_and_closure_compare():
    hv, ht = _ring_with_hole_yz((0, 0, 2, 2), (0.5, 0.5, 1.5, 1.5))
    holey = project_mesh(hv, ht)
    assert holey.area == pytest.approx(3.0)
    fv, ft = _quad_yz(0, 0, 2, 2)
    filled = project_mesh(fv, ft)
    assert filled.area == pytest.approx(4.0)
    rep = compare_projections(holey, filled)
    assert rep["source_m2"] == pytest.approx(3.0)
    assert rep["candidate_m2"] == pytest.approx(4.0)
    assert rep["relative_change"] == pytest.approx(1.0 / 3.0)
    assert rep["relative_change_abs"] == pytest.approx(1.0 / 3.0)
    assert rep["lost_m2"] == pytest.approx(0.0, abs=1e-12)
    assert rep["added_m2"] == pytest.approx(1.0)
    assert rep["symmetric_difference_m2"] == pytest.approx(1.0)
    assert rep["iou"] == pytest.approx(0.75)
    assert rep["source_holes"] == 1
    assert rep["source_hole_area_m2"] == pytest.approx(1.0)
    assert rep["candidate_holes"] == 0
    assert rep["candidate_hole_area_m2"] == pytest.approx(0.0, abs=1e-12)
    assert rep["filled_original_hole_m2"] == pytest.approx(1.0)
    assert "line-of-sight" in rep["holes_note"]


def test_ring_with_island_background_hole():
    # 2x2 ring (area 3) around a 1m2 hole, plus a solid 0.5x0.5 island
    # strictly inside the hole: background left uncovered is 1 - 0.25.
    rv, rt = _ring_with_hole_yz((0, 0, 2, 2), (0.5, 0.5, 1.5, 1.5))
    iv, it = _quad_yz(0.75, 0.75, 1.25, 1.25)
    verts = np.vstack([rv, iv])
    tris = np.vstack([rt, it + len(rv)])
    geom = project_mesh(verts, tris)
    assert geom.area == pytest.approx(3.25)
    rep = compare_projections(geom, geom)
    assert rep["source_holes"] == 1
    assert rep["source_hole_area_m2"] == pytest.approx(0.75)
    assert rep["candidate_holes"] == 1
    assert rep["candidate_hole_area_m2"] == pytest.approx(0.75)
    assert rep["filled_original_hole_m2"] == pytest.approx(0.0, abs=1e-12)
    assert rep["iou"] == pytest.approx(1.0)


def test_orientation_invariance():
    verts, tris = _quad_yz(0, 0, 1, 1)
    flipped = tris[:, ::-1].copy()
    g_ccw = project_mesh(verts, tris)
    g_cw = project_mesh(verts, flipped)
    assert g_ccw.area == pytest.approx(g_cw.area)
    assert g_ccw.symmetric_difference(g_cw).area == pytest.approx(0.0, abs=1e-12)


def _grid_yz(nx, ny, size=1.0):
    verts = []
    tris = []
    for ix in range(nx):
        for iy in range(ny):
            base = len(verts)
            y0, z0 = ix * size, iy * size
            verts.extend([
                [0, y0, z0], [0, y0 + size, z0],
                [0, y0 + size, z0 + size], [0, y0, z0 + size],
            ])
            tris.extend([[base, base + 1, base + 2], [base, base + 2, base + 3]])
    return np.array(verts, dtype=np.float64), np.array(tris, dtype=np.int64)


def test_chunk_size_consistency():
    verts, tris = _grid_yz(10, 10)
    whole = project_mesh(verts, tris, chunk_size=20000)
    small = project_mesh(verts, tris, chunk_size=7)
    assert whole.area == pytest.approx(100.0)
    assert small.area == pytest.approx(100.0)
    assert whole.symmetric_difference(small).area == pytest.approx(0.0, abs=1e-9)
    # Single-triangle blocks also work.
    tiny = project_mesh(verts, tris, chunk_size=1)
    assert tiny.area == pytest.approx(100.0)


def test_bad_index_raises():
    verts = np.array([[0, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float64)
    with pytest.raises(ValueError):
        project_mesh(verts, np.array([[0, 1, 99]], dtype=np.int64))
    with pytest.raises(ValueError):
        project_mesh(verts, np.array([[0, 1, -1]], dtype=np.int64))
    with pytest.raises(ValueError):
        project_mesh(verts, np.array([[0, 1]], dtype=np.int64))
    with pytest.raises(ValueError):
        project_mesh(verts, np.array([[0.0, 1.0, 2.0]], dtype=np.float64))
    with pytest.raises(ValueError):
        project_mesh(verts, np.array([[0, 1, 2]], dtype=np.int64), axes=(1, 1))
    with pytest.raises(ValueError):
        project_mesh(verts, np.array([[0, 1, 2]], dtype=np.int64), chunk_size=0)


def test_nonfinite_vertices_raise():
    bad = np.array([[0, 0, 0], [0, np.inf, 0], [0, 0, 1]], dtype=np.float64)
    with pytest.raises(ValueError):
        project_mesh(bad, np.array([[0, 1, 2]], dtype=np.int64))
    bad = np.array([[0, 0, 0], [0, np.nan, 0], [0, 0, 1]], dtype=np.float64)
    with pytest.raises(ValueError):
        project_mesh(bad, np.array([[0, 1, 2]], dtype=np.int64))


def test_empty_and_all_degenerate():
    empty = project_mesh(
        np.zeros((0, 3), dtype=np.float64), np.zeros((0, 3), dtype=np.int64))
    assert empty.is_empty and empty.area == pytest.approx(0.0)
    # Triangles against an empty vertex buffer are invalid, not empty.
    with pytest.raises(ValueError):
        project_mesh(
            np.zeros((0, 3), dtype=np.float64),
            np.array([[0, 1, 2]], dtype=np.int64))
    # Collinear projection: zero area everywhere.
    verts = np.array([[0, 0, 0], [0, 1, 1], [0, 2, 2]], dtype=np.float64)
    deg = project_mesh(verts, np.array([[0, 1, 2]], dtype=np.int64))
    assert deg.is_empty and deg.area == pytest.approx(0.0)
    with pytest.raises(ValueError):
        compare_projections(deg, deg)


def test_compare_partial_overlap_numbers():
    v1, t1 = _quad_yz(0, 0, 1, 1)
    v2, t2 = _quad_yz(0.5, 0.5, 1.5, 1.5)
    src = project_mesh(v1, t1)
    dst = project_mesh(v2, t2)
    rep = compare_projections(src, dst)
    assert rep["source_m2"] == pytest.approx(1.0)
    assert rep["candidate_m2"] == pytest.approx(1.0)
    assert rep["relative_change"] == pytest.approx(0.0, abs=1e-12)
    assert rep["lost_m2"] == pytest.approx(0.75)
    assert rep["added_m2"] == pytest.approx(0.75)
    assert rep["symmetric_difference_m2"] == pytest.approx(1.5)
    assert rep["iou"] == pytest.approx(0.25 / 1.75)


def test_compare_rejects_nonfinite_area():
    v, t = _quad_yz(0, 0, 1, 1)
    good = project_mesh(v, t)

    class Fake:
        area = float("nan")

        def difference(self, other):
            raise AssertionError("must raise before set operations")

        def intersection(self, other):
            raise AssertionError("must raise before set operations")

        def union(self, other):
            raise AssertionError("must raise before set operations")

        def symmetric_difference(self, other):
            raise AssertionError("must raise before set operations")

    with pytest.raises(ValueError):
        compare_projections(Fake(), good)
    with pytest.raises(ValueError):
        compare_projections(good, Fake())


def test_memmap_inputs(tmp_path):
    verts, tris = _grid_yz(4, 4)
    vpath = tmp_path / "verts.dat"
    tpath = tmp_path / "tris.dat"
    vmap = np.memmap(vpath, dtype=np.float64, mode="w+", shape=verts.shape)
    vmap[:] = verts
    vmap.flush()
    tmap = np.memmap(tpath, dtype=np.int64, mode="w+", shape=tris.shape)
    tmap[:] = tris
    tmap.flush()
    vread = np.memmap(vpath, dtype=np.float64, mode="r", shape=verts.shape)
    tread = np.memmap(tpath, dtype=np.int64, mode="r", shape=tris.shape)
    geom = project_mesh(vread, tread, chunk_size=5)
    assert geom.area == pytest.approx(16.0)


def test_default_grid_is_none():
    v, t = _quad_yz(0, 0, 1, 1)
    assert project_mesh(v, t).area == pytest.approx(
        project_mesh(v, t, grid_size=None).area)


def test_invalid_grid_size_rejected():
    v, t = _quad_yz(0, 0, 1, 1)
    for bad in (0.0, -1e-9, float("nan"), float("inf"), "1e-9", True, [1e-9]):
        with pytest.raises(ValueError):
            project_mesh(v, t, grid_size=bad)


def test_requested_grid_snaps_and_preserves_inputs():
    # One vertex nudged 1e-10 off the unit-square edge: ungridded union keeps
    # the sliver (area just above 1); a 1e-9 grid snaps it away (area 1).
    verts = np.array([
        [0, 0, 0], [0, 1, 0], [0, 1 + 1e-10, 1], [0, 0, 1],
    ], dtype=np.float64)
    tris = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
    before_v = verts.copy()
    before_t = tris.copy()
    plain = project_mesh(verts, tris)
    gridded = project_mesh(verts, tris, grid_size=1e-9)
    assert plain.area > 1.0
    assert gridded.area == pytest.approx(1.0)
    assert plain.area > gridded.area
    np.testing.assert_array_equal(verts, before_v)
    np.testing.assert_array_equal(tris, before_t)


def test_gridded_results_consistent_across_chunk_sizes():
    verts, tris = _grid_yz(10, 10)
    whole = project_mesh(verts, tris, chunk_size=20000, grid_size=1e-9)
    small = project_mesh(verts, tris, chunk_size=7, grid_size=1e-9)
    assert whole.area == pytest.approx(100.0)
    assert small.area == pytest.approx(100.0)
    assert whole.symmetric_difference(small).area == pytest.approx(0.0, abs=1e-9)
