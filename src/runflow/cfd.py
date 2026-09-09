"""Bounded Phase 1.0 orchestration. Production inputs remain private."""
from datetime import datetime, timezone
import math
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import time

from .core import read, write, digest, file_hash, validate_manifest
from .contracts import validate as validate_phase0, PARTS
from .cfd_contracts import validate
from . import cfd_guard

REPO=Path(__file__).resolve().parents[2]
BLENDER=REPO/'.tools/blender/blender-4.2.23-windows-x64/blender.exe'


def private(path):
    from .cfd_paths import is_private
    path=Path(path).resolve()
    if not is_private(path, REPO): raise ValueError('CFD input/output must remain private')
    return path


def remaining(root,stage,started):
    p=read(root/'protocol.json'); state=read(root/'state.json')
    elapsed=time.time()-state['started_epoch']
    stage_elapsed=time.monotonic()-started
    if stage=='report' and 'report_started_epoch' in state:
        stage_elapsed=max(stage_elapsed,time.time()-state['report_started_epoch'])
    return max(0,min(p['limits'][stage+'_s']-stage_elapsed,p['limits']['total_s']-elapsed))


def start_report(root):
    state=read(root/'state.json')
    state.setdefault('report_started_epoch',time.time())
    write(root/'state.json',state)


def result(root,status,stage,reason,evidence=None,coefficients=None):
    from .cfd_contracts import PROVISIONAL_VERSION
    provisional=read(root/'protocol.json').get('schema_version')==PROVISIONAL_VERSION
    if (root/'experiment.json').exists(): identity=read(root/'experiment.json')['experiment_id']
    else:
        inputs={name:file_hash(root/name) for name in ('protocol.json','source.snapshot.json','source-manifest.json','tool-pins.json','geometry/candidate.obj') if (root/name).exists()}
        write(root/'attempt-identity.json',dict(inputs=inputs,sha256=digest(inputs)))
        identity='rf-p1-unprepared-'+digest(inputs)
    value=dict(schema_version='phase1-1',experiment_id=identity,execution_status=status,
        scientific_status='UNVALIDATED_SMOKE',ranking_eligible=False,drag_N=None,Cd=None,CdA_m2=None,
        stage=stage,reason=reason,evidence=evidence or {})
    if provisional:
        value.update(schema_version=PROVISIONAL_VERSION,scientific_status='UNVALIDATED_PROVISIONAL_GEOMETRY',geometry_qualification='PROVISIONAL_USER_AUTHORIZED')
    if read(root/'protocol.json').get('schema_version')=='phase1-study-1':
        value.update(schema_version='phase1-study-1',scientific_status='UNVALIDATED_PHASE1_STUDY',geometry_qualification='PROVISIONAL_USER_AUTHORIZED')
    if status=='PASS' and coefficients: value.update(coefficients)
    validate('result',value); write(root/'result.json',value)
    state=read(root/'state.json'); state.update(status=status,stage=stage,updated_epoch=time.time())
    write(root/'state.json',state)
    return value


def guarded(root,command,log,timeout,input_bytes=None):
    limits=read(root/'protocol.json')['limits']
    run=cfd_guard.run(command,root=root,log=root/log,timeout=timeout,
        memory_bytes=limits['memory_bytes'],output_bytes=limits['output_bytes'],cwd=REPO,input_bytes=input_bytes)
    # Local absolute command paths belong in runtime logs, never in config identity.
    write(root/(log+'.execution.json'),run)
    if run['reason'] or run['returncode']!=0:
        raise ValueError(run['reason'] or 'command failed; inspect '+log)
    return run


def worker(root,stage,timeout,distro):
    if timeout<=0: raise ValueError('stage timeout')
    deadline=time.monotonic()+timeout
    script=REPO/'scripts/cfd_worker.py'
    if os.name=='nt':
        def linux(path):
            return subprocess.check_output(['wsl','-d',distro,'--','wslpath','-a',path.as_posix()],text=True,timeout=20).strip()
        command=['wsl','-d',distro,'--','bash','-s','--',
                 linux(script),'--root',linux(root),'--stage',stage,'--timeout','0']
    else:
        command=['bash','-s','--',str(script),
                 '--root',str(root),'--stage',stage,'--timeout','0']
    budget=deadline-time.monotonic()-10  # include WSL path conversion and termination grace
    if budget<=0: raise ValueError('stage timeout during WSL startup')
    command[-1]=str(budget)
    # Linux owns CFD termination; outer watchdog allows time to kill and reap ranks.
    try:
        guarded(root,command,stage+'-launcher.log',budget+8,
            input_bytes=b'set -e\nsource /opt/openfoam14/etc/bashrc\nexec python3 "$@"\n')
    except ValueError:
        path=root/(stage+'-worker.json')
        if path.exists() and read(path).get('error'): raise ValueError(read(path)['error'])
        raise
    record=read(root/(stage+'-worker.json'))
    if record['execution_status']!='PASS': raise ValueError(record['error'])
    return record


