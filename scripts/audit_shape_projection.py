"""Continuous projected-silhouette comparison of cached private geometry."""
import argparse
import json
from pathlib import Path
import time
import shutil
import shapely
from shapely.geometry import Polygon
from runflow.shape_audit import load_surface
from runflow.shape_projection import project_mesh,compare_projections,_hole_stats


def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True)
    p.add_argument('--view',choices=['front','side','top'])
    p.add_argument('--grid-m',type=float,default=0.); args=p.parse_args()
    if not 0<=args.grid_m<=1e-8: raise ValueError('Diagnostic 2D precision grid must be <= 10nm')
    root=args.root; result={}; started=time.monotonic()
    for view,axes in [('front',(1,2)),('side',(0,2)),('top',(0,1))]:
        if args.view and view!=args.view: continue
        geometries=[]
        for name in ('source','candidate'):
            print('PROJECTION_START',view,name,flush=True)
            shape=project_mesh(*load_surface(root/name),axes=axes,grid_size=args.grid_m or None)
            if args.grid_m: shape=shapely.set_precision(shape,args.grid_m)
            if not shape.is_valid: raise ValueError('Invalid union geometry')
            path=root/(view+'-'+name+'.wkb')
            if path.exists():
                archive=root/'prior-projection-output'; archive.mkdir(exist_ok=True)
                target=archive/path.name
                if target.exists(): raise ValueError('Projection evidence archive already exists')
                shutil.copyfile(path,target)
            path.write_bytes(shapely.to_wkb(shape))
            geometries.append(shape)
            print('PROJECTION_READY',view,name,shape.area,flush=True)
        a,b=geometries
        comparison=compare_projections(a,b)
        _,_,holes=_hole_stats(a)
        comparison['source_holes_at_least_1_mm2']=[]
        for hole in sorted(holes,key=lambda g:g.area,reverse=True):
            if hole.area<1e-6: continue
            fill=hole.intersection(b).area
            comparison['source_holes_at_least_1_mm2'].append(dict(area_mm2=hole.area*1e6,
                filled_mm2=fill*1e6,filled_fraction=fill/hole.area,bbox_m=list(hole.bounds)))
        comparison['axes']=axes
        comparison['precision_grid_m']=args.grid_m
        result[view]=comparison
        destination=root/('projection-'+args.view+'.json' if args.view else 'projections.json')
        destination.write_text(json.dumps(dict(views=result,complete=False),indent=2),encoding='utf-8')
    destination.write_text(json.dumps(dict(views=result,complete=True,
        elapsed_s=time.monotonic()-started,shapely_version=shapely.__version__,
        precision_grid_m=args.grid_m,
        method='All projected triangles unioned without rasterization or face culling; explicit optional 2D precision grid; 3D inputs untouched'),indent=2),encoding='utf-8')
    print('PROJECTION_AUDIT_COMPLETE',flush=True)


if __name__=='__main__': main()
