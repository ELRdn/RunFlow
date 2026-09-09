import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from local_repair_verify import cover_chunks
from local_repair_diagnostics import ray_hits


def test_full_coverage_preserves_area_and_face_ids():
    v=np.array([[0.,0,0],[.01,0,0],[0,.01,0],[0,0,.001]])
    f=np.array([[0,1,2],[0,1,3]])
    samples=np.concatenate(list(cover_chunks(v,f,.001)))
    assert samples['radius'].max()<=.001
    assert np.isclose(samples['area'].sum(),.000055)
    assert set(samples['face'])=={0,1}
    for face in (0,1):
        original=v[f[face]];expected=np.linalg.norm(np.cross(original[1]-original[0],original[2]-original[0]))*.5
        assert np.isclose(samples['area'][samples['face']==face].sum(),expected)


def test_diagnostic_visibility_does_not_skip_obstruction():
    tri=np.array([[[-1.,-1,1],[1,-1,1],[0,1,1]]])
    assert ray_hits(np.array([0.,0,0]),np.array([0.,0,1]),tri)==0
    assert ray_hits(np.array([0.,0,0]),np.array([0.,0,-1]),tri) is None
