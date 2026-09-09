"""Execute one fresh, bounded Phase 1 sensitivity case; no blind retries."""
import argparse
from pathlib import Path
import sys

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
from runflow import cfd
from runflow.cfd_study import prepare
from runflow.core import read,write


def main():
    p=argparse.ArgumentParser()
    for name in ('source','protocol','authorization','qualification','output'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--distro',default='Ubuntu');a=p.parse_args()
    result=prepare(a.source,a.protocol,a.authorization,a.qualification,a.output,a.distro)
    print('PREPARATION',result['execution_status'],result['reason'],flush=True)
    if result['execution_status']=='PREPARED':
        result=cfd.run(a.output)
        print('CFD',result['execution_status'],result['reason'],flush=True)
    cfd.report(a.output)
    result=read(a.output/'result.json')
    print('FINAL',result['execution_status'],result['drag_N'],flush=True)
    return 0 if result['execution_status']=='PASS' else 2


if __name__=='__main__':
    raise SystemExit(main())
