"""Bounded 1mm/0.9mm repair study. Reuse saved bases; never remesh or run CFD."""
import argparse
from datetime import datetime,timezone
import os
from pathlib import Path
import shutil
import sys
import time
from runflow.core import digest
from runflow.shape_audit import file_sha,load_surface
from runflow.shape_fullbody import read,write,LIMITS,private_root
from repair_trial_support import guarded as run
from runflow.shape_repair import RECIPES,validate,identity

REPO=Path(__file__).resolve().parents[1]
BLENDER=REPO/'.tools/blender/blender-4.2.23-windows-x64/blender.exe'
WORKER=REPO/'integrations/blender/repair_fullbody_surface.py'
PREVIOUS={1000:Path('E:/RunFlowPrivate/phase1-validation/fullbody-voxel-001'),
          900:Path('E:/RunFlowPrivate/phase1-validation/fullbody-voxel-002')}


def pinned(path): return dict(path=str(Path(path).resolve()),sha256=file_sha(path))


def build_request():
    previous=read(PREVIOUS[900]/'request.json')
    inputs={k:v for k,v in previous['inputs'].items() if k in
            ['source','manifest','adoption-decision','gap','projection-front','projection-side','projection-top','cfd-result']}
    for key in ('source','cleaned'):
        for name in ('vertices.npy','triangles.npy','cache.json'):
            inputs[key+'-'+name.split('.')[0]]=pinned(PREVIOUS[1000]/key/name)
    inputs['view-bounds']=pinned(PREVIOUS[1000]/'view-bounds.json')
    for base,old in PREVIOUS.items():
        for name in ('vertices.npy','triangles.npy','cache.json'):
            inputs[f'v{base}-'+name.split('.')[0]]=pinned(old/f'v{base}/candidate'/name)
    presentation={}
    for case,folder in [('source',PREVIOUS[1000]/'source-metrics')]+[(f'v{b}',p/f'v{b}/metrics') for b,p in PREVIOUS.items()]:
        for path in folder.iterdir():
            if path.name in ('views.json','forward.json','reverse.json','projection-front.json','projection-side.json','projection-top.json') or path.name.endswith('-depth.npy'):
                presentation[case+'/'+path.name]=pinned(path)
    return dict(kind='fullbody_surface_repair_v1',adoption='adopted-002',frame=0,bases_um=[1000,900],
        recipes=RECIPES,inputs=inputs,presentation=presentation,regions=previous['regions'],
        witnesses=[dict(id='prior-global-worst',point_m=read(presentation['v1000/forward.json']['path'])['max_witness_m'])],
        actual_processing_limit_s=43200,generation_limit_s=1800,measurement_limit_s=4500,
        cpu_logical_limit=24,projection_processes=8,new_voxel_generation=False,
        scientific_status='UNAPPROVED',human_adoption=None,ranking_eligible=False)


def pin_tools(root,phase):
    paths=[Path(__file__).resolve(),WORKER,REPO/'scripts/fullbody_surface_repair_report.py',
        REPO/'scripts/fullbody_voxel_metrics.py',REPO/'integrations/blender/fullbody_voxel_compare.py',
        REPO/'integrations/blender/prepare_cfd_surface.py',REPO/'integrations/blender/audit_surface_distance.py',
        REPO/'src/runflow/core.py',REPO/'src/runflow/cfd_guard.py',REPO/'uv.lock',
        REPO/'scripts/repair_trial_support.py']
    paths+=sorted((REPO/'src/runflow').glob('shape_*.py'))
    pins={'blender.exe':file_sha(BLENDER),'python.exe':file_sha(sys.executable)}
    for path in paths:
        if not path.exists(): continue  # Probe phase can precede report implementation.
        name=path.relative_to(REPO); out=root/'tool-sources'/phase/name
        out.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(path,out)
        pins[name.as_posix()]=file_sha(out)
    write(root/('tool-pins-'+phase+'.json'),pins)
    return pins


def setup(root):
    start=time.monotonic(); request=build_request(); validate(request)
    root.mkdir(parents=True,exist_ok=False); (root/'scratch').mkdir()
    write(root/'request.json',request)
    for name in ['source','cleaned']+[f'v{b}' for b in request['bases_um']]:
        dest=root/name if name in ('source','cleaned') else root/name/'candidate'
        dest.mkdir(parents=True)
        for file in ('vertices.npy','triangles.npy','cache.json'):
            item=request['inputs'][name+'-'+file.split('.')[0]]
            shutil.copyfile(item['path'],dest/file)
            if file_sha(dest/file)!=item['sha256']: raise ValueError('Copy changed input')
        load_surface(dest)
    shutil.copyfile(request['inputs']['view-bounds']['path'],root/'view-bounds.json')
    for relative,item in request['presentation'].items():
        if file_sha(item['path'])!=item['sha256']: raise ValueError('Presentation input changed')
        case,name=relative.split('/'); folder=root/'source-metrics' if case=='source' else root/case/'metrics'
        folder.mkdir(parents=True,exist_ok=True); shutil.copyfile(item['path'],folder/name)
        if file_sha(folder/name)!=item['sha256']: raise ValueError('Presentation copy changed')
    for plane in ('front','side','top'):
        shutil.copyfile(request['inputs']['projection-'+plane]['path'],root/'source-metrics'/(plane+'.wkb'))
    state=dict(kind=request['kind'],started_utc=datetime.now(timezone.utc).isoformat(),records=[],
        preparation_elapsed_s=time.monotonic()-start,finished=False,scientific_status='UNAPPROVED',ranking_eligible=False)
    write(root/'execution.json',state); return request,state


