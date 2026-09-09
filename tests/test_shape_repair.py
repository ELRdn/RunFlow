"""Behavior tests for bounded full-body surface repair helpers.

These cover pure-Python contracts (bounded motion, distance/gate logic,
request validation/identity) plus one pinned-Blender fixture run. They never
adopt a CFD surface and never read real or private assets.
"""
import copy
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from runflow.shape_audit import file_sha
from runflow.shape_repair import RECIPES, bounded_delta, distance_state, gate, identity, validate

TOL_M = 0.002
MAX_MOVE_M = 0.0005


# ---------------------------------------------------------------------------
# bounded_delta: fractional, normal-only, capped motion
# ---------------------------------------------------------------------------

def test_bounded_delta_applies_fraction_without_capping():
    delta = np.array([[0.0004, 0.0, 0.0]])
    delta.setflags(write=False)
    out = bounded_delta(delta, 0.5, MAX_MOVE_M)
    assert out.shape == (1, 3)
    assert out[0, 0] == pytest.approx(0.0002)
    assert abs(out[0, 1]) < 1e-12 and abs(out[0, 2]) < 1e-12
    assert delta[0,0] == 0.0004


def test_bounded_delta_caps_large_move_at_half_mm():
    delta = np.array([[0.01, 0.0, 0.0], [0.0, -0.004, 0.0]])
    out = bounded_delta(delta, 0.5, MAX_MOVE_M)
    norms = np.linalg.norm(out, axis=1)
    assert norms[0] == pytest.approx(MAX_MOVE_M)
    assert norms[1] == pytest.approx(MAX_MOVE_M)
    # Direction is preserved while magnitude is capped.
    assert out[0, 0] > 0 and out[1, 1] < 0
    assert abs(out[0, 1]) < 1e-12 and abs(out[1, 0]) < 1e-12


def test_bounded_delta_never_exceeds_cap_on_mixed_magnitudes():
    delta = np.array([
        [0.0001, 0.0, 0.0],
        [0.001, 0.001, 0.0],
        [0.0, 0.0, 0.0],
        [-0.003, 0.004, 0.0],
    ])
    out = bounded_delta(delta, 0.5, MAX_MOVE_M)
    norms = np.linalg.norm(out, axis=1)
    assert (norms <= MAX_MOVE_M + 1e-9).all()
    # Zero input stays exactly zero (no NaN from the normalize guard).
    assert (out[2] == 0).all()
    assert np.isfinite(out).all()


def test_bounded_delta_normal_only_removes_tangential_motion():
    delta = np.array([[0.001, 0.002, 0.002]])
    normals = np.array([[0.0, 0.0, 1.0]])
    out = bounded_delta(delta, 0.5, MAX_MOVE_M, normals)
    # Normal component 2mm * 0.5 = 1mm, capped to 0.5mm; tangential removed.
    assert out[0, 0] == pytest.approx(0.0, abs=1e-12)
    assert out[0, 1] == pytest.approx(0.0, abs=1e-12)
    assert out[0, 2] == pytest.approx(MAX_MOVE_M)


def test_bounded_delta_accepts_non_unit_normals():
    delta = np.array([[0.001, 0.001, 0.001]])
    unit = bounded_delta(delta, 0.5, MAX_MOVE_M, np.array([[0.0, 0.0, 1.0]]))
    scaled = bounded_delta(delta, 0.5, MAX_MOVE_M, np.array([[0.0, 0.0, 10.0]]))
    np.testing.assert_allclose(unit, scaled, atol=1e-12)


def test_bounded_delta_identical_shifts_preserve_spacing():
    # Bounded correction must not collapse distinct vertices that share a shift:
    # identical output deltas keep their original separation (no hole-closing claim).
    delta = np.array([[0.0004, 0.0, 0.0], [0.0004, 0.0, 0.0]])
    out = bounded_delta(delta, 0.5, MAX_MOVE_M)
    np.testing.assert_allclose(out[0], out[1], atol=1e-12)
    base = np.array([[0.0, 0.0, 0.0], [0.001, 0.0, 0.0]])
    moved = base + out
    assert np.linalg.norm(moved[1] - moved[0]) == pytest.approx(0.001)


