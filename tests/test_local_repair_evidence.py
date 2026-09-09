from pathlib import Path
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from finish_local_repair_evidence import canonical_triangles


def test_canonical_face_equality_keeps_winding_and_coordinates():
    t=np.array([[[0.,0,0],[1,0,0],[0,1,0]],[[0,0,1],[1,0,1],[0,1,1]]])
    a=canonical_triangles(t);b=canonical_triangles(np.roll(t[::-1],1,axis=1));a.sort();b.sort()
    assert np.array_equal(a,b)
    c=canonical_triangles(t[:,[0,2,1]]);c.sort();assert not np.array_equal(a,c)
    moved=t.copy();moved[0,0,0]=1e-8;d=canonical_triangles(moved);d.sort();assert not np.array_equal(a,d)
