"""Fixed-Blender surface edits of saved full bodies. No voxel-remesh operation."""
import argparse
import gc
from pathlib import Path
import shutil
import sys
import time
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO/'src'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from runflow.shape_audit import load_surface,file_sha
from runflow.shape_fullbody import read,write,finish_cache,repair_binary,save_arrays
from runflow.shape_repair import RECIPES,bounded_delta
from fullbody_voxel_compare import mesh_from_arrays,export_mesh,views,distances
from prepare_cfd_surface import topology


def tree_of(folder):
    v,f=map(np.asarray,load_surface(folder))
    return v,f,BVHTree.FromPolygons(v,f,all_triangles=True,epsilon=0)


def attach(mesh,name):
    ob=bpy.data.objects.new(name,mesh); bpy.context.collection.objects.link(ob)
    bpy.context.view_layer.objects.active=ob; ob.select_set(True)
    return ob


def release():
    for ob in list(bpy.data.objects): bpy.data.objects.remove(ob,do_unlink=True)
    for mesh in list(bpy.data.meshes):
        if not mesh.users: bpy.data.meshes.remove(mesh)
    gc.collect()


def first_visible(tree,point,low,high):
    for axis in range(3):
        for sign in (1,-1):
            origin=np.array(point,dtype=float); origin[axis]=high[axis] if sign==1 else low[axis]
            direction=np.zeros(3); direction[axis]=-sign
            hit=tree.ray_cast(origin,direction)
            if hit[0] is not None and abs(hit[0][axis]-point[axis])<=2e-6: return True
    return False


def probe(root,base):
    """Known counterexamples plus reproducible face selection, on the whole-body BVHs."""
    folder=root/base/'metrics'; folder.mkdir(parents=True,exist_ok=True)
    sv,sf,source=tree_of(root/'source'); cv,cf,candidate=tree_of(root/base/'candidate')
    request=read(root/'request.json'); low=sv.min(0)-.1; high=sv.max(0)+.1
    points=list(request.get('witnesses',[]))
    if not points: raise ValueError('Private reference witness configuration is required for new probes')
    points += [dict(id=r['id'],point_m=r['witness_m']) for r in request['regions'] if 'witness_m' in r]
    evidence=[]
    for p in points:
        h=candidate.find_nearest(p['point_m']); on=source.find_nearest(p['point_m'])[3]
        evidence.append(dict(**p,source_distance_m=on,candidate_distance_m=h[3],
            nearest_m=list(h[0]),visible_in_six_axes=first_visible(source,p['point_m'],low,high)))
    write(folder/'probe.json',dict(complete=True,witnesses=evidence,scope='Fixed witnesses only; not a global maximum',
        limitation='Six-axis invisibility does not prove a sealed interior.'))
    lower=max(max(0,p['candidate_distance_m']-p['source_distance_m']-2e-6) for p in evidence)
    write(folder/'forward-witness.json',dict(complete=False,witness_lower_m=lower,
        scope='A counterexample disproves 2mm but is not a complete global measurement'))
    # Select original cleaned faces with a visible, missing vertex or centroid; expand one vertex ring.
    v,f,cleaned=tree_of(root/'cleaned'); selected=[]
    for i,tri in enumerate(f):
        pts=np.vstack((v[tri],v[tri].mean(0)))
        if any(candidate.find_nearest(p)[3]>.001 and first_visible(source,p,low,high) for p in pts): selected.append(i)
    initial=np.array(selected,dtype=np.int32)
    ring=np.zeros(len(v),bool)
    if len(initial): ring[f[initial].reshape(-1)]=True
    selected=np.flatnonzero(ring[f].any(1)).astype(np.int32)
    np.save(root/base/'detail-face-ids.npy',selected)
    write(root/base/'detail-selection.json',dict(complete=True,initial_faces=len(initial),selected_faces=len(selected),
        source='cleaned full-body input',threshold_m=.001,neighbour_vertex_rings=1,
        selector='Any vertex/centroid >1mm from base and first-hit in at least one of six original axis views',
        face_ids_sha256=file_sha(root/base/'detail-face-ids.npy'),
        limitation='Local restoration mask, not a certificate of all visible parts; all original faces remain in the distance gate.'))
    print('REPAIR_BASELINE_RED',base,lower,'DETAIL_FACES',len(selected),flush=True)