def test_bounded_delta_rejects_bad_inputs():
    good = np.array([[0.0001, 0.0, 0.0]])
    with pytest.raises(ValueError):
        bounded_delta(np.array([[0.0001, np.nan, 0.0]]), 0.5, MAX_MOVE_M)
    with pytest.raises(ValueError):
        bounded_delta(np.array([0.0001, 0.0]), 0.5, MAX_MOVE_M)
    with pytest.raises(ValueError):
        bounded_delta(good, 0.0, MAX_MOVE_M)
    with pytest.raises(ValueError):
        bounded_delta(good, 1.0, MAX_MOVE_M)
    with pytest.raises(ValueError):
        bounded_delta(good, 0.5, 0.002)
    with pytest.raises(ValueError):
        bounded_delta(good, 0.5, MAX_MOVE_M, normals=np.array([[0.0, 0.0, 1.0], [0.0, 0.0, 1.0]]))


# ---------------------------------------------------------------------------
# distance_state / gate: counterexamples fail, incomplete never passes
# ---------------------------------------------------------------------------

def test_distance_state_single_counterexample_fails_when_incomplete():
    value = {"complete": False, "witness_lower_m": 0.0035}
    assert distance_state(value, TOL_M) == "FAIL"


def test_distance_state_incomplete_measurement_never_passes():
    assert distance_state(None) == "UNVERIFIED"
    assert distance_state({}) == "UNVERIFIED"
    assert distance_state({"complete": False, "global_max_upper_m": 0.0005}) == "UNVERIFIED"
    assert distance_state({"complete": True, "global_max_upper_m": 0.005}) == "UNVERIFIED"


def test_distance_state_complete_tight_bound_passes():
    value = {"complete": True, "global_max_upper_m": 0.001, "witness_lower_m": 0.0}
    assert distance_state(value, TOL_M) == "PASS"


def test_distance_state_global_lower_fallback_can_fail():
    assert distance_state({"global_max_lower_m": 0.004}, TOL_M) == "FAIL"


def test_region_and_reference_point_changes_change_study_identity():
    request=dict(kind='fullbody_surface_repair_v1',adoption='adopted-002',frame=0,
                 bases_um=[1000,900],recipes=RECIPES,inputs={})
    original=identity(request,{})['study_id']
    request['regions']=[dict(id='synthetic',low_m=[0,0,0],high_m=[.01,.01,.01])]
    assert identity(request,{})['study_id']!=original
    region_id=identity(request,{})['study_id']
    request['witnesses']=[dict(id='test',point_m=[0,0,.001])]
    assert identity(request,{})['study_id']!=region_id


def _passing_metrics():
    return {
        "forward": {"complete": True, "global_max_upper_m": 0.001, "witness_lower_m": 0.0},
        "reverse": {"complete": True, "global_max_upper_m": 0.001, "witness_lower_m": 0.0},
        "projection-front": {"complete": True, "relative_change_abs": 0.002},
        "topology": {"complete": True, "closed": True},
        "self-intersections": {"complete": True, "intersection_free": True},
    }


def test_gate_pass_needs_everything_and_stays_unapproved():
    result = gate(_passing_metrics(), human_parts=True)
    assert result["verdict"] == "PASS"
    assert set(result["checks"].values()) == {"PASS"}
    assert result["scientific_status"] == "UNAPPROVED"
    assert result["ranking_eligible"] is False
    assert result["human_adoption"] is None
    assert result["drag_N"] is None and result["Cd"] is None and result["CdA_m2"] is None


def test_gate_single_counterexample_fails_despite_incomplete_coverage():
    metrics = _passing_metrics()
    metrics["forward"] = {"complete": False, "witness_lower_m": 0.004}
    result = gate(metrics, human_parts=True)
    assert result["checks"]["distance_2mm"] == "FAIL"
    assert result["verdict"] == "FAIL"
    assert result["scientific_status"] == "UNAPPROVED"
    assert result["ranking_eligible"] is False


def test_gate_incomplete_distance_never_passes():
    metrics = _passing_metrics()
    metrics["reverse"] = {"complete": False, "global_max_upper_m": 0.0004}
    result = gate(metrics, human_parts=True)
    assert result["checks"]["distance_2mm"] == "UNVERIFIED"
    assert result["verdict"] == "UNVERIFIED"


