import copy
import json
import math
import shutil

import pytest

from runflow.core import generate, sample, validate_manifest, canonical, digest, read, write
from runflow.contracts import SCHEMAS
from runflow.cli import main
from runflow.geometry import area, compare
from runflow.publication import public_result
from runflow.baseline import force_rows
from jsonschema import Draft202012Validator


def test_reproduction_relocation_and_order(manifest, tmp_path):
    first, result = generate(manifest, tmp_path)
    relocated = tmp_path / "relocated"
    relocated.mkdir()
    changed = copy.deepcopy(manifest)
    for i, asset in enumerate(changed["assets"]):
        shutil.copy(tmp_path / asset["path"], relocated / f"renamed-{i}.bin")
        asset["path"] = f"renamed-{i}.bin"
    changed["assets"].reverse()
    second, _ = generate(changed, relocated)
    assert canonical(first) == canonical(second)
    assert first["config_sha256"] == digest(first["config"])
    assert result["drag_N"] is None and not result["ranking_eligible"]
    assert result["scientific_status"] == "PENDING_HUMAN_REVIEW"
    changed["tools"]["capture_version"] = "test-2"
    assert generate(changed, relocated)[0]["config_sha256"] != first["config_sha256"]


def test_sampling_excludes_endpoint(manifest):
    rows = sample(manifest)["samples"]
    assert len(rows) == 16
    assert rows[0]["time_s"] == 1 and rows[-1]["time_s"] == 1.9375
    assert sum(r["weight"] for r in rows) == 1


@pytest.mark.parametrize("field,value", [("unit", "cm"), ("height_m", 0), ("height_source", "TBD")])
def test_invalid_metadata(manifest, tmp_path, field, value):
    manifest[field] = value
    with pytest.raises(ValueError):
        generate(manifest, tmp_path)


@pytest.mark.parametrize("problem", ["missing", "tampered", "outside", "duplicate", "no_motion", "reflection", "shear", "cycle"])
def test_input_fail_closed(manifest, tmp_path, problem):
    if problem == "missing":
        (tmp_path/"model.bin").unlink()
    elif problem == "tampered":
        (tmp_path/"model.bin").write_bytes(b"different")
    elif problem == "outside":
        manifest["assets"][0]["path"] = "../model.bin"
    elif problem == "duplicate":
        manifest["assets"][1]["id"] = manifest["assets"][0]["id"]
    elif problem == "no_motion":
        manifest["assets"][1]["role"] = "other"
    elif problem == "reflection":
        manifest["transform"]["reflection"] = True
    elif problem == "shear":
        manifest["transform"]["source_to_rf"][0][1] = 0.1
    else:
        manifest["gait"]["end_s"] = 1
    with pytest.raises(ValueError):
        generate(manifest, tmp_path)


def test_explicit_cfd_cannot_be_incomplete(manifest, tmp_path):
    with pytest.raises(ValueError):
        generate(manifest, tmp_path, {"speed_m_s": 20})


def test_projection_union_and_comparison(snapshot):
    assert area(snapshot) == 1
    candidate = copy.deepcopy(snapshot)
    candidate["triangles"] *= 2
    assert area(candidate) == 1  # do not double count overlapping surfaces
    assert compare(snapshot, candidate, 1.6)["execution_status"] == "PASS"
    candidate["joints"]["left_hand"][0] += 0.009
    assert compare(snapshot, candidate, 1.6)["execution_status"] == "FAIL"


@pytest.mark.parametrize("problem", ["missing_part", "wrong_time", "bad_index", "nan", "zero_area", "joint_missing", "area_difference"])
def test_bad_geometry(snapshot, problem):
    other = copy.deepcopy(snapshot)
    if problem == "missing_part":
        other["parts"].pop()
    elif problem == "wrong_time":
        other["time_s"] += 0.1
    elif problem == "bad_index":
        other["triangles"][0][0] = 99
    elif problem == "nan":
        other["vertices"][0][0] = float("nan")
    elif problem == "zero_area":
        other["vertices"] = [[0,0,0]]*4
    elif problem == "joint_missing":
        other["joints"].pop("left_hand")
    else:
        other["vertices"][1][1] = 2
        assert compare(snapshot, other, 1.6)["execution_status"] == "FAIL"
        return
    with pytest.raises(ValueError):
        compare(snapshot, other, 1.6)


