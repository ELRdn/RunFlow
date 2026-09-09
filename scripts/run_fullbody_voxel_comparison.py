"""One authorized 12-hour study; a fresh root, fixed budgets, no automatic retry."""
import argparse
import os
from pathlib import Path
import shutil
import sys
import time
from datetime import datetime,timezone
import numpy as np
from runflow.core import digest
from runflow.shape_audit import file_sha,load_surface
from runflow.shape_fullbody import (read,write,validate_request,private_root,VOXELS,
    GENERATION_SECONDS,LIMITS,prediction,study_profile)
from runflow.shape_resources import run

REPO=Path(__file__).resolve().parents[1]
BLENDER=REPO/'.tools/blender/blender-4.2.23-windows-x64/blender.exe'
WORKER=REPO/'integrations/blender/fullbody_voxel_compare.py'


def archive_references(root,request):
    """Copy only pinned presentation records, never prior meshes or runnable code."""
    hashes={}
    for reference in request.get('reference_cases',[]):
        folder=Path(reference['folder'])
        if not folder.parts or folder.is_absolute() or '..' in folder.parts or folder.parts[0]!='references':
            raise ValueError('Reference folder must stay under references/')
        for item in reference['source_files']:
            relative=Path(item['destination'])
            allowed=relative.as_posix() in ('result.json','cache.json','metrics/views.json','metrics/render.json') or (
                len(relative.parts)==2 and relative.parts[0]=='metrics' and relative.name.endswith(('-depth.npy','-hip.png')))
            if not allowed: raise ValueError('Reference artifact not allowed')
            if file_sha(item['path'])!=item['sha256']: raise ValueError('Reference hash mismatch')
            out=root/folder/relative; out.parent.mkdir(parents=True,exist_ok=True)
            if out.exists(): raise ValueError('Duplicate reference destination')
            shutil.copyfile(item['path'],out)
            copied_sha=file_sha(out)
            if copied_sha!=item['sha256']: raise ValueError('Reference changed during copy')
            hashes[out.relative_to(root).as_posix()]=copied_sha
    write(root/'reference-artifacts.json',dict(sha256=hashes,display_only=True,new_geometry_generated=False))
    return hashes


def verify_common_preparation(root,request):
    expected=request.get('inputs',{}).get('shared-cleaned-cache')
    if expected:
        reference=read(expected['path']); current=read(root/'cleaned/cache.json')
        if current['output_hashes']!=reference['output_hashes']:
            raise ValueError('Common prepared surface differs from previous study')
        write(root/'common-input-match.json',dict(complete=True,binary_hashes_equal=True,
            prior_cache_sha256=expected['sha256'],output_hashes=current['output_hashes']))


def paused_remaining(root):
    pause=read(root/'pause-001.json')
    if not pause.get('termination_verified'): raise ValueError('Paused process termination unverified')
    started=datetime.fromisoformat(pause['original_started_utc']).timestamp()
    # Keep a conservative 10-second margin for initial hashing before started_utc was recorded.
    remaining=43200-(time.time()-started)-10
    if remaining<=0: raise ValueError('Original 12-hour deadline exhausted')
    return pause,remaining


