import math
import pytest
from runflow.gait_cycle import nested_indices,aggregate,sampling_comparison


def rows():
    return [dict(phase_index=i,execution_status='PASS',drag_N=100+10*math.sin(2*math.pi*i/32),
        CdA_m2=(100+10*math.sin(2*math.pi*i/32))/240,source_area_m2=.5+.05*math.cos(2*math.pi*i/32),
        comparison_family_sha256='a'*64) for i in range(32)]


def test_nested_periodic_samples_exclude_duplicate_endpoint():
    assert nested_indices(16)==list(range(0,32,2))
    assert nested_indices(8)==list(range(0,32,4))
    assert nested_indices(32)[-1]==31
    result=sampling_comparison(rows())
    assert result['numerical_target_met']
    assert result['aggregates']['32']['mean_drag_N']==pytest.approx(100)
    assert result['aggregates']['32']['effective_Cd']==pytest.approx(100/240/.5)
    assert result['scientific_approval'] is None and not result['ranking_eligible']


def test_missing_or_failed_phases_do_not_produce_biased_full_cycle_mean():
    data=rows();data[1]['execution_status']='NOT_CONVERGED'
    result=sampling_comparison(data)
    assert result['aggregates']['32']['mean_CdA_m2'] is None
    assert result['aggregates']['16']['mean_CdA_m2'] is not None
    assert result['relative_CdA_differences']['16_vs_32'] is None
    assert not result['numerical_target_met']


def test_mixed_methods_duplicates_and_nonfinite_values_are_rejected():
    data=rows();data[3]['comparison_family_sha256']='b'*64
    with pytest.raises(ValueError,match='mix'):aggregate(data,32)
    with pytest.raises(ValueError,match='Duplicate'):aggregate(rows()+rows()[:1],32)
    for value in (float('nan'),float('inf'),None,True):
        data=rows();data[0]['CdA_m2']=value
        with pytest.raises(ValueError):aggregate(data,32)
