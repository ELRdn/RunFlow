"""Finite local trials against the immutable saved 0.9mm whole body."""
import argparse
from pathlib import Path
import sys
import numpy as np
from local_surface_worker import surface_ref,native_surface,REPO
from local_repair_mesh import conservative_cutter,selected_faces,patch_loops,grow_faces,zipper,thin_shell,normals
from runflow.shape_fullbody import read,write,save_arrays
from runflow.shape_audit import load_surface,file_sha,source_components
from runflow.local_geometry import binary_write,inspect,nearest,native,tools_manifest,ROOT as TOOL_ROOT
from runflow.local_repair_contract import configuration_id,candidate_verdict
from repair_trial_support import manifold_backend
from manifold_surface_repair import import_manifold


def begin(root,folder,recipe):
    request=read(root/'request.json');parent=root/'candidates';parent.mkdir(exist_ok=True)
    previous=list(parent.glob('*/recipe.json'))
    if len(previous)>=request['settings']['max_candidates']:raise ValueError('24 candidate cap reached')
    dest=parent/folder.name;dest.mkdir(exist_ok=False)
    pins={'native-build':file_sha(TOOL_ROOT/'build.json'),
        'manifold':file_sha(REPO/'.tools/manifold3d-3.5.2/install.json'),
        'operators':file_sha(Path(__file__)), 'mesh-code':file_sha(REPO/'scripts/local_repair_mesh.py')}
    recipe['configuration_id']=configuration_id(request['settings'],request['input_hashes'],pins,[recipe.copy()])
    write(dest/'recipe.json',recipe);write(dest/'state.json',dict(generation='RUNNING',measurement='UNVERIFIED',
        human_review=None,scientific_status='UNAPPROVED',ranking_eligible=False,drag_N=None,Cd=None,CdA_m2=None))
    return dest


def invalid(dest,reason,extra=None):
    write(dest/'state.json',dict(generation='PRECONDITION_FAILED',reason=reason,details=extra,
        measurement='NOT_RUN',human_review=None,scientific_status='UNAPPROVED',ranking_eligible=False,
        drag_N=None,Cd=None,CdA_m2=None))
    print('LOCAL_TRIAL_PRECONDITION',dest.name,reason,flush=True)


def solid(m,v,f):
    obj=m.Manifold(m.Mesh64(np.array(v,dtype=np.float64,copy=True,order='C'),np.array(f,dtype=np.uint64,copy=True,order='C'),tolerance=0.))
    if obj.status()!=m.Error.NoError or not obj.num_tri():raise ValueError('Not an oriented closed Manifold input')
    return obj


def save_solid(obj,folder):
    if str(obj.status())!='Error.NoError' or not obj.num_tri():raise ValueError('Boolean output invalid')
    mesh=obj.to_mesh64();return save_arrays(folder,np.asarray(mesh.vert_properties)[:,:3],np.asarray(mesh.tri_verts))


def qc(root,dest,outside='UNVERIFIED'):
    path=dest/'surface.rfmesh';binary_write(path,*load_surface(dest/'candidate'))
    collision=inspect(path,dest/'intersections');native('inspect',['topology',path,dest/'topology.json'])
    topo=read(dest/'topology.json')
    v,f=load_surface(surface_ref(root,'source'));points=np.r_[v,np.asarray(v)[f].mean(1)]
    near=nearest(path,points,dest/'screen-nearest');distance=np.asarray(near[:,0])
    worst=int(distance.argmax());lower=max(0,float(distance[worst]-2e-6))
    areas={};regional={}
    for roi in read(root/'request.json')['regions']:
        mask=((points>=roi['low_m'])&(points<=roi['high_m'])).all(1)
        regional[roi['id']]=dict(samples=int(mask.sum()),maximum_sampled_lower_m=max(0,float(distance[mask].max(initial=0)-2e-6)),
            samples_above_2mm=int((distance[mask]>.002002).sum()))
    screening=dict(complete=True,scope='All source vertices and face centroids; counterexample test only, not full Hausdorff acceptance',
        samples=len(points),maximum_lower_m=lower,witness_m=points[worst].tolist(),witness_index=worst,
        source_vertex_count=len(v),samples_above_2mm=int((distance>.002002).sum()),regions=regional,all_source_faces_retained_in_metric=True)
    write(dest/'screening.json',screening)
    checks=dict(distance='FAIL' if lower>.002 else 'UNVERIFIED',area='UNVERIFIED',
        intersection='UNVERIFIED' if collision['intersection_free'] else 'FAIL',
        topology='PASS' if topo['closed_manifold'] else 'FAIL',outside_region=outside)
    result=candidate_verdict(checks);result.update(generation='COMPLETE',measurement='SCREENING_COMPLETE',
        candidate_cache_sha256=file_sha(dest/'candidate/cache.json'),human_review=None,
        native_intersection_check='PASS' if collision['intersection_free'] else 'FAIL',
        openfoam_cross_check='NOT_RUN_WSL_ACCESS_UNAVAILABLE')
    write(dest/'state.json',result)
    print('LOCAL_CANDIDATE_SCREENED',dest.name,result['verdict'],lower,collision['intersection_pairs'],flush=True)


