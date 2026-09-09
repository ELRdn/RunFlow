import json
from pathlib import Path
import subprocess
import sys
import numpy as np
import pytest
from runflow.shape_fullbody import (save_arrays,repair_binary,edge_topology,prediction,private_root,validate_request)
from runflow.shape_audit import load_surface,file_sha


def test_binary_preserves_non_degenerate_coordinates_and_unused_vertex(tmp_path):
    v=np.array([[0,0,0],[1,0,0],[0,1,0],[.1,.1,.1]],dtype=np.float32); f=np.array([[0,1,2]],np.int32)
    save_arrays(tmp_path/'raw',v,f)
    report=repair_binary(tmp_path/'raw',tmp_path/'fixed'); a,b=load_surface(tmp_path/'fixed')
    assert np.array_equal(a[b],v[f]) and report['removed_unused_vertices']==1
    del a,b
    (tmp_path/'fixed/vertices.npy').write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='hash mismatch'): load_surface(tmp_path/'fixed')


def test_direct_weld_does_not_drift_and_removes_only_collapsed_face(tmp_path):
    v=np.array([[0,0,0],[.4e-6,0,0],[1,0,0],[0,1,0]],np.float32)
    f=np.array([[0,1,2],[0,2,3]],np.int32); save_arrays(tmp_path/'raw',v,f)
    report=repair_binary(tmp_path/'raw',tmp_path/'fixed'); a,b=load_surface(tmp_path/'fixed')
    assert report['max_vertex_shift_m']<=1e-6 and len(b)==1
    assert np.array_equal(a[b[0]],v[f[1]])


def test_edge_incidence_and_open_shape(tmp_path):
    v=np.array([[0,0,0],[1,0,0],[0,1,0],[0,0,1]],np.float32)
    f=np.array([[0,2,1],[0,1,3],[0,3,2],[1,2,3]],np.int32)
    save_arrays(tmp_path/'closed',v,f); a=edge_topology(tmp_path/'closed',tmp_path/'a')
    assert a['boundary_edges']==a['nonmanifold_edges']==a['inconsistent_edges']==0
    assert a['closed'] is None and not a['self_intersection_verified']
    save_arrays(tmp_path/'open',v,f[:-1]); b=edge_topology(tmp_path/'open',tmp_path/'b')
    assert b['boundary_edges']==3


def test_predictions_are_not_measurements_and_root_is_fresh(tmp_path):
    estimate=prediction([dict(voxel_um=1000,corners=24000000)],100)
    assert estimate['skip_reason'] and estimate['predicted_corners']==2400000000
    assert private_root(tmp_path/'private/new',tmp_path)==(tmp_path/'private/new').resolve()
    with pytest.raises(ValueError): private_root(tmp_path/'public/new',tmp_path)
    (tmp_path/'private/existing').mkdir(parents=True)
    with pytest.raises(ValueError): private_root(tmp_path/'private/existing',tmp_path)


def test_input_hash_and_unit_validation(tmp_path):
    path=tmp_path/'input.json'; path.write_text(json.dumps(dict(unit='cm',coordinate_system='RF_X_FORWARD_Z_UP')))
    req=dict(kind='fullbody_voxel_comparison_v1',voxel_sizes_um=[1000,500,250,100],frame=0,adoption='adopted-002',
        inputs={'source':dict(path=str(path),sha256=file_sha(path))})
    with pytest.raises(ValueError,match='Metres'): validate_request(req)
    path.write_text('{}')
    with pytest.raises(ValueError,match='hash'): validate_request(req)


def test_blender_fullbody_four_resolutions(tmp_path):
    repo=Path(__file__).resolve().parents[1]; blender=repo/'.tools/blender/blender-4.2.23-windows-x64/blender.exe'
    if not blender.exists(): pytest.skip('Pinned Blender missing')
    result=subprocess.run([str(blender),'--background','--factory-startup','--threads','4','--python-exit-code','2',
        '--python',str(repo/'tests/blender_fullbody_voxel.py'),'--',str(tmp_path/'study')],capture_output=True,text=True,timeout=180)
    assert result.returncode==0,result.stdout+result.stderr
    assert 'BLENDER_FULLBODY_PASS' in result.stdout


def test_partial_report_does_not_trust_failed_stage_output(tmp_path):
    import importlib.util
    from runflow.shape_fullbody import write
    repo=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location('full_report',repo/'scripts/fullbody_voxel_report.py')
    report=importlib.util.module_from_spec(spec); spec.loader.exec_module(report)
    write(tmp_path/'request.json',dict(regions=[]))
    write(tmp_path/'execution-summary.json',dict(study_id='synthetic',inputs_unchanged=True,
        records=[dict(stage='v1000-projection-front',returncode=0,reason='stage timeout',termination_verified=True)]))
    write(tmp_path/'v1000/metrics/projection-front.json',dict(complete=True,relative_change=0))
    value=report.summarize(tmp_path)
    assert not value['comparison_complete'] and value['results']['v1000']['metrics']['projection-front'] is None
    assert value['results']['v1000']['drag_N'] is None and value['human_adoption'] is None
    from runflow.publication import public_result
    with pytest.raises(ValueError): public_result(value,tmp_path/'public')
    assert not (tmp_path/'public').exists()


