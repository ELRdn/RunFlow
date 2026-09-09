"""Pinned whole-input Blender stages. Invoked only by the guarded study runner."""
import argparse
import gc
import importlib.util
from pathlib import Path
import sys
import time
import bpy
import bmesh
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO/'src'))
from runflow.shape_audit import load_surface
from runflow.shape_fullbody import read,write,save_arrays,finish_cache,repair_binary
from runflow.shape_local import clip_surface


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value


def export_mesh(mesh,folder):
    """Blender foreach_get -> mmap; no tuples/Python objects per output element."""
    folder=Path(folder); folder.mkdir(parents=True,exist_ok=False)
    vertices=np.lib.format.open_memmap(folder/'vertices.npy',mode='w+',dtype=np.float32,shape=(len(mesh.vertices),3))
    mesh.vertices.foreach_get('co',vertices.reshape(-1)); vertices.flush(); del vertices
    mesh.calc_loop_triangles()
    triangles=np.lib.format.open_memmap(folder/'triangles.npy',mode='w+',dtype=np.int32,shape=(len(mesh.loop_triangles),3))
    mesh.loop_triangles.foreach_get('vertices',triangles.reshape(-1)); triangles.flush(); del triangles
    return finish_cache(folder,polygons=len(mesh.polygons),corners=len(mesh.loops))


def mesh_from_arrays(v,f,name):
    mesh=bpy.data.meshes.new(name)
    mesh.vertices.add(len(v)); mesh.vertices.foreach_set('co',np.asarray(v,dtype=np.float32).reshape(-1))
    mesh.loops.add(3*len(f)); mesh.loops.foreach_set('vertex_index',np.asarray(f,dtype=np.int32).reshape(-1))
    mesh.polygons.add(len(f)); mesh.polygons.foreach_set('loop_start',np.arange(len(f),dtype=np.int32)*3)
    mesh.polygons.foreach_set('loop_total',np.full(len(f),3,dtype=np.int32)); mesh.update()
    return mesh


def prepare(root,request):
    raw=read(request['inputs']['source']['path'])
    v=np.asarray(raw['vertices'],dtype=np.float64); f=np.asarray(raw['triangles'],dtype=np.int32)
    save_arrays(root/'source',v,f)
    data=mesh_from_arrays(v,f,'common full body')
    bm=bmesh.new(); bm.from_mesh(data)
    bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-6)
    bm.verts.index_update(); seen=set(); remove=[]
    for face in bm.faces:
        key=tuple(sorted(x.index for x in face.verts))
        if key in seen or face.calc_area()<1e-16: remove.append(face)
        else: seen.add(key)
    bmesh.ops.delete(bm,geom=remove,context='FACES_ONLY')
    bmesh.ops.delete(bm,geom=[e for e in bm.edges if not e.link_faces],context='EDGES')
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces)); bm.to_mesh(data); bm.free()
    info=export_mesh(data,root/'cleaned')
    write(root/'prepare.json',dict(complete=True,source_sha256=request['inputs']['source']['sha256'],
        cleaned=info,whole_input=True,history=['1um vertex merge','duplicate/degenerate face removal',
        'unused edges removed','face normals made consistent'],coordinate_system=raw['coordinate_system'],
        unit='m',frame=0,blender_version=bpy.app.version_string))


def remesh(root,voxel_um):
    folder=root/f'v{voxel_um}'; folder.mkdir(exist_ok=False)
    v,f=load_surface(root/'cleaned'); data=mesh_from_arrays(v,f,'whole body')
    for ob in list(bpy.data.objects): bpy.data.objects.remove(ob,do_unlink=True)
    ob=bpy.data.objects.new('whole body',data); bpy.context.collection.objects.link(ob)
    bpy.context.view_layer.objects.active=ob; ob.select_set(True)
    data.remesh_voxel_size=voxel_um/1e6; data.remesh_voxel_adaptivity=0; data.use_remesh_preserve_volume=False
    start=time.monotonic(); print('VOXEL_BEGIN',voxel_um,flush=True)
    bpy.ops.object.voxel_remesh()
    print('VOXEL_GENERATED',len(ob.data.vertices),len(ob.data.polygons),len(ob.data.loops),flush=True)
    info=export_mesh(ob.data,folder/'generated')
    write(folder/'generation.json',dict(complete=True,voxel_um=voxel_um,**info,
        cleaned_input_hashes=read(root/'cleaned/cache.json')['output_hashes'],
        elapsed_s=time.monotonic()-start,blender_version=bpy.app.version_string,
        whole_input=True,adaptivity=0,preserve_volume=False,passes=1))
    emitted=ob.data
    bpy.data.objects.remove(ob,do_unlink=True)
    bpy.data.meshes.remove(emitted)
    gc.collect()
    finish_repair(root,voxel_um)
    print('FULLBODY_REMESH_COMPLETE',voxel_um,flush=True)


