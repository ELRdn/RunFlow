"""Determine whether selected distance witnesses are directly visible in six axes."""
import argparse,json,sys
from pathlib import Path
import numpy as np
from mathutils.bvhtree import BVHTree
repo=next(p for p in Path(__file__).resolve().parents if (p/'src/runflow').is_dir())
sys.path.insert(0,str(repo/'src'))
from runflow.shape_audit import load_surface

p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True)
args=p.parse_args(sys.argv[sys.argv.index('--')+1:]); root=args.root
v,f=map(np.asarray,load_surface(root/'source')); cv,cf=map(np.asarray,load_surface(root/'candidate'))
source=BVHTree.FromPolygons(v,f,all_triangles=True,epsilon=0)
candidate=BVHTree.FromPolygons(cv,cf,all_triangles=True,epsilon=0)
low=v.min(axis=0)-.1; high=v.max(axis=0)+.1
points=json.loads((root/'witness-request.json').read_text())
out=[]
for item in points:
 point=np.asarray(item['point_m']); views=[]
 for axis in range(3):
  for sign in (1,-1):
   origin=point.copy(); origin[axis]=high[axis] if sign==1 else low[axis]
   direction=[0.,0.,0.]; direction[axis]=-sign
   hit=source.ray_cast(origin,direction)
   gap=float(abs(hit[0][axis]-point[axis])) if hit[0] is not None else None
   views.append(dict(axis=axis,sign=sign,first_hit_m=list(hit[0]) if hit[0] is not None else None,
                     separation_along_ray_m=gap,point_is_first_hit=bool(gap is not None and gap<=2e-6)))
 nearest=candidate.find_nearest(point)
 out.append(dict(**item,source_nearest_distance_m=source.find_nearest(point)[3],
     candidate_nearest_distance_m=nearest[3],candidate_nearest_point_m=list(nearest[0]),
     directly_visible_in_six_axes=any(x['point_is_first_hit'] for x in views),views=views))
(root/'witness-visibility.json').write_text(json.dumps(dict(witnesses=out,
 limitation='No direct visibility in six axis directions does not prove a sealed interior; oblique air access remains possible.'),indent=2),encoding='utf-8')
external={}
for key,info in json.loads((root/'views.json').read_text())['views'].items():
 depth=np.load(root/(key+'-source.npz'))['depth']; rows,cols=np.nonzero(np.isfinite(depth))
 points=np.empty((len(rows),3)); axes=info['axes']; extent=info['extent_m']; step=info['step_m']
 points[:,info['axis']]=depth[rows,cols]
 points[:,axes[0]]=extent[0]+(cols+.5)*step; points[:,axes[1]]=extent[2]+(rows+.5)*step
 distances=np.array([candidate.find_nearest(p)[3] for p in points],dtype=np.float32)
 image=np.full(depth.shape,np.nan,dtype=np.float32); image[rows,cols]=distances
 np.save(root/(key+'-external-nearest.npy'),image)
 top=int(np.argmax(distances))
 external[key]=dict(visible_ray_points=len(points),median_m=float(np.median(distances)),
     p95_m=float(np.quantile(distances,.95)),p99_m=float(np.quantile(distances,.99)),
     max_sampled_m=float(distances[top]),fraction_over_2mm=float((distances>.002).mean()),
     witness_m=points[top].tolist(),nearest_candidate_m=list(candidate.find_nearest(points[top])[0]))
 print('EXTERNAL_DISTANCE_DONE',key,external[key]['max_sampled_m'],flush=True)
(root/'external-distances.json').write_text(json.dumps(dict(views=external,
 sampling='First-hit surface points on a 2mm grid from six axes; fractions are projected-pixel weighted per view, not full surface area',
 limitation='No guarantee of maximum between rays or on surfaces hidden in all six views'),indent=2),encoding='utf-8')
print('WITNESS_VISIBILITY_DONE',len(out),flush=True)
