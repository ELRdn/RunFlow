"""Consolidate matched-view evidence and exact unchanged-face checks outside repair boxes."""
from pathlib import Path
import hashlib
import numpy as np
from local_surface_worker import surface_ref,REPO
from runflow.shape_audit import load_surface,file_sha
from runflow.shape_fullbody import read,write


def canonical_triangles(tri):
    tri=np.array(tri,dtype='<f8',order='C',copy=True);tri[tri==0]=0.
    points=tri.view('V24').reshape(-1,3);first=np.argsort(points,axis=1)[:,0]
    order=(first[:,None]+np.arange(3))%3
    return np.ascontiguousarray(np.take_along_axis(tri,order[:,:,None],axis=1)).reshape(-1,9).view('V72').reshape(-1)


def outside_fingerprint(folder,boxes):
    v,f=load_surface(folder);pieces=[];crossing=0
    for start in range(0,len(f),200000):
        tri=np.asarray(v)[f[start:start+200000]].astype(float);low=tri.min(1);high=tri.max(1);possible=np.zeros(len(tri),bool)
        for lo,hi in boxes:possible|=(high>=lo).all(1)&(low<=hi).all(1)
        crossing+=int(possible.sum());pieces.append(canonical_triangles(tri[~possible]))
    keys=np.concatenate(pieces);del pieces;keys.sort();face_hash=hashlib.sha256(keys).hexdigest();face_count=len(keys);del keys
    used=np.zeros(len(v),bool);used[f.ravel()]=True;inside=np.zeros(len(v),bool)
    for lo,hi in boxes:inside|=((v>=lo)&(v<=hi)).all(1)
    points=np.array(v[used&~inside],dtype='<f8',copy=True);points[points==0]=0.
    vertices=points.view('V24').reshape(-1);vertices.sort()
    return dict(wholly_outside_faces=face_count,wholly_outside_face_sha256=face_hash,
        used_outside_vertices=len(vertices),used_outside_vertex_sha256=hashlib.sha256(vertices).hexdigest(),
        faces_intersecting_box_aabbs=crossing)


def finish(root,folder,selected):
    request=read(root/'request.json');old=Path(request['source_study']);reference=old/'source-metrics';fresh=root/'verification/source/source-metrics'
    meta=read(reference/'views.json');view_checks={}
    for key in meta['views']:
        a=reference/(key+'-depth.npy');b=fresh/(key+'-depth.npy')
        view_checks[key]=dict(array_identical=bool(np.array_equal(np.load(a),np.load(b),equal_nan=True)),
            old_sha256=file_sha(a),fresh_sha256=file_sha(b))
    if not all(x['array_identical'] for x in view_checks.values()):raise ValueError('Original reference views differ from fresh regeneration')
    baseline_visible=read(root/'runs/base-visible-recheck/result.json');current_visible=read(root/'runs/selected-visible/result.json')
    original_query=file_sha(root/'runs/base-visible-recheck/nearest/queries.bin');selected_query=file_sha(root/'runs/selected-visible/nearest/queries.bin')
    if original_query!=selected_query:raise ValueError('Visible comparisons use different samples')
    previous=read(old/'final-review/final-summary.json')['results']['v900'];ref=previous['reference_metrics']['hair-gap-projection']
    if file_sha(ref['path'])!=ref['sha256']:raise ValueError('Historical gap metric hash mismatch')
    base_gap=read(ref['path']);current_gap=read(root/'verification'/selected/selected/'metrics/hair-gap-projection.json')
    comparison=dict(complete=True,source_view_reproduction=view_checks,shared_visible_query_sha256=original_query,
        base_visible=baseline_visible,current_visible=current_visible,baseline_gap=base_gap,current_gap=current_gap,
        baseline_gap_provenance=ref,baseline_summary_sha256=file_sha(old/'final-review/final-summary.json'))
    write(folder/'comparison.json',comparison)
    boxes=[];name=selected;lineage=[]
    while name!='base900':
        if name in lineage or len(lineage)>=24:raise ValueError('Invalid repair lineage')
        lineage.append(name);candidate=root/'candidates'/name
        for step in read(candidate/'generation.json')['steps']:boxes.append(np.array(step['bounds_m']))
        name=read(candidate/'recipe.json')['base']
    original=outside_fingerprint(surface_ref(root,'base900'),boxes);candidate=outside_fingerprint(surface_ref(root,selected),boxes)
    write(folder/'outside-region.json',dict(complete=True,original=original,candidate=candidate,boxes_m=[b.tolist() for b in boxes],lineage=lineage,
        outside_faces_identical=original['wholly_outside_face_sha256']==candidate['wholly_outside_face_sha256'],
        outside_vertices_identical=original['used_outside_vertex_sha256']==candidate['used_outside_vertex_sha256'],
        continuous_cross_boundary_fragments_verified=False,
        scope='Exact oriented triangle multisets wholly outside all working boxes, and used outside vertices. Cross-boundary fragments remain unverified.'))
    print('MATCHED_COMPARISON_AND_OUTSIDE_EVIDENCE_READY',flush=True)