def prepare(manifest_path,asset_root,protocol_path,output,frame=0,distro='Ubuntu'):
    began=time.time(); started=time.monotonic()
    root=private(output); asset_root=private(asset_root)
    if root.exists(): raise ValueError('Fresh CFD output required; no automatic retry')
    p=read(protocol_path); validate('protocol',p)
    if p['schema_version']!='1':raise ValueError('Saved provisional surfaces require prepare-provisional')
    if frame!=p['frame']: raise ValueError('Phase 1.0 authorizes frame 0 only')
    m=validate_manifest(read(manifest_path),asset_root)
    accepted=read(Path(manifest_path).parent/'accepted-verification.json')
    if accepted['execution_status']!='PASS' or accepted['manifest_sha256']!=file_hash(manifest_path):
        raise ValueError('Accepted intake evidence mismatch')
    source=asset_root/'unity-a/runflow_capture_f0000.snapshot.json'
    expected=[a['sha256'] for a in m['assets'] if a['path']==source.relative_to(asset_root).as_posix()]
    if expected!=[file_hash(source)]: raise ValueError('Source frame hash mismatch')
    snapshot=read(source); validate_phase0('snapshot',snapshot)
    if snapshot['parts']!=PARTS and set(snapshot['parts'])!=set(PARTS): raise ValueError('Required source parts missing')
    if not math.isclose(snapshot['time_s'],m['gait']['start_s'],abs_tol=1e-9,rel_tol=0): raise ValueError('Wrong adopted frame time')
    root.mkdir(parents=True); write(root/'protocol.json',p)
    write(root/'state.json',dict(started_epoch=began,started_utc=datetime.fromtimestamp(began,timezone.utc).isoformat(),status='PREPARING',stage='geometry',distro=distro))
    evidence={}
    try:
        shutil.copyfile(source,root/'source.snapshot.json')
        shutil.copyfile(manifest_path,root/'source-manifest.json')
        pins={}
        for path in [BLENDER,REPO/'scripts/cfd_worker.py',REPO/'scripts/cfd_surface_io.py',REPO/'scripts/cfd_area.py',
                     REPO/'scripts/cfd_report.py',REPO/'integrations/blender/prepare_cfd_surface.py',
                     REPO/'uv.lock',*sorted((REPO/'src/runflow').glob('cfd*.py'))]:
            pins['repo:'+path.relative_to(REPO).as_posix()]=file_hash(path)
        write(root/'tool-pins.json',pins)
        # Retain the exact processing sources even when geometry blocks the trial.
        for key in pins:
            relative=Path(key[5:])
            if relative.suffix.lower()=='.exe': continue
            archived=root/'tool-sources'/relative
            archived.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(REPO/relative,archived)
        (root/'geometry').mkdir()
        request=dict(source=str(root/'source.snapshot.json'),source_sha256=file_hash(source),
            output=str(root/'geometry'),geometry=p['geometry'],timeout_s=remaining(root,'geometry',started))
        write(root/'geometry-request.json',request)
        command=[str(BLENDER),'--background','--factory-startup','--threads','4','--python-exit-code','2',
            '--python',str(REPO/'integrations/blender/prepare_cfd_surface.py'),'--','--request',str(root/'geometry-request.json')]
        evidence['blender']=guarded(root,command,'blender.log',remaining(root,'geometry',started))
        geometry=read(root/'geometry/geometry.json'); evidence['geometry']=geometry
        if not geometry['candidate_topology']['closed'] or not geometry['distance_passed']:
            return result(root,'BLOCKED','geometry','CFD surface closure/distance gate failed',evidence)
        # Run expensive projected-area unions in a guarded subprocess, too.
        guarded(root,[sys.executable,str(REPO/'scripts/cfd_area.py'),'--root',str(root)],'area.log',remaining(root,'geometry',started))
        areas=read(root/'areas.json'); evidence['areas']=areas
        if areas['relative_error']>p['geometry']['max_area_relative']:
            return result(root,'BLOCKED','geometry','Projected area difference exceeds 1%',evidence)
        worker(root,'surface',remaining(root,'geometry',started),distro)
        worker(root,'reference',remaining(root,'geometry',started),distro)
        from .cfd_case import build
        case=root/'case'; (case/'constant/geometry').mkdir(parents=True,exist_ok=True)
        shutil.copyfile(root/'geometry/candidate.obj',case/'constant/geometry/oguri.obj')
        upstream=read(root/'upstream.json'); mesh=build(case,snapshot,p,upstream)
        write(root/'case-design.json',mesh)
        tools=dict(pins)
        tools.update({'upstream:'+k:v for k,v in upstream['hashes'].items()})
        tools.update({'binary:'+k:v['sha256'] for k,v in upstream['binaries'].items()})
        tools.update({'case:'+path.relative_to(case).as_posix():file_hash(path) for path in case.rglob('*') if path.is_file()})
        config=dict(source_snapshot_sha256=file_hash(source),source_manifest_sha256=file_hash(manifest_path),
            surface_sha256=file_hash(root/'geometry/candidate.obj'),protocol=p,frame_time_s=snapshot['time_s'],
            clip_phase_s=.5894131075056082,source_area_m2=areas['source_area_m2'],repaired_area_m2=areas['candidate_area_m2'],
            source_bbox=mesh['source_bbox'],tool_hashes=tools)
        sha=digest(config); experiment=dict(schema_version='phase1-1',experiment_id='rf-p1-'+sha,config_sha256=sha,config=config)
        validate('experiment',experiment); write(root/'experiment.json',experiment)
        evidence['elapsed_s']=time.monotonic()-started
        if remaining(root,'geometry',started)<=0: raise ValueError('stage timeout')
        return result(root,'PREPARED','geometry','Geometry gates passed; CFD not executed',evidence)
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:
        return result(root,'TIMEOUT' if 'timeout' in str(exc) else 'FAIL','geometry',str(exc),evidence)


