"""Supplemental closed-patch union after the fixed Blender Boolean reached its limit."""
import argparse
from pathlib import Path
import sys
import time
import numpy as np
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src')); sys.path.insert(0,str(REPO/'scripts'))
from runflow.shape_audit import load_surface,file_sha
from runflow.shape_fullbody import read,write,save_arrays,repair_binary


def patch(root,base):
    sys.path.insert(0,str(REPO/'integrations/blender'))
    import bpy
    from repair_fullbody_surface import solidify_patch,export_mesh,topology,release
    if bpy.app.version!=(4,2,23): raise ValueError('Pinned Blender required')
    release(); folder=root/(base+'-manifold'); folder.mkdir(exist_ok=False)
    v,f=load_surface(root/'cleaned'); ids=np.load(root/base/'detail-face-ids.npy')
    ob=solidify_patch(v,f[ids],.0004)
    info=export_mesh(ob.data,folder/'patch-shell'); topo=topology(ob.data)
    write(folder/'patch.json',dict(complete=True,cache=info,topology=topo,thickness_m=.0004,
        selection_sha256=file_sha(root/base/'detail-face-ids.npy'),blender_version=bpy.app.version_string))
    if not topo['closed']: raise ValueError('Restored patch is not a closed input to Manifold')
    print('CLOSED_DETAIL_PATCH_COMPLETE',base,flush=True)


def import_manifold(m,folder):
    v,f=load_surface(folder)
    # Native Mesh64 mutates its import buffers; mmap-backed float64 inputs are read-only.
    mesh=m.Mesh64(np.array(v,dtype=np.float64,order='C',copy=True),
                  np.array(f,dtype=np.uint64,order='C',copy=True),tolerance=0.)
    obj=m.Manifold(mesh); status=str(obj.status())
    print('MANIFOLD_IMPORT',str(folder),len(f),status,obj.num_tri(),flush=True)
    if obj.status()!=m.Error.NoError or obj.num_tri()==0: raise ValueError('Input is not accepted as an oriented manifold: '+status)
    return obj,dict(input_hashes=read(Path(folder)/'cache.json')['output_hashes'],input_triangles=len(f),
                    imported_triangles=obj.num_tri(),status=status,tolerance_m=obj.get_tolerance(),
                    note='Library import can collapse degenerates/unnecessary vertices; no explicit simplify, offset or smoothing operation')


def union(root,base):
    from repair_trial_support import manifold_backend
    m=manifold_backend(REPO); folder=root/(base+'-manifold'); started=time.monotonic()
    body,body_info=import_manifold(m,root/base/'candidate')
    detail,detail_info=import_manifold(m,folder/'patch-shell')
    write(folder/'imports.json',dict(body=body_info,detail=detail_info))
    joined=body+detail
    print('MANIFOLD_UNION_BEGIN',base,flush=True)
    status=joined.status(); count=joined.num_tri()
    if status!=m.Error.NoError or not count: raise ValueError('Manifold union failed: '+str(status))
    exported=joined.to_mesh64()
    info=save_arrays(folder/'generated',np.asarray(exported.vert_properties)[:,:3],np.asarray(exported.tri_verts))
    write(folder/'generation.json',dict(complete=True,backend='manifold3d 3.5.2',backend_commit='11235e6b8ebea2dbed8aec4285685aafd3d95667',
        status=str(status),body=body_info,detail=detail_info,output=info,elapsed_s=time.monotonic()-started,
        tolerance_m=joined.get_tolerance(),whole_body_operand=True,voxel_remesh_passes=0,scientific_status='UNAPPROVED',
        union_volume_m3=joined.volume(),imported_body_volume_m3=body.volume(),
        self_intersection_verified=False,ranking_eligible=False))
    cleanup=repair_binary(folder/'generated',folder/'candidate')
    write(folder/'cleanup.json',dict(complete=True,**cleanup))
    print('MANIFOLD_REPAIR_SAVED',base,info['triangles'],flush=True)


def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True)
    p.add_argument('--base',choices=['v1000','v900'],required=True); p.add_argument('--stage',choices=['patch','union'],required=True)
    argv=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else sys.argv[1:]
    a=p.parse_args(argv)
    if a.stage=='patch': patch(a.root,a.base)
    else: union(a.root,a.base)


if __name__=='__main__': main()
