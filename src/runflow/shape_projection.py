"""Memory-bounded exact 2D triangle-projection union and silhouette comparison.

Standalone reusable module for the RunFlow shape audit. It projects triangle
soup onto a coordinate plane and unions the projected triangles.

"Exact" here means no raster/snap approximation: coordinates pass through to
GEOS overlay arithmetic unchanged. It does not mean mathematically exact
real-number geometry; all operations use float64 arithmetic.

Design notes:
  - No raster/snap approximation: no snapping, rounding, gridding, buffering,
    or simplification is applied. Projected coordinates are passed to Shapely
    unchanged, and union/overlay runs in GEOS float64 arithmetic (exact with
    respect to the float64 inputs, not mathematically exact).
  - Optional explicit precision grid: ``project_mesh(..., grid_size=<float>)``
    forwards that 2D grid to every union step for robustness on nearly
    coincident geometry. It is strictly opt-in (default ``None`` keeps
    coordinates unmodified and behavior unchanged); gridded output is a
    grid-modified approximation, never exact/unmodified output.
  - No orientation culling: front/back-facing triangles are all kept because
    the source may be an open surface. Only truly degenerate projections
    (zero projected area) are skipped.
  - Memory-bounded: triangles are processed in ``chunk_size`` blocks. Only one
    block of Shapely polygons exists at a time, each block is reduced to a
    single silhouette, and block silhouettes are merged with a pairwise
    (hierarchical) union tree so peak memory scales with ``chunk_size`` plus
    the number of block results, not with the total triangle count.
  - Accepts any numpy array, including ``numpy.memmap``. Inputs are read with
    ``numpy.asanyarray`` (no whole-array copy) and gathered per chunk.
"""
from __future__ import annotations

import math
import numbers
import operator
import numpy as np
import shapely
from shapely.geometry import GeometryCollection, Polygon
from shapely.ops import unary_union

__all__ = ["project_mesh", "compare_projections"]

_EMPTY = "GEOMETRYCOLLECTION EMPTY"


def _empty_geometry():
    """Return an empty silhouette geometry."""
    return shapely.from_wkt(_EMPTY)


def _validate_axes(axes) -> tuple[int, int]:
    try:
        ax = (operator.index(axes[0]), operator.index(axes[1]))
    except Exception as exc:
        raise ValueError(f"axes must be a pair of ints from {{0, 1, 2}}: {axes!r}") from exc
    if len(axes) != 2:
        raise ValueError(f"axes must be a pair of ints from {{0, 1, 2}}: {axes!r}")
    if ax[0] not in (0, 1, 2) or ax[1] not in (0, 1, 2):
        raise ValueError(f"axes entries must each be 0, 1, or 2: {axes!r}")
    if ax[0] == ax[1]:
        raise ValueError(f"axes entries must be distinct: {axes!r}")
    return ax


def _validate_chunk_size(chunk_size) -> int:
    try:
        value = operator.index(chunk_size)
    except Exception as exc:
        raise ValueError(f"chunk_size must be a positive int: {chunk_size!r}") from exc
    if value < 1:
        raise ValueError(f"chunk_size must be a positive int: {chunk_size!r}")
    return value


def _validate_grid_size(grid_size):
    """Validate the explicit overlay precision grid (None or finite > 0)."""
    if grid_size is None:
        return None
    if isinstance(grid_size, bool) or not isinstance(grid_size, numbers.Real):
        raise ValueError(f"grid_size must be a positive float or None: {grid_size!r}")
    value = float(grid_size)
    if not math.isfinite(value) or not value > 0.0:
        raise ValueError(f"grid_size must be a finite value > 0 or None: {grid_size!r}")
    return value


def _hierarchical_union(geoms, grid_size=None):
    """Pairwise-tree union of silhouette pieces (bounded intermediates)."""
    queue = [g for g in geoms if g is not None and not g.is_empty]
    if not queue:
        return _empty_geometry()
    while len(queue) > 1:
        merged: list = []
        for i in range(0, len(queue), 2):
            if i + 1 < len(queue):
                merged.append(shapely.union_all([queue[i], queue[i + 1]], grid_size=grid_size))
            else:
                merged.append(queue[i])
        queue = merged
    return queue[0]


