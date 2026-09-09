"""Hash-bound reuse of a terminated provisional mesh and solution as an initial guess.

The verifier is standard-library only so it also runs in the pinned WSL worker.
Old runtime clocks are deliberately not copied into the new time-zero directory.
"""
import hashlib
import json
from pathlib import Path
import shutil

REPO=Path(__file__).resolve().parents[2]
FIELDS=('U','p','k','omega','nut','phi')
COMPATIBLE=('system/blockMeshDict','system/snappyHexMeshDict','system/surfaceFeaturesDict',
    'system/decomposeParDict','system/meshQualityDict','constant/geometry/oguri.obj',
    'constant/physicalProperties','constant/momentumTransport',
    *('0/'+name for name in ('U','p','k','omega','nut')))


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def private(path):
    path=Path(path).resolve()
    if not path.is_relative_to(REPO/'private'):raise ValueError('Restart data must remain private')
    return path


def verify(root):
    root=Path(root).resolve();record=read(root/'restart.json');runtime=read(root/'restart-runtime.json')
    if record.get('schema_version')!='cfd-checkpoint-initialization-1' or record.get('new_start_iteration')!=0:
        raise ValueError('Invalid restart record')
    if record.get('source_solver_iteration',-1)<300:raise ValueError('Invalid checkpoint iteration')
    required={f'processor{rank}/0/{name}' for rank in range(4) for name in FIELDS}
    if not required.issubset(record['files']):raise ValueError('Incomplete checkpoint fields')
    for relative,item in record['files'].items():
        path=(root/'case'/relative).resolve()
        if not path.is_relative_to(root/'case') or path.is_symlink() or not path.is_file():
            raise ValueError('Invalid checkpoint path')
        if path.stat().st_size!=item['bytes'] or sha(path)!=item['sha256']:
            raise ValueError('Checkpoint changed: '+relative)
    if sha(root/'snappyHexMesh.log')!=runtime['inherited_snappy_log_sha256']:
        raise ValueError('Inherited mesh generation record changed')
    return record