def main():
    p=argparse.ArgumentParser(); p.add_argument('--request',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    p.add_argument('--continue-paused',action='store_true',help='Continue only the documented cleanup correction checkpoint; never rerun a remesh')
    p.add_argument('--measure-existing',action='store_true',help='Measure saved candidates after the documented resource stop; never generate geometry')
    args=p.parse_args()
    if args.continue_paused and args.measure_existing: raise ValueError('Choose one continuation checkpoint')
    continuing=args.continue_paused or args.measure_existing
    root=private_root(args.output,REPO,existing=continuing); request=read(args.request)
    voxels,generation_seconds=study_profile(request)
    if continuing and voxels!=VOXELS: raise ValueError('Historical continuation applies only to the initial profile')
    pause,remaining=paused_remaining(root) if continuing else (None,43200)
    if not args.worker:
        suffix='-measurements-001' if args.measure_existing else '-continuation-001' if args.continue_paused else '-launch'
        launch=REPO/'private/phase1-validation'/(root.name+suffix)
        launch.mkdir(parents=True,exist_ok=False)
        command=[sys.executable,str(Path(__file__).resolve()),'--request',str(args.request.resolve()),'--output',str(root),'--worker']
        if args.continue_paused: command.append('--continue-paused')
        if args.measure_existing: command.append('--measure-existing')
        print('FULLBODY_SUPERVISOR_START',str(launch),flush=True)
        result=run(command,root=root,log=launch/'controller.log',timeout=remaining,
            limits={**LIMITS,'resource_grace_s':40},cwd=REPO)
        write(launch/'execution.json',result)
        print('FULLBODY_SUPERVISOR_END',result['returncode'],result['reason'],flush=True)
        if result['returncode']!=0 or result['reason']: raise SystemExit(2)
        return
    start=time.monotonic()-(43200-remaining); deadline=start+43200
    validate_request(request)
    if continuing:
        marker='measurement-continuation-001.json' if args.measure_existing else 'continuation-001.json'
        if (root/marker).exists(): raise ValueError('This checkpoint was already continued')
        if request!=read(root/'request.json'): raise ValueError('Paused input request changed')
        for name in ('source','cleaned','v1000/candidate','v500/candidate','v250/generated'): load_surface(root/name)
        if args.measure_existing:
            stop_record=read(root/'resource-stop-001.json')
            if not stop_record.get('termination_verified') or stop_record.get('geometry_complete'):
                raise ValueError('Resource stop checkpoint is not verified')
            load_surface(root/'v250/candidate')
            if (root/'source-metrics').exists(): raise ValueError('Measurements already started')
        elif (root/'v250/candidate').exists() or (root/'v100').exists(): raise ValueError('Unexpected continuation checkpoint')
        old_state=read(root/'execution-summary.json')
        if old_state.get('finished'): raise ValueError('Cannot resume finished study')
        before='before-measurements' if args.measure_existing else 'initial'
        shutil.copyfile(root/'identity.json',root/f'identity-{before}.json')
        shutil.copyfile(root/'tool-pins.json',root/f'tool-pins-{before}.json')
        write(root/f'execution-before-{marker}',old_state)
    else:
        root.mkdir(parents=True,exist_ok=False); (root/'scratch').mkdir()
        write(root/'request.json',request)
        archive_references(root,request)
    sources=[WORKER,Path(__file__).resolve(),REPO/'scripts/fullbody_voxel_metrics.py',REPO/'scripts/fullbody_voxel_report.py',
        REPO/'integrations/blender/audit_surface_distance.py',REPO/'uv.lock']
    sources+=sorted((REPO/'src/runflow').glob('shape_*.py'))
    sources += [REPO/'src/runflow/core.py',REPO/'src/runflow/cfd_guard.py']
    pins={'blender.exe':file_sha(BLENDER),'python.exe':file_sha(sys.executable)}
    for path in sources:
        relative=path.relative_to(REPO)
        archive=root/'tool-sources'/('measurement-001' if args.measure_existing else 'amendment-001' if args.continue_paused else '')
        out=archive/relative; out.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,out); pins[relative.as_posix()]=file_sha(out)
    write(root/'tool-pins.json',pins)
    identity=dict(kind=request['kind'],adoption=request['adoption'],frame=request['frame'],
        input_hashes={k:v['sha256'] for k,v in request['inputs'].items()},regions=request['regions'],
        voxel_sizes_um=list(voxels),weld_m=1e-6,adaptivity=0,preserve_volume=False,
        global_cover_m=.001,local_cover_m=.0001,projection_grid_m=1e-9,tool_pins=pins,
        limits=LIMITS,total_processing_s=43200,generation_seconds=list(generation_seconds),
        cpu_logical_limit=24,projection_processes=8,
        preparation_seconds=900,measurement_seconds_per_case=4500,report_seconds=2700)
    # Drive roots in resource policy are operational locations, not scientific identity.
    identity['limits']={k:v for k,v in LIMITS.items() if k!='disk_free_bytes'}
    if args.continue_paused:
        verification=REPO/'private/phase1-validation/fullbody-cleanup-equivalence-001/verification.json'
        if not read(verification).get('complete'): raise ValueError('Cleanup equivalence verification missing')
        shutil.copyfile(verification,root/'cleanup-equivalence-verification.json')
        identity['processing_amendment']=dict(initial_identity=read(root/'identity-initial.json'),
            verification_sha256=file_sha(verification),reason='Spatial index and direct remap replace quadratic loops, same representatives and surface',
            initial_generation_voxels_um=[1000,500,250],initial_cleanup_voxels_um=[1000,500],
            amended_cleanup_voxels_um=[250,100],amended_generation_voxels_um=[100],remesh_repeated=False)
    if args.measure_existing:
        identity['measurement_continuation']=dict(prior_identity=read(root/'identity-before-measurements.json'),
            resource_stop_sha256=file_sha(root/'resource-stop-001.json'),no_generation=True,
            reason='Finish independent measurements after resource stop; stage guard stops payload before outer watchdog')
    study_id='rf-full-'+digest(identity); write(root/'identity.json',dict(study_id=study_id,identity=identity))
    records=[]; state=dict(study_id=study_id,started_utc=datetime.now(timezone.utc).isoformat(),
        records=records,processing_limit_s=43200,scientific_status='UNAPPROVED',ranking_eligible=False)
    if continuing:
        records=old_state['records']; state.update(records=records,started_utc=old_state['started_utc'])
    if args.continue_paused:
        samples=[read_line for line in (root/'v250-remesh.resources.jsonl').read_text().splitlines() if (read_line:=__import__('json').loads(line))]
        records.append(dict(stage='v250-interrupted-cleanup',returncode=None,reason=pause['reason'],
            elapsed_s=pause['v250_spent_s'],termination_verified=True,launched=True,
            peak_private_commit_bytes=max(s['private_commit_bytes'] for s in samples),
            peak_rss_bytes=max(s['rss_bytes'] for s in samples)))
        write(root/'continuation-001.json',dict(reason=identity['processing_amendment']['reason'],
            remaining_total_s=remaining,remaining_v250_s=5400-pause['v250_spent_s'],new_study_id=study_id,
            original_deadline_preserved=True,generated_checkpoints_reused=True))
    if args.measure_existing:
        records.append(dict(stage='v100-remesh',returncode=1,reason=stop_record['reason'],launched=True,
            elapsed_s=stop_record['elapsed_s'],peak_private_commit_bytes=stop_record['peak_private_commit_bytes'],
            peak_rss_bytes=stop_record['peak_rss_bytes'],termination_verified=True,geometry_complete=False,
            stop_evidence='resource-stop-001.json'))
        write(root/'measurement-continuation-001.json',dict(remaining_total_s=remaining,new_study_id=study_id,
            no_new_generation=True,original_deadline_preserved=True))
    env=os.environ.copy(); env.update(TEMP=str(root/'scratch'),TMP=str(root/'scratch'),
        OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',RUNFLOW_CPU_COUNT='24')
    base=[str(BLENDER),'--background','--factory-startup','--threads','24','--python-exit-code','2','--python',str(WORKER),'--','--root',str(root)]
    cpu=[sys.executable,str(REPO/'scripts/fullbody_voxel_metrics.py'),'--root',str(root)]
    def save_state():
        state['elapsed_s']=time.monotonic()-start; write(root/'execution-summary.json',state)
    def skip(label,reason,**details):
        records.append(dict(stage=label,reason=reason,launched=False,returncode=None,
            elapsed_s=0,termination_verified=True,**details)); save_state()
    def job(label,command,cap,stage_deadline=None,log_label=None):
        remaining=min(deadline,time.monotonic()+cap,stage_deadline or deadline)-time.monotonic()
        if remaining<=0:
            skip(label,'time allocation exhausted'); return False
        print('FULLBODY_JOB_START',label,flush=True)
        log_label=log_label or label
        result=run(command,root=root,log=root/(log_label+'.log'),timeout=remaining,limits=LIMITS,cwd=REPO,env=env)
        result['stage']=label; records.append(result); write(root/(log_label+'.execution.json'),result); save_state()
        print('FULLBODY_JOB_END',label,result['returncode'],result['reason'],round(result['elapsed_s'],2),flush=True)
        if not result['termination_verified']: raise RuntimeError('Study stopped: child termination unverified')
        return result['returncode']==0 and not result['reason']
    save_state()
    prepared=True if continuing else job('prepare',base+['--stage','prepare'],900,start+900)
    if prepared: verify_common_preparation(root,request)
    previous=[]; resource_block=None
    if prepared:
        for voxel,cap in ([] if args.measure_existing else zip(voxels,generation_seconds)):
            if args.continue_paused and voxel in (1000,500):
                previous.append(read(root/f'v{voxel}/generation.json')); continue
            label=f'v{voxel}-remesh'; estimate=prediction(previous,voxel)
            if resource_block:
                skip(label,'predicted resource overrun after coarser resolution stopped',basis=resource_block,prediction=estimate); continue
            if estimate and estimate['skip_reason']:
                skip(label,estimate['skip_reason'],prediction=estimate); continue
            if args.continue_paused and voxel==250:
                ok=job(label,base+['--stage','repair','--voxel-um','250'],cap-pause['v250_spent_s'],deadline-18000-2700,
                    log_label='v250-cleanup-continued-001')
            else: ok=job(label,base+['--stage','remesh','--voxel-um',str(voxel)],cap,deadline-18000-2700)
            gen=root/f'v{voxel}/generation.json'
            if gen.exists(): previous.append(read(gen))
            if not ok and any(x in (records[-1].get('reason') or '') for x in ('commit','RAM reserve','disk reserve','output size')):
                resource_block=dict(voxel_um=voxel,reason=records[-1]['reason'],
                    measured_peak_private_commit_bytes=records[-1].get('peak_private_commit_bytes',0))
        bounds=[read(root/'source/cache.json')['bbox_m']]
        for voxel in voxels:
            path=root/f'v{voxel}/candidate/cache.json'
            if path.exists(): bounds.append(read(path)['bbox_m'])
        values=np.asarray(bounds)
        shared=request['inputs'].get('shared-view-bounds')
        if shared:
            view_bounds=read(shared['path'])
            if (values[:,0].min(0)<view_bounds['low_m']).any() or (values[:,1].max(0)>view_bounds['high_m']).any():
                raise ValueError('Candidate extends outside fixed reference views')
        else: view_bounds=dict(low_m=(values[:,0].min(0)-.05).tolist(),high_m=(values[:,1].max(0)+.05).tolist())
        write(root/'view-bounds.json',view_bounds)
        source_done=False
        for voxel in voxels:
            case=f'v{voxel}'; stop=min(time.monotonic()+4500,deadline-2700)
            if not any(r['stage']==case+'-remesh' and r.get('returncode')==0 and not r.get('reason') for r in records):
                skip(case+'-measure','generation not complete'); continue
            if not source_done:
                job('source-views',base+['--stage','views','--case','source'],300,stop)
                job('source-sections',cpu+['--stage','sections','--case','source'],120,stop)
                job('source-render',base+['--stage','render','--case','source'],180,stop)
                source_done=True
            job(case+'-topology',cpu+['--stage','topology','--case',case],600,stop)
            job(case+'-views',base+['--stage','views','--case',case],600,stop)
            job(case+'-render',base+['--stage','render','--case',case],240,stop)
            job(case+'-sections',cpu+['--stage','sections','--case',case],240,stop)
            if voxel==1000: job(case+'-reference',cpu+['--stage','reference'],120,stop)
            for view in ('front','side','top'):
                job(case+'-projection-'+view,cpu+['--stage','projection','--case',case,'--view',view],900,stop)
            for direction in ('forward','reverse','local'):
                cap=min(600,max(0,stop-time.monotonic()))
                job(case+'-distance-'+direction,base+['--stage','distance','--case',case,'--direction',direction,'--timeout',str(cap)],cap,stop)
    else:
        for voxel in voxels: skip(f'v{voxel}-remesh','common preparation failed')
    # Hash checks are part of the study deadline. Formal CFD files are also pinned inputs.
    try:
        state['inputs_unchanged']=all(file_sha(item['path'])==item['sha256'] for item in request['inputs'].values())
    except OSError: state['inputs_unchanged']=False
    save_state()
    report_deadline=min(deadline,time.monotonic()+2700)
    report_ok=job('report',[sys.executable,str(REPO/'scripts/fullbody_voxel_report.py'),'--root',str(root)],2700,report_deadline)
    if report_ok:
        # Presentation is recorded separately from scientific settings. Run its
        # frozen copy so editing a report template cannot change a running job.
        presentation=root/'presentation-source/finalize_fullbody_review.py'
        presentation.parent.mkdir(exist_ok=False)
        shutil.copyfile(REPO/'scripts/finalize_fullbody_review.py',presentation)
        write(root/'presentation-code.json',dict(sha256=file_sha(presentation),
            numerical_worker_pins_unchanged=True,separate_from_scientific_settings=True))
        job('final-review',[sys.executable,str(presentation),'--root',str(root)],2700,report_deadline)
    state['finished']=True; save_state()
    # The reporter cannot hash its own final log or the controller's final state.
    ledger_path=root/'artifact-sha256.json'
    if ledger_path.exists():
        ledger=read(ledger_path)
        for path in root.rglob('*'):
            if not path.is_file() or path==ledger_path or path.is_relative_to(root/'scratch'): continue
            key=path.relative_to(root).as_posix()
            if key not in ledger or key=='execution-summary.json': ledger[key]=file_sha(path)
        write(ledger_path,ledger)
    print('FULLBODY_STUDY_FINISHED',str(root),round(state['elapsed_s'],2),flush=True)


if __name__=='__main__': main()
