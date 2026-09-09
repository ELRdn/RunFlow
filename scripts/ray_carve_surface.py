"""Restore observed empty space in two original views; no volumetric remeshing."""
import argparse
from pathlib import Path
import sys
import time
import numpy as np
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src')); sys.path.insert(0,str(REPO/'scripts'))
from runflow.shape_audit import load_surface,file_sha
from runflow.shape_fullbody import read,write,save_arrays


def shallow_envelope(h):
    """Erode the cutter near depth discontinuities, retaining the nearer observed surface."""
    h=np.asarray(h,dtype=float)
    if h.ndim!=2 or min(h.shape)<2 or not np.isfinite(h).all() or (h<=0).any():
        raise ValueError('Positive finite depth grid required')
    padded=np.pad(h,1,mode='edge')
    return np.minimum.reduce([padded[r:r+h.shape[0],c:c+h.shape[1]] for r in range(3) for c in range(3)])


def height_volume(us,vs,h,axis,axes,sign,outside):
    """Closed triangulated solid between a view plane and a height field, in RF metres."""
    us=np.asarray(us,float); vs=np.asarray(vs,float); h=np.asarray(h,float)
    if sorted([axis,*axes])!=[0,1,2] or sign not in (-1,1): raise ValueError('Orthogonal RF view required')
    if len(us)<2 or len(vs)<2 or h.shape!=(len(vs),len(us)) or not np.isfinite(h).all() or (h<=0).any():
        raise ValueError('Invalid positive height grid')
    if not np.isfinite(us).all() or not np.isfinite(vs).all() or not np.isfinite(outside) or (np.diff(us)<=0).any() or (np.diff(vs)<=0).any():
        raise ValueError('Increasing finite axes required')
    u,v=np.meshgrid(us,vs); n=h.size; vertices=np.zeros((2*n,3),float)
    for target in (vertices[:n],vertices[n:]): target[:,axes[0]]=u.ravel(); target[:,axes[1]]=v.ravel()
    vertices[:n,axis]=outside-sign*h.ravel(); vertices[n:,axis]=outside
    ids=np.arange(n).reshape(h.shape); a=ids[:-1,:-1].ravel(); b=ids[:-1,1:].ravel()
    c=ids[1:,:-1].ravel(); d=ids[1:,1:].ravel()
    top=np.concatenate((np.stack((a,b,d),1),np.stack((a,d,c),1)))
    bottom=top[:,[0,2,1]]+n
    perimeter=np.concatenate((ids[0,:],ids[1:,-1],ids[-1,-2::-1],ids[-2:0:-1,0]))
    nxt=np.roll(perimeter,-1)
    sides=np.concatenate((np.stack((perimeter,nxt+n,nxt),1),np.stack((perimeter,perimeter+n,nxt+n),1)))
    faces=np.concatenate((top,bottom,sides)).astype(np.int32)
    matrix=np.zeros((3,3)); matrix[axes[0],0]=1; matrix[axes[1],1]=1; matrix[axis,2]=-sign
    if np.linalg.det(matrix)<0: faces=faces[:,[0,2,1]]
    return vertices,faces


def cutters(root):
    import bpy
    from mathutils.bvhtree import BVHTree
    if bpy.app.version!=(4,2,23): raise ValueError('Pinned Blender required')
    folder=root/'ray-carve-cutters'; folder.mkdir(exist_ok=False)
    v,f=map(np.asarray,load_surface(root/'source')); tree=BVHTree.FromPolygons(v,f,all_triangles=True,epsilon=0)
    low=v.min(0)-.1; high=v.max(0)+.1; records={}
    for roi in read(root/'request.json')['regions']:
        if roi['id'] not in ('face-visible','hair-visible'): continue
        axis=roi['view_axis']; axes=roi['axes']; sign=roi['view_sign']; step=.0001
        us=np.linspace(roi['low_m'][axes[0]],roi['high_m'][axes[0]],int(np.ceil((roi['high_m'][axes[0]]-roi['low_m'][axes[0]])/step))+1)
        vs=np.linspace(roi['low_m'][axes[1]],roi['high_m'][axes[1]],int(np.ceil((roi['high_m'][axes[1]]-roi['low_m'][axes[1]])/step))+1)
        outside=high[axis] if sign==1 else low[axis]; far=low[axis] if sign==1 else high[axis]
        origin=np.zeros(3); origin[axis]=outside; direction=np.zeros(3); direction[axis]=-sign
        h=np.zeros((len(vs),len(us))); misses=0
        for row,y in enumerate(vs):
            origin[axes[1]]=y
            for col,x in enumerate(us):
                origin[axes[0]]=x; hit=tree.ray_cast(origin,direction)
                if hit[0] is None: h[row,col]=abs(far-outside); misses+=1
                else: h[row,col]=hit[3]-.0002
        if (h<=0).any(): raise ValueError('Source touches camera plane')
        filtered=shallow_envelope(h); cv,cf=height_volume(us,vs,filtered,axis,axes,sign,outside)
        info=save_arrays(folder/roi['id'],cv,cf)
        np.save(folder/(roi['id']+'-raw-depth.npy'),h); np.save(folder/(roi['id']+'-filtered-depth.npy'),filtered)
        records[roi['id']]=dict(cache=info,step_m=step,stand_off_m=.0002,axis=axis,axes=axes,sign=sign,
            outside_m=float(outside),missed_rays=misses,grid_shape=list(h.shape),
            smoothing=False,depth_rule='3x3 shallow minimum; piecewise planar closed cutting solid')
        print('OBSERVED_AIR_CUTTER',roi['id'],len(cf),flush=True)
    write(folder/'cutters.json',dict(complete=True,source_hashes=read(root/'source/cache.json')['output_hashes'],regions=records,
        voxel_remesh_passes=0,limitation='Sampled original free space, not an exact continuous visibility certificate; evaluate the resulting whole surface'))


