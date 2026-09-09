from copy import deepcopy
import pytest
from runflow.sensitivity import compare,richardson_equal_ratio


def case(name,value,status='PASS'):
    return dict(root_name=name,result_sha256='a'*64,experiment_sha256='b'*64,status=status,reason=None,
        drag_N=value*240 if value else None,CdA_m2=value,Cd=value/.5 if value else None,mesh=None,
        config=dict(protocol=dict(schema_version='1',protocol_id='test',mesh=dict(background_H=.25),
                                  domain=dict(upstream_H=5),speed_m_s=20),
                    source_snapshot_sha256='a'*64,surface_sha256='b'*64,source_area_m2=.5,tool_hashes={'binary:foamRun':'c'*64}),
        design=dict(numerics=dict(profile='baseline',advection='upwind',pressure_field_relaxation=.3),wall_treatment={'blended':False}))


def test_comparison_refuses_failed_formal_difference():
    result=compare([case('a',.36),case('b',None,'NOT_CONVERGED')],'advection',.03)
    assert result['status']=='INCOMPLETE'
    assert result['pairs'][0]['relative_CdA_difference'] is None
    assert not result['numerical_target_met'] and result['scientific_approval'] is None


@pytest.mark.parametrize('mutation',['shape','density','binary','relaxation','mesh'])
def test_comparison_cannot_hide_mixed_factors(mutation):
    a=case('a',.36);b=case('b',.361)
    if mutation=='shape':b['config']['surface_sha256']='d'*64
    elif mutation=='density':b['config']['protocol']['air_density_kg_m3']=1.3
    elif mutation=='binary':b['config']['tool_hashes']['binary:foamRun']='d'*64
    elif mutation=='relaxation':b['design']['numerics']['pressure_field_relaxation']=.2
    else:b['config']['protocol']['mesh']['background_H']=.2
    with pytest.raises(ValueError,match='mixes'):compare([a,b],'advection',.03)


def test_mesh_and_advection_comparisons_allow_only_named_factor():
    a=case('a',.36);b=case('b',.361);b['design']['numerics']['advection']='linearUpwindV'
    assert compare([a,b],'advection',.03)['numerical_target_met']
    with pytest.raises(ValueError):compare([a,b],'mesh',.03)
    b['design']['numerics']['advection']='upwind';b['config']['protocol']['mesh']['background_H']=.2
    assert compare([a,b],'mesh',.03)['numerical_target_met']


def test_gci_requires_verified_grid_family_and_monotonic_convergence():
    # phi(h) = 2 + 3 h^2, h = .1, .125, .15625.
    values=[2+3*h*h for h in (.1,.125,.15625)]
    assert richardson_equal_ratio(values,1.25)['fine_GCI_rel'] is None
    result=richardson_equal_ratio(values,1.25,systematic_refinement_verified=True)
    assert result['observed_order']==pytest.approx(2)
    assert result['extrapolated']==pytest.approx(2)
    assert richardson_equal_ratio([2,2.1,2.05],1.25,systematic_refinement_verified=True)['fine_GCI_rel'] is None
    with pytest.raises(ValueError):richardson_equal_ratio([2,float('nan'),3],1.25)


def test_pairwise_target_cannot_hide_accumulated_difference():
    result=compare([case('a',.36),case('b',.369),case('c',.378)],'advection',.03)
    assert len(result['pairs'])==3
    assert not result['numerical_target_met']
