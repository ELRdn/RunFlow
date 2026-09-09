"""Witness-seeded original patches with a predeclared adaptive working box."""
import argparse
from pathlib import Path
import numpy as np
from local_surface_worker import surface_ref,native_surface,REPO
from local_repair_methods import begin,invalid,solid,save_solid,qc
from local_repair_mesh import grow_faces,patch_loops,normals,selected_faces,zipper,thin_shell
from runflow.shape_audit import load_surface,file_sha,source_components
from runflow.shape_fullbody import read,write,save_arrays
from runflow.local_geometry import nearest,binary_write,inspect
from repair_trial_support import manifold_backend
from manifold_surface_repair import import_manifold


def seeded(root,folder,extra):
    p=argparse.ArgumentParser();p.add_argument('--region',required=True);p.add_argument('--operation',choices=['replace','thin'],required=True)
    p.add_argument('--rings',type=int,choices=[1,2],default=1);p.add_argument('--thickness',type=float,choices=[.4,.2,.1],default=.4)
    p.add_argument('--base',default='base900');p.add_argument('--connected-base-patch',action='store_true');a=p.parse_args(extra)
    roi=next(r for r in read(root/'request.json')['regions'] if r['id']==a.region)
    recipe=dict(method='witness-seeded-'+a.operation,base=a.base,region=a.region,rings=a.rings,thickness_m=a.thickness/1000,
        seed_code_sha256=file_sha(Path(__file__)),
        connected_base_patch=a.connected_base_patch,
        source_selection='closest original face to the preexisting original-surface witness, then vertex adjacency rings',
        box_rule='Source patch and its nearest base points, expanded by 5mm; maximum span 150mm',
        parent_cache_sha256=file_sha(surface_ref(root,a.base)/'cache.json'))
    dest=begin(root,folder,recipe);sv,sf=load_surface(surface_ref(root,'cleaned'));v,f=load_surface(surface_ref(root,a.base))
    hit=nearest(native_surface(root,'cleaned'),np.array([roi['witness_m']]),dest/'seed-nearest')
    if hit[0,0]>.000002:invalid(dest,'Existing witness is not on the retained cleaned source within numeric margin');return
    source_ids=grow_faces(sf,[int(hit[0,4])],a.rings);source_points=np.unique(sf[source_ids]);patch=sf[source_ids]
    np.save(dest/'source-face-ids.npy',source_ids)
    try:sl=patch_loops(patch)
    except ValueError as e:invalid(dest,'Original seeded patch: '+str(e));return
    if len(sl)!=1:invalid(dest,'Original seeded patch has ambiguous boundary count',dict(loops=len(sl)));return
    fn=normals(np.asarray(sv),patch);axis=roi['view_axis'];sign=roi['view_sign']
    if fn[:,axis].mean()*sign<=0:
        invalid(dest,'Original patch winding faces away from the recorded view; no silent face reversal');return
    nearest_base=nearest(native_surface(root,a.base),sv[source_points],dest/'patch-to-base')
    points=np.r_[sv[source_points],np.asarray(nearest_base[:,1:4])]
    low=points.min(0)-.005;high=points.max(0)+.005
    if (high-low).max()>.15:invalid(dest,'Selected patch needs a working span above 150mm');return
    write(dest/'working-region.json',dict(low_m=low.tolist(),high_m=high.tolist(),determined_before_body_edit=True,
        source_faces_sha256=file_sha(dest/'source-face-ids.npy'),parent_cache_sha256=recipe['parent_cache_sha256']))
    if a.operation=='thin':
        try:pv,pf,_=thin_shell(sv,patch,recipe['thickness_m'])
        except ValueError as e:invalid(dest,str(e));return
        path=dest/'patch.rfmesh';binary_write(path,pv,pf);collision=inspect(path,dest/'patch-intersections')
        if not collision['intersection_free']:invalid(dest,'Seeded thin shell self-intersects',collision);return
        m=manifold_backend(REPO)
        try:detail=solid(m,pv,pf)
        except ValueError as e:invalid(dest,str(e));return
        body,info=import_manifold(m,surface_ref(root,a.base));result=body+detail
        save_solid(detail,dest/'patch-shell');save_solid(result,dest/'candidate')
        write(dest/'generation.json',dict(complete=True,base=info,source_faces=len(source_ids),added_volume_m3=result.volume()-body.volume(),
            original_outer_face_positions_fixed=True,smoothing=False,whole_body_operand=True))
        qc(root,dest)
    else:
        base_ids=selected_faces(v,f,low,high,True)
        if not len(base_ids):invalid(dest,'No full base faces inside the working region');return
        if a.connected_base_patch:
            closest=nearest(native_surface(root,a.base),np.array([roi['witness_m']]),dest/'base-seed-nearest')
            loc=np.flatnonzero(base_ids==int(closest[0,4]))
            if len(loc)!=1:invalid(dest,'Closest base face is not fully inside the working box');return
            vertices_used,inv=np.unique(f[base_ids],return_inverse=True)
            groups=source_components(v[vertices_used],inv.reshape(-1,3))
            selected_group=groups[loc[0]];all_ids=base_ids.copy();base_ids=base_ids[groups==selected_group]
            write(dest/'component-choice.json',dict(rule='Connected selected patch containing the whole-base nearest face to the original witness',
                seed_base_face=int(closest[0,4]),selected_faces=len(base_ids),retained_other_selected_faces=len(all_ids)-len(base_ids),
                semantic_part=None,human_parts_review=None))
        np.save(dest/'removed-base-face-ids.npy',base_ids)
        try:bl=patch_loops(f[base_ids])
        except ValueError as e:invalid(dest,'Base selected patch: '+str(e));return
        if len(bl)!=1:invalid(dest,'Base boundary correspondence is not unique',dict(base_loops=len(bl),source_loops=len(sl)));return
        if np.dot(normals(np.asarray(v),f[base_ids]).mean(0),fn.mean(0))<=0:invalid(dest,'Patch orientations disagree');return
        vertices=np.r_[v,sv];bridge=zipper(vertices,bl[0],sl[0]+len(v));keep=np.ones(len(f),bool);keep[base_ids]=False
        faces=np.r_[f[keep],patch+len(v),bridge];save_arrays(dest/'candidate',vertices,faces);np.save(dest/'seam-triangles.npy',bridge)
        write(dest/'generation.json',dict(complete=True,unchanged_retained_base_vertices_and_faces=True,
            original_faces=len(source_ids),removed_base_faces=len(base_ids),seam_faces=len(bridge)))
        qc(root,dest,'PASS')
