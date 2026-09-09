"""Adjudicate stock checker false positives with bound, exact evidence.

Requires a complete full-surface CGAL check on the identical loaded mesh, plus
independent rational tests of every stock-reported edge/face pair. Raw stock
FAIL records remain unchanged. No tolerance or surface coordinates are changed.
"""
import csv
from pathlib import Path
import re
import struct
import tarfile
import numpy as np
from .core import read,write,file_hash,digest
from .cfd_intersections import segment_triangle
from . import cfd

def exact_pairs(mesh_path,hits_path):
    with mesh_path.open('rb') as f:magic,nv,nf=struct.unpack('<8sQQ',f.read(24))
    if magic!=b'RFMESH1\0' or not nv or not nf or mesh_path.stat().st_size!=24+nv*24+nf*12:
        raise ValueError('Invalid loaded mesh')
    vertices=np.memmap(mesh_path,dtype='<f8',mode='r',offset=24,shape=(nv,3))
    faces=np.memmap(mesh_path,dtype='<u4',mode='r',offset=24+nv*24,shape=(nf,3))
    positions=[];edges=set();intersecting=0
    with hits_path.open() as f:
        for r in csv.DictReader(f):
            edge=int(r['edge']);face=int(r['face']);indices=[int(r[k]) for k in ('a','b','f0','f1','f2')]
            if edge in edges or not 0<=face<nf or any(i<0 or i>=nv for i in indices):raise ValueError('Invalid/duplicate reported pair')
            edges.add(edge)
            if not np.array_equal(faces[face],indices[2:]) or set(indices[:2])&set(indices[2:]):raise ValueError('Reported face/edge mismatch')
            value=segment_triangle(vertices[indices[0]],vertices[indices[1]],vertices[indices[2:]])
            intersecting+=value['intersects']
            point=[float(format(float(r[k]),'.6g')) for k in ('x','y','z')]
            if not np.isfinite(point).all():raise ValueError('Nonfinite reported location')
            positions.append(point)
    return dict(count=len(edges),exact_intersecting=intersecting),np.array(positions)


def establish(probe_path,reference_path):
    probe=cfd.private(probe_path);reference=cfd.private(reference_path)
    request=read(probe/'request.json');evidence=read(probe/'probe-evidence.json')
    execution=read(probe/'execution.json')['command'];geometry=read(reference/'geometry/geometry.json')
    native=geometry['exact_intersections'];io=read(reference/'surface-io.json')
    if execution['reason'] or execution['returncode'] or not execution['termination_verified'] or not evidence['complete']:
        raise ValueError('Incomplete probe execution')
    if evidence['probe_sha256']!=request['probe_sha256'] or evidence['probe_sha256']!=read(probe/'probe-build.json')['binary_sha256']:
        raise ValueError('Probe binary identity mismatch')
    loaded=file_hash(probe/'probe.rfmesh');obj=file_hash(reference/'geometry/candidate.obj')
    if loaded!=geometry['exchange']['sha256'] or loaded!=evidence['loaded_mesh_sha256'] or loaded!=request['expected_rfmesh_sha256']:
        raise ValueError('Loaded mesh differs from the full-surface exact-check input')
    if obj!=geometry['surface_sha256'] or obj!=evidence['source_sha256'] or obj!=io['source_sha256'] or obj!=io['copied_sha256']:
        raise ValueError('Stock/probe geometry mismatch')
    if file_hash(reference/'geometry/candidate.rfmesh')!=loaded or file_hash(probe/'probe.hits.csv')!=evidence['hits_sha256']:
        raise ValueError('Diagnostic input changed')
    if not native['complete'] or not native['intersection_free'] or native['intersection_pairs'] or native['degenerate_triangles']:
        raise ValueError('Full-surface exact intersection gate failed')
    if native!=read(reference/'geometry/intersections.json') or not geometry['candidate_topology']['closed_manifold'] or geometry['quality']['near_degenerate_triangles']:
        raise ValueError('Exact evidence/closure mismatch')
    if not io['complete'] or io['checker_returncode'] or file_hash(reference/'surface-diagnostics.tar')!=io['diagnostics']['sha256']:
        raise ValueError('Incomplete stock diagnostics')
    worker=read(reference/'surface-worker.json')
    if any(r['reason'] or r['returncode'] or not r['termination_verified'] for r in worker['commands']):
        raise ValueError('Stock checker did not finish')
    log=(reference/'surfaceCheck.log').read_text();found=re.search(r'Surface is self-intersecting at (\d+) locations',log)
    if not found or 'Surface is closed. All edges connected to two faces.' not in log or not re.search(r'(?m)^End\s*$',log):
        raise ValueError('Stock completed closure/intersection evidence missing')
    pairs,positions=exact_pairs(probe/'probe.rfmesh',probe/'probe.hits.csv')
    with tarfile.open(reference/'surface-diagnostics.tar') as archive:
        lines=archive.extractfile('selfInterPoints.obj').read().decode('ascii').splitlines()
    stock=np.array([[float(x) for x in line.split()[1:]] for line in lines if line.startswith('v ')])
    if pairs['count']!=int(found[1]) or not np.array_equal(stock,positions):raise ValueError('Not every stock-reported location was reproduced')
    if pairs['exact_intersecting']:raise ValueError('Exact intersection in a stock-reported pair')
    inputs=dict(source_obj_sha256=obj,loaded_rfmesh_sha256=loaded,hits_sha256=evidence['hits_sha256'],
                stock_checker_sha256=io['checker_sha256'],probe_sha256=evidence['probe_sha256'],
                full_surface_check_sha256=file_hash(reference/'geometry/intersections.json'))
    verdict=dict(schema_version='cfd-exact-qualification-1',status='PASS',
        method='FULL_SURFACE_EXACT_PREDICATES_AND_EVERY_REPORTED_PAIR_EXACT_RATIONAL',
        inputs=inputs,reported_pairs=pairs['count'],exact_intersecting_pairs=0,loaded_coordinates_identical=True,
        stock_verdict='SELF_INTERSECTION_REPORTED_FALSE_POSITIVES',shape_changed=False,
        scientific_status='UNVALIDATED_PROVISIONAL_GEOMETRY',ranking_eligible=False)
    verdict['qualification_id']=digest(verdict)
    return verdict


