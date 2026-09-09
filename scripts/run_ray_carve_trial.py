"""Observed-empty-space repair within the same original total deadline."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import shutil
import sys
import time
import psutil
from runflow.shape_fullbody import read,write,LIMITS
from runflow.shape_repair import validate
from runflow.shape_audit import file_sha
from repair_trial_support import guarded

REPO=Path(__file__).resolve().parents[1]
BLENDER=REPO/'.tools/blender/blender-4.2.23-windows-x64/blender.exe'


def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True)
    p.add_argument('--revision',type=int,choices=[1,2],default=1); a=p.parse_args(); root=a.root.resolve()
    if not root.is_relative_to(Path('E:/RunFlowPrivate').resolve()): raise ValueError('Private study root required')
    request=read(root/'request.json'); validate(request); original=read(root/'execution.json')
    deadline=datetime.fromisoformat(original['comparison_started']).timestamp()+43200-original['preparation_elapsed_s']
    suffix='2' if a.revision==2 else ''
    folder=root/('supplemental-raycarve'+suffix); folder.mkdir(exist_ok=False)
    files=[Path(__file__).resolve(),REPO/'scripts/ray_carve_surface.py',REPO/'scripts/manifold_surface_repair.py',
        REPO/'scripts/repair_trial_support.py',REPO/'integrations/blender/repair_fullbody_surface.py',
        REPO/'scripts/fullbody_voxel_metrics.py',REPO/'src/runflow/shape_resources.py']
    pins={}
    for path in files:
        target=folder/'tool-sources'/path.relative_to(REPO); target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,target); pins[path.relative_to(REPO).as_posix()]=file_sha(path)
    pins['manifold-install']=read(REPO/'.tools/manifold3d-3.5.2/install.json')
    pins['blender.exe']=file_sha(BLENDER); pins['python.exe']=file_sha(sys.executable)
    write(folder/'tool-pins.json',pins)
    state=dict(records=[],finished=False,deadline_epoch=deadline,scientific_status='UNAPPROVED',ranking_eligible=False,
        rationale='Union cannot expose an original visible face enclosed inside the filled candidate; subtract only ray-observed free space in fixed problem ROIs',
        generation='Two saved full-body bases; no voxel regeneration',grid_m=.0001,stand_off_m=.0002,cleanup_tolerance_m=.000001)
    write(folder/'execution.json',state)
    env=os.environ.copy(); env.update(TEMP=str(root/'scratch'),TMP=str(root/'scratch'),PYTHONPATH=str(REPO/'src'),
        RUNFLOW_CPU_COUNT='24',OMP_NUM_THREADS='24',OPENBLAS_NUM_THREADS='1')

    def stage(label,command,seconds):
        remaining=deadline-time.time()
        if remaining<=0: raise ValueError('Original total deadline exhausted')
        external=[]
        for process in psutil.process_iter(['cmdline']):
            try:
                cmd=process.info['cmdline'] or []
                if any(str(x).endswith(('run_fullbody_surface_repair.py','run_manifold_repair_trial.py')) for x in cmd):
                    external.append(dict(pid=process.pid,created_at=process.create_time()))
            except (psutil.NoSuchProcess,psutil.AccessDenied): pass
        result=guarded(command,root=root,log=folder/(label+'.log'),timeout=min(seconds,remaining),
            limits={**LIMITS,'accounted_external_roots':external},cwd=REPO,env=env)
        result['stage']=label; state['records'].append(result); write(folder/'execution.json',state)
        print('RAY_TRIAL_STAGE',label,result['returncode'],result['reason'],round(result['elapsed_s'],2),flush=True)
        if not result['termination_verified']: raise ValueError('Ray trial child termination unverified')
        return result['returncode']==0 and not result['reason']

    def blender(case,action,seconds,extra=None):
        cmd=[str(BLENDER),'--background','--factory-startup','--threads','24','--python-exit-code','2',
            '--python',str(REPO/'integrations/blender/repair_fullbody_surface.py'),'--','--root',str(root),'--case',case,
            '--stage',action,'--timeout',str(seconds)]
        return stage(case+'-'+action+('-'+extra if extra else ''),cmd+(['--direction',extra] if extra else []),seconds)

    if a.revision==1:
        if not stage('cutters',[str(BLENDER),'--background','--factory-startup','--threads','24','--python-exit-code','2',
            '--python',str(REPO/'scripts/ray_carve_surface.py'),'--','--root',str(root),'--stage','cutters'],600): return
    else:
        from runflow.shape_audit import load_surface
        prior=read(root/'supplemental-raycarve/execution.json')
        if not prior['finished'] or not read(root/'ray-carve-cutters/cutters.json')['complete']:
            raise ValueError('Original cutter checkpoint not complete')
        for base in ('v1000','v900'):
            log=(root/'supplemental-raycarve'/(base+'-raycarve-generate.log')).read_text()
            if 'incompatible function arguments' not in log or 'AIR_SUBTRACTED' in log or (root/(base+'-raycarve')/'generated').exists():
                raise ValueError('Only the native import failure checkpoint can be continued')
        for name in ('face-visible','hair-visible'): load_surface(root/'ray-carve-cutters'/name)
        state['implementation_correction']='Copy read-only float64 buffers required by native binding; preserved previous failures and cutters, no remesh, same original deadline'
        state['previous_execution_sha256']=file_sha(root/'supplemental-raycarve/execution.json')
        write(folder/'execution.json',state)
    successful=[]
    for base in ('v1000','v900'):
        case=base+'-raycarve'+suffix
        if stage(case+'-generate',[sys.executable,str(REPO/'scripts/ray_carve_surface.py'),'--root',str(root),'--stage','subtract','--base',base,'--revision',str(a.revision)],1800): successful.append(case)
    for case in successful:
        case_end=min(deadline,time.time()+4500)
        def remaining(cap): return max(.01,min(cap,case_end-time.time()))
        blender(case,'measure',remaining(900)); blender(case,'views',remaining(600))
        for plane in ('front','side','top'):
            stage(case+'-projection-'+plane,[sys.executable,str(REPO/'scripts/fullbody_voxel_metrics.py'),'--root',str(root),
                '--stage','projection','--case',case,'--view',plane],remaining(900))
        for direction in ('forward','reverse','local'): blender(case,'distance',remaining(1600),direction)
    validate(request)
    for path in files:
        if file_sha(path)!=pins[path.relative_to(REPO).as_posix()]: raise ValueError('Ray carving processing code changed')
    state['finished']=True; state['inputs_unchanged']=True; write(folder/'execution.json',state)


if __name__=='__main__': main()
