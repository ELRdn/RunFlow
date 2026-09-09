from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from local_repair_manual import validate_selection,same_oriented_cycle


def fixture():
    return dict(kind='runflow_local_face_selection_v1',approval_scope='FACE_AND_BOUNDARY_SELECTION_ONLY',
        decision='APPROVED',reviewer='synthetic fixture only',source_cache_sha256='a'*64,base_cache_sha256='b'*64,
        source_face_ids=[0],base_face_ids=[1],source_boundary=[0,1,2],base_boundary=[3,4,5],
        reverse_source_winding=False,low_m=[0,0,0],high_m=[1,1,1])


def test_selection_never_infers_approval_or_science():
    value=fixture();validate_selection(value,'a'*64,'b'*64,2,2)
    for key,item in [('decision',None),('reviewer',None),('approval_scope','SCIENTIFIC_APPROVAL')]:
        bad={**value,key:item}
        with pytest.raises(ValueError):validate_selection(bad,'a'*64,'b'*64,2,2)


def test_selection_pins_indices_and_working_box():
    value=fixture()
    for key,item in [('source_cache_sha256','c'*64),('base_face_ids',[3]),('source_face_ids',[True]),
                     ('source_face_ids',[0,0]),('high_m',[0,0,0]),('reverse_source_winding',None)]:
        with pytest.raises(ValueError):validate_selection({**value,key:item},'a'*64,'b'*64,2,2)
    with pytest.raises(ValueError):validate_selection({**value,'ranking_eligible':True},'a'*64,'b'*64,2,2)


def test_boundary_rotation_keeps_winding():
    assert same_oriented_cycle([0,1,2],[1,2,0])
    assert not same_oriented_cycle([0,1,2],[0,2,1])
    assert not same_oriented_cycle([0,1,2],[0,1,4])