def main():
    p=argparse.ArgumentParser(); p.add_argument('--output',type=Path,required=True)
    p.add_argument('--action',choices=['probe','compare'],required=True); args=p.parse_args()
    root=private_root(args.output,REPO,existing=args.action=='compare')
    request,state=setup(root) if args.action=='probe' else (read(root/'request.json'),read(root/'execution.json'))
    validate(request)
    if state.get('finished'): raise ValueError('Finished study cannot be retried')
    if args.action=='compare':
        if state.get('comparison_started'): raise ValueError('Comparison cannot be automatically retried')
        if not all((root/f'v{b}/detail-selection.json').exists() for b in request['bases_um']): raise ValueError('Baseline probes incomplete')
        state['comparison_started']=datetime.now(timezone.utc).isoformat(); write(root/'execution.json',state)
    pins=pin_tools(root,args.action)
    write(root/('identity-'+args.action+'.json'),identity(request,pins))
    env=os.environ.copy(); env.update(TEMP=str(root/'scratch'),TMP=str(root/'scratch'),
        PYTHONPATH=str(REPO/'src'),RUNFLOW_CPU_COUNT='24',OMP_NUM_THREADS='24',OPENBLAS_NUM_THREADS='1')
    records=state['records']; session_start=time.monotonic()
    prior_used=state['preparation_elapsed_s']+sum(r['elapsed_s'] for r in records)
    deadline=session_start+43200-prior_used

    def stage(label,command,seconds):
        left=deadline-time.monotonic()
        if left<=0:
            record=dict(stage=label,returncode=None,reason='total processing time limit',elapsed_s=0,
                        termination_verified=True,launched=False)
        else:
            record=run(command,root=root,log=root/(label+'.log'),timeout=min(seconds,left),limits=LIMITS,cwd=REPO,env=env)
            record.update(stage=label,tool_pins_sha256=file_sha(root/('tool-pins-'+args.action+'.json')))
        records.append(record); write(root/'execution.json',state)
        print('REPAIR_STAGE_END',label,record['reason'],round(record['elapsed_s'],2),flush=True)
        if not record['termination_verified']: raise RuntimeError('Owned process termination unverified; study stopped')
        return record.get('returncode')==0 and not record.get('reason')

    def blender(case,action,seconds,extra=None):
        command=[str(BLENDER),'--background','--factory-startup','--threads','24','--python-exit-code','2',
            '--python',str(WORKER),'--','--root',str(root),'--case',case,'--stage',action,'--timeout',str(seconds)]
        return stage(case+'-'+action+('-'+extra if extra else ''),command+(['--direction',extra] if extra else []),seconds)

    if args.action=='probe':
        results=[blender(f'v{base}','probe',600) for base in request['bases_um']]
        write(root/'probe-completion.json',dict(complete=all(results),actual_processing_s=state['preparation_elapsed_s']+sum(r['elapsed_s'] for r in records)))
        if not all(results): raise SystemExit(2)
        return
    # Separate geometry generation and measurement stages, sequential within this owned study.
    cases=[]
    for recipe in RECIPES:
        for base in request['bases_um']:
            case=f'v{base}-{recipe}'
            if blender(case,'generate',request['generation_limit_s']):
                load_surface(root/case/'candidate'); cases.append(case)
    # Baseline diagnostic grids use exactly the same first-hit samples as the repair candidates.
    for base in request['bases_um']: blender(f'v{base}','measure',1800)
    for case in cases:
        case_deadline=min(deadline,time.monotonic()+request['measurement_limit_s'])
        def remaining(cap): return max(.01,min(cap,case_deadline-time.monotonic()))
        blender(case,'measure',remaining(900))
        for plane in ('front','side','top'):
            stage(case+'-projection-'+plane,[sys.executable,str(REPO/'scripts/fullbody_voxel_metrics.py'),
                '--root',str(root),'--stage','projection','--case',case,'--view',plane],remaining(900))
        blender(case,'views',remaining(600))
        for direction in ('forward','reverse','local'):
            blender(case,'distance',remaining(1600),direction)
    validate(request)
    unchanged=all(file_sha(REPO/name)==sha for name,sha in pins.items() if name not in ('blender.exe','python.exe'))
    if not unchanged: raise ValueError('Processing code changed during study')
    state['inputs_unchanged']=True; state['processing_code_unchanged']=True
    state['finished']=True; state['actual_processing_s']=prior_used+time.monotonic()-session_start
    write(root/'execution.json',state)
    stage('report',[sys.executable,str(REPO/'scripts/fullbody_surface_repair_report.py'),'--root',str(root)],min(1800,max(.01,deadline-time.monotonic())))
    state['actual_processing_s']=prior_used+time.monotonic()-session_start; write(root/'execution.json',state)
    print('REPAIR_STUDY_FINISHED',str(root),flush=True)


if __name__=='__main__': main()