def deform(root,base,recipe,out):
    settings=RECIPES[recipe]; v,f=load_surface(root/base/'candidate'); sv,sf,target=tree_of(root/'source')
    normals=None
    if settings['method']=='bounded_normal':
        mesh=mesh_from_arrays(v,f,'base normals')
        normals=np.empty((len(v),3),np.float32); mesh.vertices.foreach_get('normal',normals.reshape(-1))
        bpy.data.meshes.remove(mesh); gc.collect()
    out.mkdir(parents=True,exist_ok=False)
    result=np.lib.format.open_memmap(out/'vertices.npy',mode='w+',dtype=np.float32,shape=v.shape)
    maximum=0.; squared=0.; modified=0
    for start in range(0,len(v),100000):
        points=np.asarray(v[start:start+100000],dtype=float)
        nearest=np.array([target.find_nearest(p)[0] for p in points],dtype=float)
        delta=bounded_delta(nearest-points,settings['fraction'],settings['max_move_m'],
            None if normals is None else normals[start:start+len(points)])
        actual=(points+delta).astype(np.float32); shift=np.linalg.norm(actual-points,axis=1)
        if shift.max(initial=0)>settings['max_move_m']+2e-6: raise ValueError('Movement cap exceeded')
        result[start:start+len(points)]=actual
        maximum=max(maximum,float(shift.max(initial=0))); squared+=float((shift**2).sum()); modified+=int((shift>0).sum())
        if start%1000000==0: print('REPAIR_DISPLACE',recipe,start,len(v),flush=True)
    result.flush(); del result
    shutil.copyfile(root/base/'candidate/triangles.npy',out/'triangles.npy')
    return dict(**finish_cache(out),max_vertex_shift_m=maximum,rms_vertex_shift_m=(squared/len(v))**.5,
        moved_vertices=modified,faces_identical=file_sha(out/'triangles.npy')==file_sha(root/base/'candidate/triangles.npy'),
        all_base_faces_preserved=True)


def solidify_patch(v,f,thickness):
    """Original face positions are retained as the mid-surface; measure output, don't trust thickness."""
    unique,inverse=np.unique(f,return_inverse=True)
    mesh=mesh_from_arrays(v[unique],inverse.reshape(-1,3).astype(np.int32),'original detail patches')
    ob=attach(mesh,'original detail patches'); mod=ob.modifiers.new('400um centered thickness','SOLIDIFY')
    mod.solidify_mode='NON_MANIFOLD'; mod.nonmanifold_thickness_mode='CONSTRAINTS'
    mod.thickness=thickness; mod.offset=0.; mod.use_rim=True
    bpy.ops.object.modifier_apply(modifier=mod.name)
    return ob


def union_details(root,base,out):
    release(); settings=RECIPES['detail_union']
    v,f=load_surface(root/'cleaned'); selected=np.load(root/base/'detail-face-ids.npy')
    if not len(selected): raise ValueError('No selected original detail faces')
    patch=solidify_patch(v,f[selected],settings['thickness_m'])
    patch_info=export_mesh(patch.data,out.parent/'patch-shell')
    patch_topology=topology(patch.data)
    write(out.parent/'patch.json',dict(complete=True,cache=patch_info,topology=patch_topology,
        selection_sha256=file_sha(root/base/'detail-face-ids.npy'),thickness_m=settings['thickness_m'],
        exact_thickness_guaranteed=False,solidify_mode='NON_MANIFOLD',thickness_mode='CONSTRAINTS'))
    cv,cf=load_surface(root/base/'candidate'); ob=attach(mesh_from_arrays(cv,cf,'full base'),'full base')
    patch.select_set(False)
    mod=ob.modifiers.new('Restore original detail','BOOLEAN'); mod.operation='UNION'; mod.solver='EXACT'
    mod.object=patch; mod.use_self=True; mod.use_hole_tolerant=not patch_topology['closed']
    print('REPAIR_BOOLEAN_BEGIN',base,'base',len(cf),'patch',patch_info['triangles'],flush=True)
    bpy.ops.object.modifier_apply(modifier=mod.name)
    info=export_mesh(ob.data,out)
    print('REPAIR_BOOLEAN_SAVED',base,info['triangles'],flush=True)
    return dict(**info,whole_base_boolean_operand=True,patch_source='cleaned original selected face ids',
        all_original_faces_in_distance_gate=True,interior_faces_may_be_removed_by_solid_union=True,
        use_hole_tolerant=not patch_topology['closed'])