def finish_repair(root,voxel_um):
    folder=root/f'v{voxel_um}'; start=time.monotonic()
    if not read(folder/'generation.json')['complete']: raise ValueError('Generated checkpoint is incomplete')
    repair=repair_binary(folder/'generated',folder/'candidate')
    write(folder/'remesh.json',dict(complete=True,voxel_um=voxel_um,repair=repair,
        candidate=read(folder/'candidate/cache.json'),cleanup_elapsed_s=time.monotonic()-start))
    print('FULLBODY_CLEANUP_COMPLETE',voxel_um,flush=True)


def surface_folder(root,case): return root/'source' if case=='source' else root/case/'candidate'
def metric_folder(root,case): return root/'source-metrics' if case=='source' else root/case/'metrics'


def views(root,case,request):
    folder=metric_folder(root,case); folder.mkdir(exist_ok=True)
    v,f=map(np.asarray,load_surface(surface_folder(root,case)))
    tree=BVHTree.FromPolygons(v,f,all_triangles=True,epsilon=0)
    bounds=read(root/'view-bounds.json'); low=np.array(bounds['low_m']); high=np.array(bounds['high_m'])
    metadata={}
    specs=[]
    for axis,axes,label in [(0,(1,2),'front'),(1,(0,2),'side'),(2,(0,1),'top')]:
        for sign in (1,-1): specs.append((label+('+' if sign==1 else '-'),axis,axes,sign,low,high,.002))
    for roi in request.get('regions',[]):
        specs.append((roi['id'],roi['view_axis'],roi['axes'],roi['view_sign'],np.array(roi['low_m']),np.array(roi['high_m']),.0001))
    for key,axis,axes,sign,blo,bhi,step in specs:
        us=np.arange(blo[axes[0]]+step/2,bhi[axes[0]],step); vs=np.arange(blo[axes[1]]+step/2,bhi[axes[1]],step)
        depth=np.full((len(vs),len(us)),np.nan,dtype=np.float32)
        origin=np.zeros(3); origin[axis]=high[axis] if sign==1 else low[axis]
        direction=np.zeros(3); direction[axis]=-sign
        for row,y in enumerate(vs):
            origin[axes[1]]=float(y)
            for col,x in enumerate(us):
                origin[axes[0]]=float(x); hit=tree.ray_cast(origin,direction)
                if hit[0] is not None: depth[row,col]=hit[0][axis]
        np.save(folder/(key+'-depth.npy'),depth)
        metadata[key]=dict(axis=axis,axes=list(axes),sign=sign,step_m=step,
            extent_m=[float(us[0]-step/2),float(us[-1]+step/2),float(vs[0]-step/2),float(vs[-1]+step/2)])
        write(folder/'views.json',dict(complete=False,views=metadata)); print('FULLBODY_VIEW',case,key,flush=True)
    write(folder/'views.json',dict(complete=True,views=metadata,whole_body_targets=True,
        limitation='First-hit views are sampled; hidden surfaces and all 3D passages are not certified.'))


def distances(root,case,direction,request,timeout):
    distance=module('distance_audit',REPO/'integrations/blender/audit_surface_distance.py')
    folder=metric_folder(root,case); folder.mkdir(exist_ok=True)
    sv,sf=load_surface(root/'source'); cv,cf=load_surface(surface_folder(root,case))
    deadline=time.monotonic()+timeout-5
    if direction=='forward': distance.audit(sv,sf,cv,cf,folder/'forward',.001,deadline)
    elif direction=='reverse': distance.audit(cv,cf,sv,sf,folder/'reverse',.001,deadline)
    else:
        for roi in request['regions']:
            rv,rf,_=clip_surface(sv,sf,roi['low_m'],roi['high_m'])
            # Only measurement triangles are clipped. Nearest targets always retain the whole body.
            distance.audit(rv,rf,cv,cf,folder/(roi['id']+'-forward'),.0001,deadline)
            rv,rf,_=clip_surface(cv,cf,roi['low_m'],roi['high_m'])
            if not len(rf):
                write(folder/(roi['id']+'-reverse.json'),dict(complete=False,reason='No candidate surface in ROI')); continue
            distance.audit(rv,rf,sv,sf,folder/(roi['id']+'-reverse'),.0001,deadline)


