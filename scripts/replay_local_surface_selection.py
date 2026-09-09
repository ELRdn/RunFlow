"""Guarded replay entry point; requires explicit human face selections and remaining budget."""
import argparse
from pathlib import Path
from run_local_surface_repair import run

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True)
    p.add_argument('--selection',type=Path,required=True);p.add_argument('--label',required=True);a=p.parse_args()
    result=run(a.root,'repair','manual',a.label,['--selection',str(a.selection.resolve())],900)
    if not result['complete']:raise SystemExit(2)
