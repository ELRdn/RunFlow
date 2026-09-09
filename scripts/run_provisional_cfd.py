"""One fresh pose, existing stage/time caps, no automatic retries."""
import argparse
from pathlib import Path
import sys
import time
REPO=Path(__file__).resolve().parents[1];sys.path.insert(0,str(REPO/'src'))
from runflow.core import read,write
from runflow import cfd
from runflow.cfd_provisional import prepare
from runflow.cfd_numerics import PROFILES
from runflow.cfd_case import WALL_TREATMENTS
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--receipt',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--protocol',type=Path,default=REPO/'configs/cfd.phase1-provisional.json');p.add_argument('--distro',default='Ubuntu')
    p.add_argument('--reuse-proof',type=Path);p.add_argument('--surface-qualification',type=Path)
    p.add_argument('--numerics',choices=PROFILES,default='motorbike-simplec');p.add_argument('--restart-from',type=Path)
    p.add_argument('--wall-treatment',choices=WALL_TREATMENTS,default='reference-switching');a=p.parse_args()
    record=prepare(a.receipt,a.protocol,a.output,a.distro,reuse_proof=a.reuse_proof,surface_qualification=a.surface_qualification,numerics=a.numerics,restart_from=a.restart_from,wall_treatment=a.wall_treatment)
    print('PREPARATION',record['execution_status'],record['reason'],flush=True)
    if record['execution_status']=='PREPARED':
        record=cfd.run(a.output);print('CFD',record['execution_status'],record['reason'],flush=True)
    cfd.report(a.output)
    state=read(a.output/'state.json');state['completed_epoch']=time.time();write(a.output/'state.json',state)
    record=read(a.output/'result.json');print('FINAL',record['execution_status'],record['drag_N'],flush=True)
    raise SystemExit(0 if record['execution_status']=='PASS' else 2)
