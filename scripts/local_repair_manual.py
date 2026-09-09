"""Replay only explicit source-face/boundary selections; never infer human approval."""
from pathlib import Path
import argparse
import numpy as np
from local_surface_worker import surface_ref
from local_repair_mesh import patch_loops,zipper
from local_repair_methods import begin,qc
from runflow.shape_fullbody import read,write,save_arrays
from runflow.shape_audit import file_sha,load_surface


def validate_selection(value,source_hash,base_hash,source_face_count,base_face_count):
    required={'kind','approval_scope','decision','reviewer','source_cache_sha256','base_cache_sha256',
        'source_face_ids','base_face_ids','source_boundary','base_boundary','reverse_source_winding','low_m','high_m'}
    if set(value)!=required or value['kind']!='runflow_local_face_selection_v1':raise ValueError('Unknown or missing selection fields')
    if value['decision']!='APPROVED' or value['approval_scope']!='FACE_AND_BOUNDARY_SELECTION_ONLY' or not isinstance(value['reviewer'],str) or not value['reviewer'].strip():
        raise ValueError('Explicit reviewer selection is required; approval must not be inferred')
    if value['source_cache_sha256']!=source_hash or value['base_cache_sha256']!=base_hash:raise ValueError('Selection input hash mismatch')
    for key,limit in (('source_face_ids',source_face_count),('base_face_ids',base_face_count)):
        ids=value[key]
        if not isinstance(ids,list) or not ids or any(type(i)is not int or i<0 or i>=limit for i in ids) or len(set(ids))!=len(ids):
            raise ValueError('Invalid unique face selection: '+key)
    for key in ('source_boundary','base_boundary'):
        ids=value[key]
        if not isinstance(ids,list) or len(ids)<3 or any(type(i)is not int or i<0 for i in ids) or len(set(ids))!=len(ids):raise ValueError('Invalid boundary selection')
    low=np.asarray(value['low_m'],float);high=np.asarray(value['high_m'],float)
    if low.shape!=(3,) or high.shape!=(3,) or not np.isfinite([low,high]).all() or not (low<high).all():raise ValueError('Predeclared working box required')
    if type(value['reverse_source_winding'])is not bool:raise ValueError('Explicit winding choice required')
    return value


def same_oriented_cycle(a,b):
    if len(a)!=len(b) or set(a)!=set(b):return False
    i=list(a).index(b[0]);return np.array_equal(np.roll(a,-i),b)


def replay(root,folder,extra):
    p=argparse.ArgumentParser();p.add_argument('--selection',type=Path,required=True);a=p.parse_args(extra)
    selection_path=a.selection.resolve()
    if not selection_path.is_relative_to(root.resolve()):raise ValueError('Selection must be stored in this private study')
    value=read(selection_path);sfolder=surface_ref(root,'cleaned');bfolder=surface_ref(root,'base900')
    sv,sf=load_surface(sfolder);bv,bf=load_surface(bfolder)
    validate_selection(value,file_sha(sfolder/'cache.json'),file_sha(bfolder/'cache.json'),len(sf),len(bf))
    source_ids=np.array(value['source_face_ids']);base_ids=np.array(value['base_face_ids']);patch=sf[source_ids]
    if value['reverse_source_winding']:patch=patch[:,[0,2,1]]
    sl=patch_loops(patch);bl=patch_loops(bf[base_ids])
    if len(sl)!=1 or len(bl)!=1 or not same_oriented_cycle(sl[0],value['source_boundary']) or not same_oriented_cycle(bl[0],value['base_boundary']):
        raise ValueError('Approved boundary does not match the selected oriented patch')
    low=np.array(value['low_m']);high=np.array(value['high_m'])
    for points in (sv[np.unique(patch)],bv[np.unique(bf[base_ids])]):
        if not ((points>=low)&(points<=high)).all():raise ValueError('Selected face lies outside approved region')
    recipe=dict(method='human-selected-original-patch',base='base900',selection_sha256=file_sha(selection_path),
        replay_code_sha256=file_sha(Path(__file__)),reverse_source_winding=value['reverse_source_winding'],approval_scope=value['approval_scope'])
    dest=begin(root,folder,recipe);vertices=np.r_[bv,sv]
    seam=zipper(vertices,np.array(value['base_boundary']),np.array(value['source_boundary'])+len(bv))
    keep=np.ones(len(bf),bool);keep[base_ids]=False;faces=np.r_[bf[keep],patch+len(bv),seam]
    save_arrays(dest/'candidate',vertices,faces);np.save(dest/'seam-triangles.npy',seam)
    write(dest/'human-selection.json',value)
    write(dest/'generation.json',dict(complete=True,selection_sha256=file_sha(selection_path),
        all_retained_base_faces_unchanged=True,all_base_vertex_positions_unchanged=True,
        human_geometry_acceptance=None,scientific_status='UNAPPROVED'))
    qc(root,dest,'PASS')
