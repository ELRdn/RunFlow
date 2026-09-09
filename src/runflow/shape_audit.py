"""Read-only shape audit helpers; independent of CFD admission and thresholds."""
import hashlib
import itertools
import json
from pathlib import Path
import numpy as np


def file_sha(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()


def cache_surface(path, output, expected_sha):
    """Preserve coordinates/triangles; cache a snapshot or triangle-only OBJ."""
    path=Path(path); output=Path(output)
    if file_sha(path)!=expected_sha: raise ValueError('Audit input hash mismatch')
    if output.exists(): raise ValueError('Fresh surface cache required')
    output.mkdir(parents=True)
    if path.suffix=='.json':
        value=json.loads(path.read_text(encoding='utf-8-sig'))
        if value.get('unit')!='m' or value.get('coordinate_system')!='RF_X_FORWARD_Z_UP':
            raise ValueError('Audit requires RF coordinates in metres')
        vertices=np.asarray(value['vertices'],dtype=np.float64)
        triangles=np.asarray(value['triangles'],dtype=np.int32)
    else:
        vc=[]; fc=[]
        with path.open(encoding='ascii') as stream:
            while lines:=list(itertools.islice(stream,100000)):
                vs=''.join(line[2:] for line in lines if line.startswith('v '))
                fs=''.join(line[2:] for line in lines if line.startswith('f '))
                if any(len(line.split())!=4 for line in lines if line.startswith(('v ','f '))):
                    raise ValueError('Only triangular OBJ geometry is supported')
                if vs: vc.append(np.fromstring(vs,sep=' ',dtype=np.float64).reshape(-1,3))
                if fs: fc.append(np.fromstring(fs,sep=' ',dtype=np.int32).reshape(-1,3)-1)
        vertices=np.concatenate(vc); triangles=np.concatenate(fc)
    if vertices.ndim!=2 or vertices.shape[1]!=3 or not np.isfinite(vertices).all():
        raise ValueError('Invalid vertex buffer')
    if triangles.ndim!=2 or triangles.shape[1]!=3 or not len(triangles):
        raise ValueError('Invalid triangle buffer')
    if triangles.min()<0 or triangles.max()>=len(vertices): raise ValueError('Invalid triangle index')
    np.save(output/'vertices.npy',vertices); np.save(output/'triangles.npy',triangles)
    info=dict(input_sha256=expected_sha,vertices=len(vertices),triangles=len(triangles),
              bbox_m=[vertices.min(axis=0).tolist(),vertices.max(axis=0).tolist()],
              output_hashes={name:file_sha(output/name) for name in ('vertices.npy','triangles.npy')})
    (output/'cache.json').write_text(json.dumps(info,sort_keys=True),encoding='utf-8')
    return info


def load_surface(folder):
    folder=Path(folder); info=json.loads((folder/'cache.json').read_text())
    if set(info.get('output_hashes',{}))!={'vertices.npy','triangles.npy'}:
        raise ValueError('Surface cache integrity record missing')
    for name,expected in info['output_hashes'].items():
        if file_sha(folder/name)!=expected: raise ValueError('Surface cache hash mismatch: '+name)
    return tuple(np.load(folder/name,mmap_mode='r') for name in ('vertices.npy','triangles.npy'))


SAMPLE_DTYPE=np.dtype([('point','<f4',(3,)),('distance','<f4'),('radius','<f4'),
                       ('area','<f4'),('face','<u4')])


def summarize_samples(samples, numeric_margin_m=2e-6):
    if not len(samples): raise ValueError('No distance samples')
    d=samples['distance'].astype(np.float64); r=samples['radius'].astype(np.float64)
    w=samples['area'].astype(np.float64)
    if not np.isfinite(d).all() or not np.isfinite(w).all() or not np.isfinite(r).all():
        raise ValueError('Nonfinite distance evidence')
    if (d<0).any() or (r<0).any() or (w<=0).any(): raise ValueError('Invalid distance evidence')
    total=w.sum(); order=np.argsort(d); cumulative=np.cumsum(w[order])/total
    quantiles={str(q):float(d[order[min(np.searchsorted(cumulative,q),len(d)-1)]])
               for q in (.5,.9,.95,.99,.999)}
    lower=np.maximum(0,d-r-numeric_margin_m); upper=d+r+numeric_margin_m
    thresholds={str(t):dict(estimated_fraction=float(w[d>t].sum()/total),
        definitely_over_fraction=float(w[lower>t].sum()/total),
        possibly_over_fraction=float(w[upper>t].sum()/total)) for t in (.0005,.001,.002,.005,.01,.02)}
    index=int(np.argmax(d)); upper_index=int(np.argmax(upper))
    return dict(samples=len(samples),total_triangle_area_m2=float(total),
        area_weighted_mean_m=float(np.dot(d,w)/total),area_weighted_quantiles_m=quantiles,
        measured_max_m=float(d[index]),global_max_lower_m=max(0,float(d[index])-numeric_margin_m),
        global_max_upper_m=float(upper[upper_index]),max_cover_radius_m=float(r.max()),
        max_witness_m=samples['point'][index].tolist(),max_witness_face=int(samples['face'][index]),
        numeric_margin_m=numeric_margin_m,thresholds=thresholds,
        distribution_method='Triangle-area weighted centroid estimates; every subtriangle covered by center distance +/- radius plus numeric margin',
        area_basis='All triangle surfaces, including overlapping/hidden faces; not external wetted area')


def source_components(vertices,triangles):
    """Exact-position connectivity for diagnostic grouping, never semantic labels."""
    _,inverse=np.unique(vertices,axis=0,return_inverse=True)
    parent=np.arange(int(inverse.max())+1)
    def find(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]]; i=parent[i]
        return i
    for a,b,c in inverse[triangles]:
        a=find(a); b=find(b); c=find(c); parent[b]=a; parent[c]=a
    roots=np.array([find(int(i)) for i in inverse[triangles[:,0]]])
    unique,labels=np.unique(roots,return_inverse=True)
    return labels.astype(np.int32)
