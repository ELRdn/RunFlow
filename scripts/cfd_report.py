import argparse
from pathlib import Path
from runflow.cfd_report import create

p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True)
create(p.parse_args().root)
