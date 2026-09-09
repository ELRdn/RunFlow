"""Exact rational classification of small diagnostic segment/triangle pairs.

Float inputs are converted exactly to rationals. This is a diagnostic reference,
not a replacement for the full-surface self-intersection gate.
"""
from fractions import Fraction

def sub(a,b):return tuple(x-y for x,y in zip(a,b))
def dot(a,b):return sum(x*y for x,y in zip(a,b))
def cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
def vector(p):return tuple(Fraction(float(x)) for x in p)
def orient(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
def inside(p,t):
    signs=[orient(t[i],t[(i+1)%3],p) for i in range(3)]
    return all(s>=0 for s in signs) or all(s<=0 for s in signs)
def overlaps(a,b,c,d):
    return (orient(a,b,c)*orient(a,b,d)<=0 and orient(c,d,a)*orient(c,d,b)<=0
            and all(max(min(a[k],b[k]),min(c[k],d[k]))<=min(max(a[k],b[k]),max(c[k],d[k])) for k in (0,1)))

def segment_triangle(a,b,triangle):
    a,b=vector(a),vector(b);t=tuple(vector(p) for p in triangle)
    e1,e2=sub(t[1],t[0]),sub(t[2],t[0]);normal=cross(e1,e2)
    if not any(normal):raise ValueError('Degenerate target triangle')
    direction=sub(b,a);pvec=cross(direction,e2);det=dot(e1,pvec)
    if det:
        tvec=sub(a,t[0]);qvec=cross(tvec,e1)
        u=dot(tvec,pvec)/det;v=dot(direction,qvec)/det;distance=dot(e2,qvec)/det
        return dict(intersects=bool(0<=u<=1 and 0<=v and u+v<=1 and 0<=distance<=1),coplanar=False,
                    u=str(u),v=str(v),t=str(distance),det=str(det))
    if dot(sub(a,t[0]),normal):return dict(intersects=False,coplanar=False,parallel=True)
    drop=next(i for i,x in enumerate(normal) if x);axes=[i for i in range(3) if i!=drop]
    def project(p):return tuple(p[i] for i in axes)
    a,b=project(a),project(b);t=tuple(project(p) for p in t)
    return dict(intersects=bool(inside(a,t) or inside(b,t) or any(overlaps(a,b,t[i],t[(i+1)%3]) for i in range(3))),coplanar=True)
