"""Guarded diagnostic and repair payload; operates only in a prepared private study."""
import argparse
from pathlib import Path
import sys
import time
import numpy as np
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'));sys.path.insert(0,str(REPO/'scripts'))
from runflow.shape_fullbody import read,write,save_arrays
from runflow.shape_audit import load_surface,file_sha,source_components
from runflow.local_geometry import export_cache,inspect,nearest,binary_write

def surface_ref(root,name):
    request=read(root/'request.json')
    if name in request['input_surfaces']:
        ref=request['input_surfaces'][name];path=Path(ref['path'])
        if file_sha(path/'cache.json')!=ref['cache_sha256']:raise ValueError('Input cache changed')
        load_surface(path);return path
    path=root/'candidates'/name/'candidate'
    if not path.resolve().is_relative_to((root/'candidates').resolve()):raise ValueError('Invalid candidate')
    load_surface(path);return path

def native_surface(root,name):
    folder=root/'native-inputs';folder.mkdir(exist_ok=True);path=folder/(name+'.rfmesh')
    source=surface_ref(root,name)
    if path.exists():
        meta=read(folder/(name+'.json'))
        if file_sha(path)!=meta['sha256'] or meta['cache_sha256']!=file_sha(source/'cache.json'):raise ValueError('Native input changed')
    else:
        meta=export_cache(source,path);meta['cache_sha256']=file_sha(source/'cache.json');write(folder/(name+'.json'),meta)
    return path

def intersections(root,name,folder):
    path=native_surface(root,name);result=inspect(path,folder/'intersection')
    result.update(surface=name,input_sha256=file_sha(path),source_cache_sha256=file_sha(surface_ref(root,name)/'cache.json'))
    write(folder/'result.json',result)

def atlas(root,folder):
    v,f=load_surface(surface_ref(root,'source'));tri=np.asarray(v)[f];centers=tri.mean(1)
    points=np.concatenate((v,centers));out=nearest(native_surface(root,'base900'),points,folder/'base-nearest')
    center_d=np.array(out[len(v):,0]);vertex_d=np.asarray(out[:len(v),0]);radii=np.linalg.norm(tri-centers[:,None],axis=2).max(1)
    vertex_max=vertex_d[f].max(1);face_lower=np.maximum(center_d,vertex_max)-2e-6;face_upper=center_d+radii+2e-6
    comp=source_components(v,f);np.save(folder/'source-components.npy',comp)
    np.save(folder/'face-distance-bounds.npy',np.column_stack((face_lower,face_upper,center_d,vertex_max)))
    np.save(folder/'nearest-source-vertices.npy',np.asarray(out[:len(v)]));np.save(folder/'nearest-source-centers.npy',np.asarray(out[len(v):]))
    areas=.5*np.linalg.norm(np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]),axis=1)
    records=[]
    for c in np.unique(comp):
        ids=np.flatnonzero(comp==c);bad=ids[face_lower[ids]>.002];possible=ids[face_upper[ids]>.002]
        if not len(possible):continue
        worst=ids[int(np.argmax(face_lower[ids]))]
        records.append(dict(id=int(c),triangles=int(len(ids)),definite_counterexample_faces=int(len(bad)),possible_exceedance_faces=int(len(possible)),
            sampled_max_lower_m=max(0,float(face_lower[worst])),conservative_upper_m=float(face_upper[ids].max()),
            witness_source_face=int(worst),witness_center_m=centers[worst].tolist(),bbox_m=[tri[ids].min((0,1)).tolist(),tri[ids].max((0,1)).tolist()],
            triangle_area_m2=float(areas[ids].sum()),semantic_part=None,visibility_class='UNVERIFIED',repair_class='UNCLASSIFIED'))
    records.sort(key=lambda x:-x['sampled_max_lower_m'])
    write(folder/'defect-atlas.json',dict(complete=True,source_cache_sha256=file_sha(surface_ref(root,'source')/'cache.json'),
        base_cache_sha256=file_sha(surface_ref(root,'base900')/'cache.json'),source_triangles=len(f),components=records,
        samples=len(points),scope='All source faces have bounds from vertices and centroid; coarse diagnosis, not 1mm-cover full acceptance',
        excludes_internal_faces=False,semantic_parts_review=None))
    print('DEFECT_ATLAS_COMPLETE',len(records),flush=True)