def camera_rotation(direction):
    """Blender cameras look along local -Z with local +Y toward image top."""
    return direction.to_track_quat('-Z','Y').to_euler()


def render_hip(root,case):
    root=Path(root).resolve()
    for ob in list(bpy.data.objects): bpy.data.objects.remove(ob,do_unlink=True)
    prefs=bpy.context.preferences.addons['cycles'].preferences
    prefs.compute_device_type='HIP'; prefs.refresh_devices()
    found=False
    for device in prefs.devices:
        device.use=device.type=='HIP' and 'RX 7600' in device.name; found |= device.use
    if not found: raise RuntimeError('RX7600 HIP device unavailable')
    v,f=load_surface(surface_folder(root,case)); mesh=mesh_from_arrays(v,f,case)
    ob=bpy.data.objects.new(case,mesh); bpy.context.collection.objects.link(ob)
    material=bpy.data.materials.new('surface'); material.diffuse_color=(.12,.4,.65,1) if case=='source' else (.7,.35,.10,1)
    material.use_nodes=True; material.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=material.diffuse_color
    material.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value=.65
    mesh.materials.append(material)
    bounds=read(root/'view-bounds.json'); low=Vector(bounds['low_m']); high=Vector(bounds['high_m']); center=(low+high)/2
    scene=bpy.context.scene; scene.render.engine='CYCLES'; scene.cycles.device='GPU'; scene.cycles.samples=8
    scene.render.resolution_x=900; scene.render.resolution_y=900; scene.render.resolution_percentage=100
    scene.render.film_transparent=True; scene.world.use_nodes=True
    scene.world.node_tree.nodes['Background'].inputs['Color'].default_value=(1,1,1,1)
    scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value=.25
    for label,offset,power in [('key',(3,-4,5),700),('fill',(-3,3,3),350)]:
        light=bpy.data.lights.new(label,'AREA'); light.energy=power; light.shape='DISK'; light.size=4
        lamp=bpy.data.objects.new(label,light); bpy.context.collection.objects.link(lamp)
        lamp.location=center+Vector(offset); lamp.rotation_euler=(center-lamp.location).to_track_quat('-Z','Y').to_euler()
    cam=bpy.data.cameras.new('orthographic'); cam.type='ORTHO'; cam.ortho_scale=max(high-low)*1.07
    camera=bpy.data.objects.new('camera',cam); bpy.context.collection.objects.link(camera); scene.camera=camera
    out=metric_folder(root,case); out.mkdir(exist_ok=True)
    for axis,label in [(0,'front'),(1,'side'),(2,'top')]:
        for sign in (1,-1):
            location=center.copy(); location[axis]+=sign*5; camera.location=location
            camera.rotation_euler=camera_rotation(center-location)
            scene.render.filepath=str(out/(label+('+' if sign==1 else '-')+'-hip.png'))
            bpy.ops.render.render(write_still=True)
    write(out/'render.json',dict(complete=True,backend='Cycles HIP',device='AMD Radeon RX 7600',samples=8,
        quantitative_metrics=False,mesh_simplified=False,camera_up_axis='Y'))


def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True)
    p.add_argument('--stage',choices=['prepare','remesh','repair','views','distance','render'],required=True)
    p.add_argument('--voxel-um',type=int); p.add_argument('--case'); p.add_argument('--direction'); p.add_argument('--timeout',type=float,default=4500)
    args=p.parse_args(sys.argv[sys.argv.index('--')+1:]); root=args.root.resolve()
    if bpy.app.version!=(4,2,23): raise ValueError('Pinned Blender 4.2.23 required')
    request=read(root/'request.json')
    if args.stage=='prepare': prepare(root,request)
    elif args.stage=='remesh': remesh(root,args.voxel_um)
    elif args.stage=='repair': finish_repair(root,args.voxel_um)
    elif args.stage=='views': views(root,args.case,request)
    elif args.stage=='distance': distances(root,args.case,args.direction,request,args.timeout)
    else: render_hip(root,args.case)


if __name__=='__main__': main()
