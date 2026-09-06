"""JSON Schema contracts, also exportable with `runflow schemas`."""
from jsonschema import Draft202012Validator


def obj(properties, required=None):
    return {"type": "object", "properties": properties,
            "required": list(properties) if required is None else required,
            "additionalProperties": False}


TEXT = {"type": "string", "minLength": 1}
NUM = {"type": "number"}
POS = {"type": "number", "exclusiveMinimum": 0}
HASH = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
VEC = {"type": "array", "items": NUM, "minItems": 3, "maxItems": 3}
MATRIX = {"type": "array", "minItems": 4, "maxItems": 4,
          "items": {"type": "array", "items": NUM, "minItems": 4, "maxItems": 4}}
PARTS = ["head", "torso", "left_arm", "right_arm", "left_leg", "right_leg", "ears", "hair", "tail", "costume"]
JOINTS = ["head", "hip", "left_hand", "right_hand", "left_knee", "right_knee", "left_foot", "right_foot"]

ASSET = obj({"id": TEXT, "role": {"enum": ["model", "motion", "reference", "other"]},
             "path": TEXT, "sha256": HASH})
SOURCE = obj({"region": {"const": "JP"}, "platform": {"const": "Steam"},
              "game_version": TEXT, "character_id": {"const": "1006"}, "costume_id": {"const": "100602"},
              "character_name": {"const": "オグリキャップ"},
              "costume_name": {"const": "シンデレラグレイ"}, "motion_id": TEXT,
              "motion_kind": {"const": "normal_race_straight"}})
TOOLS = obj({"umaviewer_commit": {"type": "string", "pattern": "^[a-f0-9]{40}$"},
             "umaviewer_release": TEXT, "blender": TEXT, "mmd_tools": TEXT,
             "capture_version": TEXT})
TRANSFORM = obj({"source_to_rf": MATRIX, "meters_per_source_unit": POS,
                 "reflection": {"type": "boolean"}, "scale_evidence": TEXT,
                 "root_policy": {"const": "subtract_forward_x_only"}})
GAIT = obj({"start_s": {"type": "number", "minimum": 0}, "end_s": POS,
            "contact_event": TEXT, "recording_step_s": POS,
            "warmup_steps": {"type": "integer", "minimum": 0},
            "key_reduction_level": {"const": 1}, "sample_count": {"const": 16}})
MANIFEST = obj({"schema_version": {"const": "1"}, "source": SOURCE, "tools": TOOLS,
                "unit": {"const": "m"}, "coordinate_system": {"const": "RF_X_FORWARD_Z_UP"},
                "height_m": POS, "height_source": TEXT, "height_measurement": TEXT,
                "transform": TRANSFORM, "gait": GAIT,
                "assets": {"type": "array", "items": ASSET, "minItems": 2},
                "preprocessing": {"type": "array", "items": TEXT}})
SAMPLE = obj({"index": {"type": "integer", "minimum": 0}, "phase": NUM,
              "time_s": NUM, "weight": POS})
SAMPLING = obj({"schema_version": {"const": "1"}, "motion_id": TEXT, "cycle_duration_s": POS,
                "samples": {"type": "array", "items": SAMPLE, "minItems": 16, "maxItems": 16}})
CFD = obj({"inlet_direction": VEC, "speed_m_s": POS, "air_density_kg_m3": POS,
           "dynamic_viscosity_Pa_s": POS, "ground_condition": TEXT, "turbulence_model": TEXT,
           "force_patches": {"type": "array", "items": TEXT, "minItems": 1},
           "domain_policy": TEXT, "mesh_policy": TEXT, "convergence_policy": TEXT,
           "solver": {"const": "OpenFOAM Foundation 14/incompressibleFluid"}})
SNAPSHOT = obj({"schema_version": {"const": "1"}, "time_s": NUM,
                "joints": {"type": "object", "required": JOINTS, "additionalProperties": VEC},
                "parts": {"type": "array", "items": {"enum": PARTS}, "uniqueItems": True,
                          "minItems": len(PARTS)},
                "vertices": {"type": "array", "items": VEC, "minItems": 3},
                "triangles": {"type": "array", "minItems": 1, "items": {
                    "type": "array", "items": {"type": "integer", "minimum": 0}, "minItems": 3, "maxItems": 3}},
                "root_position": VEC, "unit": {"const": "m"},
                "coordinate_system": {"const": "RF_X_FORWARD_Z_UP"}})
