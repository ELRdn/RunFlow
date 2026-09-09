"""One selected campaign case, with cumulative compute/output accounting."""
import argparse
from pathlib import Path
import sys
import time

REPO=Path(__file__).resolve().parents[1];sys.path.insert(0,str(REPO/'src'))
from runflow.core import read,write,file_hash,digest
from runflow import cfd,cfd_guard
from runflow.cfd_study import verify_authorization
from runflow.cfd_paths import reserve_reason


def main():
    p=argparse.ArgumentParser();p.add_argument('--request',required=True,type=Path)
    p.add_argument('--case-id',required=True);p.add_argument('--attempt',default='001')
    a=p.parse_args();request=read(a.request);source_request=a.request.parent
    if not a.attempt.isdigit() or len(a.attempt)!=3:raise ValueError('Three-digit attempt id required')
    cases={c['case_id']:c for c in request['cases']}
    if a.case_id not in cases:raise ValueError('Case not in approved finite campaign')
    authority=read(source_request/'authorization.json');verify_authorization(authority)
    if digest(authority)!=request['authorization_sha256']:raise ValueError('Campaign authorization changed')
    protocol=source_request/(a.case_id+'.json')
    if digest(read(protocol))!=cases[a.case_id]['protocol_sha256']:raise ValueError('Planned protocol changed')
    root=cfd.private(request['output_root'])
    if root.exists():
        if read(root/'request.json')!=request:raise ValueError('Campaign request changed')
    else:
        root.mkdir(parents=True);write(root/'request.json',request);write(root/'authorization.json',authority)
    ledger_path=root/'campaign.json'
    ledger=read(ledger_path) if ledger_path.exists() else dict(schema_version='phase1-campaign-execution-1',attempts=[],scientific_approval=None,ranking_eligible=False)
    if (root/'active.json').exists():raise ValueError('Campaign has an active or interrupted attempt; inspect before continuing')
    elapsed=sum(row['execution']['elapsed_s'] for row in ledger['attempts'])
    # Reserve one hour INSIDE the authorized 24h total for the short Unity/Blender
    # intake, binding, and optional local-edit work. Parallel time is charged
    # conservatively rather than extending the campaign beyond the user's budget.
    auxiliary_reserve=3600
    if elapsed+3630+auxiliary_reserve>request['execution_budget_s']:raise ValueError('No full trial budget remains after auxiliary reserve')
    used=cfd_guard.directory_bytes(root);remaining_bytes=request['max_output_bytes']-used
    if remaining_bytes<10*1024**3:raise ValueError('Campaign storage reserve insufficient for one trial')
    if reserve_reason(root):raise ValueError(reserve_reason(root))
    label=a.case_id+'-'+a.attempt;output=root/label
    if output.exists():raise ValueError('Fresh trial output required')
    write(root/'active.json',dict(label=label,started_epoch=time.time(),protocol_sha256=file_hash(protocol)))
    command=[sys.executable,str(REPO/'scripts/run_phase1_study.py'),'--source',request['source_root'],
        '--protocol',str(protocol),'--authorization',str(source_request/'authorization.json'),
        '--qualification',str(REPO/'private/phase1/surface-qualification-001'),'--output',str(output)]
    execution=cfd_guard.run(command,log=root/(label+'.launcher.log'),root=output,timeout=3630,
        memory_bytes=12*1024**3,output_bytes=10*1024**3,cwd=REPO,cancel_path=output/'cancel-request.txt')
    result=read(output/'result.json') if (output/'result.json').exists() else None
    if execution['reason'] or execution['returncode'] not in (0,2) or not execution['termination_verified']:
        status='SUPERVISOR_FAILURE'
    else:status=result['execution_status'] if result else 'MISSING_RESULT'
    record=dict(label=label,case_id=a.case_id,status=status,execution=execution,
        result_sha256=file_hash(output/'result.json') if result else None,
        output_bytes=cfd_guard.directory_bytes(output),protocol_sha256=cases[a.case_id]['protocol_sha256'])
    ledger['attempts'].append(record);ledger['consumed_compute_s']=elapsed+execution['elapsed_s']
    ledger['auxiliary_reserved_s']=auxiliary_reserve
    ledger['remaining_cfd_budget_s']=max(0,request['execution_budget_s']-auxiliary_reserve-ledger['consumed_compute_s'])
    write(ledger_path,ledger)
    # Only our exact lock is removed; no recursive cleanup or result deletion.
    if status!='SUPERVISOR_FAILURE':(root/'active.json').unlink()
    print(status,'compute_s',round(ledger['consumed_compute_s'],3),flush=True)
    return 0 if status=='PASS' else 2


if __name__=='__main__':raise SystemExit(main())
