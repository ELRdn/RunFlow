import copy
from pathlib import Path
import pytest
from runflow.core import read, digest, file_hash, write
from runflow.cfd_contracts import validate, PROVISIONAL_PROTOCOL
from runflow.cfd_study import protocol_for, build_case, verify_authorization, verify_prepared_study
from runflow.publication import public_result

REPO=Path(__file__).parents[1]
SOLUTION='''solvers {p {solver GAMG; tolerance 1e-7; relTol 0.01;}}
SIMPLE {nNonOrthogonalCorrectors 0; consistent yes;}
relaxationFactors {equations {U 0.9; k 0.5; omega 0.5;}}'''


def authority():
    return dict(schema_version='phase1-study-authorization-1',scope='PHASE1_SENSITIVITY_AND_FULL_GAIT',
        actor='user',instruction='Continue Phase 1 within 24 hours',scientific_approval=None,
        ranking_eligible=False,trial_limit_s=3600,campaign_limit_s=86400)


def protocol(**kwargs):
    return protocol_for(read(REPO/'configs/cfd.phase1-provisional.json'),'a'*64,authority(),
                        purpose=kwargs.pop('purpose','advection'),advection=kwargs.pop('advection','upwind'),**kwargs)


def reference():
    return {'files':{'tutorial/system/fvSolution':SOLUTION,
        'tutorial/system/fvSchemes':'divSchemes {div(phi,U) bounded Gauss linearUpwindV grad(U); div(phi,k) bounded Gauss upwind;}\nddtSchemes {default steadyState;}',
        'tutorial/system/meshQualityDict':'// pinned quality'}}


@pytest.mark.parametrize('advection',['upwind','linearUpwindV','limitedLinearV'])
def test_only_velocity_scheme_changes_for_advection_comparison(tmp_path,advection):
    a=tmp_path/'reference';b=tmp_path/'candidate';snapshot={'vertices':[[0,0,0],[1,1,1]]}
    build_case(a,snapshot,protocol(),reference())
    design=build_case(b,snapshot,protocol(advection=advection),reference())
    for path in a.rglob('*'):
        if path.is_file() and path.name!='fvSchemes':
            assert file_hash(path)==file_hash(b/path.relative_to(a))
    assert 'div(phi,k) bounded Gauss upwind;' in (b/'system/fvSchemes').read_text()
    assert advection in design['numerics']['advection']
    assert design['numerics']['velocity_equation_relaxation']==.5


@pytest.mark.parametrize('field,value', [('speed_m_s',30),('frame',1),('ground_condition','moving'),
                                       ('schema_version','phase1-provisional-1')])
def test_study_does_not_open_unplanned_physics_or_smoke_contract(field,value):
    p=protocol();p[field]=value
    with pytest.raises(ValueError):validate('protocol',p)


@pytest.mark.parametrize('purpose,mesh,domain',[('mesh',1.25,1),('mesh',.8,1),('domain',1,1.25),('domain',1,1.5)])
def test_planned_spacing_and_domain_comparisons_preserve_gates(purpose,mesh,domain):
    original=copy.deepcopy(PROVISIONAL_PROTOCOL)
    p=protocol(purpose=purpose,mesh_scale=mesh,domain_scale=domain)
    validate('protocol',p)
    baseline=read(REPO/'configs/cfd.phase1-provisional.json')
    for name in ('limits','convergence','geometry'):assert p[name]==baseline[name]
    assert p['mesh']['background_H']==.25*mesh
    assert p['domain']['downstream_H']==15*domain
    assert PROVISIONAL_PROTOCOL==original


@pytest.mark.parametrize('purpose,mesh,domain',[('advection',.8,1),('mesh',.8,1.25),('domain',.8,1.25)])
def test_mixed_factor_comparisons_fail(purpose,mesh,domain):
    with pytest.raises(ValueError):protocol(purpose=purpose,mesh_scale=mesh,domain_scale=domain)


def test_inconsistent_declared_spacing_fails():
    p=protocol(purpose='mesh',mesh_scale=.8);p['mesh']['background_H']=.25
    with pytest.raises(ValueError,match='spacing'):validate('protocol',p)


def test_scientific_approval_and_unbounded_budget_cannot_be_invented():
    for key,value in [('scientific_approval','approved'),('campaign_limit_s',999999),('trial_limit_s',7200)]:
        a=authority();a[key]=value
        with pytest.raises(ValueError):verify_authorization(a)


def test_success_remains_excluded_from_public_output_and_failure_has_nulls(tmp_path):
    r=dict(schema_version='phase1-study-1',experiment_id='test',execution_status='PASS',
        scientific_status='UNVALIDATED_PHASE1_STUDY',ranking_eligible=False,
        geometry_qualification='PROVISIONAL_USER_AUTHORIZED',drag_N=10,Cd=1,CdA_m2=.1,
        reason='synthetic',stage='solver',evidence={})
    validate('result',r)
    with pytest.raises(ValueError):public_result(r,tmp_path/'public')
    assert not (tmp_path/'public').exists()
    r['execution_status']='NOT_CONVERGED'
    with pytest.raises(ValueError):validate('result',r)


def test_case_authorization_mutation_stops_before_execution(tmp_path):
    a=authority();p=protocol();descriptor=dict(source_snapshot_sha256='a'*64,surface_sha256='b'*64)
    config=dict(study_authorization_sha256=digest(a),protocol=p,study_source_sha256=digest(descriptor),**descriptor)
    write(tmp_path/'study-authorization.json',a);write(tmp_path/'study-source.json',descriptor)
    write(tmp_path/'runtime-evidence-hashes.json',{})
    verify_prepared_study(tmp_path,config)
    a['instruction']='Changed after preparation';write(tmp_path/'study-authorization.json',a)
    with pytest.raises(ValueError,match='authorization changed'):verify_prepared_study(tmp_path,config)
