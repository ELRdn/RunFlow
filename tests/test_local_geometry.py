from pathlib import Path
import subprocess
import numpy as np
import pytest
from runflow.local_geometry import binary_write,binary_read,inspect,nearest,ROOT,tools_manifest

def triangles():
    return np.array([[0,0,0],[1,0,0],[0,1,0],[.25,.25,-1],[.25,.25,1],[.75,.25,0]],float),np.array([[0,1,2],[3,4,5]])

def test_binary_coordinates_and_truncation(tmp_path):
    v,f=triangles();p=tmp_path/'a.bin';binary_write(p,v,f);a,b=binary_read(p)
    assert np.array_equal(a,v) and np.array_equal(b,f)
    with pytest.raises(FileExistsError):binary_write(p,v,f)
    bad=tmp_path/'bad';bad.write_bytes(p.read_bytes()[:-1])
    with pytest.raises(ValueError):binary_read(bad)
    empty=tmp_path/'empty';empty.write_bytes(b'RFMESH1')
    with pytest.raises(ValueError,match='header'):binary_read(empty)
    with pytest.raises(ValueError,match='integer'):binary_write(tmp_path/'fractional',v,f.astype(float)+.1)

@pytest.mark.skipif(not (ROOT/'build.json').exists(),reason='Pinned native geometry not installed')
def test_native_crossing_adjacent_and_coplanar(tmp_path):
    tools_manifest();v,f=triangles();p=tmp_path/'cross.bin';binary_write(p,v,f)
    assert inspect(p,tmp_path/'cross')['intersection_pairs']==1
    # Two triangles sharing only their indexed edge are valid adjacent surfaces.
    v=np.array([[0,0,0],[1,0,0],[0,1,0],[1,1,0]],float);f=np.array([[0,1,2],[1,3,2]])
    p=tmp_path/'adj.bin';binary_write(p,v,f);assert inspect(p,tmp_path/'adj')['intersection_free']
    # Same plane, overlapping interiors, different face indices.
    v=np.concatenate((v[:3],v[:3]+[.1,.1,0]));f=np.array([[0,1,2],[3,4,5]])
    p=tmp_path/'cop.bin';binary_write(p,v,f);assert inspect(p,tmp_path/'cop')['intersection_pairs']==1

@pytest.mark.skipif(not (ROOT/'build.json').exists(),reason='Pinned native geometry not installed')
def test_native_distance_and_autorefine(tmp_path):
    v,f=triangles();p=tmp_path/'input.bin';binary_write(p,v,f[:1])
    out=nearest(p,np.array([[.25,.25,1],[0,0,0]]),tmp_path/'nearest')
    assert np.allclose(out[:,0],[1,0],atol=1e-14)
    cross=tmp_path/'cross.bin';binary_write(cross,v,f)
    fixed=tmp_path/'fixed.bin'
    r=subprocess.run([str(ROOT/'native-build/Release/runflow_autorefine.exe'),str(cross),str(fixed),'30','5'],capture_output=True,timeout=60)
    assert r.returncode==0,r.stdout+r.stderr
    assert inspect(fixed,tmp_path/'fixed')['intersection_free']


@pytest.mark.skipif(not (ROOT/'build.json').exists(),reason='Pinned native geometry not installed')
def test_degenerate_point_and_line_remain_distance_targets(tmp_path):
    v=np.array([[0.,0,0],[1,0,0],[2,0,0],[3,0,0]])
    f=np.array([[0,1,2],[3,3,3]])
    path=tmp_path/'target';binary_write(path,v,f)
    result=nearest(path,np.array([[1.,1,0],[3,1,0]]),tmp_path/'queries')
    assert np.allclose(result[:,0],1)
    assert np.allclose(result[:,1:4],[[1,0,0],[3,0,0]])
    assert np.array_equal(result[:,4],[0,1])
