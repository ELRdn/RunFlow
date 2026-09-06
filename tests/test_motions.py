"""Pure motion-catalog classification tests for RunFlow Phase 0.

All records use synthetic in-memory path strings. No live catalog,
game data, database files or private directories are read. Racemain
examples mirror the live path shape with placeholder markers, but they
remain synthetic strings for heuristic coverage only.
"""

import pytest

from runflow.motions import classify


def one(path, extra=None):
    record = {"path": path}
    if extra:
        record.update(extra)
    return classify([record])[0]


def test_empty_input():
    assert classify([]) == []


def test_sort_and_dedupe_full_path():
    back = chr(92)
    slash_dup = "3d/motion/synthetic/b_run01_base"
    back_dup = "3d" + back + "motion" + back + "synthetic" + back + "b_run01_base"
    records = [
        {"path": "3d/motion/synthetic/c_run01_base", "asset_hash": "second"},
        {"path": slash_dup, "asset_hash": "first"},
        {"path": back_dup, "asset_hash": "first"},
        {"path": "3d//motion/synthetic/a_run01_base/"},
        {"path": "3d/motion/other/run01_base"},
        {"path": "3d/motion/synthetic/run01_base"},
    ]
    out = classify(records)
    paths = [item["source_path"] for item in out]
    assert paths == sorted(paths)
    keep = [item for item in out if item["source_path"] == slash_dup][0]
    assert keep["asset_hash"] == "first"
    same_base = [p for p in paths if p.endswith("/run01_base")]
    assert len(same_base) == 2
    assert "3d/motion/synthetic/a_run01_base" in paths
    assert "3d/motion/other/run01_base" in paths
    assert "3d/motion/synthetic/run01_base" in paths


def test_eye_only_run_is_never_body_candidate():
    item = one("3d/motion/synthetic/eye_run01_base")
    assert item["signals"]["name_eye"] is True
    assert item["signals"]["name_run"] is True
    assert item["signals"]["name_base"] is True
    assert item["body_motion_candidate"] is False
    assert "body_motion_candidate" not in item["categories"]
    assert "name_heuristic:eye" in item["categories"]
    assert "name_heuristic:run" in item["categories"]
    ear = one("3d/motion/synthetic/ear_race01_base")
    assert ear["signals"]["name_ear"] is True
    assert ear["body_motion_candidate"] is False


def test_race_body_outside_generic():
    item = one("3d/motion/racemain/_default/anm_rac_typexx_run01_base")
    assert item["ui_generic_eligible"] is False
    assert item["ui_generic_reason"] == "no-positive-marker"
    assert item["body_motion_candidate"] is True
    assert "body_motion_candidate" in item["categories"]
    for hint in ("racemain", "default", "run", "base"):
        assert hint in item["name_heuristics"]
        assert "name_heuristic:" + hint in item["categories"]


def test_racemain_pitch_stride_body_family():
    item = one("3d/motion/racemain/body/synthetic_run02_base_pitch_stride")
    assert item["ui_generic_eligible"] is False
    assert item["body_motion_candidate"] is True
    for hint in ("racemain", "body", "run", "base", "pitch", "stride"):
        assert hint in item["name_heuristics"]
    typed = one("3d/motion/racemain/body/type01/anm_rac_type01_run02_base_pitch")
    assert typed["signals"]["has_type0"] is True
    assert typed["ui_generic_eligible"] is True
    assert typed["target"] == "unknown"
    assert typed["body_motion_candidate"] is True
    assert "pitch" in typed["name_heuristics"]


def test_overrun_is_separate_from_run():
    item = one("3d/motion/racemain/_default/anm_rac_overrun01_base")
    assert item["signals"]["name_overrun"] is True
    assert item["signals"]["name_run"] is False
    assert "overrun" in item["name_heuristics"]
    assert "run" not in item["name_heuristics"]
    assert item["body_motion_candidate"] is False
    assert "body_motion_candidate" not in item["categories"]
    mixed = one("3d/motion/synthetic/race_overrun01_base")
    assert mixed["signals"]["name_race"] is True
    assert mixed["signals"]["name_overrun"] is True
    assert mixed["body_motion_candidate"] is False


