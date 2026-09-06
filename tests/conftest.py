import copy
import hashlib
import pytest

from runflow.contracts import JOINTS, PARTS


@pytest.fixture
def manifest(tmp_path):
    assets = []
    for role in ("model", "motion"):
        # Original synthetic bytes, not game assets. Metadata exercises target checks only.
        data = ("RUNFLOW_SYNTHETIC_" + role).encode()
        (tmp_path / (role + ".bin")).write_bytes(data)
        assets.append({"id": "synthetic-"+role, "role": role, "path": role+".bin",
                       "sha256": hashlib.sha256(data).hexdigest()})
    return {"schema_version": "1", "source": {"region": "JP", "platform": "Steam", "game_version": "synthetic-test",
            "character_id": "1006", "costume_id": "100602", "character_name": "オグリキャップ",
            "costume_name": "シンデレラグレイ", "motion_id": "synthetic-cycle", "motion_kind": "normal_race_straight"},
            "tools": {"umaviewer_commit": "d50b28379337b507751a7df705a10afeab2c37ce", "umaviewer_release": "synthetic",
                      "blender": "4.2.synthetic", "mmd_tools": "4.synthetic", "capture_version": "test-1"},
            "unit": "m", "coordinate_system": "RF_X_FORWARD_Z_UP", "height_m": 1.6,
            "height_source": "synthetic fixture", "height_measurement": "synthetic head to sole",
            "transform": {"source_to_rf": [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]],
                          "meters_per_source_unit": 1, "reflection": False, "scale_evidence": "synthetic meter cube",
                          "root_policy": "subtract_forward_x_only"},
            "gait": {"start_s": 1, "end_s": 2, "contact_event": "synthetic left contact", "recording_step_s": 1/60,
                     "warmup_steps": 60, "key_reduction_level": 1, "sample_count": 16},
            "assets": assets, "preprocessing": []}


@pytest.fixture
def snapshot():
    return {"schema_version": "1", "time_s": 1, "joints": {j:[0,0,1] for j in JOINTS}, "parts": PARTS.copy(),
            "vertices": [[0,0,0],[0,1,0],[0,1,1],[0,0,1]], "triangles": [[0,1,2],[0,2,3]],
            "root_position": [0,0,0], "unit": "m", "coordinate_system": "RF_X_FORWARD_Z_UP"}
