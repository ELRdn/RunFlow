"""Bounded by the normal provisional geometry-stage guard."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from runflow.cfd_restart import copy_checkpoint

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--root',type=Path,required=True)
    a=p.parse_args();r=copy_checkpoint(a.source,a.root)
    print('CHECKPOINT_VERIFIED',r['source_solver_iteration'],len(r['files']),flush=True)
