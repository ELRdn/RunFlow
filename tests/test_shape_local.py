import numpy as np
import pytest
from runflow.shape_local import clip_surface,select_context_faces


def area(v,f):
    t=v[f]; return np.linalg.norm(np.cross(t[:,1]-t[:,0],t[:,2]-t[:,0]),axis=1).sum()/2


def test_clip_crossing_triangle_area_winding_and_no_caps():
    v=np.array([[0.,0,0],[2,0,0],[0,2,0]]); f=np.array([[0,1,2]])
    before=v.copy(); a,b,ids=clip_surface(v,f,[0,0,-1],[1,1,1])
    assert area(a,b)==pytest.approx(1.)
    assert (ids==0).all() and (a[:,2]==0).all()
    t=a[b]; assert (np.cross(t[:,1]-t[:,0],t[:,2]-t[:,0])[:,2]>0).all()
    np.testing.assert_array_equal(v,before)
    np.testing.assert_array_equal(select_context_faces(v,f,[0,0,-1],[1,1,1]),[0])


def test_source_ids_inside_outside_boundary_and_degenerate():
    v=np.array([[0.,0,0],[1,0,0],[0,1,0],[3,0,0],[4,0,0],[3,1,0]])
    f=np.array([[3,4,5],[0,1,2],[0,0,0]])
    a,b,ids=clip_surface(v,f,[-1,-1,0],[2,2,1])
    assert area(a,b)==pytest.approx(.5)
    np.testing.assert_array_equal(ids,[1])
    a,b,ids=clip_surface(v,f,[5,5,5],[6,6,6])
    assert a.shape==b.shape==(0,3) and ids.shape==(0,)


def test_empty_surface_and_invalid_inputs():
    v=np.empty((0,3)); f=np.empty((0,3),dtype=int)
    assert clip_surface(v,f,[0,0,0],[1,1,1])[0].shape==(0,3)
    v=np.array([[0.,0,0],[1,0,0],[0,1,0]]); f=np.array([[0,1,2]])
    for fn in (clip_surface,select_context_faces):
        with pytest.raises(ValueError): fn(v,f,[1,0,0],[0,1,1])
        with pytest.raises(ValueError): fn(v,f.astype(float),[0,0,0],[1,1,1])
        with pytest.raises(ValueError): fn(v,np.array([[0,1,3]]),[0,0,0],[1,1,1])
        with pytest.raises(ValueError): fn(v+np.nan,f,[0,0,0],[1,1,1])


def test_negative_winding_retained_across_multiple_planes():
    v=np.array([[-2.,-2,0],[0,3,0],[3,-2,0]]); f=np.array([[0,1,2]])
    a,b,ids=clip_surface(v,f,[-.5,-.5,-1],[.5,.5,1])
    assert area(a,b)==pytest.approx(1.)
    t=a[b]; assert (np.cross(t[:,1]-t[:,0],t[:,2]-t[:,0])[:,2]<0).all()
