import numpy as np
from runflow.shape_sections import section_segments


def test_triangle_plane_intersection_and_exact_vertex():
    v=np.array([[0.,0,-1],[1,0,1],[0,1,1]])
    lines,ignored=section_segments(v,np.array([[0,1,2]]),2,0)
    assert ignored==0 and lines.shape==(1,2,3)
    assert set(map(tuple,lines[0]))=={(.5,0,0),(0,.5,0)}
    lines,ignored=section_segments(v,np.array([[0,1,2]]),2,1)
    assert set(map(tuple,lines[0]))=={(1,0,1),(0,1,1)}


def test_coplanar_triangle_recorded_not_fabricated_as_solid():
    v=np.array([[0.,0,0],[1,0,0],[0,1,0]])
    lines,ignored=section_segments(v,np.array([[0,1,2]]),2,0)
    assert ignored==1 and lines.shape==(0,2,3)
