from pathlib import Path
import sys
import numpy as np
import pytest
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'scripts'))
from ray_carve_surface import height_volume,shallow_envelope,import_cutter
from runflow.shape_fullbody import save_arrays
from repair_trial_support import manifold_backend
from manifold_surface_repair import import_manifold


@pytest.mark.parametrize('axis,axes,sign',[(2,[0,1],-1),(1,[0,2],-1),(0,[1,2],1)])
def test_oriented_closed_height_volume_and_difference(axis,axes,sign):
    if not (REPO/'.tools/manifold3d-3.5.2/install.json').exists(): pytest.skip('Optional pinned backend absent')
    m=manifold_backend(REPO)
    v,f=height_volume([0,.01,.02],[0,.01,.02],np.full((3,3),.005),axis,axes,sign,0.)
    solid=m.Manifold(m.Mesh64(v,f.astype(np.uint64)))
    assert solid.status()==m.Error.NoError
    assert solid.volume()==pytest.approx(.02*.02*.005,rel=1e-9)
    body=m.Manifold.cube((.04,.04,.04),True)
    difference=body-solid
    assert difference.status()==m.Error.NoError
    assert difference.volume()==pytest.approx(.04**3-.02*.02*.005,rel=1e-8)
    # Each edge has two opposite orientations, including the boundary wall.
    edges=np.concatenate((f[:,[0,1]],f[:,[1,2]],f[:,[2,0]]))
    _,counts=np.unique(np.sort(edges,axis=1),axis=0,return_counts=True)
    assert (counts==2).all()


def test_shallow_envelope_does_not_carve_behind_a_nearer_neighbour():
    raw=np.full((5,5),.01); raw[2,2]=.002
    h=shallow_envelope(raw)
    assert np.all(h<=raw) and np.all(h[1:4,1:4]==.002)
    assert h[0,0]==.01
    with pytest.raises(ValueError): shallow_envelope(np.full((3,3),np.nan))
    with pytest.raises(ValueError): height_volume([0,1],[0,1],np.zeros((2,2)),2,[0,1],-1,0.)


def test_native_import_from_readonly_float64_cache_keeps_coordinates(tmp_path):
    if not (REPO/'.tools/manifold3d-3.5.2/install.json').exists(): pytest.skip('Optional pinned backend absent')
    m=manifold_backend(REPO)
    v,f=height_volume([0,.01],[0,.01],np.full((2,2),.003),2,[0,1],-1,-.005)
    before=save_arrays(tmp_path/'cutter',v,f)
    result,info=import_cutter(m,tmp_path/'cutter')
    assert result.volume()==pytest.approx(.01*.01*.003)
    assert info['input_hashes']==before['output_hashes']
    assert info['binary_coordinates_preserved']
    union_input,union_info=import_manifold(m,tmp_path/'cutter')
    assert union_input.volume()==pytest.approx(result.volume())
    assert union_info['input_hashes']==before['output_hashes']