def test_gate_requires_both_directions_so_hidden_faces_stay_in_scope():
    # Both directions are required. The forward direction accounts for missing
    # original faces; the reverse direction accounts for added surfaces.
    metrics = _passing_metrics()
    metrics["reverse"] = {"complete": False, "global_max_upper_m": 0.0004}
    result = gate(metrics, human_parts=True)
    assert result["verdict"] != "PASS"
    metrics["forward"] = {"complete": False, "global_max_upper_m": 0.0004}
    metrics["reverse"] = _passing_metrics()["reverse"]
    assert gate(metrics, human_parts=True)["verdict"] != "PASS"


def test_gate_requires_human_review():
    assert gate(_passing_metrics(), human_parts=None)["verdict"] == "UNVERIFIED"
    refused = gate(_passing_metrics(), human_parts=False)
    assert refused["checks"]["mandatory_parts_human_review"] == "FAIL"
    assert refused["verdict"] == "FAIL"


def test_gate_area_topology_and_intersection_conditions():
    metrics = _passing_metrics()
    metrics["projection-front"] = {"complete": True, "relative_change_abs": 0.05}
    assert gate(metrics, human_parts=True)["verdict"] == "FAIL"
    metrics = _passing_metrics()
    metrics["topology"] = {"complete": True, "closed": False}
    assert gate(metrics, human_parts=True)["verdict"] == "FAIL"
    metrics = _passing_metrics()
    metrics["self-intersections"] = {"complete": True, "intersection_free": False}
    assert gate(metrics, human_parts=True)["verdict"] == "FAIL"
    metrics = _passing_metrics()
    metrics["projection-front"] = {"complete": False}
    assert gate(metrics, human_parts=True)["verdict"] == "UNVERIFIED"


# ---------------------------------------------------------------------------
# validate / identity: pinned bases, hash/unit checks, path-independent study id
# ---------------------------------------------------------------------------

def _write_json(path, value):
    path = Path(path)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    return file_sha(path)


def _valid_repair_request(tmp_path):
    tmp_path = Path(tmp_path)
    source_value = {
        "unit": "m",
        "coordinate_system": "RF_X_FORWARD_Z_UP",
        "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
        "triangles": [[0, 1, 2]],
    }
    source_path = tmp_path / "source.json"
    source_sha = _write_json(source_path, source_value)
    manifest_path = tmp_path / "manifest.json"
    manifest_sha = _write_json(manifest_path, {"assets": [
        {"path": "unity-a/runflow_capture_f0000.snapshot.json", "sha256": source_sha},
    ]})
    inputs = {
        "source": {"path": str(source_path), "sha256": source_sha},
        "manifest": {"path": str(manifest_path), "sha256": manifest_sha},
    }
    for base in (1000, 900):
        v_path = tmp_path / f"v{base}-vertices.npy"
        f_path = tmp_path / f"v{base}-triangles.npy"
        np.save(v_path, np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32))
        np.save(f_path, np.array([[0, 1, 2]], dtype=np.int32))
        cache_path = tmp_path / f"v{base}-cache.json"
        cache_sha = _write_json(cache_path, {"output_hashes": {
            "vertices.npy": file_sha(v_path),
            "triangles.npy": file_sha(f_path),
        }})
        inputs[f"v{base}-cache"] = {"path": str(cache_path), "sha256": cache_sha}
        inputs[f"v{base}-vertices"] = {"path": str(v_path), "sha256": file_sha(v_path)}
        inputs[f"v{base}-triangles"] = {"path": str(f_path), "sha256": file_sha(f_path)}
    request = {
        "kind": "fullbody_surface_repair_v1",
        "bases_um": [1000, 900],
        "recipes": copy.deepcopy(RECIPES),
        "frame": 0,
        "adoption": "adopted-002",
        "inputs": inputs,
    }
    return request


def test_validate_accepts_synthetic_pinned_request(tmp_path):
    request = _valid_repair_request(tmp_path)
    source = validate(request)
    assert source["unit"] == "m"
    assert source["coordinate_system"] == "RF_X_FORWARD_Z_UP"


