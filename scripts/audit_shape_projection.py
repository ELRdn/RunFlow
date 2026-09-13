"""Continuous projected-silhouette comparison of cached private geometry.

A1: an explicit benchmark path may run the same input at coarser explicit
precision grids.  The production guard is unchanged - a normal audit still
rejects any grid coarser than 10 nm.

A2: the source silhouette is cached by content identity.  Candidate geometry
differs between repair attempts and is never cached.

A3: this script remains per-view when --view is given, so three views can run
concurrently into one audit root.  Only the caller merges them, because a
per-view run never writes the canonical projections.json.
"""
import argparse
import json
from pathlib import Path
import shutil
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import shapely

from runflow import projection_cache
from runflow.audit_contract import REQUIRED_VIEWS, VIEW_AXES, merge_views
from runflow.shape_audit import load_surface
from runflow.shape_projection import project_mesh, compare_projections, _hole_stats

MAX_LEGACY_GRID_M = 1e-8
MAX_BENCHMARK_GRID_M = 1e-3
CHUNK_SIZE = 20000
HOLES_MIN_M2 = 1e-6


def _archive(path):
    if not path.exists():
        return
    archive = path.parent / "prior-projection-output"
    archive.mkdir(exist_ok=True)
    target = archive / path.name
    if target.exists():
        raise ValueError("Projection evidence archive already exists: " + str(target))
    shutil.copyfile(path, target)


def _validated_grid(args):
    if args.benchmark:
        if not 0.0 < args.grid_m <= MAX_BENCHMARK_GRID_M:
            raise ValueError("Benchmark precision grid must be within (0, 1e-3] m")
        return args.grid_m
    if not 0 <= args.grid_m <= MAX_LEGACY_GRID_M:
        raise ValueError("Diagnostic 2D precision grid must be <= 10nm unless --benchmark is set")
    return args.grid_m


def _silhouette(root, name, view, axes, grid_m, args, record):
    """Project one surface, reusing the cache for the immutable source only."""
    cache_root = Path(args.cache_root) if args.cache_root else root
    use_cache = (not args.no_projection_cache) and name == "source"
    payload = key = None
    if use_cache:
        geometry_sha256 = json.loads((root / name / "cache.json").read_text(encoding="utf-8"))["input_sha256"]
        payload = projection_cache.cache_payload(geometry_sha256=geometry_sha256, view=view,
                                                 axes=axes, grid_m=grid_m, chunk_size=CHUNK_SIZE)
        key = projection_cache.cache_key(payload)
        cached = projection_cache.lookup(cache_root, key, payload)
        if cached is not None:
            record["cache"] = dict(status="hit", key=key, root=str(cache_root),
                                   version=projection_cache.CACHE_VERSION)
            return cached
        record["cache"] = dict(status="miss", key=key, root=str(cache_root),
                               version=projection_cache.CACHE_VERSION)
    shape = project_mesh(*load_surface(root / name), axes=axes, grid_size=grid_m or None)
    if grid_m:
        shape = shapely.set_precision(shape, grid_m)
    if not shape.is_valid:
        raise ValueError("Invalid union geometry for " + view + " " + name)
    if use_cache:
        projection_cache.store(cache_root, key, payload, shape)
    return shape


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--view', choices=list(REQUIRED_VIEWS))
    p.add_argument('--grid-m', type=float, default=0.)
    p.add_argument('--benchmark', action='store_true',
                   help='allow an explicit grid coarser than 10nm and mark the output as a benchmark')
    p.add_argument('--no-projection-cache', action='store_true')
    p.add_argument('--cache-root', type=Path)
    args = p.parse_args()
    grid_m = _validated_grid(args)
    root = args.root
    result = {}
    timings = {}
    records = {}
    started = time.monotonic()
    for view in REQUIRED_VIEWS:
        if args.view and view != args.view:
            continue
        axes = VIEW_AXES[view]
        view_started = time.monotonic()
        record = {}
        geometries = []
        for name in ('source', 'candidate'):
            print('PROJECTION_START', view, name, flush=True)
            shape = _silhouette(root, name, view, axes, grid_m, args, record)
            path = root / (view + '-' + name + '.wkb')
            _archive(path)
            path.write_bytes(shapely.to_wkb(shape))
            geometries.append(shape)
            print('PROJECTION_READY', view, name, shape.area, flush=True)
        a, b = geometries
        comparison = compare_projections(a, b)
        _, _, holes = _hole_stats(a)
        comparison['source_holes_at_least_1_mm2'] = []
        for hole in sorted(holes, key=lambda g: g.area, reverse=True):
            if hole.area < HOLES_MIN_M2:
                continue
            fill = hole.intersection(b).area
            comparison['source_holes_at_least_1_mm2'].append(dict(area_mm2=hole.area*1e6,
                filled_mm2=fill*1e6, filled_fraction=fill/hole.area, bbox_m=list(hole.bounds)))
        comparison['axes'] = list(axes)
        comparison['precision_grid_m'] = grid_m
        result[view] = comparison
        records[view] = record
        timings[view] = round(time.monotonic() - view_started, 3)
        destination = root / (('projection-' + view + '.json') if args.view else 'projections.json')
        destination.write_text(json.dumps(dict(views={view: comparison}, complete=False,
            benchmark=bool(args.benchmark)), indent=2), encoding='utf-8')
    metadata = dict(elapsed_s=round(time.monotonic() - started, 3), view_elapsed_s=timings,
        shapely_version=shapely.__version__, precision_grid_m=grid_m, benchmark=bool(args.benchmark),
        cache=records,
        projection_cache=dict(enabled=not args.no_projection_cache,
            version=projection_cache.CACHE_VERSION, algorithm=projection_cache.ALGORITHM_VERSION),
        method='All projected triangles unioned without rasterization or face culling; '
               'explicit optional 2D precision grid; 3D inputs untouched')
    if args.view:
        destination = root / ('projection-' + args.view + '.json')
        document = dict(views={args.view: result[args.view]}, complete=True, **metadata)
        destination.write_text(json.dumps(document, indent=2), encoding='utf-8')
    else:
        destination = root / 'projections.json'
        document = merge_views(result)
        document.update(metadata)
        destination.write_text(json.dumps(document, indent=2), encoding='utf-8')
    print('PROJECTION_AUDIT_COMPLETE', flush=True)


if __name__ == '__main__':
    main()
