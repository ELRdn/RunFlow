"""Own and budget one immutable stage of the approved local repair campaign."""
import argparse
import os
from pathlib import Path
import shutil
import sys
import time
import math
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
from runflow.shape_fullbody import read,write,LIMITS,private_root
from runflow.shape_audit import file_sha
from runflow.local_repair_contract import validate_settings,remaining_budget
from runflow.local_geometry import tools_manifest,ROOT as GEOMETRY_ROOT
from repair_trial_support import guarded

def _run(root,stage,task,label,options,cap):
    started=time.monotonic()
    root=private_root(root,REPO,existing=True);request=read(root/'request.json');validate_settings(request['settings'])
    state=read(root/'execution.json')
    if state.get('finished'):raise ValueError('Campaign already finished')
    if not label.replace('-','').replace('_','').isalnum():raise ValueError('Simple unique label required')
    if not math.isfinite(cap) or cap<=0:raise ValueError('Positive finite stage cap required')
    budget=min(cap,remaining_budget(state['records'],stage))
    if budget<=0:raise ValueError('Campaign or stage budget exhausted')
    folder=root/'runs'/label;folder.mkdir(parents=True,exist_ok=False)
    sources=[REPO/'scripts/local_surface_worker.py',Path(__file__).resolve(),REPO/'src/runflow/local_geometry.py',
        REPO/'src/runflow/local_repair_contract.py',REPO/'src/runflow/shape_resources.py',REPO/'scripts/repair_trial_support.py']
    for path in (REPO/'scripts').glob('local_repair_*.py'):sources.append(path)
    sources.extend(REPO/p for p in ('scripts/ray_carve_surface.py','scripts/manifold_surface_repair.py',
        'scripts/fullbody_voxel_metrics.py','src/runflow/shape_fullbody.py','src/runflow/shape_audit.py',
        'src/runflow/shape_projection.py','src/runflow/shape_sections.py'))
    for path in (REPO/'integrations/geometry').rglob('*'):
        if path.is_file():sources.append(path)
    sources.extend(REPO/p for p in ('integrations/blender/fullbody_voxel_compare.py',
        'integrations/blender/audit_surface_distance.py','integrations/blender/prepare_cfd_surface.py',
        'src/runflow/shape_local.py'))
    if task=='report':sources.append(REPO/'scripts/report_local_surface_repair.py')
    if task=='finish-evidence':sources.append(REPO/'scripts/finish_local_repair_evidence.py')
    pins={}
    for path in sources:
        target=folder/'code'/path.relative_to(REPO);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
        pins[path.relative_to(REPO).as_posix()]=file_sha(path)
    write(folder/'code-pins.json',pins)
    native_manifest=tools_manifest()
    write(folder/'native-build.json',native_manifest)
    tool_pins={'native-build':file_sha(GEOMETRY_ROOT/'build.json'),
        'python':file_sha(sys.executable),'manifold-install':file_sha(REPO/'.tools/manifold3d-3.5.2/install.json')}
    write(folder/'tool-pins.json',tool_pins)
    scratch=root/'scratch';scratch.mkdir(exist_ok=True)
    env={k.upper():v for k,v in os.environ.items()};env.update(TEMP=str(scratch),TMP=str(scratch),
        PYTHONPATH=str(REPO/'src'),RUNFLOW_CPU_COUNT='24',OMP_NUM_THREADS='24',OPENBLAS_NUM_THREADS='1')
    command=[sys.executable,str(REPO/'scripts/local_surface_worker.py'),'--root',str(root),'--task',task,'--label',label,*options]
    preflight=time.monotonic()-started
    if preflight>=budget:raise ValueError('Stage budget consumed by preflight')
    result=guarded(command,root=root,log=folder/'launcher.log',timeout=budget-preflight,limits=LIMITS,cwd=REPO,env=env)
    result['preflight_elapsed_s']=preflight
    result.update(stage=stage,task=task,label=label,code_pins=pins,tool_pins=tool_pins)
    result['processing_code_unchanged']=all(file_sha(REPO/p)==h for p,h in pins.items())
    result['complete']=result['returncode']==0 and result['reason'] is None and result['termination_verified'] and result['processing_code_unchanged']
    result['elapsed_s']=time.monotonic()-started
    write(folder/'execution.json',result);state['records'].append(result);write(root/'execution.json',state)
    candidate=root/'candidates'/label
    if not result['complete'] and candidate.exists():
        write(candidate/'state.json',dict(generation='RESOURCE_STOP' if result['reason'] else 'EXECUTION_FAILED',
            reason=result['reason'] or 'Inspect stage launcher log',measurement='UNVERIFIED',human_review=None,
            scientific_status='UNAPPROVED',ranking_eligible=False,drag_N=None,Cd=None,CdA_m2=None))
    print('LOCAL_REPAIR_STAGE',label,result['complete'],result['reason'],round(result['elapsed_s'],2),flush=True)
    if not result['termination_verified']:raise ValueError('Owned child termination not verified')
    return result


def run(root,stage,task,label,options,cap):
    root=private_root(root,REPO,existing=True);lock=root/'active-stage.lock'
    with lock.open('x') as stream:stream.write(str(os.getpid()))
    try:return _run(root,stage,task,label,options,cap)
    finally:lock.unlink()

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--stage',required=True,choices=['diagnosis','precision','repair','verification','report']);p.add_argument('--task',required=True);p.add_argument('--label',required=True);p.add_argument('--cap',type=float,default=1800)
    a,extra=p.parse_known_args();r=run(a.root,a.stage,a.task,a.label,extra,a.cap)
    if not r['complete']:raise SystemExit(2)

if __name__=='__main__':main()