EXPERIMENT_ID = {"type":"string", "pattern":"^rf-(baseline-)?[a-f0-9]{64}$"}
RESULT = obj({"schema_version": {"const": "1"}, "experiment_id": EXPERIMENT_ID,
              "execution_status": {"enum": ["NOT_RUN", "PASS", "FAIL", "BLOCKED"]},
              "scientific_status": {"const": "PENDING_HUMAN_REVIEW"},
              "ranking_eligible": {"const": False},
              "drag_N": {"type": ["number", "null"]}, "Cd": {"type": ["number", "null"]},
              "CdA_m2": {"type": ["number", "null"]}, "notes": {"type": "array", "items": TEXT}})
LOG = obj({"schema_version": {"const": "1"}, "task_id": TEXT, "experiment_id": TEXT,
           "agent": TEXT, "actions": {"type": "array", "items": TEXT},
           "files_changed": {"type": "array", "items": TEXT},
           "parameters_changed": {"type": "array", "items": TEXT},
           "errors": {"type": "array", "items": TEXT}, "validation_pending": {"const": True}})
SCHEMAS = {"manifest": MANIFEST, "sampling": SAMPLING, "cfd": CFD,
           "snapshot": SNAPSHOT, "result": RESULT, "log": LOG}

PORTABLE_MANIFEST = obj({**MANIFEST["properties"], "assets": {"type": "array", "minItems": 2,
    "items": obj({"id": TEXT, "role": ASSET["properties"]["role"], "sha256": HASH})}})
CONFIG = obj({"schema_version": {"const": "1"}, "generator_version": TEXT,
              "input": PORTABLE_MANIFEST, "sampling": SAMPLING,
              "cfd": {"anyOf": [CFD, {"type": "null"}]},
              "purpose": {"const": "phase0_import_validation"},
              "character_cfd_execution_allowed": {"const": False}})
SCHEMAS["experiment"] = obj({"experiment_id": TEXT, "config_sha256": HASH, "config": CONFIG})
SCHEMAS["public-summary"] = obj({k: v for k, v in RESULT["properties"].items() if k != "notes"})
SCHEMAS["baseline-config"] = obj({"solver_package": TEXT,
    "tutorial": {"const": "incompressibleFluid/cylinder"}, "Re": {"const": 1},
    "diameter_m": POS, "inlet_speed_m_s": POS, "kinematic_viscosity_m2_s": POS,
    "input_files": {"type": "array", "minItems": 1, "items": TEXT}, "runner_sha256": HASH})
SCHEMAS["force-history"] = obj({"rows": {"type": "array", "minItems": 2,
    "items": {"type": "array", "minItems": 7, "items": NUM}}, "source_sha256": HASH, "note": TEXT})
SCHEMAS["comparison"] = obj({"reference_sha256": HASH, "candidate_sha256": HASH,
    "time_s": NUM, "height_m": POS, "max_joint_error_m": {"type":"number","minimum":0},
    "joint_errors_m": {"type":"object","required":JOINTS,"additionalProperties":{"type":"number","minimum":0}},
    "reference_area_m2": POS, "candidate_area_m2": POS, "relative_area_error": {"type":"number","minimum":0},
    "execution_status": {"enum":["PASS","FAIL"]}, "scientific_status":{"const":"PENDING_HUMAN_REVIEW"},
    "ranking_eligible":{"const":False}})
SCHEMAS["gait-verification"] = obj({"schema_version":{"const":"1"},
    "comparisons":{"type":"array","minItems":16,"maxItems":16,"items":SCHEMAS["comparison"]},
    "reference_repeat_identical":{"type":"array","minItems":16,"maxItems":16,"items":{"type":"boolean"}},
    "execution_status":{"enum":["PASS","FAIL"]}, "scientific_status":{"const":"PENDING_HUMAN_REVIEW"},
    "ranking_eligible":{"const":False}, "note":TEXT})


def validate(kind, value):
    errors = sorted(Draft202012Validator(SCHEMAS[kind]).iter_errors(value), key=lambda e: str(e.path))
    if errors:
        raise ValueError("; ".join(f"{kind}:{'/'.join(map(str, e.path))}: {e.message}" for e in errors[:8]))
