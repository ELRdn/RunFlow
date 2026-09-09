"""Independent complete distance coverage, projections, and private review measurements."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import numpy as np
from local_surface_worker import surface_ref,native_surface,REPO
from runflow.shape_audit import load_surface,file_sha,summarize_samples
from runflow.shape_fullbody import read,write
from runflow.local_geometry import native,nearest

DTYPE=np.dtype([('point','<f8',3),('distance','<f8'),('radius','<f8'),('area','<f8'),('face','<u4')])


def cover_chunks(v,f,cover):
    """Centroid balls cover every subtriangle; subdivide all four children equally."""
    batch=128 if len(f)<100000 else 20000
    for start in range(0,len(f),batch):
        tri=np.asarray(v)[f[start:start+batch]].astype(float);ids=np.arange(start,start+len(tri),dtype=np.uint32)
        while len(tri):
            centers=tri.mean(1);radius=np.linalg.norm(tri-centers[:,None],axis=2).max(1)
            done=radius<=cover
            if done.any():
                t=tri[done];out=np.zeros(len(t),dtype=DTYPE);out['point']=centers[done];out['radius']=radius[done]
                out['area']=.5*np.linalg.norm(np.cross(t[:,1]-t[:,0],t[:,2]-t[:,0]),axis=1);out['face']=ids[done]
                yield out
            tri=tri[~done];ids=ids[~done]
            if not len(tri):break
            if len(tri)>2000000:raise ValueError('Subdivision working-set face limit')
            a,b,c=tri[:,0],tri[:,1],tri[:,2];ab=(a+b)/2;bc=(b+c)/2;ca=(c+a)/2
            tri=np.concatenate((np.stack((a,ab,ca),1),np.stack((ab,b,bc),1),np.stack((ca,bc,c),1),np.stack((ab,bc,ca),1)))
            ids=np.tile(ids,4)


def distance(root,name,direction,folder,roi=None):
    from runflow.shape_local import clip_surface
    source='source' if direction=='forward' else name;target=name if direction=='forward' else 'source'
    v,f=load_surface(surface_ref(root,source));target_path=native_surface(root,target)
    cover=.001
    if roi is not None:
        v,f,_=clip_surface(v,f,roi['low_m'],roi['high_m']);cover=.0001
    if not len(f):write(folder/'result.json',dict(complete=False,reason='No measured surface in ROI'));return
    sample_path=folder/'samples.bin';query=folder/'queries.bin';count=0;zero_area=0
    with sample_path.open('xb') as out,query.open('xb') as q:
        for part in cover_chunks(v,f,cover):
            count+=len(part);zero_area+=int((part['area']==0).sum());part.tofile(out);part['point'].tofile(q)
    print('COMPLETE_COVER_GENERATED',name,direction,count,flush=True)
    native('inspect',['nearest',target_path,query,folder/'nearest.bin'])
    if (folder/'nearest.bin').stat().st_size!=count*40:raise ValueError('Partial nearest file')
    values=np.memmap(folder/'nearest.bin',dtype='<f8',mode='r',shape=(count,5))
    data=np.memmap(sample_path,dtype=DTYPE,mode='r+',shape=(count,))
    for i in range(0,count,200000):data['distance'][i:i+200000]=values[i:i+200000,0]
    data.flush()
    positive=data['area']>0
    if not positive.any():raise ValueError('No area for area-weighted statistics')
    result=summarize_samples(data[positive] if zero_area else data)
    # Zero-area faces have zero statistical weight, but their point/line supports
    # remain in both global distance bounds and in the target nearest calculation.
    worst=int(np.argmax(data['distance']));result.update(samples=len(data),zero_area_samples=zero_area,
        global_max_lower_m=max(0,float(data['distance'][worst])-2e-6),
        global_max_upper_m=float((data['distance']+data['radius']+2e-6).max()),
        measured_max_m=float(data['distance'][worst]),max_witness_m=data['point'][worst].tolist(),
        max_witness_face=int(data['face'][worst]),degenerate_supports_in_distance=True,
        max_cover_radius_m=float(data['radius'].max()))
    result.update(complete=True,direction=direction,source_triangles=len(f),
        cover_m=cover,coordinate_dtype='float64',query_sha256=file_sha(query),sample_sha256=file_sha(sample_path),
        input_cache_sha256=file_sha(surface_ref(root,source)/'cache.json'),target_cache_sha256=file_sha(surface_ref(root,target)/'cache.json'))
    write(folder/'result.json',result);print('FULL_DISTANCE_COMPLETE',name,direction,result['global_max_lower_m'],result['global_max_upper_m'],flush=True)


def adapter(root,name):
    request=read(root/'request.json');folder=root/'verification'/name
    if folder.exists():return folder
    folder.mkdir(parents=True,exist_ok=False)
    for src,dest in ((surface_ref(root,'source'),folder/'source'),(surface_ref(root,name),folder/name/'candidate')):
        dest.mkdir(parents=True)
        for file in src.glob('*.npy'):shutil.copyfile(file,dest/file.name)
        shutil.copyfile(src/'cache.json',dest/'cache.json')
    shutil.copyfile(request['old_inputs']['view-bounds']['path'],folder/'view-bounds.json')
    write(folder/'request.json',dict(regions=request['regions'],inputs=request['old_inputs']))
    original=Path(request['source_study'])/'source-metrics'
    dst=folder/'source-metrics';dst.mkdir()
    for path in original.iterdir():
        if path.suffix in ('.npy','.json','.wkb'):shutil.copyfile(path,dst/path.name)
    return folder


def visible_distances(root,name,folder):
    original=Path(read(root/'request.json')['source_study'])/'source-metrics'
    metadata=read(original/'views.json')['views'];blocks=[];layout=[]
    for label,meta in metadata.items():
        depth=np.load(original/(label+'-depth.npy'));rows,cols=np.nonzero(np.isfinite(depth))
        p=np.empty((len(rows),3));axis=meta['axis'];axes=meta['axes'];extent=meta['extent_m'];step=meta['step_m']
        p[:,axis]=depth[rows,cols];p[:,axes[0]]=extent[0]+(cols+.5)*step;p[:,axes[1]]=extent[2]+(rows+.5)*step
        blocks.append(p);layout.append((label,rows,cols,depth.shape))
    out=nearest(native_surface(root,name),np.concatenate(blocks),folder/'nearest');offset=0;records={}
    for label,rows,cols,shape in layout:
        ds=np.asarray(out[offset:offset+len(rows),0]);offset+=len(rows);im=np.full(shape,np.nan);im[rows,cols]=ds
        np.save(folder/(label+'-visible-distance.npy'),im)
        records[label]=dict(samples=len(ds),max_sampled_m=float(ds.max()),p99_m=float(np.quantile(ds,.99)),fraction_over_2mm=float((ds>.002).mean()))
    write(folder/'result.json',dict(complete=True,views=records,
        scope='Original first-hit samples from fixed whole-body views. Not a continuous exterior maximum or hidden-surface exclusion.'))


def dispatch(root,folder,extra):
    p=argparse.ArgumentParser();p.add_argument('--candidate',required=True);p.add_argument('--part',required=True)
    p.add_argument('--direction',choices=['forward','reverse']);p.add_argument('--region');a=p.parse_args(extra)
    if a.part=='distance':
        roi=next(r for r in read(root/'request.json')['regions'] if r['id']==a.region) if a.region else None
        if not a.direction:raise ValueError('Distance direction required')
        distance(root,a.candidate,a.direction,folder,roi)
    elif a.part=='visible':visible_distances(root,a.candidate,folder)
    elif a.part=='quality':
        v,f=load_surface(surface_ref(root,a.candidate));small=[];minimum=float('inf');nonfinite=0
        for i in range(0,len(f),200000):
            t=np.asarray(v)[f[i:i+200000]].astype(float)
            area=.5*np.linalg.norm(np.cross(t[:,1]-t[:,0],t[:,2]-t[:,0]),axis=1)
            minimum=min(minimum,float(area.min()));nonfinite+=int((~np.isfinite(area)).sum())
            small.extend((np.flatnonzero(area<1e-16)+i).tolist())
        np.save(folder/'near-degenerate-face-ids.npy',np.asarray(small,dtype=np.int64))
        write(folder/'result.json',dict(complete=True,triangles=len(f),area_threshold_m2=1e-16,
            near_degenerate_triangles=len(small),minimum_triangle_area_m2=minimum,nonfinite_areas=nonfinite,
            existing_area_quality_gate='FAIL' if small or nonfinite else 'PASS',
            note='Exact intersections and closed topology are separate checks; no cleanup was applied'))
    elif a.part=='provenance':
        from runflow.shape_local import clip_surface
        records={}
        for roi in read(root/'request.json')['regions']:
            for direction in ('forward','reverse'):
                measured='source' if direction=='forward' else a.candidate
                v,f=load_surface(surface_ref(root,measured));cv,cf,mapping=clip_surface(v,f,roi['low_m'],roi['high_m'])
                path=root/'runs'/('selected-'+roi['id']+'-'+direction)/'result.json';result=read(path)
                if not result.get('complete') or result['source_triangles']!=len(cf):raise ValueError('Regional face map does not match completed measurement')
                name=roi['id']+'-'+direction;np.save(folder/(name+'-original-face-ids.npy'),mapping)
                records[name]=dict(measured_cache_sha256=file_sha(surface_ref(root,measured)/'cache.json'),
                    original_face_id=int(mapping[result['max_witness_face']]),clipped_face_id=result['max_witness_face'],
                    index_namespace='Measurement result indexes clipped triangles; sidecar maps to the recorded full mesh',
                    mapping_sha256=file_sha(folder/(name+'-original-face-ids.npy')))
        write(folder/'result.json',dict(complete=True,regions=records,source_geometry_changed=False))
    elif a.part in ('projection','sections'):
        from fullbody_voxel_metrics import project,sections
        compat=adapter(root,a.candidate)
        if a.part=='projection':
            for view in ('front','side','top'):project(compat,a.candidate,view)
        else:sections(compat,a.candidate)
    elif a.part=='views':
        compat=adapter(root,a.candidate);blender=REPO/'.tools/blender/blender-4.2.23-windows-x64/blender.exe'
        worker=REPO/'integrations/blender/fullbody_voxel_compare.py'
        write(folder/'blender-pins.json',dict(binary_sha256=file_sha(blender),script_sha256=file_sha(worker),version='4.2.23'))
        subprocess.run([str(blender),'--background','--factory-startup','--threads','24','--python-exit-code','2',
            '--python',str(worker),'--','--root',str(compat),'--stage','views','--case',a.candidate],check=True)
    else:raise ValueError('Unknown verification part')
