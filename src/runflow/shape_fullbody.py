"""Contracts and binary geometry helpers for the private full-body study."""
import json
from pathlib import Path
import itertools
import numpy as np
from runflow.shape_audit import file_sha, load_surface

GIB=1024**3
VOXELS=(1000,500,250,100)
GENERATION_SECONDS=(900,2700,5400,12600)
TRANSITION_VOXELS=(900,800,700,600)
LIMITS=dict(private_commit_bytes=80*GIB,min_available_ram_bytes=8*GIB,
    min_commit_headroom_bytes=16*GIB,output_bytes=300*GIB,
    disk_free_bytes={'E:\\':50*GIB,'C:\\':20*GIB,'D:\\':15*GIB})
PLANES=[('sagittal',1,0.),('raised-foot',2,.83),('knee',2,.55),
        ('waist-hands',2,1.02),('head-hair',2,1.38),('ears',2,1.58)]


def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def write(path,value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8'); tmp.replace(path)


def study_profile(request):
    """Two explicitly authorized four-condition profiles; no implicit unit conversion."""
    values=request.get('voxel_sizes_um',list(VOXELS))
    if not isinstance(values,list) or any(type(v) is not int for v in values):
        raise ValueError('Integer micrometre resolutions required')
    voxels=tuple(values)
    if voxels==VOXELS: return voxels,GENERATION_SECONDS
    if voxels==TRANSITION_VOXELS: return voxels,(2700,)*4
    raise ValueError('Four fixed resolutions required: coarse or 900/800/700/600 um')


def validate_request(request):
    if request.get('kind')!='fullbody_voxel_comparison_v1': raise ValueError('Wrong study kind')
    if 'voxel_sizes_um' not in request: raise ValueError('Four fixed resolutions required')
    study_profile(request)
    if request.get('frame')!=0 or request.get('adoption')!='adopted-002': raise ValueError('Wrong adoption/frame')
    for item in request['inputs'].values():
        if file_sha(item['path'])!=item['sha256']: raise ValueError('Input hash mismatch')
    raw=read(request['inputs']['source']['path'])
    if raw.get('unit')!='m' or raw.get('coordinate_system')!='RF_X_FORWARD_Z_UP':
        raise ValueError('Metres and RF coordinates required')
    manifest=read(request['inputs']['manifest']['path'])
    capture=next((a for a in manifest['assets'] if a['path']=='unity-a/runflow_capture_f0000.snapshot.json'),None)
    if capture is None or capture['sha256']!=request['inputs']['source']['sha256']:
        raise ValueError('Source is not adopted frame 0')
    if manifest['source']['character_id']!='1006' or manifest['source']['costume_id']!='100602':
        raise ValueError('Wrong adopted character or costume')
    return raw


def private_root(path,repo,existing=False):
    path=Path(path).resolve()
    if not any(path.is_relative_to(p.resolve()) and path!=p.resolve() for p in
               (Path(repo)/'private',Path('E:/RunFlowPrivate'))):
        raise ValueError('Fresh dedicated private study root required')
    if existing and not path.is_dir(): raise ValueError('Paused study root missing')
    if not existing and path.exists(): raise ValueError('Output already exists')
    return path


def finish_cache(folder,**extra):
    folder=Path(folder)
    v=np.load(folder/'vertices.npy',mmap_mode='r'); f=np.load(folder/'triangles.npy',mmap_mode='r')
    if v.ndim!=2 or v.shape[1]!=3 or f.ndim!=2 or f.shape[1]!=3 or not len(f):
        raise ValueError('Empty or malformed surface')
    for i in range(0,len(v),1000000):
        if not np.isfinite(v[i:i+1000000]).all(): raise ValueError('Nonfinite coordinates')
    if f.min()<0 or f.max()>=len(v): raise ValueError('Bad vertex index')
    info=dict(vertices=len(v),triangles=len(f),bbox_m=[v.min(0).tolist(),v.max(0).tolist()],
        output_hashes={n:file_sha(folder/n) for n in ('vertices.npy','triangles.npy')},**extra)
    write(folder/'cache.json',info); return info


def save_arrays(folder,v,f):
    folder=Path(folder); folder.mkdir(parents=True,exist_ok=False)
    np.save(folder/'vertices.npy',v); np.save(folder/'triangles.npy',np.asarray(f,dtype=np.int32))
    return finish_cache(folder)


def prediction(previous,voxel_um):
    """Estimate only; never report an unattempted resolution as measured failure."""
    if not previous: return None
    old=previous[-1]; scale=(old['voxel_um']/voxel_um)**2
    corners=int(old['corners']*scale)
    return dict(basis_voxel_um=old['voxel_um'],area_scaling_factor=scale,
        predicted_corners=corners,method='surface area / voxel width squared; estimate, not measurement',
        skip_reason='predicted Blender signed-32-bit corner overflow' if corners>=2**31-1 else None)


def repair_binary(source,output,weld_m=1e-6):
    """Equivalent local degenerate-vertex merge without duplicating a full BMesh.

    Never removes a positive-area nondegenerate triangle. No general weld.
    Representatives are existing vertices with direct distances <= 1um.
    """
    source=Path(source); output=Path(output); v,f=load_surface(source)
    bad_ids=[]; bad_count=0
    for i in range(0,len(f),200000):
        faces=np.asarray(f[i:i+200000]); t=np.asarray(v)[faces].astype(np.float64)
        areas=np.linalg.norm(np.cross(t[:,1]-t[:,0],t[:,2]-t[:,0]),axis=1)*.5
        bad=areas<1e-16; bad_count+=int(bad.sum())
        if bad.any(): bad_ids.extend(np.unique(faces[bad]).tolist())
    ids=sorted(set(bad_ids)); cells={}; replacements={}; distances=[]
    offsets=list(itertools.product((-1,0,1),repeat=3))
    for i in ids:
        point=v[i].astype(float); cell=tuple(np.floor(point/weld_m).astype(np.int64))
        nearby=[]
        for offset in offsets:
            nearby.extend(cells.get(tuple(c+d for c,d in zip(cell,offset)),()))
        # Original implementation picked the first retained vertex in ascending ID order,
        # not the nearest one. Preserve that rule exactly across neighbouring bins.
        target=next((j for j in sorted(nearby) if np.linalg.norm(v[j].astype(float)-point)<=weld_m),None)
        if target is None: cells.setdefault(cell,[]).append(i)
        else: replacements[i]=target; distances.append(float(np.linalg.norm(v[target].astype(float)-v[i])))
    output.mkdir(parents=True,exist_ok=False)
    used=np.zeros(len(v),dtype=bool); removed=[]; count=0
    remap=np.arange(len(v),dtype=np.int32)
    for a,b in replacements.items(): remap[a]=b
    # At most the tiny degenerate neighbourhood is mapped. Keep original indices until compaction.
    temp=output/'faces.partial.bin'
    with temp.open('wb') as stream:
        for i in range(0,len(f),200000):
            faces=remap[np.asarray(f[i:i+200000])]
            repeated=(faces[:,0]==faces[:,1])|(faces[:,1]==faces[:,2])|(faces[:,2]==faces[:,0])
            removed.extend((np.flatnonzero(repeated)+i).tolist())
            faces=faces[~repeated]; used[faces]=True; faces.tofile(stream); count+=len(faces)
    if not count: raise ValueError('Empty repaired surface')
    mapping=np.cumsum(used,dtype=np.int32)-1
    outv=np.lib.format.open_memmap(output/'vertices.npy',mode='w+',dtype=v.dtype,shape=(int(used.sum()),3))
    offset=0
    for i in range(0,len(v),200000):
        block=np.asarray(v[i:i+200000])[used[i:i+200000]]; outv[offset:offset+len(block)]=block; offset+=len(block)
    outv.flush(); del outv
    tempf=np.memmap(temp,dtype=np.int32,mode='r',shape=(count,3))
    outf=np.lib.format.open_memmap(output/'triangles.npy',mode='w+',dtype=np.int32,shape=(count,3))
    for i in range(0,count,200000): outf[i:i+200000]=mapping[tempf[i:i+200000]]
    outf.flush(); del outf,tempf; temp.unlink()
    record=dict(method='local_degenerate_direct_weld_binary_v1',weld_m=weld_m,
        degenerate_triangles_before=bad_count,affected_vertices=len(ids),merged_vertices=len(replacements),
        max_vertex_shift_m=max(distances,default=0),replacements=[dict(vertex_index=a,target_index=b) for a,b in replacements.items()],
        removed_collapsed_faces=removed,removed_unused_vertices=int((~used).sum()),
        smoothing=False,added_thickness=False,part_deletion=False)
    finish_cache(output); write(output/'repair.json',record); return record


def edge_topology(folder,output):
    """Disk-backed edge incidence; vertex-fan and self-intersections stay unverified."""
    v,f=load_surface(folder); output=Path(output); output.mkdir(exist_ok=True)
    buckets=64; paths=[output/f'edges-{i:02}.bin' for i in range(buckets)]
    dtype=np.dtype([('key','<u8'),('direction','i1')]); degenerate=0
    for start in range(0,len(f),200000):
        faces=np.asarray(f[start:start+200000]); t=np.asarray(v)[faces].astype(float)
        degenerate+=int((np.linalg.norm(np.cross(t[:,1]-t[:,0],t[:,2]-t[:,0]),axis=1)*.5<1e-16).sum())
        edges=faces[:,[0,1,1,2,2,0]].reshape(-1,2).astype(np.uint64)
        lo=edges.min(1); hi=edges.max(1); bins=lo%buckets
        data=np.empty(len(edges),dtype=dtype); data['key']=(lo<<np.uint64(32))|hi
        data['direction']=np.where(edges[:,0]<edges[:,1],1,-1)
        for i,path in enumerate(paths):
            with path.open('ab') as stream: data[bins==i].tofile(stream)
    boundary=nonmanifold=inconsistent=total=0
    for path in paths:
        if not path.stat().st_size: path.unlink(); continue
        data=np.memmap(path,dtype=dtype,mode='r+'); data.sort(order='key')
        # A bucket is ~1/64 of all edges; allocation remains bounded by bucket size.
        starts=np.r_[0,np.flatnonzero(data['key'][1:]!=data['key'][:-1])+1]
        counts=np.diff(np.r_[starts,len(data)])
        sums=np.add.reduceat(data['direction'].astype(np.int32),starts)
        total+=len(starts); boundary+=int((counts==1).sum()); nonmanifold+=int((counts!=2).sum())
        inconsistent+=int(((counts==2)&(sums!=0)).sum())
        del data; path.unlink()
    result=dict(vertices=len(v),triangles=len(f),edges=total,boundary_edges=boundary,
        nonmanifold_edges=nonmanifold,inconsistent_edges=inconsistent,degenerate_faces=degenerate,
        nonmanifold_vertices=None,self_intersection_verified=False,closed=None,
        edge_checks_complete=True,vertex_fans_verified=False,
        note='Edge incidence is not a complete manifold/solid certificate.')
    write(output/'topology.json',result); return result
