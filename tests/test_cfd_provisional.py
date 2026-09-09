import copy
from pathlib import Path
import numpy as np
import pytest
from runflow.core import read,write,file_hash,digest
from runflow.cfd_contracts import validate,PROVISIONAL_VERSION
from runflow.cfd_provisional import verify_authorization,receipt_identity
from runflow.cfd_surface import prepare_surface,obj64,changed_area_bound
from runflow.shape_fullbody import save_arrays
from runflow.shape_audit import load_surface

REPO=Path(__file__).resolve().parents[1]
def protocol():return read(REPO/'configs/cfd.phase1-provisional.json')
def receipt():
    return dict(schema_version='provisional-input-1',study_path='private/study',study_ledger_sha256='1'*64,
        candidate='sample',candidate_cache_sha256='2'*64,asset_root='private/asset',adoption_manifest_sha256='3'*64,
        source_snapshot_sha256='4'*64,authorization=dict(decision='MEASURE_CURRENT_GEOMETRY_BEFORE_FURTHER_FIDELITY_WORK',actor='user',
            instruction='Measure this one provisional pose before more fidelity optimization.',candidate_cache_sha256='2'*64,
            source_snapshot_sha256='4'*64,scope='ONE_POSE_20M_S_PROVISIONAL_CFD',scientific_approval=None,required_parts_new_review=None,
            fidelity_gate='DEFERRED_BY_USER_FOR_PROVISIONAL_MEASUREMENT'))

def test_fidelity_deferral_cannot_relax_numerical_protocol():
    p=protocol();validate('protocol',p)
    for key,value in [('speed_m_s',10),('schema_version','1')]:
        bad=copy.deepcopy(p);bad[key]=value
        with pytest.raises(ValueError):validate('protocol',bad)
    for group,key,value in [('limits','total_s',7200),('mesh','surface_level',4),('convergence','pressure_residual',1e-3),('geometry','local_weld_m',1e-4)]:
        bad=copy.deepcopy(p);bad[group][key]=value
        with pytest.raises(ValueError):validate('protocol',bad)

def test_receipt_requires_explicit_scoped_authorization():
    r=receipt();verify_authorization(r)
    for field,value in [('decision',None),('actor','agent'),('candidate_cache_sha256','5'*64),('scientific_approval',True)]:
        bad=copy.deepcopy(r);bad['authorization'][field]=value
        with pytest.raises(ValueError):verify_authorization(bad)

def test_provisional_result_keeps_failure_coefficients_null_and_private(tmp_path):
    from runflow.publication import public_result
    r=dict(schema_version=PROVISIONAL_VERSION,experiment_id='test',execution_status='PASS',
        scientific_status='UNVALIDATED_PROVISIONAL_GEOMETRY',geometry_qualification='PROVISIONAL_USER_AUTHORIZED',ranking_eligible=False,
        drag_N=100.,Cd=1.,CdA_m2=.5,stage='solver',reason='converged provisional numerical trial',evidence={})
    validate('result',r)
    with pytest.raises(ValueError):public_result(r,tmp_path/'public')
    r['execution_status']='NOT_CONVERGED'
    with pytest.raises(ValueError):validate('result',r)
    r.update(drag_N=None,Cd=None,CdA_m2=None);validate('result',r)

def test_export_preserves_binary64_coordinates(tmp_path):
    v=np.array([[.12345678901234567,0,0],[0,.9876543210987654,0],[0,0,1.0000000000000002]])
    f=np.array([[0,1,2]]);path=tmp_path/'surface.obj';obj64(path,v,f)
    restored=np.array([[float(x) for x in line.split()[1:]] for line in path.read_text().splitlines() if line.startswith('v ')])
    assert np.array_equal(v,restored)
    assert 'f 1 2 3' in path.read_text()

