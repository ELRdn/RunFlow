"""Double-coordinate binary exchange and pinned native geometry execution."""
from pathlib import Path
import struct
import subprocess
import numpy as np
from runflow.shape_audit import file_sha,load_surface
from runflow.shape_fullbody import read,save_arrays

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/'.tools/local-geometry-6.2.1'
MAGIC=b'RFMESH1\0'

def tools_manifest():
    manifest=read(ROOT/'build.json')
    if manifest['cgal']!='6.2.1' or file_sha(ROOT/'install.json')!=manifest['install_manifest_sha256']:
        raise ValueError('Geometry installation pin mismatch')
    for n,h in manifest['files'].items():
        if file_sha(ROOT/'native-build/Release'/n)!=h:raise ValueError('Geometry executable pin mismatch: '+n)
    for n,h in manifest['source_hashes'].items():
        if file_sha(REPO/n)!=h:raise ValueError('Geometry source differs from compiled code: '+n)
    return manifest

def binary_write(path,v,f):
    path=Path(path)
    if np.asarray(v).dtype.kind not in 'fiu' or np.asarray(f).dtype.kind not in 'iu':raise ValueError('Numeric vertices and integer triangle indices required')
    if len(v)>40000000 or len(f)>40000000 or len(v)==0 or len(f)==0:raise ValueError('Native face/vertex limit')
    if np.asarray(v).ndim!=2 or np.asarray(v).shape[1]!=3 or np.asarray(f).ndim!=2 or np.asarray(f).shape[1]!=3:
        raise ValueError('N by 3 mesh required')
    if not np.isfinite(v).all() or np.asarray(f).min()<0 or np.asarray(f).max()>=len(v): raise ValueError('Malformed mesh')
    with path.open('xb') as stream:
        stream.write(MAGIC+struct.pack('<QQ',len(v),len(f)))
        for i in range(0,len(v),200000):np.asarray(v[i:i+200000],dtype='<f8').tofile(stream)
        for i in range(0,len(f),200000):np.asarray(f[i:i+200000],dtype='<u4').tofile(stream)
    return dict(sha256=file_sha(path),vertices=len(v),triangles=len(f),coordinate_dtype='float64')

def binary_read(path):
    path=Path(path)
    with path.open('rb') as stream:header=stream.read(24)
    if len(header)!=24:raise ValueError('Truncated native header')
    magic=header[:8];nv,nf=struct.unpack('<QQ',header[8:])
    if magic!=MAGIC or not nv or not nf or nv>40000000 or nf>40000000 or path.stat().st_size!=24+nv*24+nf*12:
        raise ValueError('Invalid native binary')
    v=np.memmap(path,mode='r',dtype='<f8',offset=24,shape=(nv,3))
    f=np.memmap(path,mode='r',dtype='<u4',offset=24+nv*24,shape=(nf,3))
    if not np.isfinite(v).all() or f.max()>=nv:raise ValueError('Invalid native geometry')
    return v,f

def export_cache(folder,dest):return binary_write(dest,*load_surface(folder))

def native(name,args):
    tools_manifest()
    command=[str(ROOT/'native-build/Release'/('runflow_'+name+'.exe')),*map(str,args)]
    # Parent study guard owns this process and its lifetime. Standalone tests set timeout.
    result=subprocess.run(command,check=False)
    if result.returncode:raise ValueError(f'Native {name} failed: exit {result.returncode}')

def inspect(path,prefix):
    prefix=Path(prefix)
    if Path(str(prefix)+'.json').exists():raise ValueError('Existing intersection result')
    native('inspect',['intersect',path,prefix])
    result=read(str(prefix)+'.json')
    if not result.get('complete'):raise ValueError('Incomplete native inspection')
    return result

def nearest(path,points,folder):
    folder=Path(folder);folder.mkdir(exist_ok=False)
    q=folder/'queries.bin';p=np.asarray(points,dtype='<f8')
    if p.ndim!=2 or p.shape[1]!=3 or not np.isfinite(p).all():raise ValueError('Finite N by 3 queries required')
    p.tofile(q);native('inspect',['nearest',path,q,folder/'nearest.bin'])
    if (folder/'nearest.bin').stat().st_size!=len(p)*40:raise ValueError('Partial nearest result')
    out=np.memmap(folder/'nearest.bin',mode='r',dtype='<f8',shape=(len(p),5))
    if not np.isfinite(out).all():raise ValueError('Nonfinite nearest result')
    return out