def test_validate_rejects_unknown_kind_bases_recipes_frame(tmp_path):
    request = _valid_repair_request(tmp_path)
    bad = copy.deepcopy(request)
    bad["kind"] = "something_else"
    with pytest.raises(ValueError):
        validate(bad)
    bad = copy.deepcopy(request)
    bad["bases_um"] = [1000]
    with pytest.raises(ValueError):
        validate(bad)
    bad = copy.deepcopy(request)
    bad["recipes"] = dict(copy.deepcopy(RECIPES))
    bad["recipes"]["nearest25"] = dict(bad["recipes"]["nearest25"])
    bad["recipes"]["nearest25"]["fraction"] = 0.9
    with pytest.raises(ValueError, match="recipe"):
        validate(bad)
    bad = copy.deepcopy(request)
    bad["frame"] = 1
    with pytest.raises(ValueError):
        validate(bad)


def test_validate_rejects_tampered_input_hash(tmp_path):
    request = _valid_repair_request(tmp_path)
    with open(request["inputs"]["source"]["path"], "ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(ValueError, match="hash"):
        validate(request)


def test_validate_rejects_unit_change(tmp_path):
    request = _valid_repair_request(tmp_path)
    source_path = Path(request["inputs"]["source"]["path"])
    value = json.loads(source_path.read_text(encoding="utf-8"))
    value["unit"] = "cm"
    request["inputs"]["source"]["sha256"] = _write_json(source_path, value)
    with pytest.raises(ValueError, match="Metres"):
        validate(request)


def test_validate_rejects_unadopted_source(tmp_path):
    request = _valid_repair_request(tmp_path)
    manifest_path = Path(request["inputs"]["manifest"]["path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["assets"][0]["sha256"] = "0" * 64
    request["inputs"]["manifest"]["sha256"] = _write_json(manifest_path, manifest)
    with pytest.raises(ValueError, match="adopted frame"):
        validate(request)


def test_validate_rejects_base_cache_identity_change(tmp_path):
    request = _valid_repair_request(tmp_path)
    v_path = Path(request["inputs"]["v1000-vertices"]["path"])
    np.save(v_path, np.array([[0, 0, 1], [1, 0, 1], [0, 1, 1]], dtype=np.float32))
    request["inputs"]["v1000-vertices"]["sha256"] = file_sha(v_path)
    # Cache still points at the old vertex hash, so the base identity no longer lines up.
    with pytest.raises(ValueError, match="Base cache identity"):
        validate(request)


def test_identity_ignores_paths_and_wall_time(tmp_path):
    request = _valid_repair_request(tmp_path)
    pins = {"blender": "4.2.23", "python": "synthetic-test"}
    first = identity(request, pins)
    renamed = copy.deepcopy(request)
    for key, item in renamed["inputs"].items():
        item["path"] = str(Path(tmp_path) / ("moved-" + key + ".bin"))
    second = identity(renamed, pins)
    assert first["study_id"] == second["study_id"]
    assert first["study_id"].startswith("rf-repair-")
    assert "moved-" not in json.dumps(second["config"], sort_keys=True)


def test_identity_changes_with_content_hash(tmp_path):
    request = _valid_repair_request(tmp_path)
    pins = {"blender": "4.2.23"}
    first = identity(request, pins)
    altered = copy.deepcopy(request)
    altered["inputs"]["source"]["sha256"] = "1" * 64
    assert identity(altered, pins)["study_id"] != first["study_id"]


def test_identity_pins_distance_and_area_thresholds(tmp_path):
    config = identity(_valid_repair_request(tmp_path), {"blender": "4.2.23"})["config"]
    assert config["thresholds"] == {"distance_m": 0.002, "frontal_area_relative": 0.01}
    assert config["global_cover_m"] == 0.001
    assert config["local_cover_m"] == 0.0001
    assert config["bases_um"] == [1000, 900]


# ---------------------------------------------------------------------------
# Pinned Blender fixture: solidify + bounded edits + boolean restoration
# ---------------------------------------------------------------------------

def test_pinned_blender_repair_helpers(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    blender = repo / ".tools/blender/blender-4.2.23-windows-x64/blender.exe"
    if not blender.exists():
        pytest.skip("Pinned Blender unavailable")
    out = tmp_path / "repair-fixture"
    result = subprocess.run(
        [str(blender), "--background", "--factory-startup", "--threads", "4",
         "--python-exit-code", "2",
         "--python", str(repo / "tests/blender_shape_repair.py"), "--", str(out)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "BLENDER_SHAPE_REPAIR_PASS" in result.stdout
