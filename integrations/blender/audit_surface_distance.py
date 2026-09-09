"""Complete surface-cover distance audit. No geometry edits, repair or CFD."""
import argparse
import gc
import json
from pathlib import Path
import sys
import time
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

repo=next(p for p in Path(__file__).resolve().parents if (p/'src/runflow').is_dir())
sys.path.insert(0,str(repo/'src'))
from runflow.shape_audit import load_surface,SAMPLE_DTYPE,summarize_samples


def audit(vertices,triangles,target_v,target_f,output,cover_m,deadline):
    # Blender expands sequence rows internally. Strip memmap's subclass so
    # each row is a plain ndarray view rather than a costly memmap object.
    vertices,triangles,target_v,target_f=map(np.asarray,(vertices,triangles,target_v,target_f))
    print('BUILD_BVH',len(target_f),flush=True)
    tree=BVHTree.FromPolygons(target_v,target_f,all_triangles=True,epsilon=0)
    output=Path(output); started=time.monotonic(); buffer=[]; samples=0; omitted=0
    last=time.monotonic()
    with output.with_suffix('.samples').open('wb') as stream:
        for index,face in enumerate(triangles):
            stack=[tuple(Vector(vertices[int(i)]) for i in face)]
            while stack:
                if time.monotonic()>deadline: raise TimeoutError('Complete distance audit time limit')
                a,b,c=stack.pop(); center=(a+b+c)/3
                radius=max((x-center).length for x in (a,b,c))
                area=(b-a).cross(c-a).length*.5
                if area==0: omitted+=1; continue
                if radius>cover_m:
                    ab=(a+b)/2; bc=(b+c)/2; ca=(c+a)/2
                    stack.extend(((a,ab,ca),(ab,b,bc),(ca,bc,c),(ab,bc,ca)))
                    continue
                hit=tree.find_nearest(center)
                if hit[0] is None: raise ValueError('No nearest surface')
                buffer.append((tuple(center),hit[3],radius,area,index)); samples+=1
                if len(buffer)>=50000:
                    np.array(buffer,dtype=SAMPLE_DTYPE).tofile(stream); buffer.clear()
            if time.monotonic()-last>20:
                print('DISTANCE_PROGRESS',index+1,len(triangles),samples,flush=True); last=time.monotonic()
        if buffer: np.array(buffer,dtype=SAMPLE_DTYPE).tofile(stream)
    del tree; gc.collect()
    data=np.memmap(output.with_suffix('.samples'),dtype=SAMPLE_DTYPE,mode='r')
    summary=summarize_samples(data)
    summary.update(complete=True,source_triangles=len(triangles),zero_area_subtriangles=omitted,
                   elapsed_s=time.monotonic()-started,blender_version=bpy.app.version_string)
    output.with_suffix('.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    return summary


def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True)
    p.add_argument('--direction',choices=['source-to-candidate','candidate-to-source'],required=True)
    p.add_argument('--cover-m',type=float,default=.001); p.add_argument('--timeout',type=float,default=1200)
    args=p.parse_args(sys.argv[sys.argv.index('--')+1:])
    if bpy.app.version!=(4,2,23): raise ValueError('Pinned Blender required')
    if not 0<args.cover_m<=.001: raise ValueError('Audit cover must be <= 1mm')
    source,candidate=load_surface(args.root/'source'),load_surface(args.root/'candidate')
    a,b=(source,candidate) if args.direction=='source-to-candidate' else (candidate,source)
    audit(*a,*b,args.root/args.direction,args.cover_m,time.monotonic()+args.timeout-10)
    print('DISTANCE_AUDIT_COMPLETE',args.direction,flush=True)


if __name__=='__main__': main()
