"""Selected cross-sections of completed candidates, under the original study deadline."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import shutil
import sys
import time
from runflow.shape_audit import file_sha
from runflow.shape_fullbody import LIMITS,read,write
from runflow.shape_repair import validate
from repair_trial_support import guarded

REPO=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True); a=p.parse_args()
    root=a.root.resolve()
    if not root.is_relative_to(Path('E:/RunFlowPrivate').resolve()): raise ValueError('Private study required')
    request=read(root/'request.json'); validate(request); original=read(root/'execution.json')
    if not original['finished']: raise ValueError('Main comparison is still active')
    deadline=datetime.fromisoformat(original['comparison_started']).timestamp()+43200-original['preparation_elapsed_s']
    folder=root/'supplemental-sections'; folder.mkdir(exist_ok=False)
    files=[Path(__file__).resolve(),REPO/'scripts/fullbody_voxel_metrics.py',REPO/'scripts/repair_trial_support.py',
        *sorted((REPO/'src/runflow').glob('shape_*.py'))]
    pins={}
    for path in files:
        name=path.relative_to(REPO); target=folder/'tool-sources'/name; target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,target); pins[name.as_posix()]=file_sha(target)
    write(folder/'tool-pins.json',pins)
    state=dict(finished=False,records=[],deadline_epoch=deadline,scientific_status='UNAPPROVED',ranking_eligible=False)
    write(folder/'execution.json',state)
    env=os.environ.copy(); env.update(TEMP=str(root/'scratch'),TMP=str(root/'scratch'),OPENBLAS_NUM_THREADS='1')
    cases=['source']+[f'v{b}'+suffix for b in (1000,900) for suffix in ('','-nearest25','-normal50','-manifold','-raycarve2')]
    for case in cases:
        remaining=deadline-time.time()
        if remaining<=0: raise ValueError('Original study deadline exhausted')
        command=[sys.executable,str(REPO/'scripts/fullbody_voxel_metrics.py'),'--root',str(root),'--case',case,'--stage','sections']
        r=guarded(command,root=root,log=folder/(case+'.log'),timeout=min(300,remaining),limits=LIMITS,cwd=REPO,env=env)
        r['stage']=case+'-sections'; state['records'].append(r); write(folder/'execution.json',state)
        print('REPAIR_SECTIONS',case,r['returncode'],r['reason'],flush=True)
        if not r['termination_verified']: raise ValueError('Section child termination unverified')
    validate(request)
    if not all(file_sha(REPO/name)==sha for name,sha in pins.items()): raise ValueError('Section code changed during measurement')
    state.update(finished=True,inputs_unchanged=True,processing_code_unchanged=True)
    write(folder/'execution.json',state)


if __name__=='__main__': main()
