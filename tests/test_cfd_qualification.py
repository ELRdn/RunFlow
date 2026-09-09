import csv
import io
import struct
import tarfile
import numpy as np
import pytest
from runflow import cfd
from runflow.core import read,write,file_hash
from runflow.cfd_qualification import establish,freeze,reuse

def fixture(tmp,monkeypatch,actual_intersection=False):
    monkeypatch.setattr(cfd,'REPO',tmp)
    probe=tmp/'private/probe';ref=tmp/'private/ref';probe.mkdir(parents=True);(ref/'geometry').mkdir(parents=True)
    height=-1 if actual_intersection else 2
    vertices=np.array([[.25,.25,height],[.25,.25,1],[0,0,0],[1,0,0],[0,1,0]],dtype='<f8')
    faces=np.array([[2,3,4]],dtype='<u4')
    data=struct.pack('<8sQQ',b'RFMESH1\0',5,1)+vertices.tobytes()+faces.tobytes()
    (probe/'probe.rfmesh').write_bytes(data);(ref/'geometry/candidate.rfmesh').write_bytes(data)
    (ref/'geometry/candidate.obj').write_text('synthetic-object-identity')
    (probe/'probe.hits.csv').write_text('edge,face,a,b,f0,f1,f2,x,y,z\n0,0,0,1,2,3,4,0.25,0.25,0\n')
    loaded=file_hash(probe/'probe.rfmesh');obj=file_hash(ref/'geometry/candidate.obj')
    write(probe/'request.json',dict(expected_rfmesh_sha256=loaded,source_sha256=obj,probe_sha256='a'*64))
    write(probe/'probe-evidence.json',dict(complete=True,source_sha256=obj,loaded_mesh_sha256=loaded,hits_sha256=file_hash(probe/'probe.hits.csv'),probe_sha256='a'*64))
    write(probe/'probe-build.json',dict(binary_sha256='a'*64))
    done=dict(returncode=0,reason=None,termination_verified=True)
    write(probe/'execution.json',dict(command=done));write(ref/'surface-worker.json',dict(commands=[done]))
    exact=dict(complete=True,intersection_free=True,intersection_pairs=0,degenerate_triangles=0)
    write(ref/'geometry/intersections.json',exact)
    write(ref/'geometry/geometry.json',dict(exchange=dict(sha256=loaded),surface_sha256=obj,exact_intersections=exact,
          candidate_topology=dict(closed_manifold=True),quality=dict(near_degenerate_triangles=0)))
    (ref/'surfaceCheck.log').write_text('Surface is closed. All edges connected to two faces.\nSurface is self-intersecting at 1 locations.\nEnd\n')
    point=b'v 0.25 0.25 0\n'
    with tarfile.open(ref/'surface-diagnostics.tar','w') as t:
        info=tarfile.TarInfo('selfInterPoints.obj');info.size=len(point);t.addfile(info,io.BytesIO(point))
    write(ref/'surface-io.json',dict(complete=True,checker_returncode=0,source_sha256=obj,copied_sha256=obj,checker_sha256='b'*64,
          diagnostics=dict(sha256=file_hash(ref/'surface-diagnostics.tar'))))
    return probe,ref

def test_requires_both_full_surface_and_every_exact_reported_pair(tmp_path,monkeypatch):
    p,r=fixture(tmp_path,monkeypatch);result=establish(p,r)
    assert result['status']=='PASS' and result['reported_pairs']==1 and result['stock_verdict'].endswith('FALSE_POSITIVES')
    x=read(r/'geometry/geometry.json');x['exact_intersections']['intersection_pairs']=1;write(r/'geometry/geometry.json',x)
    with pytest.raises(ValueError,match='Full-surface exact'):establish(p,r)

def test_real_reported_intersection_blocks_even_if_other_checker_claims_pass(tmp_path,monkeypatch):
    p,r=fixture(tmp_path,monkeypatch,True)
    with pytest.raises(ValueError,match='Exact intersection in'):establish(p,r)

def test_loaded_mesh_and_every_reported_location_must_match(tmp_path,monkeypatch):
    p,r=fixture(tmp_path,monkeypatch)
    (r/'surfaceCheck.log').write_text('Surface is closed. All edges connected to two faces.\nSurface is self-intersecting at 2 locations.\nEnd\n')
    with pytest.raises(ValueError,match='Not every'):establish(p,r)
    with (p/'probe.rfmesh').open('ab') as f:f.write(b'changed')
    with pytest.raises(ValueError,match='Loaded mesh differs'):establish(p,r)

def test_cached_evidence_tampering_and_changed_surface_are_rejected(tmp_path,monkeypatch):
    p,r=fixture(tmp_path,monkeypatch);q=tmp_path/'private/qualification';freeze(p,r,q)
    run=tmp_path/'private/run';(run/'geometry').mkdir(parents=True)
    write(run/'geometry/geometry.json',read(r/'geometry/geometry.json'))
    (run/'geometry/candidate.obj').write_text('different geometry')
    write(run/'upstream.json',dict(binaries=dict(surfaceCheck=dict(sha256='b'*64))))
    with pytest.raises(ValueError,match='different surface'):reuse(q,run)
    (p/'probe.hits.csv').write_text('changed')
    with pytest.raises(ValueError,match='evidence changed'):reuse(q,run)
