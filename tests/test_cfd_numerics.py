import copy
from pathlib import Path

import pytest

from runflow.cfd_case import build
from runflow.cfd_numerics import solution,schemes
from runflow.core import digest,read,file_hash


SOLUTION='''solvers {p {solver GAMG; tolerance 1e-7; relTol 0.01;}}
SIMPLE {nNonOrthogonalCorrectors 0; consistent yes;}
relaxationFactors {equations {U 0.9; k 0.5; omega 0.5;}}
'''


def test_iteration_profile_does_not_change_physics_mesh_or_stopping_rules(tmp_path):
    protocol=read(Path(__file__).parents[1]/'configs/cfd.phase1-provisional.json')
    before=copy.deepcopy(protocol)
    ref={'files':{'tutorial/system/'+name:SOLUTION if name=='fvSolution' else '// fixed '+name
                  for name in ('fvSolution','fvSchemes','meshQualityDict')}}
    source={'vertices':[[0,0,0],[1,1,1]]}
    old=tmp_path/'old';new=tmp_path/'new'
    a=build(old,source,protocol,ref)
    b=build(new,source,protocol,ref,numerics='standard-simple')
    assert protocol==before
    for path in old.rglob('*'):
        if path.is_file() and path.name!='fvSolution':
            assert path.read_bytes()==(new/path.relative_to(old)).read_bytes()
    assert 'consistent no;' in (new/'system/fvSolution').read_text()
    assert 'fields { p 0.3; }' in (new/'system/fvSolution').read_text()
    assert {k:v for k,v in a.items() if k!='numerics'}=={k:v for k,v in b.items() if k!='numerics'}
    assert digest({'case':file_hash(old/'system/fvSolution')})!=digest({'case':file_hash(new/'system/fvSolution')})
    assert (old/'system/fvSolution').read_text()==SOLUTION


@pytest.mark.parametrize('bad',[SOLUTION.replace('consistent yes;','consistent no;'),SOLUTION+SOLUTION])
def test_unexpected_upstream_is_rejected(bad):
    with pytest.raises(ValueError,match='pinned'):
        solution(bad,'standard-simple')


def test_unknown_profile_cannot_create_case(tmp_path):
    with pytest.raises(ValueError,match='Unknown numerical profile'):
        build(tmp_path,{}, {}, {},numerics='loosen-gates')
    assert not list(tmp_path.iterdir())


def test_limiter_changes_only_velocity_advection():
    original='''divSchemes {div(phi,U) bounded Gauss linearUpwindV grad(U);
    div(phi,k) bounded Gauss upwind; div(phi,omega) bounded Gauss upwind;}
    ddtSchemes {default steadyState;}'''
    revised=schemes(original,'standard-simple-limited')
    assert revised.split('\n',1)[1].replace('div(phi,U) bounded Gauss limitedLinearV 1;',
        'div(phi,U) bounded Gauss linearUpwindV grad(U);')==original
    assert solution(SOLUTION,'standard-simple-limited')==solution(SOLUTION,'standard-simple')
    assert schemes(original,'standard-simple')==original
    with pytest.raises(ValueError,match='pinned'):
        schemes(revised,'standard-simple-limited')


def test_first_order_is_explicit_and_does_not_relax_other_equations():
    from runflow.cfd_numerics import description
    original='div(phi,U) bounded Gauss linearUpwindV grad(U);\ndiv(phi,k) bounded Gauss upwind;'
    changed=schemes(original,'standard-simple-upwind')
    assert changed.split('\n',1)[1]=='div(phi,U) bounded Gauss upwind;\ndiv(phi,k) bounded Gauss upwind;'
    assert 'FIRST_ORDER_UPWIND' in description('standard-simple-upwind')['spatial_accuracy_note']
    assert description('standard-simple-upwind')['convergence_thresholds_changed'] is False
    assert solution(SOLUTION,'standard-simple-upwind')==solution(SOLUTION,'standard-simple')


def test_conventional_damping_only_changes_velocity_relaxation():
    from runflow.cfd_numerics import description
    old=solution(SOLUTION,'standard-simple-upwind')
    damped=solution(SOLUTION,'standard-simple-upwind-damped')
    assert damped.replace('U 0.5;','U 0.7;')==old
    settings=description('standard-simple-upwind-damped')
    assert settings['pressure_field_relaxation']==.3
    assert settings['velocity_equation_relaxation']==.5
    assert settings['convergence_thresholds_changed'] is False
    assert settings['spatial_accuracy_note'].startswith('FIRST_ORDER_UPWIND')


def test_nonorthogonal_correction_keeps_first_initial_residual(tmp_path):
    from runflow.cfd_metrics import read_residuals
    from runflow.cfd_numerics import description
    previous=solution(SOLUTION,'standard-simple-upwind-damped')
    changed=solution(SOLUTION,'standard-simple-upwind-damped-nonorth')
    assert changed.replace('nNonOrthogonalCorrectors 1;','nNonOrthogonalCorrectors 0;')==previous
    assert description('standard-simple-upwind-damped-nonorth')['velocity_equation_relaxation']==.5
    path=tmp_path/'log'
    path.write_text('Time = 400s\nSolving for p, Initial residual = 0.001, Final residual = 1e-8\nSolving for p, Initial residual = 1e-7, Final residual = 1e-8\n')
    assert read_residuals(path)[400]['p']==.001