def import_cutter(m,folder):
    # The native binding requires writable buffers even though it only imports
    # them. A float64 read-only mmap must be copied; ascontiguousarray can alias it.
    v,f=load_surface(folder)
    obj=m.Manifold(m.Mesh64(np.array(v,dtype=np.float64,order='C',copy=True),
        np.array(f,dtype=np.uint64,order='C',copy=True),tolerance=0.))
    if obj.status()!=m.Error.NoError or not obj.num_tri(): raise ValueError('Invalid closed cutter')
    return obj,dict(input_hashes=read(Path(folder)/'cache.json')['output_hashes'],input_triangles=len(f),
        imported_triangles=obj.num_tri(),status=str(obj.status()),tolerance_m=obj.get_tolerance(),
        binary_coordinates_preserved=True,writable_native_import_copy=True)


def subtract(root,base,revision):
    from repair_trial_support import manifold_backend
    from manifold_surface_repair import import_manifold
    m=manifold_backend(REPO); folder=root/(base+'-raycarve'+('2' if revision==2 else '')); folder.mkdir(exist_ok=False)
    started=time.monotonic(); body,body_info=import_manifold(m,root/base/'candidate'); before=body.volume()
    result=body; steps=[]
    for name in ('face-visible','hair-visible'):
        cutter,info=import_cutter(m,root/'ray-carve-cutters'/name)
        result=result-cutter
        if result.status()!=m.Error.NoError or not result.num_tri(): raise ValueError('Empty or invalid difference')
        steps.append(dict(region=name,cutter=info,triangles=result.num_tri(),volume_m3=result.volume()))
        print('AIR_SUBTRACTED',base,name,result.num_tri(),flush=True)
    raw=result.to_mesh64(); raw_info=save_arrays(folder/'generated',np.asarray(raw.vert_properties)[:,:3],np.asarray(raw.tri_verts))
    # Preserve manifoldness through the library's bounded simplifier, rather than
    # merging nearby but disconnected vertices after a Boolean operation.
    simplified=result.simplify(1e-6)
    if simplified.status()!=m.Error.NoError: raise ValueError('Bounded topological cleanup failed')
    simplified_mesh=simplified.to_mesh64()
    rounded=m.Manifold(m.Mesh(np.ascontiguousarray(simplified_mesh.vert_properties[:,:3],dtype=np.float32),
        np.ascontiguousarray(simplified_mesh.tri_verts,dtype=np.uint32),tolerance=0.))
    if rounded.status()!=m.Error.NoError or not rounded.num_tri(): raise ValueError('Binary32 round-trip is not manifold')
    final=rounded.to_mesh(); info=save_arrays(folder/'candidate',np.asarray(final.vert_properties)[:,:3],np.asarray(final.tri_verts))
    if rounded.volume()>before+1e-9: raise ValueError('Difference increased volume')
    write(folder/'generation.json',dict(complete=True,backend='manifold3d 3.5.2',body=body_info,steps=steps,
        raw=raw_info,candidate=info,elapsed_s=time.monotonic()-started,voxel_remesh_passes=0,
        removed_volume_m3=before-rounded.volume(),cleanup=dict(method='manifold.simplify',tolerance_m=1e-6,
            library_surface_displacement_bound_m=1e-6,independent_1um_surface_bound_verified=False,
            arbitrary_vertex_weld=False,binary32_roundtrip_status=str(rounded.status())),
        scientific_status='UNAPPROVED',ranking_eligible=False,self_intersection_verified=False))
    print('RAY_CARVE_SAVED',base,info['triangles'],flush=True)


def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True)
    p.add_argument('--stage',choices=['cutters','subtract'],required=True); p.add_argument('--base',choices=['v1000','v900'])
    p.add_argument('--revision',type=int,choices=[1,2],default=1)
    argv=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else sys.argv[1:]; a=p.parse_args(argv)
    if a.stage=='cutters': cutters(a.root)
    else:
        if a.base is None: raise ValueError('Base required')
        subtract(a.root,a.base,a.revision)


if __name__=='__main__': main()
