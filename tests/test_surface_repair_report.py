import copy
from pathlib import Path
import sys
import pytest
from runflow.shape_fullbody import write
from runflow.shape_audit import file_sha

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from finalize_surface_repair import STATES,collect


def fixture(root,measurement_reason=None):
    write(root/'request.json',dict(inputs={'source':{'sha256':'a'*64}},regions=[]))
    for name in STATES:
        (root/name).parent.mkdir(parents=True,exist_ok=True)
        write(root/name,dict(finished=True,records=[]))
    records=[]
    for suffix,reason in [('generate',None),('projection-front',measurement_reason)]:
        records.append(dict(stage='v1000-nearest25-'+suffix,returncode=0,reason=reason,
                            termination_verified=True,launched=True,elapsed_s=1.))
    write(root/'execution.json',dict(finished=True,records=records))
    write(root/'tool-pins-compare.json',{})
    for name in ['v1000','v1000-nearest25']:
        (root/name/'candidate').mkdir(parents=True)
        write(root/name/'candidate/cache.json',dict(output_hashes={'vertices.npy':'b'*64,'triangles.npy':'c'*64}))
    case=root/'v1000-nearest25'; (case/'metrics').mkdir()
    write(case/'generation.json',dict(complete=True))
    write(case/'metrics/projection-front.json',dict(complete=True,relative_change_abs=.001))
    return case


def test_finished_json_from_failed_stage_does_not_become_a_measurement(tmp_path):
    fixture(tmp_path,measurement_reason='stage timeout')
    summary=collect(tmp_path,final=True); result=summary['results']['v1000-nearest25']
    assert result['generation_complete']
    assert result['metrics']['projection-front'] is None
    assert not result['measurement_complete']
    assert result['gates']['verdict']=='UNVERIFIED'
    assert result['failures'][0]['reason']=='stage timeout'
    assert summary['human_adoption'] is None and summary['drag_N'] is None


def test_selfcheck_for_other_candidate_is_rejected(tmp_path):
    case=fixture(tmp_path)
    write(case/'metrics/self-intersections.json',dict(complete=True,intersection_free=True,
        termination_verified=True,input={'candidate_cache_sha256':'0'*64}))
    with pytest.raises(ValueError,match='different candidate'): collect(tmp_path,final=True)


def test_failed_intersection_is_an_executed_failure_and_final_requires_finished(tmp_path):
    case=fixture(tmp_path)
    write(case/'metrics/self-intersections.json',dict(complete=True,intersection_free=False,
        termination_verified=True,input={'candidate_cache_sha256':file_sha(case/'candidate/cache.json')}))
    result=collect(tmp_path,final=True)['results']['v1000-nearest25']
    assert result['gates']['checks']['self_intersections']=='FAIL'
    assert result['gates']['verdict']=='FAIL'
    write(tmp_path/STATES[-1],dict(finished=False,records=[]))
    with pytest.raises(ValueError,match='still active'): collect(tmp_path,final=True)


def test_saved_gap_reference_requires_same_region_and_fixed_plane(tmp_path):
    fixture(tmp_path)
    from runflow.shape_fullbody import read
    request=read(tmp_path/'request.json'); request['regions']=[dict(id='hair-gap',axes=[0,2])]
    prior=tmp_path/'previous-study'; old_case=prior/'v1000'; old_cache=old_case/'candidate/cache.json'
    write(old_cache,read(tmp_path/'v1000/candidate/cache.json'))
    write(prior/'request.json',dict(regions=request['regions']))
    plane=old_case/'metrics/projection-side.json'; write(plane,dict(complete=True))
    write(old_case/'metrics/hair-gap-projection.json',dict(gap_filled_fraction=.25))
    request['inputs']['v1000-cache']=dict(path=str(old_cache))
    request['presentation']={'v1000/projection-side.json':dict(sha256=file_sha(plane))}
    write(tmp_path/'request.json',request)
    result=collect(tmp_path,True)['results']['v1000']
    assert result['metrics']['hair-gap-projection']['gap_filled_fraction']==.25
    assert result['reference_metrics']['hair-gap-projection']['reused_measurement']
    write(plane,dict(complete=True,changed=True))
    with pytest.raises(ValueError,match='projection pin changed'): collect(tmp_path,True)
