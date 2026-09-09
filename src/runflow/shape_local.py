"""Local surface selection and box clipping for measurement; never add caps."""
import numpy as np


def _validate(vertices,triangles,low,high):
    v=np.asarray(vertices); f=np.asarray(triangles); lo=np.asarray(low,dtype=float); hi=np.asarray(high,dtype=float)
    if v.ndim!=2 or v.shape[1]!=3 or v.dtype.kind not in 'fiu' or not np.isfinite(v).all():
        raise ValueError('Finite Nx3 vertices required')
    if f.ndim!=2 or f.shape[1]!=3 or f.dtype.kind not in 'iu': raise ValueError('Integer Mx3 triangles required')
    if len(f) and (f.min()<0 or f.max()>=len(v)): raise ValueError('Triangle index outside vertex buffer')
    if lo.shape!=(3,) or hi.shape!=(3,) or not np.isfinite([lo,hi]).all() or not (lo<hi).all():
        raise ValueError('Finite ordered box bounds required')
    return v,f,lo,hi


def select_context_faces(vertices,triangles,low,high):
    """Return indices of full triangles whose AABBs intersect the closed box."""
    v,f,lo,hi=_validate(vertices,triangles,low,high); selected=[]
    for start in range(0,len(f),100000):
        t=v[f[start:start+100000]]
        mask=(t.max(axis=1)>=lo).all(axis=1)&(t.min(axis=1)<=hi).all(axis=1)
        selected.append(np.flatnonzero(mask)+start)
    return np.concatenate(selected) if selected else np.empty(0,dtype=np.int64)


def _clip_polygon(poly,axis,bound,greater):
    result=[]
    for a,b in zip(poly,poly[1:]+poly[:1]):
        a_in=a[axis]>=bound if greater else a[axis]<=bound
        b_in=b[axis]>=bound if greater else b[axis]<=bound
        if a_in: result.append(a)
        if a_in!=b_in:
            alpha=(bound-a[axis])/(b[axis]-a[axis]); point=a+alpha*(b-a)
            point[axis]=bound; result.append(point)
    return result


def clip_surface(vertices,triangles,low,high):
    """Clip each triangle with six planes, retaining winding and original IDs.

    Output is a triangle soup with repeated vertices. All generated triangles
    lie on original triangle surfaces; no cross-section caps are introduced.
    """
    v,f,lo,hi=_validate(vertices,triangles,low,high)
    ids=select_context_faces(v,f,lo,hi)
    if not len(ids): return np.empty((0,3)),np.empty((0,3),dtype=np.int32),np.empty(0,dtype=np.int64)
    t=v[f[ids]].astype(np.float64)
    inside=((t>=lo)&(t<=hi)).all(axis=(1,2))
    pieces=[t[inside]]; labels=[ids[inside]]
    boundary=[]; boundary_ids=[]
    for face_id,triangle in zip(ids[~inside],t[~inside]):
        poly=list(triangle)
        for axis in range(3):
            poly=_clip_polygon(poly,axis,lo[axis],True)
            if not poly: break
            poly=_clip_polygon(poly,axis,hi[axis],False)
            if not poly: break
        for index in range(1,len(poly)-1):
            boundary.append([poly[0],poly[index],poly[index+1]]); boundary_ids.append(face_id)
    if boundary: pieces.append(np.asarray(boundary)); labels.append(np.asarray(boundary_ids,dtype=np.int64))
    triangles_out=np.concatenate(pieces); face_ids=np.concatenate(labels)
    positive=np.linalg.norm(np.cross(triangles_out[:,1]-triangles_out[:,0],triangles_out[:,2]-triangles_out[:,0]),axis=1)>0
    triangles_out=triangles_out[positive]; face_ids=face_ids[positive]
    out_v=triangles_out.reshape(-1,3)
    return out_v,np.arange(len(out_v),dtype=np.int32).reshape(-1,3),face_ids
