import pytest
from runflow.local_repair_contract import SETTINGS,validate_settings,remaining_budget,configuration_id,candidate_verdict

@pytest.mark.parametrize('key,value',[('frame',False),('distance_m',.003),('numeric_cleanup_m',float('nan')),('max_candidates',25),('max_candidates',True),('ranking_eligible',True),('human_adoption','YES'),('voxel_remesh_passes',1),('path','C:/private')])
def test_reject_changed_scope(key,value):
    with pytest.raises(ValueError): validate_settings({**SETTINGS,key:value})

def test_cumulative_stage_and_total_budget():
    assert remaining_budget([dict(stage='diagnosis',elapsed_s=7100)],'diagnosis')==100
    assert remaining_budget([dict(stage='repair',elapsed_s=18000)],'repair')==0
    assert remaining_budget([dict(stage='repair',elapsed_s=43200)],'report')==0
    with pytest.raises(ValueError): remaining_budget([dict(stage='repair',elapsed_s=float('nan'))],'repair')

def test_identity_and_hash_validation():
    assert configuration_id(SETTINGS,{'a':'a'*64},{'b':'b'*64})==configuration_id(dict(reversed(list(SETTINGS.items()))),{'a':'a'*64},{'b':'b'*64})
    with pytest.raises(ValueError): configuration_id(SETTINGS,{'a':'broken'},{'b':'b'*64})

def test_unmeasured_and_human_review_are_not_pass():
    checks=dict.fromkeys(['distance','area','topology','intersection','outside_region'],'PASS')
    assert candidate_verdict(checks)['verdict']=='UNVERIFIED'
    assert candidate_verdict(checks,True)['verdict']=='PASS'
    assert candidate_verdict({**checks,'distance':'FAIL'},True)['verdict']=='FAIL'
    assert candidate_verdict({},True)['verdict']=='UNVERIFIED'
    assert candidate_verdict(checks,True)['drag_N'] is None