def test_target_overrides():
    assert one("3d/motion/synthetic/chara1006_run01_base")["target"] == "character:1006"
    assert one("3d/motion/synthetic/chr1006_run01_base")["target"] == "character:1006"
    assert one("3d/motion/synthetic/character1006_run01_base")["target"] == "character:1006"
    assert one("3d/motion/synthetic/card1006_run01_base")["target"] == "card-body:1006"
    assert one("3d/motion/synthetic/body1006_run01_base")["target"] == "card-body:1006"
    assert one("3d/motion/synthetic/crd1006_run01_base")["target"] == "card-body:1006"
    loose = one("3d/motion/synthetic/chara_card1006_run01_base")
    assert loose["target"] == "card-body:1006"
    both = one("3d/motion/synthetic/chara1006_card1006_run01_base")
    assert both["target"] == "character:1006"
    bare = one("3d/motion/synthetic/1006_run01_base")
    assert bare["target"] == "unknown"
    assert bare["signals"]["has_1006"] is True
    assert one("3d/motion/synthetic/run01_base")["target"] == "unknown"


def test_type_numbers_and_running_type_never_map():
    typed = one("3d/motion/racemain/body/type02/synthetic_run02_base")
    assert typed["signals"]["has_type0"] is True
    assert typed["target"] == "unknown"
    extra = one("3d/motion/synthetic/run01_base", {"race_running_type": 1})
    assert extra["target"] == "unknown"
    assert extra["body_motion_candidate"] is True


def test_ui_generic_positives():
    assert one("3d/motion/type01/synthetic_base")["ui_generic_eligible"] is True
    assert one("3d/motion/type99/synthetic_base")["ui_generic_eligible"] is True
    assert one("3d/motion/synthetic/anm_sty_run01_base")["ui_generic_eligible"] is True
    reason = one("3d/motion/type01/synthetic_base")["ui_generic_reason"]
    assert reason.startswith("positive:")


@pytest.mark.parametrize("tail", [
    "3d/motion/type01/mini_run01_base",
    "3d/motion/type01/facial_run01_base",
    "3d/motion/type01/synthetic_cam_run01_base",
    "3d/motion/type01/mirror_run01_base",
    "3d/motion/type01/synthetic_run_s",
    "3d/motion/type01/synthetic_run_e",
    "3d/motion/type01/synthetic_run_pos",
    "3d/motion/type01/synthetic_run_pose",
    "3d/motion/type01/tail/synthetic_run01_base",
    "3d/motion/type01/synthetic_prop_base",
    "3d/motion/type01/synthetic_defaultmotion_base",
])
def test_ui_generic_exclusions(tail):
    item = one(tail)
    assert item["ui_generic_eligible"] is False
    assert item["ui_generic_reason"].startswith("excluded:")


def test_default_vs_defaultmotion():
    keep = one("3d/motion/type01/_default/synthetic_run01_base")
    assert keep["ui_generic_eligible"] is True
    assert keep["signals"]["excluded_defaultmotion"] is False
    assert keep["signals"]["name_default"] is True
    blocked = one("3d/motion/type01/synthetic_defaultmotion_base")
    assert blocked["ui_generic_eligible"] is False
    assert "defaultmotion" in blocked["ui_generic_reason"]
    assert blocked["signals"]["name_default"] is False
    assert blocked["signals"]["name_base"] is True


def test_passthrough_and_aliases():
    out = classify([{"source_path": "3d/motion/synthetic/a_run01_base", "sha256": "abc", "requires": "3d/motion/synthetic/b_run01_base"}])[0]
    assert out["source_path"] == "3d/motion/synthetic/a_run01_base"
    assert out["asset_hash"] == "abc"
    assert out["prerequisites"] == ["3d/motion/synthetic/b_run01_base"]
    full = classify([{"full_path": "3d/motion/synthetic/d_run01_base", "prerequisites": ["x", "y"]}])[0]
    assert full["prerequisites"] == ["x", "y"]
    empty_hash = one("3d/motion/synthetic/e_run01_base", {"asset_hash": "   "})
    assert empty_hash["asset_hash"] is None


