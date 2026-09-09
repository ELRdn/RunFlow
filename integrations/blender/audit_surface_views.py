"""Six-view first-hit depth evidence; no solid/interior or physics inference."""
import argparse
import json
from pathlib import Path
import sys
import time
import gc
import bpy
import numpy as np
from mathutils.bvhtree import BVHTree

repo=next(p for p in Path(__file__).resolve().parents if (p/'src/runflow').is_dir())
sys.path.insert(0,str(repo/'src'))
from runflow.shape_audit import load_surface


def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True)
    args=p.parse_args(sys.argv[sys.argv.index('--')+1:]); root=args.root
    if bpy.app.version!=(4,2,23): raise ValueError('Pinned Blender required')
    source=tuple(map(np.asarray,load_surface(root/'source')))
    candidate=tuple(map(np.asarray,load_surface(root/'candidate')))
    low=np.minimum(source[0].min(axis=0),candidate[0].min(axis=0))-.01
    high=np.maximum(source[0].max(axis=0),candidate[0].max(axis=0))+.01
    step=.002; metadata={}; started=time.monotonic()
    for name,(v,f) in [('source',source),('candidate',candidate)]:
        tree=BVHTree.FromPolygons(v,f,all_triangles=True,epsilon=0)
        for axis,axes,label in [(0,(1,2),'front'),(1,(0,2),'side'),(2,(0,1),'top')]:
            us=np.arange(low[axes[0]]+step/2,high[axes[0]],step)
            vs=np.arange(low[axes[1]]+step/2,high[axes[1]],step)
            for sign in (1,-1):
                key=label+('+' if sign==1 else '-')
                depth=np.full((len(vs),len(us)),np.nan,dtype=np.float32)
                face_ids=np.full(depth.shape,-1,dtype=np.int32)
                direction=[0.,0.,0.]; direction[axis]=-sign
                origin=[0.,0.,0.]; origin[axis]=high[axis] if sign==1 else low[axis]
                for row,z in enumerate(vs):
                    origin[axes[1]]=float(z)
                    for col,u in enumerate(us):
                        origin[axes[0]]=float(u)
                        hit=tree.ray_cast(origin,direction)
                        if hit[0] is not None:
                            depth[row,col]=hit[0][axis]; face_ids[row,col]=hit[2]
                np.savez_compressed(root/(key+'-'+name+'.npz'),depth=depth,faces=face_ids)
                metadata[key]=dict(axis=axis,axes=axes,sign=sign,step_m=step,
                    extent_m=[float(us[0]-step/2),float(us[-1]+step/2),float(vs[0]-step/2),float(vs[-1]+step/2)])
                print('DEPTH_VIEW_DONE',name,key,depth.shape,flush=True)
        del tree; gc.collect()
    results={}
    for key,info in metadata.items():
        a=np.load(root/(key+'-source.npz'))['depth']; b=np.load(root/(key+'-candidate.npz'))['depth']
        am=np.isfinite(a); bm=np.isfinite(b); common=am&bm
        d=np.abs(a[common].astype(float)-b[common])
        results[key]={**info,'common_pixels':int(common.sum()),'source_only_pixels':int((am&~bm).sum()),
            'candidate_only_pixels':int((bm&~am).sum()),'median_first_hit_difference_m':float(np.median(d)),
            'p99_first_hit_difference_m':float(np.quantile(d,.99)),'max_first_hit_difference_m':float(d.max()),
            'common_fraction_depth_over_2mm':float((d>.002).mean())}
    (root/'views.json').write_text(json.dumps(dict(views=results,complete=True,
        elapsed_s=time.monotonic()-started,
        limitation='2mm ray spacing; first-hit depth can switch from foreground to background at a silhouette edge. Six views do not certify all 3D gaps or hidden parts.'),indent=2),encoding='utf-8')


if __name__=='__main__': main()