def test_publication_has_no_geometry_or_private_notes(manifest, tmp_path):
    _, result = generate(manifest, tmp_path)
    result["notes"] = ["C:/private/game/model.pmx"]
    public_result(result, tmp_path/"export")
    data = (tmp_path/"export/summary.json").read_text()
    assert "private" not in data and "notes" not in data
    result["vertices"] = [[1,2,3]]
    with pytest.raises(ValueError):
        public_result(result, tmp_path/"export2")
    with pytest.raises(FileExistsError):
        public_result({k:v for k,v in result.items() if k != "vertices"}, tmp_path/"export")


def test_cli_roundtrip_and_no_overwrite(manifest, tmp_path):
    path = tmp_path/"input.json"
    write(path, manifest)
    args = ["generate", str(path), "--asset-root", str(tmp_path), "--output", str(tmp_path/"out")]
    assert main(args) == 0
    assert main(args) == 2
    assert main(["validate",str(path),"--asset-root",str(tmp_path)]) == 0


def test_json_rejects_duplicate_and_nonfinite(tmp_path):
    p = tmp_path/"bad.json"
    for data in ['{"a":1,"a":2}', '{"a":NaN}']:
        p.write_text(data)
        with pytest.raises(ValueError):
            read(p)


def test_force_parser(tmp_path):
    p = tmp_path/"forces.dat"
    p.write_text('# header\n1 ((1 2 3) (4 5 6))\n2 ((2 3 4) (5 6 7))\n')
    assert len(force_rows(p)) == 2
    p.write_text('1 ((NaN 2 3) (4 5 6))\n2 ((2 3 4) (5 6 7))\n')
    with pytest.raises(ValueError):
        force_rows(p)


def test_schemas_valid():
    for schema in SCHEMAS.values():
        Draft202012Validator.check_schema(schema)


def test_gait_repeat_and_timing_gate(manifest,snapshot,tmp_path):
    from runflow.geometry import verify_gait
    dirs=[tmp_path/name for name in ("ref","candidate","repeat")]
    for d in dirs:
        d.mkdir()
        for i in range(16):
            s=copy.deepcopy(snapshot);s["time_s"]=1+i/16
            write(d/f"frame-{i:02d}.snapshot.json",s)
    assert verify_gait(manifest,*dirs)["execution_status"]=="PASS"
    target=dirs[2]/"frame-00.snapshot.json"
    altered=read(target);altered["root_position"][0]=0.1;write(target,altered)
    assert verify_gait(manifest,*dirs)["execution_status"]=="FAIL"
    target.unlink()
    with pytest.raises(ValueError,match="exactly 16"):
        verify_gait(manifest,*dirs)


def test_baseline_reynolds_validation(tmp_path):
    from runflow.baseline import reynolds
    for dirname in ["0","system","constant"]:(tmp_path/dirname).mkdir()
    (tmp_path/"0/U").write_text('Uinlet 0.015;\n')
    (tmp_path/"system/blockMeshDict").write_text('diameter 0.001;\n')
    (tmp_path/"constant/physicalProperties").write_text('nu 1.5e-5;\n')
    assert reynolds(tmp_path)["Re"]==1
    (tmp_path/"0/U").write_text('Uinlet 0.15;\n')
    with pytest.raises(ValueError,match="Re=1"):
        reynolds(tmp_path)


def test_baseline_missing_runtime_writes_failure(tmp_path,monkeypatch):
    import runflow.baseline as b
    def unavailable(*args,**kwargs):raise FileNotFoundError("test runtime missing")
    monkeypatch.setattr(b.subprocess,"run",unavailable)
    result=b.run(tmp_path/"run")
    assert result["execution_status"]=="FAIL"
    assert read(tmp_path/"run/task-log.json")["errors"]


def test_publication_rejects_text_in_identity(manifest,tmp_path):
    _,result=generate(manifest,tmp_path)
    result["experiment_id"]="C:/private/oguri.pmx"
    with pytest.raises(ValueError):public_result(result,tmp_path/"export")


def test_whitespace_metadata_is_unresolved(manifest,tmp_path):
    manifest["height_source"]="   "
    with pytest.raises(ValueError,match="Unresolved"):
        generate(manifest,tmp_path)


def test_requested_costume_cannot_be_substituted(manifest,tmp_path):
    manifest["source"]["costume_id"]="100601"
    with pytest.raises(ValueError,match="100602"):
        generate(manifest,tmp_path)
