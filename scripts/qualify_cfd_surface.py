"""Exact adjudication / revalidation; use inside the existing geometry watchdog."""
import argparse
from pathlib import Path
import sys
REPO=Path(__file__).resolve().parents[1];sys.path.insert(0,str(REPO/'src'))
from runflow.cfd_qualification import freeze,reuse
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--probe',type=Path);p.add_argument('--reference',type=Path)
    p.add_argument('--output',type=Path);p.add_argument('--qualification',type=Path);p.add_argument('--root',type=Path);a=p.parse_args()
    if a.qualification:reuse(a.qualification,a.root)
    else:freeze(a.probe,a.reference,a.output)
    print('EXACT_SURFACE_QUALIFICATION_VERIFIED',flush=True)
