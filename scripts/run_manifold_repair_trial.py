"""Bounded alternative backend, with its own records inside the original 12h deadline."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import shutil
import sys
import time
import psutil
from runflow.shape_audit import load_surface,file_sha
from runflow.shape_fullbody import read,write,LIMITS
from runflow.shape_repair import validate
from repair_trial_support import guarded

REPO=Path(__file__).resolve().parents[1]
BLENDER=REPO/'.tools/blender/blender-4.2.23-windows-x64/blender.exe'


def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True)
    p.add_argument('--action',choices=['generate','measure'],required=True); a=p.parse_args(); root=a.root.resolve()
    if not root.is_relative_to(Path('E:/RunFlowPrivate').resolve()): raise ValueError('Private study root required')
    request=read(root/'request.json'); validate(request); original=read(root/'execution.json')
    deadline=datetime.fromisoformat(original['comparison_started']).timestamp()+43200-original['preparation_elapsed_s']
    supplemental=root/'supplemental-manifold'; supplemental.mkdir(exist_ok=True)
    record_path=supplemental/(a.action+'-execution.json')
    if record_path.exists(): raise ValueError('This supplemental action already ran; no automatic retry')
    pins={}
    files=[Path(__file__).resolve(),REPO/'scripts/manifold_surface_repair.py',REPO/'scripts/repair_trial_support.py',
        REPO/'integrations/blender/repair_fullbody_surface.py',REPO/'scripts/fullbody_voxel_metrics.py',
        REPO/'src/runflow/shape_resources.py',REPO/'src/runflow/shape_repair.py']
    for path in files:
        target=supplemental/'tool-sources'/a.action/path.relative_to(REPO); target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,target); pins[path.relative_to(REPO).as_posix()]=file_sha(path)
    pins['blender.exe']=file_sha(BLENDER); pins['python.exe']=file_sha(sys.executable)
    pins['manifold-install']=read(REPO/'.tools/manifold3d-3.5.2/install.json')
    write(supplemental/('pins-'+a.action+'.json'),pins)
    state=dict(action=a.action,deadline_epoch=deadline,records=[],finished=False,
        reason='Different Boolean backend after Blender Exact commit spike; no voxel regeneration or retry of Exact',
        hard_commit_cap_bytes=LIMITS['private_commit_bytes'])
    write(record_path,state)
    env=os.environ.copy(); env.update(TEMP=str(root/'scratch'),TMP=str(root/'scratch'),PYTHONPATH=str(REPO/'src'),
        RUNFLOW_CPU_COUNT='24',OMP_NUM_THREADS='24',OPENBLAS_NUM_THREADS='1')

    def stage(label,command,seconds):
        left=deadline-time.time()
        if left<=0: raise ValueError('Original total deadline exhausted')
        external=[]
        # Account for the original study's currently owned tree, without stopping it.
        for process in psutil.process_iter(['cmdline']):
            try:
                cmd=process.info['cmdline'] or []
                if any(str(x).endswith('run_fullbody_surface_repair.py') for x in cmd) and '--action' in cmd and 'compare' in cmd:
                    for child in [process]+process.children(recursive=True): external.append(dict(pid=child.pid,created_at=child.create_time()))
            except (psutil.NoSuchProcess,psutil.AccessDenied): pass
        result=guarded(command,root=root,log=supplemental/(label+'.log'),timeout=min(seconds,left),
            limits={**LIMITS,'accounted_external_roots':external},cwd=REPO,env=env)
        result.update(stage=label); state['records'].append(result); write(record_path,state)
        print('SUPPLEMENT_STAGE',label,result['returncode'],result['reason'],round(result['elapsed_s'],2),flush=True)
        if not result['termination_verified']: raise ValueError('Supplemental child termination unverified')
        return result['returncode']==0 and not result['reason']

    def blender(case,action,seconds=900,extra=None):
        command=[str(BLENDER),'--background','--factory-startup','--threads','24','--python-exit-code','2',
            '--python',str(REPO/'integrations/blender/repair_fullbody_surface.py'),'--','--root',str(root),
            '--case',case,'--stage',action,'--timeout',str(seconds)]
        return stage(case+'-'+action+('-'+extra if extra else ''),command+(['--direction',extra] if extra else []),seconds)

    if a.action=='generate':
        for base in ('v1000','v900'):
            case=base+'-manifold'; target=root/case
            if target.exists(): raise ValueError('Supplemental candidate already exists')
            previous=root/(base+'-detail_union')
            if (previous/'patch.json').exists() and read(previous/'patch.json')['topology']['closed']:
                load_surface(previous/'patch-shell'); target.mkdir()
                shutil.copytree(previous/'patch-shell',target/'patch-shell'); shutil.copyfile(previous/'patch.json',target/'patch.json')
                write(target/'reused-patch.json',dict(source=str(previous),sha256=file_sha(previous/'patch.json'),new_solidify=False))
            else:
                cmd=[str(BLENDER),'--background','--factory-startup','--threads','24','--python-exit-code','2',
                     '--python',str(REPO/'scripts/manifold_surface_repair.py'),'--','--root',str(root),'--base',base,'--stage','patch']
                if not stage(case+'-patch',cmd,300): continue
            stage(case+'-generate',[sys.executable,str(REPO/'scripts/manifold_surface_repair.py'),'--root',str(root),
                '--base',base,'--stage','union'],1800)
    else:
        generation=read(supplemental/'generate-execution.json')
        cases=[r['stage'].removesuffix('-generate') for r in generation['records'] if r['stage'].endswith('-generate') and r['returncode']==0 and not r['reason']]
        # These original diagnostic stages were never launched while the disk reserve was low.
        for case in ('v1000','v900','v1000-nearest25'):
            prior=next(r for r in original['records'] if r['stage']==case+'-measure')
            if prior.get('launched') is False:
                existing=root/case/'metrics/forward-witness.json'
                if existing.exists(): shutil.copyfile(existing,existing.with_name('forward-witness-before-supplement.json'))
                blender(case,'measure',900)
        for case in cases:
            case_end=min(deadline,time.time()+4500)
            def remaining(cap): return max(.01,min(cap,case_end-time.time()))
            blender(case,'measure',remaining(900))
            for plane in ('front','side','top'):
                stage(case+'-projection-'+plane,[sys.executable,str(REPO/'scripts/fullbody_voxel_metrics.py'),'--root',str(root),
                    '--stage','projection','--case',case,'--view',plane],remaining(900))
            blender(case,'views',remaining(600))
            for direction in ('forward','reverse','local'): blender(case,'distance',remaining(1600),direction)
    validate(request)
    for path in files:
        if file_sha(path)!=pins[path.relative_to(REPO).as_posix()]: raise ValueError('Supplemental processing code changed')
    state['finished']=True; state['inputs_unchanged']=True; write(record_path,state)


if __name__=='__main__': main()
