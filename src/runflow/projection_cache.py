"""Deterministic cache for source-mesh 2D projection silhouettes.

The cache is a pure performance aid.  It never changes a scientific result and
never substitutes for an authoritative artifact.  An entry is reusable only
when every input that can change the projection matches: the source geometry
content hash, the view plane, the precision grid, the chunk size, the
projection algorithm version, and the GEOS/Shapely version that produced it.

Only the source silhouette is cached.  Repair candidates differ between
attempts, so they have no immutable identity and are always recomputed.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import shapely

from .shape_audit import file_sha

CACHE_VERSION = "runflow-projection-cache-1"
ALGORITHM_VERSION = "project_mesh-hierarchical-union-1"
CACHE_DIRNAME = "projection-cache"


def cache_payload(*, geometry_sha256, view, axes, grid_m, chunk_size):
    """Return the identity payload that fully determines a cached silhouette."""
    return dict(
        cache_version=CACHE_VERSION,
        algorithm=ALGORITHM_VERSION,
        shapely_version=str(shapely.__version__),
        geometry_sha256=str(geometry_sha256),
        view=str(view),
        axes=[int(axes[0]), int(axes[1])],
        grid_m=(None if grid_m in (None, 0, 0.0) else float(grid_m)),
        chunk_size=int(chunk_size),
    )


def cache_key(payload):
    """Return the hex key for a payload produced by cache_payload."""
    if not isinstance(payload, dict):
        raise ValueError("Cache payload must be a mapping")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def cache_dir(root):
    return Path(root) / CACHE_DIRNAME


def _entry_paths(root, key):
    folder = cache_dir(root)
    return folder / (key + ".wkb"), folder / (key + ".json")


def lookup(root, key, payload):
    """Return the cached silhouette, or None when the entry is absent or unusable.

    A corrupted, truncated, version-mismatched, or empty entry is reported as a
    miss so the caller recomputes instead of silently reusing bad geometry.
    """
    wkb_path, manifest_path = _entry_paths(root, key)
    if not wkb_path.is_file() or not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(manifest, dict):
        return None
    if manifest.get("key") != key or manifest.get("payload") != payload:
        return None
    expected = manifest.get("wkb_sha256")
    if not isinstance(expected, str):
        return None
    try:
        if file_sha(wkb_path) != expected:
            return None
        geometry = shapely.from_wkb(wkb_path.read_bytes())
    except Exception:
        return None
    if geometry is None or geometry.is_empty:
        return None
    return geometry


def store(root, key, payload, geometry):
    """Publish one cache entry atomically and return its manifest."""
    wkb_path, manifest_path = _entry_paths(root, key)
    wkb_path.parent.mkdir(parents=True, exist_ok=True)
    data = shapely.to_wkb(geometry)
    wkb_temp = wkb_path.with_suffix(".wkb.tmp")
    manifest_temp = manifest_path.with_suffix(".json.tmp")
    manifest = dict(cache_version=CACHE_VERSION, key=key, payload=payload,
                    wkb_sha256=hashlib.sha256(data).hexdigest(), wkb_bytes=len(data))
    wkb_temp.write_bytes(data)
    manifest_temp.write_text(json.dumps(manifest, sort_keys=True, allow_nan=False), encoding="utf-8")
    os.replace(wkb_temp, wkb_path)
    os.replace(manifest_temp, manifest_path)
    return manifest
