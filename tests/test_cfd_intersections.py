import pytest
from runflow.cfd_intersections import segment_triangle

T=((0,0,0),(1,0,0),(0,1,0))
@pytest.mark.parametrize('a,b,expected',[
    ((.25,.25,-1),(.25,.25,1),True),
    ((.25,.25,1),(.25,.25,2),False),
    ((1,1,-1),(1,1,1),False),
    ((0,0,-1),(0,0,0),True),
    ((-.5,.25,0),(.5,.25,0),True),
    ((2,2,0),(3,3,0),False),
    ((.25,.25,1e-30),(.75,.25,1e-30),False),
    ((.5,.5,0),(.5,.5,0),True),
    ((1+2**-51,0,-1),(1+2**-51,0,1),False),
])
def test_exact_segment_contact_and_near_miss(a,b,expected):
    assert segment_triangle(a,b,T)['intersects']==expected
    assert segment_triangle(b,a,T)['intersects']==expected
def test_degenerate_face_is_not_silently_accepted():
    with pytest.raises(ValueError):segment_triangle((0,0,1),(0,0,-1),((0,0,0),)*3)
