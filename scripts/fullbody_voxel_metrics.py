"""Guarded CPU measurements; projection workers share read-only binary files."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import time
import numpy as np
import shapely
from runflow.shape_fullbody import read,write,PLANES,edge_topology
from runflow.shape_audit import load_surface
from runflow.shape_projection import project_mesh,compare_projections,_hierarchical_union,_hole_stats
from runflow.shape_sections import section_segments


def union_chunk(args):
    folder,axes,start,end=args
    v=np.load(Path(folder)/'vertices.npy',mmap_mode='r'); f=np.load(Path(folder)/'triangles.npy',mmap_mode='r')
    return shapely.to_wkb(project_mesh(v,f[start:end],axes=axes,grid_size=1e-9))


def projection(folder,axes):
    v,f=load_surface(folder)
    if len(f)<200000: return shapely.set_precision(project_mesh(v,f,axes=axes,grid_size=1e-9),1e-9)
    tasks=((str(folder),axes,i,min(i+200000,len(f))) for i in range(0,len(f),200000))
    pieces=[]
    with ProcessPoolExecutor(max_workers=8) as pool:
        for i,wkb in enumerate(pool.map(union_chunk,tasks)):
            pieces.append(shapely.from_wkb(wkb))
            if i%10==0: print('PROJECTION_CHUNKS',i+1,(len(f)+199999)//200000,flush=True)
    return shapely.set_precision(_hierarchical_union(pieces,grid_size=1e-9),1e-9)


def project(root,case,view):
    axes={'front':(1,2),'side':(0,2),'top':(0,1)}[view]
    source_path=root/'source-metrics'/(view+'.wkb')
    if not source_path.exists():
        source=projection(root/'source',axes); source_path.parent.mkdir(exist_ok=True)
        source_path.write_bytes(shapely.to_wkb(source))
    source=shapely.from_wkb(source_path.read_bytes())
    if case=='source': return
    folder=root/case/'metrics'; folder.mkdir(exist_ok=True)
    candidate=projection(root/case/'candidate',axes)
    if not candidate.is_valid: raise ValueError('Invalid projected geometry')
    (folder/(view+'.wkb')).write_bytes(shapely.to_wkb(candidate))
    result=compare_projections(source,candidate)
    # Use original historical hole geometry as the stable region identifier.
    request=read(root/'request.json'); reference=shapely.from_wkb(Path(request['inputs']['projection-'+view]['path']).read_bytes())
    _,_,holes=_hole_stats(reference); _,_,remaining_holes=_hole_stats(candidate)
    bounded=shapely.union_all(remaining_holes) if remaining_holes else shapely.GeometryCollection()
    hole_records=[]
    for index,hole in enumerate(sorted((h for h in holes if h.area>=1e-6),key=lambda h:h.area,reverse=True)):
        unfilled=hole.difference(candidate); filled=hole.intersection(candidate)
        retained=unfilled.intersection(bounded); opened=unfilled.difference(bounded)
        connected=[h for h in remaining_holes if h.intersects(unfilled)]
        expanded=shapely.union_all(connected).difference(hole).area if connected else 0.
        hole_records.append(dict(id=f'{view}-{index}',area_mm2=hole.area*1e6,
            filled_mm2=filled.area*1e6,filled_fraction=filled.area/hole.area,
            retained_bounded_mm2=retained.area*1e6,opened_to_exterior_mm2=opened.area*1e6,
            connected_hole_expansion_mm2=expanded*1e6,bbox_m=list(hole.bounds)))
    result.update(complete=True,axes=axes,precision_grid_m=1e-9,original_holes=hole_records,
        holes_note='Original view-dependent background regions; filling, expansion and opening are distinct. Not 3D flow connectivity.')
    for roi in request['regions']:
        if roi['axes']!=list(axes): continue
        box=shapely.box(roi['low_m'][axes[0]],roi['low_m'][axes[1]],roi['high_m'][axes[0]],roi['high_m'][axes[1]])
        a=source.intersection(box); b=candidate.intersection(box)
        local=compare_projections(a,b) if a.area else dict(source_m2=0,candidate_m2=b.area)
        if 'gap_input' in roi:
            gap=shapely.from_wkb(Path(request['inputs'][roi['gap_input']]['path']).read_bytes())
            local['gap_filled_fraction']=gap.intersection(candidate).area/gap.area
        local['whole_body_projection']=True
        write(folder/(roi['id']+'-projection.json'),local)
    write(folder/('projection-'+view+'.json'),result)
    print('FULLBODY_PROJECTION',case,view,result['relative_change'],flush=True)


def sections(root,case):
    folder=root/'source-metrics' if case=='source' else root/case/'metrics'
    folder.mkdir(exist_ok=True); surface=root/'source' if case=='source' else root/case/'candidate'
    v,f=load_surface(surface); results={}
    for label,axis,value in PLANES:
        segments,coplanar=section_segments(v,f,axis,value)
        np.save(folder/(label+'-section.npy'),segments)
        results[label]=dict(axis=axis,value_m=value,segments=len(segments),coplanar_triangles=coplanar)
    write(folder/'sections.json',dict(complete=True,sections=results))


def reference_match(root):
    request=read(root/'request.json'); old_v,old_f=load_surface(Path(request['reference_cache']))
    v,f=load_surface(root/'v1000/candidate')
    # Triangle coordinate equality independent of unused vertices and vertex renumbering.
    if len(f)!=len(old_f):
        write(root/'reference-1mm.json',dict(complete=True,triangle_count_equal=False,surface_equal_in_order=False,
            reason='Triangle count differs; no equivalence claim')); return
    maximum=0.
    for i in range(0,len(f),200000):
        a=np.asarray(v)[f[i:i+200000]].astype(float); b=np.asarray(old_v)[old_f[i:i+200000]].astype(float)
        maximum=max(maximum,float(np.linalg.norm(a-b,axis=2).max()))
    write(root/'reference-1mm.json',dict(complete=True,triangle_count_equal=True,
        maximum_corresponding_corner_difference_m=maximum,surface_equal_in_order=maximum<=2e-6,
        tolerance_m=2e-6,unused_vertices_do_not_affect_comparison=True,
        note='Ordered triangle coordinate comparison; mismatch does not prove unequal geometric surfaces.'))


def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True)
    p.add_argument('--stage',choices=['projection','sections','topology','reference'],required=True)
    p.add_argument('--case'); p.add_argument('--view'); args=p.parse_args(); root=args.root
    if args.stage=='projection': project(root,args.case,args.view)
    elif args.stage=='sections': sections(root,args.case)
    elif args.stage=='reference': reference_match(root)
    else: edge_topology(root/args.case/'candidate',root/args.case/'metrics')


if __name__=='__main__': main()
