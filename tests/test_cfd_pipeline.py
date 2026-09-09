import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from runflow.core import read,write,digest,file_hash
from runflow.cfd_contracts import validate
from runflow.cfd_case import build
from runflow.cfd_guard import run
from runflow.cfd_report import read_vtk

REPO=Path(__file__).resolve().parents[1]


def protocol(): return read(REPO/'configs/cfd.phase1-smoke.json')


def cube():
    return dict(vertices=[[-.01,-.01,-.01],[.01,-.01,-.01],[.01,.01,-.01],[-.01,.01,-.01],
                          [-.01,-.01,.01],[.01,-.01,.01],[.01,.01,.01],[-.01,.01,.01]],
        triangles=[[0,2,1],[0,3,2],[4,5,6],[4,6,7],[0,1,5],[0,5,4],
                   [1,2,6],[1,6,5],[2,3,7],[2,7,6],[3,0,4],[3,4,7]])


def test_protocol_cannot_silently_relax_limits():
    p=protocol(); validate('protocol',p)
    for field,value in [('speed_m_s',None),('frame',1),('ground_condition','wall')]:
        changed=copy.deepcopy(p); changed[field]=value
        with pytest.raises(ValueError): validate('protocol',changed)
    changed=copy.deepcopy(p); changed['geometry']['max_distance_m']=.003
    with pytest.raises(ValueError): validate('protocol',changed)


def test_case_has_airflow_sign_free_space_density_and_mesh_limits(tmp_path):
    ref={'files':{'tutorial/system/'+n:'// reference '+n for n in ('fvSchemes','fvSolution','meshQualityDict')}}
    design=build(tmp_path,cube(),protocol(),ref)
    control=(tmp_path/'system/controlDict').read_text(); velocity=(tmp_path/'0/U').read_text()
    assert '(-20 0 0)' in velocity and 'noSlip' in velocity
    assert '"procBoundary.*" {type processor;}' in velocity
    assert 'rho rhoInf; rhoInf 1.2;' in control
    assert 'patch inlet;' in control and 'patch outlet;' in control and 'regionType' not in control
    assert 'lowerWall' not in velocity and 'symmetryPlane' in velocity
    mesh=(tmp_path/'system/snappyHexMeshDict').read_text()
    assert 'maxGlobalCells 1000000;' in mesh and 'level (5 5)' in mesh
    assert design['domain_bbox'][0][0] < -.01-14*1.67
    assert design['inlet_k']==pytest.approx(.06)
    assert 'firstLayerThickness 0.2;' in mesh


def test_guard_timeout_stops_child_tree(tmp_path):
    marker=tmp_path/'child.pid'
    code="import subprocess,sys,time; from pathlib import Path; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(60)"
    item=run([sys.executable,'-c',code,str(marker)],log=tmp_path/'log',root=tmp_path,
        timeout=1,memory_bytes=1024**3,output_bytes=1024**2)
    assert item['reason']=='stage timeout' and item['termination_verified']
    import psutil
    assert not psutil.pid_exists(int(marker.read_text()))


def test_vtk_cell_units_are_preserved(tmp_path):
    p=tmp_path/'field.vtk'
    p.write_text('# vtk DataFile Version 2.0\ntest\nASCII\nDATASET UNSTRUCTURED_GRID\nPOINTS 4 float\n0 0 0 1 0 0 0 1 0 0 0 1\nCELLS 1 5\n4 0 1 2 3\nCELL_TYPES 1\n10\nCELL_DATA 1\nFIELD attributes 2\np 1 1 float\n2\nU 3 1 float\n-20 0 0\n')
    points,cells,fields=read_vtk(p)
    assert fields['p']==[(2.,)] and fields['U']==[(-20.,0.,0.)]
    assert len(points)==4 and cells==[[0,1,2,3]]


def test_prepared_geometry_hash_must_still_match(tmp_path):
    from runflow.cfd import verify_prepared
    (tmp_path/'geometry').mkdir(); (tmp_path/'geometry/candidate.obj').write_text('synthetic surface')
    (tmp_path/'source.snapshot.json').write_text('synthetic source')
    write(tmp_path/'protocol.json',protocol()); write(tmp_path/'source-manifest.json',{})
    config=dict(source_snapshot_sha256=file_hash(tmp_path/'source.snapshot.json'),source_manifest_sha256=file_hash(tmp_path/'source-manifest.json'),
        surface_sha256=file_hash(tmp_path/'geometry/candidate.obj'),protocol=protocol(),frame_time_s=0,
        clip_phase_s=0,source_area_m2=1,repaired_area_m2=1,source_bbox=[[0,0,0],[1,1,1]],tool_hashes={})
    sha=digest(config)
    write(tmp_path/'experiment.json',dict(schema_version='phase1-1',experiment_id='rf-p1-'+sha,config_sha256=sha,config=config))
    verify_prepared(tmp_path)
    (tmp_path/'geometry/candidate.obj').write_text('changed surface')
    with pytest.raises(ValueError,match='Geometry changed'): verify_prepared(tmp_path)


def test_failed_result_never_contains_formal_coefficients():
    value=dict(schema_version='phase1-1',experiment_id='test',execution_status='NOT_CONVERGED',
        scientific_status='UNVALIDATED_SMOKE',ranking_eligible=False,drag_N=None,Cd=None,CdA_m2=None,
        stage='solver',reason='unstable',evidence={})
    validate('result',value)
    value['drag_N']=1
    with pytest.raises(ValueError): validate('result',value)


def test_phase1_result_is_rejected_by_public_export(tmp_path):
    from runflow.publication import public_result
    value=dict(schema_version='phase1-1',experiment_id='test',execution_status='BLOCKED',
        scientific_status='UNVALIDATED_SMOKE',ranking_eligible=False,drag_N=None,Cd=None,CdA_m2=None,
        stage='geometry',reason='private',evidence={})
    with pytest.raises(ValueError): public_result(value,tmp_path/'public')
    assert not (tmp_path/'public').exists()


def test_blocked_geometry_never_launches_solver(tmp_path,monkeypatch):
    from runflow import cfd
    monkeypatch.setattr(cfd,'REPO',tmp_path)
    root=tmp_path/'private/test'; root.mkdir(parents=True)
    write(root/'state.json',dict(status='BLOCKED',stage='geometry'))
    def forbidden(*args,**kwargs): pytest.fail('A blocked surface launched a process')
    monkeypatch.setattr(cfd,'worker',forbidden)
    with pytest.raises(ValueError,match='PREPARED'): cfd.run(root)


def test_report_budget_includes_field_export_and_command_gap(tmp_path):
    import time
    from runflow.cfd import remaining
    write(tmp_path/'protocol.json',protocol())
    write(tmp_path/'state.json',dict(started_epoch=time.time()-1000,report_started_epoch=time.time()-290))
    assert 0 < remaining(tmp_path,'report',time.monotonic()) <= 10
