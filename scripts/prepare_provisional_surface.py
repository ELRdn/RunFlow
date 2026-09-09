"""Run under the Phase 1 geometry watchdog."""
import argparse
from pathlib import Path
import sys
REPO=Path(__file__).resolve().parents[1];sys.path.insert(0,str(REPO/'src'))
from runflow.cfd_surface import prepare_surface
from runflow.core import file_hash
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--source',type=Path,required=True)
    p.add_argument('--reuse-proof',type=Path)
    a=p.parse_args()
    if a.reuse_proof:
        from runflow.cfd_reuse import reuse
        reuse(a.root,a.reuse_proof,file_hash(a.source/'cache.json'))
    else:
        prepare_surface(a.root,a.source)