def carve(root,folder,a):
    recipe=dict(method='continuous-certified-carve',base=a.base,regions=a.regions.split(','),
        margin_m=a.margin/1000,observation_step_m=a.step/1000,angles_deg=[float(x) for x in a.angles.split(',')],
        collar_m=.005,cleanup='none',output_dtype='float64',voxel_remesh_passes=0,
        empty_view_policy='record unavailable free space and skip that view')
    if any(x not in (-35.,0.,35.) for x in recipe['angles_deg']):raise ValueError('Unplanned view')
    if a.base not in ('base900','reference1000'):
        parent=a.base;seen=set()
        while parent!='base900':
            if parent in seen or len(seen)>=24:raise ValueError('Invalid parent lineage')
            seen.add(parent);parent_path=surface_ref(root,parent).parent
            if read(parent_path/'state.json').get('generation')!='COMPLETE':raise ValueError('Incomplete parent')
            parent=read(parent_path/'recipe.json')['base']
        recipe['parent_cache_sha256']=file_sha(surface_ref(root,a.base)/'cache.json')
    request=read(root/'request.json');rois={r['id']:r for r in request['regions']}
    if a.atlas_regions:
        path=root/'runs/defect-sides/proposed-regions.json';additional=read(path)
        recipe['atlas_regions_sha256']=file_sha(path);rois.update({r['id']:r for r in additional['regions']})
    dest=begin(root,folder,recipe)
    if not set(recipe['regions'])<=set(rois):raise ValueError('Unknown repair region')
    m=manifold_backend(REPO);body,info=import_manifold(m,surface_ref(root,a.base));result=body
    sv,sf=load_surface(surface_ref(root,'source'));steps=[]
    for name in recipe['regions']:
        roi=rois[name];low=np.asarray(roi['low_m'])-.005;high=np.asarray(roi['high_m'])+.005
        box=m.Manifold.cube((high-low).tolist()).translate(low.tolist())
        for angle in recipe['angles_deg']:
            cfldr=dest/f'cutter-{name}-{angle:g}';cfldr.mkdir()
            cv,cf,settings=conservative_cutter(sv,sf,roi,recipe['observation_step_m'],recipe['margin_m'],angle)
            cutter=solid(m,cv,cf)^box
            if not cutter.num_tri():
                write(cfldr/'view-skipped.json',dict(status='NO_CERTIFIED_FREE_SPACE_IN_REGION',settings=settings,
                    reason='Original occluders and the conservative envelope leave no cutter inside the predeclared ROI'))
                print('OCCLUDED_VIEW_SKIPPED',name,angle,flush=True);continue
            save_solid(cutter,cfldr/'candidate');cpath=cfldr/'surface.rfmesh';binary_write(cpath,*load_surface(cfldr/'candidate'))
            native('inspect',['cutter',cpath,native_surface(root,'source'),cfldr/'certificate.json'])
            cert=read(cfldr/'certificate.json')
            if not cert['source_surface_untouched']:
                invalid(dest,'Continuous source/cutter certificate failed',dict(region=name,angle=angle,certificate=cert));return
            result=result-cutter
            if result.status()!=m.Error.NoError or not result.num_tri():raise ValueError('Whole-body difference failed')
            steps.append(dict(region=name,view=angle,settings=settings,certificate=cert,bounds_m=[low.tolist(),high.tolist()],
                cutter_cache_sha256=file_sha(cfldr/'candidate/cache.json')))
            print('CERTIFIED_LOCAL_CUT',name,angle,result.num_tri(),flush=True)
    if not steps:invalid(dest,'No certified free space in any declared view');return
    save_solid(result,dest/'candidate')
    write(dest/'generation.json',dict(complete=True,base=info,steps=steps,removed_volume_m3=body.volume()-result.volume(),
        explicit_simplification=False,float32_roundtrip=False,outside_region_equality='UNVERIFIED',
        note='Exact source/cutter predicates certify the cutter; output Boolean still requires whole-body checks'))
    qc(root,dest)