def test_original_gap_opening_is_not_counted_as_successful_gap_retention(tmp_path):
    import importlib.util
    import shapely
    from runflow.shape_fullbody import write
    repo=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location('full_metrics',repo/'scripts/fullbody_voxel_metrics.py')
    metrics=importlib.util.module_from_spec(spec); spec.loader.exec_module(metrics)
    def rectangles(boxes):
        vertices=[]; faces=[]
        for x0,y0,x1,y1 in boxes:
            i=len(vertices); vertices.extend([[x0,y0,0],[x1,y0,0],[x1,y1,0],[x0,y1,0]])
            faces.extend([[i,i+1,i+2],[i,i+2,i+3]])
        return np.array(vertices,float)*.001,np.array(faces,np.int32)
    ring=[(0,0,6,1),(0,5,6,6),(0,1,1,5),(5,1,6,5)]
    save_arrays(tmp_path/'source',*rectangles(ring))
    (tmp_path/'v1000').mkdir(); save_arrays(tmp_path/'v1000/candidate',*rectangles(ring[:-1]))
    metrics.project(tmp_path,'source','top')
    write(tmp_path/'request.json',dict(regions=[],inputs={'projection-top':dict(path=str(tmp_path/'source-metrics/top.wkb'))}))
    metrics.project(tmp_path,'v1000','top')
    result=metrics.read(tmp_path/'v1000/metrics/projection-top.json'); hole=result['original_holes'][0]
    assert hole['area_mm2']==pytest.approx(16) and hole['filled_fraction']==0
    assert hole['opened_to_exterior_mm2']==pytest.approx(16) and result['lost_m2']>0


def test_paused_continuation_preserves_original_deadline(tmp_path,monkeypatch):
    import importlib.util
    from datetime import datetime,timezone
    from runflow.shape_fullbody import write
    repo=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location('full_runner',repo/'scripts/run_fullbody_voxel_comparison.py')
    runner=importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)
    now=2000000000.; monkeypatch.setattr(runner.time,'time',lambda:now)
    value=dict(termination_verified=True,original_started_utc=datetime.fromtimestamp(now-3600,timezone.utc).isoformat())
    write(tmp_path/'pause-001.json',value)
    _,remaining=runner.paused_remaining(tmp_path)
    assert remaining==43200-3600-10
    value['termination_verified']=False; write(tmp_path/'pause-001.json',value)
    with pytest.raises(ValueError,match='termination'): runner.paused_remaining(tmp_path)


def test_visible_depth_separates_surface_loss_and_depth_change():
    import importlib.util
    repo=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location('final_review',repo/'scripts/finalize_fullbody_review.py')
    review=importlib.util.module_from_spec(spec); spec.loader.exec_module(review)
    a=np.array([[1.,np.nan],[1.,np.nan]])
    b=np.array([[1.003,np.nan],[np.nan,2.]])
    result=review.depth_change(a,b,.002)
    assert result['lost_pixels']==result['added_pixels']==1
    assert result['lost_coverage_estimate_m2']==pytest.approx(4e-6)
    assert result['common_first_hit_mean_abs_m']==pytest.approx(.003)
    assert result['common_first_hit_sampled_max_abs_m']==pytest.approx(.003)
    empty=review.depth_change(a,np.full(a.shape,np.nan),.002)
    assert empty['common_first_hit_sampled_max_abs_m'] is None and empty['lost_pixels']==2
    with pytest.raises(ValueError,match='Common view'): review.depth_change(a,np.zeros((1,1)),.002)


def test_render_fallback_keeps_original_case_and_study_deadlines(tmp_path):
    import importlib.util
    from datetime import datetime,timezone
    from runflow.shape_fullbody import write
    repo=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location('finish_metrics',repo/'scripts/finish_fullbody_metrics.py')
    runner=importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)
    initial=2_000_000_000.; case=initial+1000
    write(tmp_path/'pause-001.json',dict(original_started_utc=datetime.fromtimestamp(initial,timezone.utc).isoformat()))
    write(tmp_path/'v250-topology.execution.json',dict(owned_processes=[dict(created_at=case+1),dict(created_at=case)]))
    total,measurement=runner.deadlines(tmp_path)
    assert total==initial+43200-10 and measurement==case+4500-10