def verify_prepared(root):
    exp=read(root/'experiment.json'); validate('experiment',exp)
    config=exp['config']
    from .cfd_contracts import PROVISIONAL_VERSION
    provisional=exp['schema_version']==PROVISIONAL_VERSION
    study=exp['schema_version']=='phase1-study-1'
    prefix='rf-p1s-' if study else ('rf-p1p-' if provisional else 'rf-p1-')
    if digest(config)!=exp['config_sha256'] or exp['experiment_id']!=prefix+exp['config_sha256']: raise ValueError('Experiment identity mismatch')
    if provisional:
        from .cfd_provisional import verify_authorization,receipt_identity
        receipt=read(root/'provisional-receipt.json')
        if receipt_identity(receipt)!=config['input_receipt_sha256'] or digest(receipt['authorization'])!=config['provisional_authorization_sha256']:
            raise ValueError('Provisional authorization or receipt changed')
        verify_authorization(receipt)
        if receipt['source_snapshot_sha256']!=config['source_snapshot_sha256']:
            raise ValueError('Provisional authorization source does not match experiment')
        if (root/'geometry/geometry.json').exists():
            if read(root/'geometry/geometry.json')['input_cache_sha256']!=receipt['candidate_cache_sha256']:
                raise ValueError('Provisional authorization candidate does not match prepared surface')
        if (root/'runtime-evidence-hashes.json').exists():
            for name,sha in read(root/'runtime-evidence-hashes.json').items():
                path=(root/name).resolve()
                if not path.is_relative_to(root.resolve()) or file_hash(path)!=sha:
                    raise ValueError('Runtime evidence changed: '+name)
    if study:
        from .cfd_study import verify_prepared_study
        verify_prepared_study(root,config)
    if read(root/'protocol.json')!=config['protocol']: raise ValueError('Protocol changed after preparation')
    if file_hash(root/'source-manifest.json')!=config['source_manifest_sha256']: raise ValueError('Source manifest changed after preparation')
    if file_hash(root/'source.snapshot.json')!=config['source_snapshot_sha256'] or file_hash(root/'geometry/candidate.obj')!=config['surface_sha256']:
        raise ValueError('Geometry changed after preparation')
    for key,sha in config['tool_hashes'].items():
        if key.startswith('repo:'): path=REPO/key[5:]
        elif key.startswith('run:'):path=root/key[4:]
        elif key.startswith('case:'): path=root/'case'/key[5:]
        elif key.startswith('upstream:'):
            if read(root/'upstream.json')['hashes'][key[9:]]!=sha: raise ValueError('Upstream archive changed')
            continue
        elif key.startswith('binary:'):
            if read(root/'upstream.json')['binaries'][key[7:]]['sha256']!=sha: raise ValueError('Binary archive changed')
            continue
        else: continue
        if file_hash(path)!=sha: raise ValueError('Prepared input changed: '+key)
    return exp


