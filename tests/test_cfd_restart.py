import copy
from pathlib import Path

import pytest

from runflow import cfd_restart as restart
from runflow.core import read,write,file_hash,digest
from runflow.cfd_contracts import PROVISIONAL_VERSION


def fixture(tmp_path,monkeypatch):
    monkeypatch.setattr(restart,'REPO',tmp_path)
    source=tmp_path/'private/source';target=tmp_path/'private/new'
    source.mkdir(parents=True);target.mkdir(parents=True)
    protocol=read(Path(__file__).parents[1]/'configs/cfd.phase1-provisional.json')
    pins={}
    for root in (source,target):
        write(root/'protocol.json',protocol)
        for name in ('source.snapshot.json','geometry/candidate.obj',*('case/'+n for n in restart.COMPATIBLE)):
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('synthetic '+name)
    for name in restart.COMPATIBLE:pins['case:'+name]=file_hash(source/'case'/name)
    config=dict(source_snapshot_sha256=file_hash(source/'source.snapshot.json'),source_manifest_sha256='1'*64,
        surface_sha256=file_hash(source/'geometry/candidate.obj'),protocol=protocol,frame_time_s=0,clip_phase_s=0,
        source_area_m2=1,repaired_area_m2=1,repaired_area_bounds_m2=[1,1],source_bbox=[[0,0,0],[1,1,1]],tool_hashes=pins,
        provisional_authorization_sha256='2'*64,input_receipt_sha256='3'*64,fidelity_status='DEFERRED_BY_USER_FOR_PROVISIONAL_MEASUREMENT')
    identity='rf-p1p-'+digest(config)
    write(source/'experiment.json',dict(schema_version=PROVISIONAL_VERSION,experiment_id=identity,config_sha256=digest(config),config=config))
    write(source/'state.json',dict(started_epoch=1,completed_epoch=2))
    write(source/'result.json',dict(schema_version=PROVISIONAL_VERSION,experiment_id=identity,execution_status='NOT_CONVERGED',
        scientific_status='UNVALIDATED_PROVISIONAL_GEOMETRY',geometry_qualification='PROVISIONAL_USER_AUTHORIZED',ranking_eligible=False,
        drag_N=None,Cd=None,CdA_m2=None,stage='solver',reason='synthetic',evidence={'convergence':{'metrics':{'last_iteration':500}}}))
    for stage in ('mesh','solver','fields'):
        write(source/(stage+'-worker.json'),dict(execution_status='PASS',error=None,
            commands=[dict(returncode=0,reason=None,termination_verified=True)]))
    write(source/'mesh-evidence.json',dict(cells=1,body_faces=6,min_body_cell_level=5,refinement_reached=True,wake_refinement_reached=True))
    for directory in (source/'case/constant/polyMesh',*(source/f'case/processor{rank}/constant/polyMesh' for rank in range(4))):
        directory.mkdir(parents=True);(directory/'points').write_text('synthetic unchanged mesh')
    for rank in range(4):
        directory=source/f'case/processor{rank}/500';directory.mkdir(parents=True)
        for field in restart.FIELDS:(directory/field).write_text('checkpoint '+str(rank)+' '+field)
        (directory/'uniform').mkdir();(directory/'uniform/time').write_text('timeIndex 500; value 500;')
    (source/'snappyHexMesh.log').write_text('synthetic inherited generation log')
    path=source/'case/postProcessing/forces/0/forces.dat';path.parent.mkdir(parents=True)
    path.write_text('# Time forces(pressure viscous) moments(pressure viscous)\n500 ((-10 2 3) (-2 .5 .5)) ((0 0 0) (0 0 0))\n')
    return source,target


def test_checkpoint_is_copied_exactly_without_old_clock_or_source_mutation(tmp_path,monkeypatch):
    source,target=fixture(tmp_path,monkeypatch)
    old_result=file_hash(source/'result.json');old_state=file_hash(source/'state.json')
    record=restart.copy_checkpoint(source,target)
    assert record['source_solver_iteration']==500 and record['new_start_iteration']==0
    assert record['prior_cumulative_solver_iterations']==500
    for rank in range(4):
        assert not (target/f'case/processor{rank}/0/uniform').exists()
        for field in restart.FIELDS:
            assert (target/f'case/processor{rank}/0/{field}').read_bytes()==(source/f'case/processor{rank}/500/{field}').read_bytes()
    assert restart.verify(target)==record
    assert old_result==file_hash(source/'result.json') and old_state==file_hash(source/'state.json')
    assert str(source) not in (target/'restart.json').read_text()


@pytest.mark.parametrize('change',['active','field_missing','physics_changed','worker_unterminated'])
def test_unqualified_restart_sources_are_rejected(tmp_path,monkeypatch,change):
    source,target=fixture(tmp_path,monkeypatch)
    if change=='active':write(source/'state.json',dict(started_epoch=1))
    elif change=='field_missing':(source/'case/processor2/500/phi').unlink()
    elif change=='physics_changed':(target/'case/constant/physicalProperties').write_text('different')
    else:
        worker=read(source/'solver-worker.json');worker['commands'][0]['termination_verified']=False;write(source/'solver-worker.json',worker)
    with pytest.raises(ValueError):restart.copy_checkpoint(source,target)
    assert not (target/'restart.json').exists()


def test_copied_field_tampering_and_wrong_initial_force_fail(tmp_path,monkeypatch):
    source,target=fixture(tmp_path,monkeypatch);restart.copy_checkpoint(source,target)
    field=target/'case/processor0/0/U';field.write_text('changed')
    with pytest.raises(ValueError,match='Checkpoint changed'):restart.verify(target)
    force=target/'case/postProcessing/forces/0/forces.dat';force.parent.mkdir(parents=True)
    original=(source/'case/postProcessing/forces/0/forces.dat').read_text().replace('\n500 ','\n0 ')
    force.write_text(original);assert restart.initial_force_check(target)['status']=='PASS'
    force.write_text(original.replace('-10 2 3','-11 2 3'))
    with pytest.raises(ValueError,match='initial force'):restart.initial_force_check(target)