def replacement(root,folder,a):
    recipe=dict(method='original-patch-zipper',base='base900',region=a.region,rings=a.rings,collar_m=.005)
    dest=begin(root,folder,recipe);roi=next(r for r in read(root/'request.json')['regions'] if r['id']==a.region)
    v,f=load_surface(surface_ref(root,'base900'));sv,sf=load_surface(surface_ref(root,'cleaned'))
    low=np.asarray(roi['low_m'])-.005;high=np.asarray(roi['high_m'])+.005
    base_ids=selected_faces(v,f,low,high,True);seed=selected_faces(sv,sf,np.asarray(roi['low_m']),np.asarray(roi['high_m']),True)
    if not len(base_ids) or not len(seed):invalid(dest,'No whole source/candidate patch inside declared region');return
    source_ids=grow_faces(sf,seed,a.rings)
    np.save(dest/'source-face-ids.npy',source_ids);np.save(dest/'removed-base-face-ids.npy',base_ids)
    try:bl=patch_loops(f[base_ids]);sl=patch_loops(sf[source_ids])
    except ValueError as e:invalid(dest,str(e));return
    if len(bl)!=1 or len(sl)!=1:
        invalid(dest,'Boundary correspondence is not unique; human selection required',dict(base_loops=len(bl),source_loops=len(sl)));return
    source_tri=np.asarray(sv)[sf[source_ids]]
    if not ((source_tri>=low)&(source_tri<=high)).all():invalid(dest,'Source neighbor rings extend outside predeclared collar');return
    vertices=np.r_[v,sv];source_faces=sf[source_ids]+len(v)
    bridge=zipper(vertices,bl[0],sl[0]+len(v))
    # Orientation agreement is a precondition; no guessed reversal of original faces.
    bn=normals(np.asarray(v),f[base_ids]).mean(0);sn=normals(np.asarray(sv),sf[source_ids]).mean(0)
    if np.dot(bn,sn)<=0:invalid(dest,'Source and candidate patch orientation mismatch');return
    kept=np.ones(len(f),bool);kept[base_ids]=False;out=np.r_[f[kept],source_faces,bridge]
    save_arrays(dest/'candidate',vertices,out);np.save(dest/'seam-triangles.npy',bridge)
    write(dest/'generation.json',dict(complete=True,unchanged_base_vertices=True,unchanged_retained_faces=True,
        replaced_faces=len(base_ids),source_faces=len(source_ids),seam_faces=len(bridge),outside_region_equality='exact by retained arrays'))
    qc(root,dest,'PASS')


def thin(root,folder,a):
    recipe=dict(method='original-thin-shell-union',base=a.base,region=a.region,thickness_m=a.thickness/1000,collar_m=.005,
        side='Source normals inward; outer original face fixed. Side remains subject to human review.')
    dest=begin(root,folder,recipe);roi=next(r for r in read(root/'request.json')['regions'] if r['id']==a.region)
    sv,sf=load_surface(surface_ref(root,'cleaned'));ids=selected_faces(sv,sf,np.asarray(roi['low_m']),np.asarray(roi['high_m']),True)
    if not len(ids):invalid(dest,'No complete original face inside region');return
    np.save(dest/'source-face-ids.npy',ids)
    try:pv,pf,_=thin_shell(sv,sf[ids],recipe['thickness_m'])
    except ValueError as e:invalid(dest,str(e));return
    p=dest/'patch.rfmesh';binary_write(p,pv,pf);coll=inspect(p,dest/'patch-intersections')
    if not coll['intersection_free']:invalid(dest,'Thin shell self-intersects',coll);return
    m=manifold_backend(REPO)
    try:patch=solid(m,pv,pf)
    except ValueError as e:invalid(dest,str(e));return
    save_solid(patch,dest/'patch-shell');body,info=import_manifold(m,surface_ref(root,a.base));joined=body+patch
    save_solid(joined,dest/'candidate');write(dest/'generation.json',dict(complete=True,base=info,
        added_volume_m3=joined.volume()-body.volume(),source_patch_faces=len(ids),outside_region_equality='UNVERIFIED'))
    qc(root,dest)