def project_mesh(vertices, triangles, axes=(1, 2), chunk_size=20000, grid_size=None):
    """Project triangles onto a coordinate plane and union them.

    Args:
        vertices: ``(N, 3)`` numpy array (ndarray or memmap) of XYZ coords.
        triangles: ``(M, 3)`` numpy integer array (ndarray or memmap) of indices.
        axes: pair selecting the kept coordinates, default ``(1, 2)`` (Y-Z).
        chunk_size: number of triangles unioned per block; bounds peak memory.
        grid_size: optional explicit 2D precision grid (positive float, same
            units as the projected coordinates), forwarded to every Shapely
            ``union_all`` step. Default ``None`` preserves current behavior:
            projected coordinates reach GEOS unchanged. When set, GEOS snaps
            overlay arithmetic to that grid, so results are grid-modified
            approximations for robustness, not exact/unmodified output. There
            is no automatic fallback: overlay errors propagate to the caller.
            Input arrays are never modified; the grid applies inside GEOS
            overlay only.

    "Exact" means no raster/snap approximation (coordinates reach GEOS
    unchanged with ``grid_size=None``); overlay results still use float64
    arithmetic, not mathematically exact real-number geometry.

    Returns:
        Shapely silhouette geometry (Polygon / MultiPolygon / empty
        GeometryCollection). Empty input or all-degenerate projections yield
        an empty geometry with area 0.

    Raises:
        ValueError: on bad shapes, bad dtypes, out-of-range or negative
            indices (including any triangle against an empty vertex buffer),
            non-finite coordinates, bad axes, bad chunk_size, bad grid_size,
            or non-finite projected area.
    """
    ax = _validate_axes(axes)
    block = _validate_chunk_size(chunk_size)
    grid = _validate_grid_size(grid_size)

    vertices = np.asanyarray(vertices)
    triangles = np.asanyarray(triangles)

    if vertices.ndim != 2 or vertices.shape[1] != 3:
        raise ValueError(f"vertices must have shape (N, 3), got {vertices.shape!r}")
    if triangles.ndim != 2 or triangles.shape[1] != 3:
        raise ValueError(f"triangles must have shape (M, 3), got {triangles.shape!r}")
    if vertices.dtype.kind not in "fiub":
        raise ValueError(f"vertices must be a numeric array, got dtype {vertices.dtype}")
    if triangles.dtype.kind not in "iu":
        raise ValueError(f"triangles must be an integer array, got dtype {triangles.dtype}")

    n_verts = int(vertices.shape[0])
    n_tris = int(triangles.shape[0])
    if n_tris == 0:
        return _empty_geometry()
    if n_verts == 0:
        raise ValueError("triangles reference an empty vertex buffer of size 0")

    # Index bounds without copying index data (min/max stream over memmap).
    try:
        lo = int(np.min(triangles))
        hi = int(np.max(triangles))
    except Exception as exc:
        raise ValueError(f"could not inspect triangle indices: {exc}") from exc
    if lo < 0:
        raise ValueError(f"triangle indices must be non-negative, got min {lo}")
    if hi >= n_verts:
        raise ValueError(f"triangle index {hi} outside vertex buffer of size {n_verts}")

    # Finite-coordinate check streamed in row blocks to stay memory-bounded.
    if vertices.dtype.kind == "f":
        step = 65536
        for start in range(0, n_verts, step):
            window = np.asarray(vertices[start:start + step])
            if not bool(np.all(np.isfinite(window))):
                raise ValueError("vertices contain non-finite (NaN/inf) coordinates")

    base = np.asarray(vertices)
    parts: list = []
    for start in range(0, n_tris, block):
        idx = np.asarray(triangles[start:start + block], dtype=np.int64)
        coords3d = base[idx]  # (k, 3, 3); bounded copy of this block only
        coords2d = coords3d[:, :, list(ax)]  # (k, 3, 2); no snap/round/grid
        polys = shapely.polygons(coords2d)  # vectorized construction
        areas = shapely.area(polys)
        if not bool(np.all(np.isfinite(areas))):
            raise ValueError("non-finite projected triangle area")
        keep = polys[areas > 0.0]  # skip degenerate only; keep every orientation
        if keep.size == 0:
            continue
        parts.append(shapely.union_all(keep, grid_size=grid))
    return _hierarchical_union(parts, grid)