def collect_histories(root):
    """Keep available diagnostics on failed runs without awarding coefficients."""
    from .cfd_metrics import read_forces,read_residuals
    warnings=[]
    files=list((root/'case/postProcessing/forces').rglob('forces.dat'))
    if len(files)==1:
        try: write(root/'force-history.json',read_forces(files[0]))
        except (ValueError,OSError) as exc: warnings.append('Force trace: '+str(exc))
    if (root/'foamRun.log').exists():
        try: write(root/'residual-history.json',read_residuals(root/'foamRun.log'))
        except (ValueError,OSError) as exc: warnings.append('Residual trace: '+str(exc))
    return warnings


def run(output):
    root=private(output); state=read(root/'state.json')
    if state['status']!='PREPARED': raise ValueError('Only a fresh PREPARED case may run')
    exp=verify_prepared(root); protocol=exp['config']['protocol']; evidence={}
    stage='mesh'; started=time.monotonic()
    result(root,'BLOCKED','mesh','Execution in progress; not a successful result')
    try:
        evidence['mesh']=worker(root,'mesh',remaining(root,stage,started),state['distro'])
        stage='solver'; started=time.monotonic()
        evidence['solver']=worker(root,'solver',remaining(root,stage,started),state['distro'])
        from .cfd_metrics import read_forces,read_residuals,assess,coefficients
        files=list((root/'case/postProcessing/forces').rglob('forces.dat'))
        if len(files)!=1: raise ValueError('Force history missing/ambiguous')
        forces=read_forces(files[0]); residuals=read_residuals(root/'foamRun.log')
        # Worker emits the same independent inlet/outlet sums used for its live gate.
        flux=read(root/'flux-history.json')
        assessment=assess(forces,residuals,flux); evidence['convergence']=assessment
        write(root/'force-history.json',forces); write(root/'residual-history.json',residuals)
        with (root/'foamRun.log').open('rb') as log:
            log.seek(max(0,log.seek(0,2)-8192)); tail=log.read().decode('utf-8','replace')
        if not re.search(r'(?m)^\s*End\s*$',tail): raise ValueError('Solver normal completion missing')
        status='PASS' if assessment['converged'] else 'NOT_CONVERGED'
        coeff=coefficients(assessment['window_mean_drag_N'],protocol['air_density_kg_m3'],protocol['speed_m_s'],exp['config']['source_area_m2']) if status=='PASS' else None
        stage='report'; started=time.monotonic(); start_report(root)
        evidence['fields']=worker(root,'fields',remaining(root,stage,started),state['distro'])
        return result(root,status,'solver','All smoke convergence gates passed' if status=='PASS' else '; '.join(assessment['reasons']),evidence,coeff)
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:
        evidence['diagnostic_warnings']=collect_histories(root)
        return result(root,'TIMEOUT' if 'timeout' in str(exc) else 'FAIL',stage,str(exc),evidence)


def report(output):
    root=private(output)
    start_report(root)
    started=time.monotonic(); timeout=remaining(root,'report',started)
    if timeout<=0:
        write(root/'report-unavailable.json',dict(reason='total execution budget exhausted'))
        previous=read(root/'result.json')
        return result(root,'TIMEOUT','report','report/total execution budget exhausted',dict(prior_result=previous))
    try:
        guarded(root,[sys.executable,str(REPO/'scripts/cfd_report.py'),'--root',str(root)],'report.log',timeout)
    except (OSError,ValueError,RuntimeError) as exc:
        previous=read(root/'result.json')
        return result(root,'TIMEOUT' if 'timeout' in str(exc) else 'FAIL','report',str(exc),dict(prior_result=previous))
    state=read(root/'state.json'); state['completed_epoch']=time.time(); write(root/'state.json',state)
    # Include the report subprocess in the machine-readable resource accounting.
    from .cfd_report import _collect_resources,_build_summary
    metadata=read(root/'report/report.json'); resources=_collect_resources(root)
    metadata.update(resources=resources,summary=_build_summary(root,resources)); write(root/'report/report.json',metadata)
    return read(root/'result.json')
