"""Finish unstarted metrics after the documented HIP stop; no stage is retried."""
import argparse
from datetime import datetime,timezone
import os
from pathlib import Path
import shutil
import sys
import time
import psutil
from runflow.core import digest
from runflow.shape_audit import file_sha,load_surface
from runflow.shape_fullbody import read,write,private_root,LIMITS
from runflow.shape_resources import run

REPO=Path(__file__).resolve().parents[1]
BLENDER=REPO/'.tools/blender/blender-4.2.23-windows-x64/blender.exe'
JOBS=('sections','projection-front','projection-side','projection-top',
      'distance-forward','distance-reverse','distance-local')


def deadlines(root):
    pause=read(root/'pause-001.json')
    total=datetime.fromisoformat(pause['original_started_utc']).timestamp()+43200-10
    first=read(root/'v250-topology.execution.json')
    # Use process creation (minus startup margin) to retain the original 75-minute
    # measurement window, including the failed render and the inspection pause.
    case=min(p['created_at'] for p in first['owned_processes'])+4500-10
    return total,case


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args(); root=private_root(args.root,REPO,existing=True)
    total_deadline,case_deadline=deadlines(root)
    if time.time()>=total_deadline: raise ValueError('Original study deadline exhausted')
    launch=REPO/'private/phase1-validation'/(root.name+'-finish-metrics-001')
    if not args.worker:
        launch.mkdir(exist_ok=False)
        result=run([sys.executable,str(Path(__file__).resolve()),'--root',str(root),'--worker'],
            root=root,log=launch/'controller.log',timeout=total_deadline-time.time(),
            limits={**LIMITS,'resource_grace_s':40},cwd=REPO)
        write(launch/'execution.json',result)
        print('FINISH_METRICS_SUPERVISOR',result['returncode'],result['reason'],flush=True)
        if result['returncode']!=0 or result['reason']: raise SystemExit(2)
        return
    marker=root/'render-fallback-continuation-001.json'
    if marker.exists(): raise ValueError('This checkpoint was already used')
    state=read(root/'execution-summary.json')
    if state.get('finished'): raise ValueError('Study already finished')
    outer_path=REPO/'private/phase1-validation'/(root.name+'-measurements-001/execution.json')
    outer=read(outer_path); stopped=read(root/'v250-render.execution.json')
    if not outer['termination_verified'] or stopped['reason']!='physical RAM reserve':
        raise ValueError('Unexpected stop checkpoint')
    for owned in stopped['owned_processes']:
        try:
            p=psutil.Process(owned['pid'])
            if abs(p.create_time()-owned['created_at'])<.01: raise ValueError('Render process remains alive')
        except psutil.NoSuchProcess: pass
    for label in JOBS:
        if (root/('v250-'+label+'.log')).exists(): raise ValueError('A remaining stage was already started: '+label)
    for name in ('source','cleaned','v1000/candidate','v500/candidate','v250/candidate'):
        load_surface(root/name)
    request=read(root/'request.json')
    for item in request['inputs'].values():
        if file_sha(item['path'])!=item['sha256']: raise ValueError('Input hash changed')
    if not read(root/'v250/metrics/views.json').get('complete'): raise ValueError('Measured depth fallback missing')
    evidence=dict(termination_verified=True,original_stage_record_unchanged=True,
        failed_render_sha256=file_sha(root/'v250-render.execution.json'),
        supervisor_sha256=file_sha(outer_path),verified_owned_processes=stopped['owned_processes'],
        observed_at_utc=datetime.now(timezone.utc).isoformat(),no_new_geometry=True,no_render_retry=True,
        original_total_deadline_unix=total_deadline,original_case_deadline_unix=case_deadline)
    write(root/'render-stop-001.json',evidence)
    shutil.copyfile(root/'identity.json',root/'identity-before-render-fallback.json')
    shutil.copyfile(root/'tool-pins.json',root/'tool-pins-before-render-fallback.json')
    shutil.copyfile(root/'execution-summary.json',root/'execution-before-render-fallback.json')
    old_identity=read(root/'identity.json'); old_pins=read(root/'tool-pins.json')
    pins=dict(old_pins); changed={}
    paths=[Path(__file__).resolve(),REPO/'src/runflow/shape_resources.py']
    for path in paths:
        relative=path.relative_to(REPO).as_posix(); out=root/'tool-sources/render-fallback-001'/relative
        out.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(path,out)
        pins[relative]=file_sha(out); changed[relative]=pins[relative]
    for relative,expected in old_pins.items():
        if relative in changed: continue
        path=BLENDER if relative=='blender.exe' else Path(sys.executable) if relative=='python.exe' else REPO/relative
        if file_sha(path)!=expected: raise ValueError('Unexpected processing code change: '+relative)
    # Scientific identity must not inherit run timestamps or absolute launcher
    # paths through a hash of operational stop evidence. Preserve those separately.
    identity=dict(initial_settings=read(root/'identity-initial.json')['identity'],
        processing_tool_chain=[read(root/name) for name in ('tool-pins-initial.json',
            'tool-pins-before-measurements.json','tool-pins-before-render-fallback.json')]+[pins],
        completion_code_pins=changed,remaining_stages=list(JOBS),no_new_geometry=True,
        no_render_retry=True,budgets_extended=False)
    study_id='rf-full-'+digest(identity); state['study_id']=study_id
    write(root/'identity.json',dict(study_id=study_id,identity=identity)); write(root/'tool-pins.json',pins)
    write(marker,dict(**evidence,new_study_id=study_id,remaining_stages=list(JOBS)))
    env=os.environ.copy(); env.update(TEMP=str(root/'scratch'),TMP=str(root/'scratch'),
        OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',RUNFLOW_CPU_COUNT='24')
    cpu=[sys.executable,str(REPO/'scripts/fullbody_voxel_metrics.py'),'--root',str(root),'--case','v250']
    blender=[str(BLENDER),'--background','--factory-startup','--threads','24','--python-exit-code','2',
        '--python',str(REPO/'integrations/blender/fullbody_voxel_compare.py'),'--','--root',str(root),'--case','v250']
    def save():
        state['elapsed_s']=time.time()-(total_deadline-43200)
        write(root/'execution-summary.json',state)
    def job(label,command,cap,deadline):
        budget=min(cap,deadline-time.time(),total_deadline-time.time())
        if budget<=0:
            result=dict(reason='time allocation exhausted',returncode=None,launched=False,
                elapsed_s=0,termination_verified=True)
        else:
            print('FULLBODY_JOB_START',label,flush=True)
            result=run(command,root=root,log=root/(label+'.log'),timeout=budget,limits=LIMITS,cwd=REPO,env=env)
        result['stage']=label; state['records'].append(result); write(root/(label+'.execution.json'),result); save()
        print('FULLBODY_JOB_END',label,result['returncode'],result['reason'],round(result['elapsed_s'],2),flush=True)
        if not result['termination_verified']: raise RuntimeError('Child termination unverified')
    save()
    for suffix in JOBS:
        if suffix=='sections': command=cpu+['--stage','sections']; cap=240
        elif suffix.startswith('projection-'):
            command=cpu+['--stage','projection','--view',suffix.split('-')[1]]; cap=900
        else:
            cap=min(600,max(0,case_deadline-time.time()))
            command=blender+['--stage','distance','--direction',suffix.split('-')[1],'--timeout',str(cap)]
        job('v250-'+suffix,command,cap,min(case_deadline,total_deadline-2700))
    state['inputs_unchanged']=all(file_sha(x['path'])==x['sha256'] for x in request['inputs'].values()); save()
    job('report',[sys.executable,str(REPO/'scripts/fullbody_voxel_report.py'),'--root',str(root)],2700,total_deadline)
    state['finished']=True; save()
    ledger_path=root/'artifact-sha256.json'
    if ledger_path.exists():
        ledger=read(ledger_path)
        for path in root.rglob('*'):
            if not path.is_file() or path==ledger_path or path.is_relative_to(root/'scratch'): continue
            key=path.relative_to(root).as_posix()
            if key not in ledger or key=='execution-summary.json': ledger[key]=file_sha(path)
        write(ledger_path,ledger)
    print('FULLBODY_COMPLETION_FINISHED',flush=True)


if __name__=='__main__': main()
