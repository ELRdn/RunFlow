"""Freeze a completed bounded campaign, including failures and unexecuted work."""
import argparse
from pathlib import Path
import sys
import time
import os
REPO=Path(__file__).resolve().parents[1];sys.path.insert(0,str(REPO/'src'))
from runflow.shape_fullbody import read,write,private_root,LIMITS
from runflow.shape_audit import file_sha,load_surface
from runflow.local_repair_contract import remaining_budget


def finalize(root,guarded_worker=False):
    started=time.monotonic()
    root=private_root(root,REPO,existing=True)
    lock=root/'active-stage.lock'
    if lock.exists() and not (guarded_worker and lock.read_text()=='local-repair-finalization'):
        raise ValueError('An owned stage is still active')
    state=read(root/'execution.json');request=read(root/'request.json')
    if state.get('finished'):raise ValueError('Campaign already frozen')
    if not (root/'review/summary.json').exists():raise ValueError('Review not yet generated')
    for item in request['old_inputs'].values():
        if file_sha(item['path'])!=item['sha256']:raise ValueError('Original or reference input changed')
    for name,ref in request['input_surfaces'].items():
        if file_sha(Path(ref['path'])/'cache.json')!=ref['cache_sha256']:raise ValueError('Input cache changed: '+name)
        load_surface(ref['path'])
    for run in state['records']:
        if run.get('launched') and not run.get('termination_verified'):raise ValueError('Unverified owned process termination')
        for relative,sha in run.get('code_pins',{}).items():
            if file_sha(root/'runs'/run['label']/'code'/relative)!=sha:raise ValueError('Stored code snapshot changed')
    for path in (root/'candidates').glob('*/candidate/cache.json'):load_surface(path.parent)
    a=root/'candidates/combined-repro-a';b=root/'candidates/combined-repro-b'
    ca=read(a/'candidate/cache.json');cb=read(b/'candidate/cache.json')
    ea=read(root/'runs/combined-repro-a/execution.json');eb=read(root/'runs/combined-repro-b/execution.json')
    repro=dict(complete=ea['complete'] and eb['complete'],input_configuration_ids_match=read(a/'recipe.json')['configuration_id']==read(b/'recipe.json')['configuration_id'],
        arrays_sha256_match=ca['output_hashes']==cb['output_hashes'],generation_code_pins_match=ea['code_pins']==eb['code_pins'],tool_pins_match=ea['tool_pins']==eb['tool_pins'],
        first_hashes=ca['output_hashes'],second_hashes=cb['output_hashes'])
    write(root/'review/reproducibility.json',repro)
    if not all(repro[k] for k in ('complete','input_configuration_ids_match','arrays_sha256_match','generation_code_pins_match','tool_pins_match')):
        raise ValueError('Reproduction evidence did not pass')
    if (root/'runtime-after-reproduction.json').exists():
        before=read(root/'runtime-during-reproduction.json');after=read(root/'runtime-after-reproduction.json')
        if before['fingerprint']!=after['fingerprint']:raise ValueError('Runtime package audit changed')
        write(root/'review/runtime-audit.json',dict(fingerprints_equal=before['fingerprint']==after['fingerprint'],
            versions=after['versions'],before_time=before['audited_at'],after_time=after['audited_at'],
            scope='Package audit during first replay and after second; not a retroactive pre-run pin'))
        for filename,audit in (('runtime-during-reproduction.json',before),('runtime-after-reproduction.json',after)):
            if not any(r.get('label')==filename for r in state['records']):
                state['records'].append(dict(stage='diagnosis',label=filename,task='package-audit',elapsed_s=audit['elapsed_s'],
                    complete=True,launched=False,sha256=file_sha(root/filename),scope='Read-only measured package audit'))
    attempts=list((root/'candidates').glob('*/recipe.json'))
    if len(attempts)>request['settings']['max_candidates']:raise ValueError('Candidate cap exceeded')
    used=sum(r['elapsed_s'] for r in state['records'])
    if used>43200:raise ValueError('Recorded campaign processing budget exceeded')
    exclusions=('artifact-sha256.json','E-copy-verification.json','finalization-guard.json','finalization.json','execution.json','active-stage.lock')
    paths=[p for p in root.rglob('*') if p.is_file() and 'scratch' not in p.relative_to(root).parts and
        not (p.parent==root and p.name in exclusions)]
    files={p.relative_to(root).as_posix():dict(sha256=file_sha(p),bytes=p.stat().st_size) for p in sorted(paths)}
    elapsed=time.monotonic()-started
    if elapsed>remaining_budget(state['records'],'report'):raise ValueError('Finalization exceeded report budget')
    finalization=dict(stage='report',label='finalization',task='validate-and-freeze',elapsed_s=elapsed,complete=True,
        processing_code_sha256=file_sha(Path(__file__)),
        scope='Input validation and artifact hashing; excludes final small manifest writes and E copy. Outer owned guard receipt is adjacent to the study.')
    state['records'].append(finalization)
    state.update(finished=True,finish_kind='BOUNDED_TRIALS_ENDED_WITH_UNRESOLVED_REGIONS',attempts=len(attempts),
        inputs_verified_unchanged=True,all_local_methods_exhausted=False,scientific_status='UNAPPROVED',ranking_eligible=False,
        human_adoption=None,drag_N=None,Cd=None,CdA_m2=None,E_delivery_status_at_freeze='PENDING_COPY')
    write(root/'execution.json',state)
    write(root/'finalization.json',finalization)
    for name in ('execution.json','finalization.json'):
        p=root/name;files[name]=dict(sha256=file_sha(p),bytes=p.stat().st_size)
    write(root/'artifact-sha256.json',dict(files=files,source_root=str(root),private_only=True,
        total_bytes=sum(v['bytes'] for v in files.values()),excluded=['scratch/','artifact-sha256.json','E-copy-verification.json','finalization-guard.json']))
    print('LOCAL_REPAIR_FROZEN',len(files),sum(v['bytes'] for v in files.values()),repro,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--worker',action='store_true');a=p.parse_args()
    if a.worker:finalize(a.root,guarded_worker=True)
    else:
        from repair_trial_support import guarded
        root=private_root(a.root,REPO,existing=True);state=read(root/'execution.json')
        if state.get('finished') or (root/'active-stage.lock').exists():raise ValueError('Study is frozen or still running')
        receipt=root.parent/(root.name+'-finalization-guard.json')
        if receipt.exists():raise ValueError('Previous finalization receipt exists; inspect before another attempt')
        env={k.upper():v for k,v in os.environ.items()};env['RUNFLOW_CPU_COUNT']='24'
        lock=root/'active-stage.lock'
        with lock.open('x') as stream:stream.write('local-repair-finalization')
        try:
            result=guarded([sys.executable,str(Path(__file__).resolve()),'--root',str(root),'--worker'],root=root,
                log=root.parent/(root.name+'-finalization-launcher.log'),timeout=min(900,remaining_budget(state['records'],'report')),
                limits=LIMITS,cwd=REPO,env=env)
        finally:lock.unlink()
        result['complete']=result['returncode']==0 and not result['reason'] and result['termination_verified']
        result['artifact_ledger_sha256']=file_sha(root/'artifact-sha256.json') if result['complete'] else None
        write(receipt,result)
        if not result['complete']:raise ValueError('Finalization did not complete; inspect outer guard receipt')
        print('LOCAL_REPAIR_FINALIZATION_VERIFIED',round(result['elapsed_s'],2),flush=True)
