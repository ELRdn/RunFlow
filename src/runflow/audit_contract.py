"""Deterministic projection-audit contract: validation, merge, and promotion.

The authoritative artifact is PROJECTIONS.json inside the audit root, holding
all three views (front, side, top) with complete = true.

The legacy split form - a partial PROJECTIONS.json plus a separate merged
artifact - is accepted for CFD admission only when the merged document passes
the same validation and the input hashes it records still match the files on
disk.  A merged document can never mask an actually incomplete audit.

Promotion rewrites the canonical file from already valid evidence.  It never
recomputes a projection and never deletes the previous bytes: the earlier file
is archived as PROJECTIONS-PRIOR.json and its hash is recorded.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import time

from .shape_audit import file_sha

CANONICAL_NAME = "projections.json"
MERGED_NAME = "projections-merged.json"
PRIOR_NAME = "projections-prior.json"
SCHEMA_VERSION = "phase1-cycle-projection-audit-2"
REQUIRED_VIEWS = ("front", "side", "top")
VIEW_AXES = {"front": (1, 2), "side": (0, 2), "top": (0, 1)}
_METRIC_KEYS = ("source_m2", "candidate_m2", "relative_change_abs", "iou")


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def validate_projections(document, require_views=REQUIRED_VIEWS):
    """Validate a projection document; returns it or raises ValueError."""
    if not isinstance(document, dict):
        raise ValueError("Projection audit must be a JSON object")
    if document.get("complete") is not True:
        raise ValueError("Projection audit is not complete")
    views = document.get("views")
    if not isinstance(views, dict):
        raise ValueError("Projection audit views are missing")
    expected = set(require_views)
    if set(views) != expected:
        raise ValueError("Projection audit must contain exactly: " + ", ".join(require_views))
    for name in require_views:
        row = views[name]
        if not isinstance(row, dict):
            raise ValueError("Projection view is malformed: " + name)
        for key in _METRIC_KEYS:
            if key not in row:
                raise ValueError("Projection view is missing " + key + ": " + name)
        source = _finite(row["source_m2"])
        candidate = _finite(row["candidate_m2"])
        if source is None or candidate is None or source <= 0.0 or candidate <= 0.0:
            raise ValueError("Projection view areas must be finite and positive: " + name)
        change = _finite(row["relative_change_abs"])
        if change is None or change < 0.0:
            raise ValueError("Projection view area difference is not a finite magnitude: " + name)
        iou = _finite(row["iou"])
        if iou is None or not 0.0 <= iou <= 1.0:
            raise ValueError("Projection view IoU is out of range: " + name)
        axes = row.get("axes")
        if axes is not None:
            try:
                value = tuple(int(item) for item in axes)
            except (TypeError, ValueError):
                raise ValueError("Projection view axes are malformed: " + name)
            if value != VIEW_AXES[name]:
                raise ValueError("Projection view axes do not match the canonical plane: " + name)
    return document


def load_view_file(path, view):
    """Load and validate one per-view projection file, returning its row."""
    if view not in REQUIRED_VIEWS:
        raise ValueError("Unknown projection view: " + str(view))
    document = _read(path)
    if not isinstance(document, dict):
        raise ValueError("Per-view projection file must be a JSON object: " + str(path))
    views = document.get("views")
    if not isinstance(views, dict) or set(views) != {view}:
        raise ValueError("Per-view projection file must contain exactly one view: " + str(path))
    validate_projections({"complete": True, "views": views}, require_views=(view,))
    return views[view]


def merge_views(rows):
    """Merge view rows into a canonical document with deterministic ordering."""
    if not isinstance(rows, dict):
        raise ValueError("Projection merge rows must be a mapping")
    missing = [name for name in REQUIRED_VIEWS if name not in rows]
    if missing:
        raise ValueError("Projection merge is missing views: " + ", ".join(missing))
    unknown = sorted(set(rows) - set(REQUIRED_VIEWS))
    if unknown:
        raise ValueError("Projection merge received unknown views: " + ", ".join(unknown))
    document = {"views": {name: rows[name] for name in REQUIRED_VIEWS}, "complete": True}
    validate_projections(document)
    return document


def _verify_merged_inputs(audit_root, document):
    inputs = document.get("inputs")
    if not isinstance(inputs, dict) or not inputs:
        raise ValueError("Merged projection audit must record the hashes of its inputs")
    verified = {}
    for name, expected in inputs.items():
        path = audit_root / str(name)
        if not isinstance(expected, str) or not path.is_file():
            raise ValueError("Merged projection input is missing: " + str(name))
        actual = file_sha(path)
        if actual != expected:
            raise ValueError("Merged projection input changed: " + str(name))
        verified[str(name)] = actual
    return verified


def load_authoritative_projections(audit_root):
    """Return (document, source_name) for the authoritative projection evidence.

    The canonical file wins when it is valid.  Otherwise a verified legacy
    merged artifact is accepted.  Anything else raises, so an incomplete or
    corrupted audit still blocks admission.
    """
    audit_root = Path(audit_root)
    canonical = audit_root / CANONICAL_NAME
    if canonical.is_file():
        try:
            document = _read(canonical)
            validate_projections(document)
            return document, CANONICAL_NAME
        except (OSError, ValueError):
            pass
    merged = audit_root / MERGED_NAME
    if merged.is_file():
        document = _read(merged)
        validate_projections(document)
        _verify_merged_inputs(audit_root, document)
        return document, MERGED_NAME
    raise ValueError("Shape audit projection stage is incomplete")


def promote(audit_root):
    """Rewrite the canonical projection artifact from already valid evidence.

    Never recomputes a projection.  The previous canonical bytes are archived
    as projections-prior.json with its hash recorded, so the promotion chain is
    auditable.  Returns a machine-readable summary.
    """
    audit_root = Path(audit_root)
    if not audit_root.is_dir():
        raise ValueError("Audit root is missing: " + str(audit_root))
    canonical = audit_root / CANONICAL_NAME
    if canonical.is_file():
        try:
            validate_projections(_read(canonical))
            return dict(promoted=False, reason="canonical projection audit is already valid",
                        canonical=CANONICAL_NAME, canonical_sha256=file_sha(canonical))
        except (OSError, ValueError):
            pass
    rows = {}
    for view in REQUIRED_VIEWS:
        path = audit_root / ("projection-" + view + ".json")
        if path.is_file():
            try:
                rows[view] = load_view_file(path, view)
            except (OSError, ValueError):
                # A per-view file that does not validate is not evidence; the
                # merged or final validation below still has to pass.
                continue
    evidence = {}
    if set(rows) != set(REQUIRED_VIEWS):
        merged = audit_root / MERGED_NAME
        if not merged.is_file():
            raise ValueError("Projection promotion needs all three views or a merged artifact")
        document = _read(merged)
        validate_projections(document)
        verified = _verify_merged_inputs(audit_root, document)
        rows = {name: document["views"][name] for name in REQUIRED_VIEWS}
        evidence = dict(document=MERGED_NAME, document_sha256=file_sha(merged), inputs=verified)
    elif all((audit_root / ("projection-" + name + ".json")).is_file() for name in REQUIRED_VIEWS):
        evidence = dict(per_view={name: file_sha(audit_root / ("projection-" + name + ".json"))
                                  for name in REQUIRED_VIEWS})
    document = merge_views(rows)
    chain = {}
    if canonical.is_file():
        prior = audit_root / PRIOR_NAME
        if prior.exists():
            raise ValueError("Projection promotion archive already exists: " + PRIOR_NAME)
        prior.write_bytes(canonical.read_bytes())
        chain[PRIOR_NAME] = file_sha(prior)
        chain[CANONICAL_NAME] = file_sha(canonical)
    document["promotion"] = dict(schema_version=SCHEMA_VERSION, promoted_epoch=time.time(),
                                 prior=chain, evidence=evidence)
    temp = canonical.with_suffix(".json.tmp")
    temp.write_text(json.dumps(document, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(canonical)
    return dict(promoted=True, canonical=CANONICAL_NAME, canonical_sha256=file_sha(canonical),
                prior=chain, evidence=evidence)
