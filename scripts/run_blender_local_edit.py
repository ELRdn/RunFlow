"""Bounded local native-Blender experiment; never adopts or launches CFD."""
import argparse
from pathlib import Path
import subprocess
import sys
import time
import numpy as np
REPO=Path(__file__).resolve().parents[1];sys.path.insert(0,str(REPO/'src'))
from runflow.core import read,write,file_hash,digest
from runflow.local_geometry import binary_read,binary_write,inspect,nearest
from runflow.cfd_paths import is_private


def extract(v,f,center,radius):
    inside=np.linalg.norm(np.asarray(v)-center,axis=1)<radius
    selected=[]
    for i in range(0,len(f),200000):
        mask=np.any(inside[f[i:i+200000]],axis=1)
        if mask.any():selected.append(np.asarray(f[i:i+200000])[mask])
    faces=np.concatenate(selected);ids=np.unique(faces)
    return ids,np.asarray(v)[ids],np.searchsorted(ids,faces)


def execute(root):
    started=time.monotonic();root=Path(root).resolve()
    if not is_private(root):raise ValueError('Explicit private output required')
    root.mkdir(parents=True,exist_ok=False)
    source=REPO/'private/phase1/provisional-016';surface=source/'geometry/candidate.rfmesh'
    expected=read(source/'geometry/geometry.json')['exchange']['sha256']
    if file_hash(surface)!=expected:raise ValueError('Qualified base changed')
    reference=REPO/'private/phase1-validation/local-repair-001/verification/combined-repro-b'
    view=read(reference/'source-metrics/views.json')['views']['face-visible']
    a=np.load(reference/'source-metrics/face-visible-depth.npy')
    b=np.load(reference/'combined-repro-b/metrics/face-visible-depth.npy')
    valid=np.isfinite(a)&np.isfinite(b);difference=np.where(valid,np.abs(a-b),-1.)
    row,col=np.unravel_index(np.argmax(difference),difference.shape)
    point=np.zeros(3);point[view['axis']]=float(b[row,col])
    point[view['axes'][0]]=view['extent_m'][0]+(col+.5)*view['step_m']
    point[view['axes'][1]]=view['extent_m'][2]+(row+.5)*view['step_m']
    move=np.zeros(3);move[view['axis']]=np.sign(float(a[row,col])-float(b[row,col]))*.001
    v,f=binary_read(surface);snapshot=read(source/'source.snapshot.json')
    sv=np.array(snapshot['vertices']);sf=np.array(snapshot['triangles'])
    ids,pv,pf=extract(v,f,point,.020);_,local_sv,local_sf=extract(sv,sf,point,.020)
    np.savez(root/'patch.npz',vertices=pv,faces=pf,source_vertices=local_sv,source_faces=local_sf,global_vertex_ids=ids)
    config=dict(base_rfmesh_sha256=expected,source_snapshot_sha256=file_hash(source/'source.snapshot.json'),
        center_m=point.tolist(),radius_m=.012,translation_m=move.tolist(),view_axis=view['axis'],
        view_axes=view['axes'],view_sign=view['sign'],selection_actor='assistant',selection_basis='Worst common first-hit sample in the pre-existing face-visible region',
        sampled_depth_difference_before_m=float(difference[row,col]),
        operation='Native Blender BMesh proportional translation; cosine falloff; 1 mm maximum',
        original_all_surface_tolerance_m=.002,original_area_tolerance_rel=.01,
        human_approval=None,scientific_approval=None,ranking_eligible=False)
    blender=REPO/'.tools/blender/blender-4.2.23-windows-x64/blender.exe'
    integration=REPO/'integrations/blender/edit_local_surface.py'
    config['processing_hashes']={str(p.relative_to(REPO)):file_hash(p) for p in (Path(__file__),integration,blender)}
    write(root/'edit.json',config)
    with (root/'blender.log').open('wb') as log:
        subprocess.run([str(blender),'--background','--factory-startup','--threads','12','--python',str(integration),
                        '--','--root',str(root)],check=True,stdout=log,stderr=subprocess.STDOUT)
    delta=np.load(root/'blender-delta.npy');weights=np.linalg.norm(pv-point,axis=1)<.012
    if delta.shape!=pv.shape or not np.isfinite(delta).all() or np.linalg.norm(delta,axis=1).max()>.001001:
        raise ValueError('Blender movement outside prescribed limit')
    if np.any(delta[~weights]!=0):raise ValueError('Blender changed fixed boundary')
    result_v=np.array(v);result_v[ids]+=delta
    old=pv[pf];new=(pv+delta)[pf]
    old_n=np.cross(old[:,1]-old[:,0],old[:,2]-old[:,0]);new_n=np.cross(new[:,1]-new[:,0],new[:,2]-new[:,0])
    inverted=int(np.count_nonzero(np.einsum('ij,ij->i',old_n,new_n)<=0))
    exchange=binary_write(root/'candidate.rfmesh',result_v,f)
    check=inspect(root/'candidate.rfmesh',root/'intersections')
    # Independent full-mesh nearest queries include all original local vertices and
    # the prior global counterexample; this is not a continuous whole-body maximum.
    atlas=read(REPO/'private/phase1-validation/local-repair-001/runs/source-defect-atlas/defect-atlas.json')
    witness=np.array(atlas['components'][0]['witness_center_m'])
    queries=np.r_[local_sv,witness[None,:]]
    before=nearest(surface,queries,root/'nearest-before')
    after=nearest(root/'candidate.rfmesh',queries,root/'nearest-after')
    outside=np.ones(len(v),bool);outside[ids[weights]]=False
    output=dict(config_sha256=digest(config),exchange=exchange,full_body_faces_unchanged=True,
        outside_support_vertices_bitwise_identical=bool(np.array_equal(np.asarray(v)[outside],result_v[outside])),
        inverted_local_faces=inverted,exact_intersections=check,
        local_original_vertex_query_count=len(local_sv),
        local_mean_distance_before_m=float(before[:-1,0].mean()),local_mean_distance_after_m=float(after[:-1,0].mean()),
        local_max_sampled_distance_before_m=float(before[:-1,0].max()),local_max_sampled_distance_after_m=float(after[:-1,0].max()),
        global_counterexample_distance_before_m=float(before[-1,0]),global_counterexample_distance_after_m=float(after[-1,0]),
        full_original_surface_gate='FAIL' if after[-1,0]>.002 else 'UNVERIFIED',
        full_area_change='UNMEASURED',human_parts_review=None,scientific_approval=None,ranking_eligible=False,
        automatically_adopted=False,elapsed_s=time.monotonic()-started,
        limitation='Nearest queries are sampled; the fixed counterexample can reject but cannot certify the full shape.')
    write(root/'result.json',output)
    print('BLENDER_TRIAL_FINISHED',output['full_original_surface_gate'],check['intersection_free'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();execute(a.output)