def precision(root,folder):
    from repair_trial_support import manifold_backend
    from manifold_surface_repair import import_manifold
    m=manifold_backend(REPO)
    obj,imported=import_manifold(m,surface_ref(root,'raw_carve64'))
    records={};parent=root/'candidates';parent.mkdir(exist_ok=True)
    stages=[('raw-import64',obj.to_mesh64())]
    simplified=obj.simplify(1e-6);sm=simplified.to_mesh64();stages.append(('simplified64',sm))
    for name,mesh in stages:
        path=parent/name;path.mkdir(exist_ok=False);meta=save_arrays(path/'candidate',np.asarray(mesh.vert_properties)[:,:3],np.asarray(mesh.tri_verts))
        records[name]=meta
    path=parent/'rounded32';path.mkdir(exist_ok=False)
    records['rounded32']=save_arrays(path/'candidate',np.asarray(sm.vert_properties)[:,:3].astype(np.float32),np.asarray(sm.tri_verts))
    write(folder/'precision-stages.json',dict(complete=True,imported=imported,stages=records,
        note='Diagnostic re-execution from saved post-Boolean float64 state; no new voxel mesh. No scientific acceptance.'))


def reimport32(root,folder):
    from repair_trial_support import manifold_backend
    m=manifold_backend(REPO);v,f=load_surface(surface_ref(root,'rounded32'))
    obj=m.Manifold(m.Mesh(np.array(v,dtype=np.float32,copy=True),np.array(f,dtype=np.uint32,copy=True),tolerance=0.))
    if obj.status()!=m.Error.NoError:raise ValueError('Binary32 diagnostic reimport failed')
    mesh=obj.to_mesh();dest=root/'candidates/reimport32';dest.mkdir(exist_ok=False)
    info=save_arrays(dest/'candidate',np.asarray(mesh.vert_properties)[:,:3],np.asarray(mesh.tri_verts))
    write(folder/'precision-reimport.json',dict(complete=True,output=info,
        original_output_equal=info['output_hashes']==read(surface_ref(root,'old_carve32')/'cache.json')['output_hashes']))

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--label',required=True);p.add_argument('--task',required=True);p.add_argument('--surface',default='base900')
    a,extra=p.parse_known_args();root=a.root.resolve();folder=root/'runs'/a.label
    for item in read(root/'request.json')['old_inputs'].values():
        if file_sha(item['path'])!=item['sha256']:raise ValueError('Pinned original or reference input changed')
    if a.task=='intersections':intersections(root,a.surface,folder)
    elif a.task=='atlas':atlas(root,folder)
    elif a.task=='precision':precision(root,folder)
    elif a.task=='reimport32':reimport32(root,folder)
    elif a.task=='verify':
        from local_repair_verify import dispatch
        dispatch(root,folder,extra)
    elif a.task=='diagnostics':
        from local_repair_diagnostics import diagnose
        diagnose(root,folder)
    elif a.task=='classify':
        from local_repair_diagnostics import classify_sides
        classify_sides(root,folder)
    elif a.task=='seed':
        from local_repair_seed import seeded
        seeded(root,folder,extra)
    elif a.task=='manual':
        from local_repair_manual import replay
        replay(root,folder,extra)
    elif a.task=='finish-evidence':
        from finish_local_repair_evidence import finish
        p=argparse.ArgumentParser();p.add_argument('--selected',required=True)
        finish(root,folder,p.parse_args(extra).selected)
    elif a.task=='report':
        from report_local_surface_repair import report
        p=argparse.ArgumentParser();p.add_argument('--selected',required=True)
        report(root,p.parse_args(extra).selected)
    else:
        from local_repair_methods import dispatch
        dispatch(root,folder,a.task,extra)

if __name__=='__main__':main()