def freeze(probe,reference,output):
    output=cfd.private(output)
    if output.exists():raise ValueError('Fresh qualification required')
    verdict=establish(probe,reference)
    output.mkdir(parents=True)
    write(output/'verdict.json',verdict)
    paths={'probe':str(cfd.private(probe)),'reference':str(cfd.private(reference))}
    names={'probe':['request.json','probe-evidence.json','execution.json','probe.rfmesh','probe.hits.csv','probe-build.json'],
           'reference':['geometry/geometry.json','geometry/intersections.json','geometry/candidate.obj','geometry/candidate.rfmesh',
                        'surfaceCheck.log','surface-worker.json','surface-io.json','surface-diagnostics.tar']}
    files={group+'/'+name:file_hash(Path(paths[group])/name) for group in names for name in names[group]}
    write(output/'evidence-ledger.json',dict(paths=paths,files=files,verdict_sha256=file_hash(output/'verdict.json')))
    return verdict


def reuse(qualification,root):
    qualification=cfd.private(qualification);ledger=read(qualification/'evidence-ledger.json')
    if file_hash(qualification/'verdict.json')!=ledger['verdict_sha256']:raise ValueError('Qualification verdict changed')
    for name,expected in ledger['files'].items():
        group,relative=name.split('/',1);base=cfd.private(ledger['paths'][group]);path=(base/relative).resolve()
        if not path.is_relative_to(base) or file_hash(path)!=expected:raise ValueError('Qualification evidence changed: '+name)
    value=establish(ledger['paths']['probe'],ledger['paths']['reference'])
    if value!=read(qualification/'verdict.json'):raise ValueError('Qualification recomputation mismatch')
    geometry=read(root/'geometry/geometry.json');upstream=read(root/'upstream.json')
    if value['inputs']['source_obj_sha256']!=file_hash(root/'geometry/candidate.obj') or value['inputs']['loaded_rfmesh_sha256']!=geometry['exchange']['sha256']:
        raise ValueError('Qualification is for a different surface')
    if value['inputs']['stock_checker_sha256']!=upstream['binaries']['surfaceCheck']['sha256']:
        raise ValueError('Stock checker version changed')
    write(root/'surface-qualification.json',value)
    write(root/'surface-qualification-reuse.json',dict(path=str(qualification),verdict_sha256=ledger['verdict_sha256'],fully_revalidated=True))
    write(root/'surface-worker.json',dict(execution_status='PASS',error=None,commands=[],
        mode='REUSED_AND_REVALIDATED_EXACT_QUALIFICATION',qualification_id=value['qualification_id'],stock_raw_pass=False))