def test_fail_closed():
    with pytest.raises(ValueError):
        classify("not-an-iterable-record-list")
    with pytest.raises(ValueError):
        classify([{"no_path": "x"}])
    with pytest.raises(ValueError):
        classify([{"path": 123}])
    with pytest.raises(ValueError):
        classify([{"path": "   "}])
    with pytest.raises(ValueError):
        classify([{"path": "a" + chr(0) + "b"}])
    with pytest.raises(ValueError):
        classify([{"path": "3d/motion/a", "asset_hash": 123}])
    with pytest.raises(ValueError):
        classify([{"path": "3d/motion/a", "prerequisites": [123]}])
    with pytest.raises(ValueError):
        classify([{"path": "3d/motion/a", "prerequisites": {"x": 1}}])
    with pytest.raises(ValueError):
        classify(["3d/motion/a"])


def test_false_certainty_avoidance():
    item = one("3d/motion/synthetic/ambient01")
    assert item["verified"] is False
    assert item["scientific_status"] == "PENDING_HUMAN_REVIEW"
    assert item["ranking_eligible"] is False
    assert "unknown" in item["categories"]
    for key in ("motion_id", "clip_id", "motionId", "clipId", "scientific_pass"):
        assert key not in item
        assert key not in item["signals"]
    body = one("3d/motion/racemain/_default/anm_rac_typexx_run01_base")
    assert body["verified"] is False
    assert body["scientific_status"] == "PENDING_HUMAN_REVIEW"
    assert body["ranking_eligible"] is False
    assert body["target"] == "unknown"


def test_duplicate_conflicts_raise():
    with pytest.raises(ValueError):
        classify([
            {"path": "3d/motion/synthetic/dup_run01_base", "asset_hash": "aaa"},
            {"path": "3d/motion/synthetic/dup_run01_base", "asset_hash": "bbb"},
        ])
    with pytest.raises(ValueError):
        classify([
            {"path": "3d/motion/synthetic/dup2_run01_base", "prerequisites": ["x"]},
            {"path": "3d/motion/synthetic/dup2_run01_base", "prerequisites": ["y"]},
        ])
    with pytest.raises(ValueError):
        classify([
            {"path": "3d/motion/synthetic/dup3_run01_base", "asset_hash": "  aaa  "},
            {"path": "3d/motion/synthetic/dup3_run01_base", "asset_hash": "aaa", "prerequisites": ["x"]},
        ])
    with pytest.raises(ValueError):
        classify([
            {"path": "3d/motion/synthetic/order_run01_base", "prerequisites": ["x", "y"]},
            {"path": "3d/motion/synthetic/order_run01_base", "prerequisites": ["y", "x"]},
        ])


def test_identical_repeats_dedupe():
    back = chr(92)
    slash_path = "3d/motion/synthetic/ident_run01_base"
    back_path = "3d" + back + "motion" + back + "synthetic" + back + "ident_run01_base"
    out = classify([
        {"path": slash_path, "asset_hash": "  abc  ", "prerequisites": ["x"]},
        {"path": back_path, "sha256": "abc", "requires": "x"},
        {"source_path": "3d//motion/synthetic/ident_run01_base/", "asset_hash": "abc", "prerequisites": ["x"]},
    ])
    assert len(out) == 1
    assert out[0]["source_path"] == slash_path
    assert out[0]["asset_hash"] == "abc"
    assert out[0]["prerequisites"] == ["x"]


