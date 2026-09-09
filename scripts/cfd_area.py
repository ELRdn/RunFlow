"""Area comparison isolated so resource and stage limits can interrupt GEOS."""
import argparse
from runflow.core import read,write
from runflow.geometry import area

p=argparse.ArgumentParser(); p.add_argument('--root',required=True); args=p.parse_args()
from pathlib import Path
root=Path(args.root)
source=area(read(root/'source.snapshot.json')); candidate=area(read(root/'geometry/candidate.snapshot.json'))
write(root/'areas.json',dict(source_area_m2=source,candidate_area_m2=candidate,relative_error=abs(candidate-source)/source))
