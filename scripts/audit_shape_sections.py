import argparse
import json
from pathlib import Path
import time
import numpy as np
from runflow.shape_audit import load_surface
from runflow.shape_sections import section_segments


def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True); args=p.parse_args()
    root=args.root; result={}; started=time.monotonic()
    planes=[('sagittal',1,0.),('raised-foot',2,.83),('knee',2,.55),
            ('waist-hands',2,1.02),('head-hair',2,1.38),('ears',2,1.58)]
    for name in ('source','candidate'):
        v,f=load_surface(root/name)
        for label,axis,value in planes:
            segments,coplanar=section_segments(v,f,axis,value)
            np.save(root/(label+'-'+name+'-section.npy'),segments)
            result[label+'-'+name]=dict(axis=axis,value_m=value,segments=len(segments),coplanar_triangles=coplanar)
            print('SECTION_DONE',label,name,len(segments),flush=True)
    (root/'sections.json').write_text(json.dumps(dict(sections=result,complete=True,
        elapsed_s=time.monotonic()-started,
        note='Selected planes only. Contours are geometry intersections, not inside/outside or complete air-passage certification.'),indent=2),encoding='utf-8')


if __name__=='__main__': main()
