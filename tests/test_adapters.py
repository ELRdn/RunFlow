import importlib.util
import copy
from pathlib import Path
import pytest

path=Path(__file__).resolve().parents[1]/"integrations/blender/runflow_capture.py"
spec=importlib.util.spec_from_file_location("adapter",path)
adapter=importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


def test_forward_translation_preserves_vertical_motion():
    vertices,joints=adapter.normalize_x([[5,2,3]],{"hip":[5,2,4]},[4,1,2])
    assert vertices==[[1,2,3]]
    assert joints=={"hip":[1,2,4]}


def test_transform_scale_applied_once():
    matrix=[[.01,0,0,0],[0,.01,0,0],[0,0,.01,0],[0,0,0,1]]
    assert adapter.transform(matrix,[100,200,300])==[1,2,3]


def test_vmd_name_mismatch_cannot_pass_import():
    with pytest.raises(ValueError,match="Unbound"):
        adapter.check_vmd_bindings(["センター","左足"],["Position","Thigh_L"])
    adapter.check_vmd_bindings(["Position","Thigh_L"],["Position","Thigh_L","Head"])


def test_adapter_rejects_shape_deformation(tmp_path):
    m={"schema_version":"1","route":"obj_sequence","source_to_rf":[[1,0.1,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]],"meters_per_source_unit":1}
    with pytest.raises(ValueError,match="nonuniform"):
        adapter.validate_manifest(m,tmp_path)


def direct_manifest(tmp_path, count, version):
    obj=tmp_path/'input.obj';obj.write_text('v 0 0 0\n',encoding='utf-8')
    snapshot=tmp_path/'input.json';snapshot.write_text('{}',encoding='utf-8')
    return dict(schema_version=version,route='obj_sequence',source_to_rf=copy.deepcopy(adapter.IDENTITY),
        meters_per_source_unit=1,parts_review_reference='existing-reviewed-source',
        samples=[dict(time_s=i/32,obj=obj.name,snapshot=snapshot.name,
                      obj_sha256=adapter.sha(obj),snapshot_sha256=adapter.sha(snapshot)) for i in range(count)])


def test_dense_capture_has_separate_contract_and_checks_every_input(tmp_path):
    m=direct_manifest(tmp_path,32,'phase1-cycle-adapter-1')
    assert adapter.validate_manifest(m,tmp_path) is m
    m['samples'][-1]['snapshot_sha256']='0'*64
    with pytest.raises(ValueError,match='changed direct capture'):
        adapter.validate_manifest(m,tmp_path)


@pytest.mark.parametrize('version,count',[('1',32),('phase1-cycle-adapter-1',16)])
def test_dense_capture_does_not_relax_phase0_sample_count(tmp_path,version,count):
    with pytest.raises(ValueError,match='sample times'):
        adapter.validate_manifest(direct_manifest(tmp_path,count,version),tmp_path)


def test_dense_capture_rejects_unverified_mmd_route(tmp_path):
    m=direct_manifest(tmp_path,32,'phase1-cycle-adapter-1');m['route']='mmd_tools_pmx_vmd'
    with pytest.raises(ValueError,match='direct baked input'):
        adapter.validate_manifest(m,tmp_path)