def fit(root,folder,a):
    recipe=dict(method='component-constrained-fit',base='base900',region=a.region,mode=a.mode,
        step_m=.0001,steps=a.steps,cumulative_limit_m=.0005,collar_m=.005)
    if a.mode not in ('nearest','normal','axis') or not 1<=a.steps<=5:raise ValueError('Unplanned fit')
    dest=begin(root,folder,recipe);roi=next(r for r in read(root/'request.json')['regions'] if r['id']==a.region)
    v,f=load_surface(surface_ref(root,'base900'));sv,sf=load_surface(surface_ref(root,'cleaned'))
    pts=np.asarray(v);mask=((pts>roi['low_m'])&(pts<roi['high_m'])).all(1);ids=np.flatnonzero(mask)
    if not len(ids):invalid(dest,'No interior candidate vertices');return
    hit=nearest(native_surface(root,'cleaned'),pts[ids],dest/'correspondence');target=np.asarray(hit[:,1:4]);face_ids=np.asarray(hit[:,4],dtype=int)
    component=source_components(sv,sf);face_norm=normals(np.asarray(sv),sf)[face_ids]
    eligible=(hit[:,0]<.0005)&(hit[:,0]>2e-6)
    # Freeze original face and side, and require adjacent candidate normals to agree.
    local_faces=selected_faces(pts,f,np.asarray(roi['low_m'])-.005,np.asarray(roi['high_m'])+.005)
    cn=normals(pts,f[local_faces]);vn=np.zeros_like(pts,dtype=float)
    for k in range(3):np.add.at(vn,f[local_faces,k],cn)
    vnlen=np.linalg.norm(vn[ids],axis=1);eligible&=(np.einsum('ij,ij->i',vn[ids],face_norm)>.5*vnlen)
    ids=ids[eligible];target=target[eligible];face_norm=face_norm[eligible];face_ids=face_ids[eligible]
    if not len(ids):invalid(dest,'No small-displacement same-side correspondences');return
    np.save(dest/'vertex-ids.npy',ids);np.save(dest/'source-face-ids.npy',face_ids);np.save(dest/'source-components.npy',component[face_ids])
    delta=target-pts[ids]
    if a.mode=='normal':delta=face_norm*np.einsum('ij,ij->i',delta,face_norm)[:,None]
    if a.mode=='axis':
        axis=roi['view_axis'];tmp=np.zeros_like(delta);tmp[:,axis]=delta[:,axis];delta=tmp
    size=np.linalg.norm(delta,axis=1);scale=np.minimum(1,.0001*a.steps/np.maximum(size,1e-30));delta*=scale[:,None]
    vertices=np.array(v,dtype=float);vertices[ids]+=delta
    after=normals(vertices,f[local_faces]);inverted=np.einsum('ij,ij->i',cn,after)<=0
    if inverted.any():invalid(dest,'Proposed update flips a face',dict(flipped_faces=int(inverted.sum())));return
    # Each prescribed intermediate update is independently checked before final acceptance.
    for k in range(1,a.steps+1):
        vertices[ids]=pts[ids]+delta*k/a.steps;p=dest/f'update-{k}.rfmesh';binary_write(p,vertices,f)
        check=inspect(p,dest/f'update-{k}-intersections')
        if not check['intersection_free']:invalid(dest,'Update creates a global intersection',dict(step=k,inspection=check));return
    save_arrays(dest/'candidate',vertices,f)
    write(dest/'generation.json',dict(complete=True,moved_vertices=len(ids),maximum_displacement_m=float(np.linalg.norm(delta,axis=1).max()),
        outside_vertices_and_faces_exactly_preserved=True,correspondence_frozen=True,semantic_part=None))
    qc(root,dest,'PASS')


def dispatch(root,folder,task,extra):
    p=argparse.ArgumentParser();p.add_argument('--base',default='base900');p.add_argument('--regions',default='face-visible,hair-visible')
    p.add_argument('--region',default='face-visible');p.add_argument('--margin',type=float,default=.2);p.add_argument('--step',type=float,default=.1)
    p.add_argument('--angles',default='0');p.add_argument('--rings',type=int,choices=[1,2],default=1)
    p.add_argument('--atlas-regions',action='store_true')
    p.add_argument('--thickness',type=float,default=.4);p.add_argument('--mode',default='nearest');p.add_argument('--steps',type=int,default=1)
    a=p.parse_args(extra)
    actions={'carve':carve,'replacement':replacement,'thin':thin,'fit':fit}
    if task not in actions:raise ValueError('Unknown repair task')
    actions[task](root,folder,a)