def generate(root,case):
    base,recipe=case.split('-',1); folder=root/case; folder.mkdir(exist_ok=False)
    start=time.monotonic(); raw=folder/'generated'
    info=union_details(root,base,raw) if recipe=='detail_union' else deform(root,base,recipe,raw)
    write(folder/'generation.json',dict(complete=True,recipe=RECIPES[recipe],base=base,output=info,
        base_hashes=read(root/base/'candidate/cache.json')['output_hashes'],
        elapsed_s=time.monotonic()-start,blender_version=bpy.app.version_string,voxel_remesh_passes=0))
    release()
    cleanup=repair_binary(raw,folder/'candidate')
    write(folder/'cleanup.json',dict(complete=True,**cleanup))
    print('REPAIR_GENERATION_COMPLETE',case,flush=True)


def measure(root,case,timeout):
    """Cheap strict rejection plus externally visible errors, separate from full-surface audit."""
    folder=root/case/'metrics'; folder.mkdir(exist_ok=True)
    sv,sf,source=tree_of(root/'source'); v,f,target=tree_of(root/case/'candidate')
    base=case.split('-',1)[0]
    evidence=[]
    for p in read(root/base/'metrics/probe.json')['witnesses']:
        hit=target.find_nearest(p['point_m'])
        evidence.append(dict(id=p['id'],point_m=p['point_m'],distance_m=hit[3],nearest_m=list(hit[0]),
            lower_m=max(0,hit[3]-p['source_distance_m']-2e-6)))
    write(folder/'forward-witness.json',dict(complete=False,witness_lower_m=max(p['lower_m'] for p in evidence),
        witnesses=evidence,scope='Fixed counterexamples, not a full global measurement'))
    external={}
    for key,meta in read(root/'source-metrics/views.json')['views'].items():
        depth=np.load(root/'source-metrics'/(key+'-depth.npy')); rows,cols=np.nonzero(np.isfinite(depth))
        points=np.empty((len(rows),3)); axes=meta['axes']; ext=meta['extent_m']; step=meta['step_m']
        points[:,meta['axis']]=depth[rows,cols]
        points[:,axes[0]]=ext[0]+(cols+.5)*step; points[:,axes[1]]=ext[2]+(rows+.5)*step
        ds=np.array([target.find_nearest(p)[3] for p in points],np.float32)
        image=np.full(depth.shape,np.nan,np.float32); image[rows,cols]=ds
        np.save(folder/(key+'-external-nearest.npy'),image)
        external[key]=dict(samples=len(ds),max_sampled_m=float(ds.max()) if len(ds) else None,
            p99_m=float(np.quantile(ds,.99)) if len(ds) else None,
            fraction_over_2mm=float((ds>.002).mean()) if len(ds) else None)
        print('REPAIR_VISIBLE_DISTANCE',case,key,flush=True)
    write(folder/'external-distances.json',dict(complete=True,views=external,
        scope='First-hit original surfaces, projected pixel weighting; not all surfaces or a continuous maximum'))
    del source,target; gc.collect()
    mesh=mesh_from_arrays(v,f,'topology'); topo=topology(mesh)
    write(folder/'topology.json',dict(complete=True,**topo,self_intersection_verified=False))
    release()


def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True)
    p.add_argument('--stage',choices=['probe','generate','measure','views','distance'],required=True)
    p.add_argument('--case',required=True); p.add_argument('--direction'); p.add_argument('--timeout',type=float,default=4500)
    a=p.parse_args(sys.argv[sys.argv.index('--')+1:]); root=a.root
    if bpy.app.version!=(4,2,23): raise ValueError('Pinned Blender 4.2.23 required')
    if a.stage=='probe': probe(root,a.case)
    elif a.stage=='generate': generate(root,a.case)
    elif a.stage=='measure': measure(root,a.case,a.timeout)
    elif a.stage=='views': views(root,a.case,read(root/'request.json'))
    else: distances(root,a.case,a.direction,read(root/'request.json'),a.timeout)


if __name__=='__main__': main()