def test_malformed_duplicate_not_ignored():
    with pytest.raises(ValueError):
        classify([
            {"path": "3d/motion/synthetic/bad_run01_base"},
            {"path": "3d/motion/synthetic/bad_run01_base", "asset_hash": 123},
        ])
    with pytest.raises(ValueError):
        classify([
            {"path": "3d/motion/synthetic/bad2_run01_base"},
            {"path": "3d/motion/synthetic/bad2_run01_base", "prerequisites": [123]},
        ])
    with pytest.raises(ValueError):
        classify([
            {"path": "3d/motion/synthetic/bad3_run01_base"},
            {"path": "3d/motion/synthetic/bad3_run01_base", "asset_hash": "a" + chr(0) + "b"},
        ])
    with pytest.raises(ValueError):
        classify([
            {"path": "3d/motion/synthetic/bad4_run01_base", "asset_hash": "same"},
            {"path": "3d//motion/synthetic/bad4_run01_base/", "asset_hash": "same", "prerequisites": [123]},
        ])


def test_target_numeric_boundary():
    assert one("3d/motion/synthetic/chr1006_run01_base")["target"] == "character:1006"
    assert one("3d/motion/synthetic/chr10060_run01_base")["target"] == "unknown"
    assert one("3d/motion/synthetic/chr10060_run01_base")["signals"]["has_1006"] is True
    assert one("3d/motion/synthetic/chara10060_run01_base")["target"] == "unknown"
    assert one("3d/motion/synthetic/card1006_run01_base")["target"] == "card-body:1006"
    assert one("3d/motion/synthetic/card10060_run01_base")["target"] == "unknown"
    assert one("3d/motion/synthetic/body10060_run01_base")["target"] == "unknown"
    assert one("3d/motion/synthetic/crd1006_run01_base")["target"] == "card-body:1006"
    assert one("3d/motion/synthetic/crd10060_run01_base")["target"] == "unknown"
    assert one("3d/motion/synthetic/chr1006")["target"] == "character:1006"
    assert one("3d/motion/synthetic/body1006")["target"] == "card-body:1006"
    assert one("3d/motion/synthetic/chr10060_chr1006_base")["target"] == "character:1006"


def test_target_bare_words_no_bind():
    bare_body = one("3d/motion/synthetic/body/1006_run01_base")
    assert bare_body["target"] == "unknown"
    assert bare_body["signals"]["has_1006"] is True
    assert bare_body["signals"]["card_body_hint"] is False
    loose_chara = one("3d/motion/synthetic/chara/1006_run01_base")
    assert loose_chara["target"] == "unknown"
    assert loose_chara["signals"]["chara_hint"] is False
    assert one("3d/motion/synthetic/body_1006_run01_base")["target"] == "unknown"
    assert one("3d/motion/synthetic/chara_1006_run01_base")["target"] == "unknown"
    card_loose = one("3d/motion/synthetic/chara_card1006_run01_base")
    assert card_loose["target"] == "card-body:1006"
    assert card_loose["signals"]["chara_hint"] is False
    assert card_loose["signals"]["card_body_hint"] is True
    both = one("3d/motion/synthetic/chara1006_card1006_run01_base")
    assert both["target"] == "character:1006"
    assert both["signals"]["chara_hint"] is True
    assert both["signals"]["card_body_hint"] is True


def test_bound_target_stays_heuristic():
    item = one("3d/motion/synthetic/chr1006_run01_base")
    assert item["target"] == "character:1006"
    assert item["verified"] is False
    assert item["scientific_status"] == "PENDING_HUMAN_REVIEW"
    assert item["ranking_eligible"] is False
    assert "target:character:1006" in item["categories"]
    card = one("3d/motion/synthetic/body1006_run01_base")
    assert card["target"] == "card-body:1006"
    assert card["verified"] is False
    assert card["scientific_status"] == "PENDING_HUMAN_REVIEW"
    assert card["ranking_eligible"] is False


def test_string_prerequisite_rejects_nul():
    with pytest.raises(ValueError, match="NUL"):
        classify([{"path": "3d/motion/test", "prerequisites": "bad\x00path"}])
