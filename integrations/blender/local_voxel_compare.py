"""Private local remesh experiment. No whole-body replacement or CFD admission."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time
import bpy
import bmesh
import numpy as np
from mathutils.bvhtree import BVHTree

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO/'src'))
from runflow.shape_audit import file_sha,load_surface
from runflow.shape_local import clip_surface,select_context_faces


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value


repair=module('cfd_surface',REPO/'integrations/blender/prepare_cfd_surface.py')
distance=module('distance_audit',REPO/'integrations/blender/audit_surface_distance.py')


def write(path,value): path.write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')


def save_arrays(folder,v,f):
    folder.mkdir(parents=True,exist_ok=False)
    np.save(folder/'vertices.npy',np.asarray(v,dtype=np.float64))
    np.save(folder/'triangles.npy',np.asarray(f,dtype=np.int32))
    write(folder/'cache.json',dict(output_hashes={n:file_sha(folder/n) for n in ('vertices.npy','triangles.npy')}))


def compact(v,f):
    ids,inverse=np.unique(f,return_inverse=True)
    return np.asarray(v)[ids],inverse.reshape(-1,3)


def mesh(v,f,name):
    value=bpy.data.meshes.new(name); value.from_pydata(v.tolist(),[],f.tolist()); value.update(); return value


def prepare(root,request):
    v,f=map(np.asarray,load_surface(Path(request['audit_root'])/'source'))
    cv,cf=map(np.asarray,load_surface(Path(request['audit_root'])/'candidate'))
    save_arrays(root/'raw',v,f)
    cleaned=mesh(v,f,'cleaned source'); bm=bmesh.new(); bm.from_mesh(cleaned)
    bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-6)
    bm.verts.index_update(); seen=set(); remove=[]
    for face in bm.faces:
        key=tuple(sorted(x.index for x in face.verts))
        if key in seen or face.calc_area()<1e-16: remove.append(face)
        else: seen.add(key)
    bmesh.ops.delete(bm,geom=remove,context='FACES_ONLY')
    bmesh.ops.delete(bm,geom=[e for e in bm.edges if not e.link_faces],context='EDGES')
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces)); bm.to_mesh(cleaned); bm.free()
    clean_v,clean_f=map(np.asarray,repair.arrays(cleaned)); save_arrays(root/'cleaned',clean_v,clean_f)
    for roi in request['regions']:
        folder=root/roi['id']; folder.mkdir()
        low=np.array(roi['low_m']); high=np.array(roi['high_m'])
        rv,rf,ids=clip_surface(v,f,low,high); save_arrays(folder/'source-core',rv,rf)
        np.save(folder/'source-core/source-face-ids.npy',ids)
        global_ids=select_context_faces(cv,cf,low-.05,high+.05)
        gv,gf=compact(cv,cf[global_ids]); save_arrays(folder/'global',gv,gf)
        bv,bf,bids=clip_surface(gv,gf,low,high); save_arrays(folder/'global-core',bv,bf)
        for halo in request['halos_m']:
            selected=select_context_faces(clean_v,clean_f,low-halo,high+halo)
            lv,lf=compact(clean_v,clean_f[selected])
            target=folder/('context-'+str(round(halo*1000)))
            save_arrays(target,lv,lf); np.save(target/'cleaned-face-ids.npy',selected)
            write(target/'selection.json',dict(requested_low_m=(low-halo).tolist(),requested_high_m=(high+halo).tolist(),
                actual_bbox_m=[lv.min(axis=0).tolist(),lv.max(axis=0).tolist()],faces=len(lf),
                method='Retain entire original cleaned triangles intersecting padded AABB; no slicing, capping, translation or thickness added'))
        print('LOCAL_REGION_PREPARED',roi['id'],len(rf),flush=True)


def remesh(root,request,roi,halo_um,voxel_um):
    folder=root/roi['id']/f'h{halo_um//1000}-v{voxel_um}'
    folder.mkdir(exist_ok=False)
    source=root/roi['id']/('context-'+str(halo_um//1000))
    v,f=map(np.asarray,load_surface(source))
    for ob in list(bpy.data.objects): bpy.data.objects.remove(ob,do_unlink=True)
    data=mesh(v,f,'local context'); ob=bpy.data.objects.new('local context',data)
    bpy.context.collection.objects.link(ob); bpy.context.view_layer.objects.active=ob; ob.select_set(True)
    data.remesh_voxel_size=voxel_um/1e6; data.remesh_voxel_adaptivity=0; data.use_remesh_preserve_volume=False
    started=time.monotonic(); bpy.ops.object.voxel_remesh()
    local_repair=repair.repair_voxel_degeneracy(ob.data,1e-6)
    v,f=map(np.asarray,repair.arrays(ob.data))
    if not len(f): raise ValueError('Local remesh emitted no surface')
    save_arrays(folder/'surface',v,f)
    core_v,core_f,ids=clip_surface(v,f,roi['low_m'],roi['high_m'])
    save_arrays(folder/'core',core_v,core_f)
    record=dict(voxel_m=voxel_um/1e6,halo_m=halo_um/1e6,vertices=len(v),triangles=len(f),
        core_triangles=len(core_f),local_repair=local_repair,elapsed_s=time.monotonic()-started,
        input_hashes=json.loads((source/'cache.json').read_text())['output_hashes'],
        algorithm='Blender 4.2.23 voxel_remesh; adaptivity 0; preserve volume false; no smoothing; one 1um degeneracy weld',
        scientific_status='LOCAL_DIAGNOSTIC_ONLY',whole_body_replacement=False)
    write(folder/'remesh.json',record); print('LOCAL_REMESH_COMPLETE',roi['id'],halo_um,voxel_um,len(f),flush=True)


def measure(root,request,roi,case):
    base=root/roi['id']; folder=base/case
    candidate_folder=base/'global' if case=='global' else folder/'surface'
    core_folder=base/'global-core' if case=='global' else folder/'core'
    sv,sf=load_surface(base/'source-core'); rv,rf=load_surface(root/'raw')
    cv,cf=load_surface(candidate_folder); bv,bf=load_surface(core_folder)
    if not len(bf):
        write(folder/'measurement.json',dict(complete=False,reason='Empty surface in measurement core')); return
    deadline=time.monotonic()+request['measurement_timeout_s']-10
    forward=distance.audit(sv,sf,cv,cf,folder/'forward',request['cover_m'],deadline)
    reverse=distance.audit(bv,bf,rv,rf,folder/'reverse',request['cover_m'],deadline)
    tree=BVHTree.FromPolygons(np.asarray(cv),np.asarray(cf),all_triangles=True,epsilon=0)
    point=roi.get('witness_m'); witness=None
    if point:
        hit=tree.find_nearest(point); witness=dict(distance_m=hit[3],nearest_m=list(hit[0]))
    axes=roi['axes']; axis=roi['view_axis']; sign=roi['view_sign']; step=request['ray_step_m']
    low=np.array(roi['low_m']); high=np.array(roi['high_m'])
    xs=np.arange(low[axes[0]]+step/2,high[axes[0]],step)
    ys=np.arange(low[axes[1]]+step/2,high[axes[1]],step)
    depth=np.full((len(ys),len(xs)),np.nan,dtype=np.float32)
    direction=np.zeros(3); direction[axis]=-sign
    origin=np.zeros(3); origin[axis]=cv[:,axis].max()+.01 if sign==1 else cv[:,axis].min()-.01
    for row,y in enumerate(ys):
        origin[axes[1]]=y
        for col,x in enumerate(xs):
            origin[axes[0]]=x; hit=tree.ray_cast(origin,direction)
            if hit[0] is not None: depth[row,col]=hit[0][axis]
        if time.monotonic()>deadline: raise TimeoutError('Local view timeout')
    np.save(folder/'depth.npy',depth)
    write(folder/'measurement.json',dict(complete=True,forward=forward,reverse=reverse,witness=witness,
        ray_step_m=step,depth_shape=list(depth.shape),note='Core-clipped measured surfaces; nearest target retains context. Local diagnosis, no CFD admission.'))
    print('LOCAL_MEASUREMENT_COMPLETE',roi['id'],case,flush=True)


def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True)
    p.add_argument('--stage',choices=['prepare','remesh','measure'],required=True)
    p.add_argument('--region'); p.add_argument('--halo-um',type=int); p.add_argument('--voxel-um',type=int); p.add_argument('--case')
    args=p.parse_args(sys.argv[sys.argv.index('--')+1:]); root=args.root.resolve()
    if not root.is_relative_to(REPO/'private'): raise ValueError('Private output required')
    if bpy.app.version!=(4,2,23): raise ValueError('Pinned Blender required')
    request=json.loads((root/'request.json').read_text())
    for item in request['inputs'].values():
        if file_sha(item['path'])!=item['sha256']: raise ValueError('Original input changed')
    if args.stage=='prepare': prepare(root,request); return
    roi=next(r for r in request['regions'] if r['id']==args.region)
    if args.stage=='remesh': remesh(root,request,roi,args.halo_um,args.voxel_um)
    else: measure(root,request,roi,args.case)


if __name__=='__main__': main()