def _hole_polygons(geom) -> list:
    """Collect one filled polygon per bounded interior ring (hole)."""
    holes: list = []
    stack = [geom]
    while stack:
        item = stack.pop()
        if item is None or item.is_empty:
            continue
        gtype = item.geom_type
        if gtype == "Polygon":
            for ring in item.interiors:
                holes.append(Polygon(ring))
        elif gtype in ("MultiPolygon", "GeometryCollection"):
            stack.extend(item.geoms)
    return holes


def _background_holes(geom) -> list:
    """Actually uncovered background: ring fill minus solid silhouette.

    Interior rings alone overcount when a solid island (a separate polygon
    member) sits inside the ring. Subtracting the geometry itself leaves only
    genuinely uncovered background, split into disjoint polygon components.
    """
    rings = _hole_polygons(geom)
    if not rings:
        return []
    background = unary_union(rings).difference(geom)
    if background.is_empty:
        return []
    parts: list = []
    stack = [background]
    while stack:
        item = stack.pop()
        if item is None or item.is_empty:
            continue
        gtype = item.geom_type
        if gtype == "Polygon":
            if float(item.area) > 0.0:
                parts.append(item)
        elif gtype in ("MultiPolygon", "GeometryCollection"):
            stack.extend(item.geoms)
    return parts


def _hole_stats(geom) -> tuple[int, float, list]:
    parts = _background_holes(geom)
    total = 0.0
    for part in parts:
        total += float(part.area)
    if not math.isfinite(total):
        raise ValueError("non-finite hole area")
    return len(parts), total, parts


def compare_projections(source, candidate) -> dict:
    """Compare two projected silhouettes and return JSON-friendly metrics.

    ``source`` is the reference silhouette, ``candidate`` the new silhouette
    (both as returned by :func:`project_mesh`). Areas use the geometry's own
    square units (call them m^2 when inputs are meters).

    Note: counted holes are actually uncovered background regions of the 2D
    projection (union of interior-ring fills minus the silhouette itself,
    split into disjoint polygon components), i.e. line-of-sight background
    enclosed by silhouette in this view plane. Solid islands inside a ring
    are silhouette, not background. Projected holes are not full 3D
    tunnels/through-holes; a 3D tunnel along the view direction is invisible
    here, and a projected hole may be a pocket rather than a tunnel.

    Raises:
        ValueError: on non-finite area of either silhouette or on
            non-positive source area (empty/degenerate reference).
    """
    try:
        source_area = float(source.area)
        candidate_area = float(candidate.area)
    except Exception as exc:
        raise ValueError(f"source/candidate must be shapely geometries: {exc}") from exc
    if not math.isfinite(source_area) or not math.isfinite(candidate_area):
        raise ValueError("non-finite silhouette area")
    if not source_area > 0.0:
        raise ValueError("source silhouette area must be positive")

    inter_area = float(source.intersection(candidate).area)
    union_area = float(source.union(candidate).area)
    lost_area = float(source.difference(candidate).area)
    added_area = float(candidate.difference(source).area)
    sym_area = float(source.symmetric_difference(candidate).area)
    for value in (inter_area, union_area, lost_area, added_area, sym_area):
        if not math.isfinite(value):
            raise ValueError("non-finite comparison area")
    iou = (inter_area / union_area) if union_area > 0.0 else 0.0

    src_holes, src_hole_area, src_hole_parts = _hole_stats(source)
    dst_holes, dst_hole_area, _ = _hole_stats(candidate)
    if src_hole_parts:
        filled = float(unary_union(src_hole_parts).intersection(candidate).area)
    else:
        filled = 0.0
    if not math.isfinite(filled):
        raise ValueError("non-finite filled-hole area")

    return {
        "source_m2": source_area,
        "candidate_m2": candidate_area,
        "relative_change": (candidate_area - source_area) / source_area,
        "relative_change_abs": abs(candidate_area - source_area) / source_area,
        "lost_m2": lost_area,
        "added_m2": added_area,
        "symmetric_difference_m2": sym_area,
        "intersection_m2": inter_area,
        "union_m2": union_area,
        "iou": float(iou),
        "source_holes": int(src_holes),
        "source_hole_area_m2": float(src_hole_area),
        "candidate_holes": int(dst_holes),
        "candidate_hole_area_m2": float(dst_hole_area),
        "filled_original_hole_m2": float(filled),
        "holes_note": (
            "Projected holes are bounded interior rings (line-of-sight "
            "background enclosed in this view plane), not full 3D "
            "tunnels/through-holes."
        ),
    }