def copy_checkpoint(source,root):
    from .core import digest,write
    from .cfd_contracts import validate,PROVISIONAL_VERSION
    source=private(source);root=private(root)
    if source==root or (root/'restart.json').exists():raise ValueError('Fresh restart destination required')
    state=read(source/'state.json');result=read(source/'result.json');experiment=read(source/'experiment.json')
    validate('result',result);validate('experiment',experiment)
    if result['execution_status']!='NOT_CONVERGED' or state.get('completed_epoch',0)<=state['started_epoch']:
        raise ValueError('Only a completed unconverged source may initialize this retry')
    config=experiment['config']
    if experiment['schema_version']!=PROVISIONAL_VERSION or digest(config)!=experiment['config_sha256']:
        raise ValueError('Source experiment identity mismatch')
    if result['experiment_id']!=experiment['experiment_id'] or experiment['experiment_id']!='rf-p1p-'+experiment['config_sha256']:
        raise ValueError('Source result identity mismatch')
    for stage in ('mesh','solver','fields'):
        worker=read(source/(stage+'-worker.json'))
        if worker['execution_status']!='PASS' or not worker['commands'] or any(
            c.get('returncode')!=0 or c.get('reason') or c.get('termination_verified') is not True for c in worker['commands']):
            raise ValueError('Source processes did not complete cleanly: '+stage)
    if read(root/'protocol.json')!=config['protocol']:
        raise ValueError('Restart cannot change physical protocol or gates')
    for name,key in [('source.snapshot.json','source_snapshot_sha256'),('geometry/candidate.obj','surface_sha256')]:
        if sha(root/name)!=config[key] or sha(source/name)!=config[key]:raise ValueError('Restart source geometry differs')
    for name in COMPATIBLE:
        expected=config['tool_hashes'].get('case:'+name)
        if expected is None or sha(source/'case'/name)!=expected or sha(root/'case'/name)!=expected:
            raise ValueError('Restart mesh/physics input differs: '+name)
    mesh=read(source/'mesh-evidence.json')
    if not mesh['refinement_reached'] or not mesh['wake_refinement_reached'] or mesh['cells']>1000000:
        raise ValueError('Source mesh is not qualified')
    iteration=result['evidence']['convergence']['metrics']['last_iteration']
    if int(iteration)!=iteration or not 300<=iteration<=2000:raise ValueError('Invalid source iteration')
    iteration=int(iteration);files={}
    for directory in (source/'case/constant/polyMesh',*(source/f'case/processor{r}/constant/polyMesh' for r in range(4))):
        if not directory.is_dir():raise ValueError('Source mesh partition missing')
        for path in sorted(directory.rglob('*')):
            if path.is_file():files[path.relative_to(source/'case').as_posix()]=path
    for rank in range(4):
        for field in FIELDS:
            path=source/f'case/processor{rank}/{iteration}/{field}'
            if not path.is_file():raise ValueError('Final checkpoint field missing: '+str(path))
            files[f'processor{rank}/0/{field}']=path
    if any((root/f'case/processor{rank}').exists() for rank in range(4)):
        raise ValueError('Destination already has a decomposition')
    ledger={}
    for relative,path in files.items():
        if path.is_symlink() or not path.resolve().is_relative_to(source/'case'):
            raise ValueError('Source checkpoint path escapes case')
        target=root/'case'/relative;target.parent.mkdir(parents=True,exist_ok=True)
        checksum=sha(path);shutil.copyfile(path,target)
        if sha(target)!=checksum or sha(path)!=checksum:raise ValueError('Checkpoint changed during copy')
        ledger[relative]=dict(sha256=checksum,bytes=target.stat().st_size,
            source_relative_path=path.relative_to(source/'case').as_posix())
    previous=read(source/'restart.json') if (source/'restart.json').exists() else {}
    record=dict(schema_version='cfd-checkpoint-initialization-1',purpose='INITIAL_GUESS_ONLY',
        source_experiment_id=experiment['experiment_id'],source_solver_iteration=iteration,new_start_iteration=0,
        prior_cumulative_solver_iterations=previous.get('prior_cumulative_solver_iterations',0)+iteration,
        files=ledger,source_mesh_evidence=mesh,geometry_changed=False,mesh_regenerated=False,
        runtime_clock_copied=False,convergence_gates_changed=False)
    from .cfd_metrics import read_forces
    forcepaths=list((source/'case/postProcessing/forces').rglob('forces.dat'))
    if len(forcepaths)!=1:raise ValueError('Source force history is ambiguous')
    last_force=read_forces(forcepaths[0])[-1]
    if last_force['iteration']!=iteration:raise ValueError('Checkpoint and force iteration differ')
    record['expected_initial_total_force_N']=last_force['total']
    shutil.copyfile(source/'snappyHexMesh.log',root/'snappyHexMesh.log')
    write(root/'restart.json',record)
    write(root/'restart-runtime.json',dict(source_root=str(source),
        source_result_sha256=sha(source/'result.json'),source_state_sha256=sha(source/'state.json'),
        inherited_snappy_log_sha256=sha(root/'snappyHexMesh.log'),mesh_log_is_inherited=True,
        source_fields_first_sealed_at_copy=True))
    verify(root)
    return record


def initial_force_check(root):
    from .cfd_metrics import read_forces
    root=Path(root);record=read(root/'restart.json')
    paths=list((root/'case/postProcessing/forces').rglob('forces.dat'))
    if len(paths)!=1:raise ValueError('Restart force history missing')
    first=read_forces(paths[0])[0]
    if first['iteration']!=0:raise ValueError('Restart did not reset the iteration clock')
    expected=record['expected_initial_total_force_N']
    error=max(abs(x-y) for x,y in zip(expected,first['total']))
    limit=max(1e-5,max(abs(x) for x in expected)*1e-5)
    if error>limit:raise ValueError('Restart initial force differs from source checkpoint')
    return dict(status='PASS',max_component_error_N=error,tolerance_N=limit,
        source_iteration=record['source_solver_iteration'],new_iteration=0)