def test_tighter_inner_solves_do_not_change_relaxation_or_outer_gates():
    from runflow.cfd_numerics import description
    complete=SOLUTION.replace('solvers {p {solver GAMG; tolerance 1e-7; relTol 0.01;}}',
        'solvers {p {solver GAMG; tolerance 1e-7; relTol 0.01;} '+
        ' '.join(f'{f} {{solver smoothSolver; tolerance 1e-8; relTol 0.1;}}' for f in ('U','k','omega'))+'}')
    profile='standard-simple-upwind-damped-nonorth-tight'
    value=solution(complete,profile)
    assert value.count('tolerance 1e-10;')==4 and value.count('relTol 0;')==4
    info=description(profile)
    assert info['non_orthogonal_correctors']==1 and info['velocity_equation_relaxation']==.5
    assert info['pressure_field_relaxation']==.3 and not info['convergence_thresholds_changed']
    with pytest.raises(ValueError,match='four pinned'):solution(SOLUTION,profile)


def test_simplec_upwind_reuses_reference_coupling_without_pressure_relaxation():
    from runflow.cfd_numerics import description
    assert solution(SOLUTION,'motorbike-simplec-upwind')==SOLUTION
    settings=description('motorbike-simplec-upwind')
    assert settings['algorithm']=='SIMPLEC' and settings['pressure_field_relaxation'] is None
    assert settings['velocity_equation_relaxation']==.9 and settings['advection']=='bounded Gauss upwind'


def test_limited_diffusion_preserves_time_physics_and_strict_inner_solves():
    from runflow.cfd_numerics import description
    profile='standard-simple-upwind-damped-nonorth-tight-limiteddiffusion'
    original='''ddtSchemes {default steadyState;}
    divSchemes {div(phi,U) bounded Gauss linearUpwindV grad(U);}
    laplacianSchemes {default Gauss linear corrected;}
    snGradSchemes {default corrected;}'''
    changed=schemes(original,profile)
    assert changed.count('limited corrected 0.5;')==2
    assert 'default steadyState;' in changed
    info=description(profile)
    assert info['linear_tolerances']['U']==1e-10 and info['linear_relative_tolerances']['p']==0
    assert info['velocity_equation_relaxation']==.5 and not info['convergence_thresholds_changed']
    with pytest.raises(ValueError,match='pinned nonorthogonal'):
        schemes(original.replace('snGradSchemes','wrongSchemes'),profile)


def test_turbulence_damping_changes_only_equation_updates_not_model():
    from runflow.cfd_numerics import description
    complete=SOLUTION.replace('solvers {p {solver GAMG; tolerance 1e-7; relTol 0.01;}}',
        'solvers {p {solver GAMG; tolerance 1e-7; relTol 0.01;} '+
        ' '.join(f'{f} {{solver smoothSolver; tolerance 1e-8; relTol 0.1;}}' for f in ('U','k','omega'))+'}')
    base='standard-simple-upwind-damped-nonorth-tight'
    changed=solution(complete,base+'-turbdamped')
    assert changed.replace('k 0.3;','k 0.5;').replace('omega 0.3;','omega 0.5;')==solution(complete,base)
    settings=description(base+'-turbdamped')
    assert settings['turbulence_equation_relaxation']==.3
    assert settings['velocity_equation_relaxation']==.5 and settings['non_orthogonal_scheme']=='corrected'
    assert settings['linear_tolerances']['U']==1e-10 and not settings['convergence_thresholds_changed']


def test_pressure_gradient_override_preserves_velocity_force_gradient():
    from runflow.cfd_numerics import description
    original='''gradSchemes {default Gauss linear; grad(U) cellLimited Gauss linear 1;}
    divSchemes {div(phi,U) bounded Gauss linearUpwindV grad(U);}
    ddtSchemes {default steadyState;}'''
    profile='standard-simple-upwind-damped-nonorth-tight-pressurelsq'
    changed=schemes(original,profile)
    assert 'grad(p) leastSquares;' in changed and 'grad(U) cellLimited Gauss linear 1;' in changed
    assert 'default steadyState;' in changed
    info=description(profile)
    assert info['pressure_gradient']=='leastSquares' and info['turbulence_equation_relaxation']==.5
    assert info['non_orthogonal_scheme']=='corrected' and not info['convergence_thresholds_changed']
    with pytest.raises(ValueError,match='Unexpected explicit pressure gradient'):
        schemes(original.replace('default Gauss linear;','grad(p) Gauss linear;'),profile)


def test_wall_blending_changes_only_omega_wall_option_and_records_accuracy_limit(tmp_path):
    protocol=read(Path(__file__).parents[1]/'configs/cfd.phase1-provisional.json')
    ref={'files':{'tutorial/system/'+name:SOLUTION if name=='fvSolution' else '// fixed '+name
                  for name in ('fvSolution','fvSchemes','meshQualityDict')}}
    old=tmp_path/'old';new=tmp_path/'new';source={'vertices':[[0,0,0],[1,1,1]]}
    a=build(old,source,protocol,ref);b=build(new,source,protocol,ref,wall_treatment='omega-blended')
    for path in old.rglob('*'):
        if not path.is_file():continue
        raw=(new/path.relative_to(old)).read_bytes()
        if path.relative_to(old).as_posix()=='0/omega':
            assert raw.count(b'blended true; ')==1;raw=raw.replace(b'blended true; ',b'')
        assert raw==path.read_bytes()
    assert b['wall_treatment']['omega_blended'] is True and not a['wall_treatment']['omega_blended']
    assert b['wall_treatment']['accuracy_status']=='UNVALIDATED'
    assert {k:v for k,v in a.items() if k!='wall_treatment'}=={k:v for k,v in b.items() if k!='wall_treatment'}
    with pytest.raises(ValueError,match='Unknown wall treatment'):
        build(tmp_path/'invalid',source,protocol,ref,wall_treatment='remove-wall')
