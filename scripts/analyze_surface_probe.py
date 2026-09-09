"""Check the exact same loaded edge/face pairs, without changing any surface."""
import argparse
import csv
from pathlib import Path
import struct
import sys
import numpy as np
REPO=Path(__file__).resolve().parents[1];sys.path.insert(0,str(REPO/'src'))
from runflow.core import read,write,file_hash
from runflow.cfd_intersections import segment_triangle
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);a=p.parse_args();root=a.root.resolve()
    proof=read(root/'probe-evidence.json');assert proof['complete']
    assert file_hash(root/'probe.rfmesh')==proof['loaded_mesh_sha256']
    assert file_hash(root/'probe.hits.csv')==proof['hits_sha256']
    with (root/'probe.rfmesh').open('rb') as f:magic,nv,nf=struct.unpack('<8sQQ',f.read(24))
    assert magic==b'RFMESH1\0'
    v=np.memmap(root/'probe.rfmesh',dtype='<f8',mode='r',offset=24,shape=(nv,3))
    faces=np.memmap(root/'probe.rfmesh',dtype='<u4',mode='r',offset=24+nv*24,shape=(nf,3))
    records=[];samples=[]
    with (root/'probe.hits.csv').open() as f:
        for row in csv.DictReader(f):
            ids=[int(row[k]) for k in ('a','b','f0','f1','f2')]
            assert np.array_equal(faces[int(row['face'])],ids[2:])
            assert not set(ids[:2])&set(ids[2:])
            value=segment_triangle(v[ids[0]],v[ids[1]],v[ids[2:]])
            records.append(dict(edge=int(row['edge']),face=int(row['face']),indices=ids,exact=value))
            if len(samples)<5:samples.append(dict(indices=ids,vertices=v[ids].tolist(),exact=value))
    write(root/'exact-classification.json',dict(complete=True,count=len(records),
        loaded_mesh_matches_original=proof['loaded_mesh_matches_original'],
        exact_intersecting=sum(x['exact']['intersects'] for x in records),
        exact_disjoint=sum(not x['exact']['intersects'] for x in records),
        coplanar=sum(x['exact']['coplanar'] for x in records),
        scope='Exact rational tests of reported pairs only; not a full-surface intersection gate.',records=records))
    write(root/'minimal-pair-examples.json',samples)
    print('EXACT_PAIRS',len(records),sum(x['exact']['intersects'] for x in records),'LOADED_MATCH',proof['loaded_mesh_matches_original'],flush=True)
