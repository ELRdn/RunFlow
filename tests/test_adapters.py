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
