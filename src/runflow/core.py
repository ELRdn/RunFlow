import hashlib
import json
import math
from pathlib import Path

from . import __version__
from .contracts import validate


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    def reject_constant(value):
        raise ValueError(f"Non-finite JSON value: {value}")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), parse_constant=reject_constant, object_pairs_hook=unique)


def write(path, value):
    path = Path(path)
    payload = canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def asset_path(root, relative):
    # Portable paths only, with symlink/junction escape protection.
    if "\\" in relative or ":" in relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError(f"Asset path must be portable and relative: {relative}")
    resolved = (Path(root) / relative).resolve()
    if not resolved.is_relative_to(Path(root).resolve()) or not resolved.is_file():
        raise ValueError(f"Missing or outside-root asset: {relative}")
    return resolved


def validate_manifest(manifest, root):
    canonical(manifest)  # also rejects NaN passed through the Python API
    validate("manifest", manifest)
    for value in [*manifest["source"].values(), *manifest["tools"].values(),
                  manifest["height_source"], manifest["height_measurement"],
                  manifest["transform"]["scale_evidence"], manifest["gait"]["contact_event"], *manifest["preprocessing"]]:
        if str(value).strip().lower() in {"", "unknown", "todo", "tbd", "pending", "replace_me"}:
            raise ValueError("Unresolved input metadata")
    if manifest["gait"]["end_s"] <= manifest["gait"]["start_s"]:
        raise ValueError("Cycle end must follow start")
    m = manifest["transform"]["source_to_rf"]
    if m[3] != [0, 0, 0, 1]:
        raise ValueError("Transform must be affine")
    # Matrix includes uniform scale. Separate field is an audited assertion, not a second multiplication.
    scale = manifest["transform"]["meters_per_source_unit"]
    for i in range(3):
        for j in range(3):
            dot = sum(m[k][i] * m[k][j] for k in range(3))
            if not math.isclose(dot, scale * scale if i == j else 0, rel_tol=1e-8, abs_tol=1e-12):
                raise ValueError("Transform must preserve proportions and match declared scale")
    det = (m[0][0]*(m[1][1]*m[2][2]-m[1][2]*m[2][1])
           - m[0][1]*(m[1][0]*m[2][2]-m[1][2]*m[2][0])
           + m[0][2]*(m[1][0]*m[2][1]-m[1][1]*m[2][0]))
    if (det < 0) != manifest["transform"]["reflection"]:
        raise ValueError("Reflection declaration differs from transform determinant")
    assets = manifest["assets"]
    if len({a["id"] for a in assets}) != len(assets):
        raise ValueError("Duplicate asset ID")
    if not {"model", "motion"}.issubset({a["role"] for a in assets}):
        raise ValueError("Both model and motion assets are required")
    for asset in assets:
        if file_hash(asset_path(root, asset["path"])) != asset["sha256"]:
            raise ValueError(f"SHA-256 mismatch: {asset['id']}")
    return manifest


def sample(manifest):
    validate("manifest", manifest)
    gait = manifest["gait"]
    duration = gait["end_s"] - gait["start_s"]
    if duration <= 0:
        raise ValueError("Cycle end must follow start")
    result = {"schema_version": "1", "motion_id": manifest["source"]["motion_id"],
              "cycle_duration_s": duration, "samples": [
                  {"index": i, "phase": i/16, "time_s": gait["start_s"] + duration*i/16,
                   "weight": 1/16} for i in range(16)]}
    validate("sampling", result)
    return result


def generate(manifest, root, cfd=None):
    validate_manifest(manifest, root)
    if cfd is not None:
        validate("cfd", cfd)
        canonical(cfd)
        for value in [v for v in cfd.values() if isinstance(v,str)] + cfd["force_patches"]:
            if value.strip().lower() in {"", "unknown", "todo", "tbd", "pending", "replace_me"}:
                raise ValueError("Unresolved CFD metadata")
        if cfd["inlet_direction"] != [-1, 0, 0]:
            raise ValueError("Forward +X requires incoming air along -X")
    # Paths do not define scientific identity; content, IDs and tool versions do.
    portable = {**manifest, "assets": sorted(
        [{k: a[k] for k in ("id", "role", "sha256")} for a in manifest["assets"]], key=lambda a: a["id"])}
    config = {"schema_version": "1", "generator_version": __version__, "input": portable,
              "sampling": sample(manifest), "cfd": cfd, "purpose": "phase0_import_validation",
              "character_cfd_execution_allowed": False}
    identity = digest(config)
    result = {"schema_version": "1", "experiment_id": "rf-" + identity,
              "execution_status": "NOT_RUN", "scientific_status": "PENDING_HUMAN_REVIEW",
              "ranking_eligible": False, "drag_N": None, "Cd": None, "CdA_m2": None,
              "notes": ["Phase 0: no character CFD or scientific approval"]}
    validate("result", result)
    envelope = {"experiment_id": result["experiment_id"], "config_sha256": identity, "config": config}
    validate("experiment", envelope)
    return envelope, result