def test_one_local_numerical_weld_keeps_closed_object(tmp_path):
    v=np.array([[0,0,0],[1,0,0],[1,1,0],[0,1,0],[0,0,1],[1,0,1],[1,1,1],[0,1,1],[1e-18,1e-18,0]],dtype=float)
    f=np.array([[0,2,8],[2,1,8],[1,0,8],[0,3,2],[4,5,6],[4,6,7],[0,1,5],[0,5,4],
        [1,2,6],[1,6,5],[2,3,7],[2,7,6],[3,0,4],[3,4,7]],dtype=np.int32)
    save_arrays(tmp_path/'input',v,f);root=tmp_path/'run';root.mkdir()
    prepare_surface(root,tmp_path/'input');result=read(root/'geometry/geometry.json')
    assert result['repair']['merged_vertices']==1
    assert result['repair']['max_vertex_shift_m']<=1e-6
    assert result['candidate_topology']['closed_manifold'] and result['exact_intersections']['intersection_free']
    assert result['quality']['near_degenerate_triangles']==0 and result['remesh_passes']==0
    output_v,_=load_surface(root/'geometry/surface-cache');assert np.array_equal(output_v,v[:8])
    assert not result['distance_passed']

def test_unmoved_surface_has_zero_area_change_bound():
    value=changed_area_bound(np.eye(3),np.array([[0,1,2]]),[])
    assert value['absolute_area_change_upper_m2']==0 and value['affected_source_face_ids']==[]

def test_report_labels_provisional_geometry_without_promoting_fidelity(tmp_path):
    from runflow.cfd_report import create
    write(tmp_path/'result.json',dict(execution_status='NOT_CONVERGED',reason='synthetic',
        scientific_status='UNVALIDATED_PROVISIONAL_GEOMETRY',geometry_qualification='PROVISIONAL_USER_AUTHORIZED',drag_N=None,Cd=None,CdA_m2=None))
    create(tmp_path);page=(tmp_path/'report/index.html').read_text(encoding='utf-8')
    assert 'UNVALIDATED_PROVISIONAL_GEOMETRY' in page and '2mm' in page and 'null (not established)' in page

def test_prepared_provisional_authorization_is_immutable(tmp_path):
    from runflow.cfd import verify_prepared
    root=tmp_path; (root/'geometry').mkdir()
    for name in ('source-manifest.json','source.snapshot.json','geometry/candidate.obj'):(root/name).write_text('synthetic')
    write(root/'protocol.json',protocol());r=receipt()
    r['source_snapshot_sha256']=r['authorization']['source_snapshot_sha256']=file_hash(root/'source.snapshot.json')
    write(root/'provisional-receipt.json',r)
    config=dict(source_snapshot_sha256=file_hash(root/'source.snapshot.json'),source_manifest_sha256=file_hash(root/'source-manifest.json'),
        surface_sha256=file_hash(root/'geometry/candidate.obj'),protocol=protocol(),frame_time_s=0,clip_phase_s=0,
        source_area_m2=1.,repaired_area_m2=1.,repaired_area_bounds_m2=[.999,1.001],source_bbox=[[0,0,0],[1,1,1]],tool_hashes={},
        provisional_authorization_sha256=digest(r['authorization']),input_receipt_sha256=receipt_identity(r),
        fidelity_status='DEFERRED_BY_USER_FOR_PROVISIONAL_MEASUREMENT')
    h=digest(config);write(root/'experiment.json',dict(schema_version=PROVISIONAL_VERSION,experiment_id='rf-p1p-'+h,config_sha256=h,config=config))
    verify_prepared(root);r['authorization']['instruction']='changed';write(root/'provisional-receipt.json',r)
    with pytest.raises(ValueError,match='receipt changed'):verify_prepared(root)


def test_receipt_identity_excludes_runtime_locations():
    first=receipt();second=copy.deepcopy(first)
    second.update(study_path='E:/another/private/study',asset_root='D:/another/adopted')
    assert receipt_identity(first)==receipt_identity(second)
    second['candidate']='changed'
    assert receipt_identity(first)!=receipt_identity(second)
