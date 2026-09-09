import sys
from pathlib import Path
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from local_repair_mesh import conservative_cutter,patch_loops,thin_shell,zipper
from runflow.local_geometry import ROOT,binary_write,native,inspect
from runflow.shape_fullbody import read


def test_boundary_branch_rejected_and_shell_closed(tmp_path):
    with pytest.raises(ValueError,match='branches'):
        patch_loops(np.array([[0,1,2],[0,3,4]]))
    v=np.array([[0.,0,0],[1,0,0],[1,1,0],[0,1,0]])
    f=np.array([[0,1,2],[0,2,3]])
    pv,pf,ids=thin_shell(v,f,.0004)
    assert np.array_equal(pv[:4],v)
    assert not patch_loops(pf)
    if not (ROOT/'build.json').exists():pytest.skip('Pinned native build not installed')
    binary_write(tmp_path/'shell',pv,pf);r=inspect(tmp_path/'shell',tmp_path/'inspect')
    assert r['intersection_free']
    native('inspect',['topology',tmp_path/'shell',tmp_path/'topology.json'])
    assert read(tmp_path/'topology.json')['closed_manifold']
    points=np.array([[.5,.5,-.0002],[.5,.5,.1],[.5,.5,0]],dtype='<f8');points.tofile(tmp_path/'points')
    native('inspect',['inside',tmp_path/'shell',tmp_path/'points',tmp_path/'sides'])
    assert np.array_equal(np.fromfile(tmp_path/'sides',dtype=np.int8),[1,-1,0])


def test_continuous_cutter_preserves_slanted_and_thin_source(tmp_path):
    if not (ROOT/'build.json').exists():pytest.skip('Pinned native build not installed')
    v=np.array([[0,0,.001],[.001,0,.002],[0,.001,.001],
        [.000401,0,.0007],[.000402,0,.0007],[.000401,.001,.0007]],float)
    f=np.array([[0,1,2],[3,4,5]])
    roi=dict(low_m=[0,0,0],high_m=[.001,.001,.003],axes=[0,1],view_axis=2,view_sign=-1)
    cv,cf,meta=conservative_cutter(v,f,roi,.0001,.00005)
    binary_write(tmp_path/'source',v,f);binary_write(tmp_path/'cutter',cv,cf)
    native('inspect',['cutter',tmp_path/'cutter',tmp_path/'source',tmp_path/'result.json'])
    assert read(tmp_path/'result.json')['source_surface_untouched']
    assert meta['whole_original_occluders']


def test_zipper_preserves_oriented_boundary():
    v=np.array([[0,0,0],[2,0,0],[2,2,0],[0,2,0],[.5,.5,0],[1.5,.5,0],[1.5,1.5,0],[.5,1.5,0]],float)
    bridge=zipper(v,np.arange(4),np.arange(4,8))
    assert len(bridge)==8
    faces=np.r_[bridge,[[4,5,6],[4,6,7]]]
    loops=patch_loops(faces)
    assert len(loops)==1 and set(loops[0])==set(range(4))


def test_grid_limit_before_allocating():
    v=np.array([[0.,0,1],[1,0,1],[0,1,1]]);f=np.array([[0,1,2]])
    roi=dict(low_m=[0,0,0],high_m=[1,1,2],axes=[0,1],view_axis=2,view_sign=-1)
    with pytest.raises(ValueError,match='grid limit'):conservative_cutter(v,f,roi,.0001,.00005,max_cells=100)
