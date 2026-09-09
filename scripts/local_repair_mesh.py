"""Local geometry operators. No voxelization, smoothing, or inferred source faces."""
import itertools
import numpy as np
import shapely
from ray_carve_surface import height_volume


def frame(roi,angle=0.):
    basis=np.eye(3)[[*roi['axes'],roi['view_axis']]].copy()
    basis[2]*=-roi['view_sign']
    a=np.deg2rad(angle);v=basis[1].copy();d=basis[2].copy()
    basis[1]=np.cos(a)*v+np.sin(a)*d;basis[2]=-np.sin(a)*v+np.cos(a)*d
    return basis


def conservative_cutter(v,f,roi,step,margin,angle=0.,max_cells=2000000):
    """Minimum over clipped triangles in each cell, then incident-cell minimum.

    The native continuous certificate is still required after construction/Boolean.
    Degenerate projections use the minimum triangle depth as a conservative bound.
    """
    if step not in (.0001,.00005) or margin not in (.0002,.0001,.00005):raise ValueError('Unplanned observation settings')
    basis=frame(roi,angle);q=np.asarray(v,dtype=float)@basis.T
    corners=np.array(list(itertools.product(*zip(roi['low_m'],roi['high_m']))))@basis.T
    low=corners.min(0);high=corners.max(0)
    dims=np.ceil((high[:2]-low[:2])/step).astype(int)
    if dims.prod()>max_cells:raise ValueError('Predicted observation grid limit')
    us=np.linspace(low[0],high[0],dims[0]+1);vs=np.linspace(low[1],high[1],dims[1]+1)
    x,y=np.meshgrid(us[:-1],vs[:-1]);xx,yy=np.meshgrid(us[1:],vs[1:])
    boxes=shapely.box(x.ravel(),y.ravel(),xx.ravel(),yy.ravel());tree=shapely.STRtree(boxes)
    outside=float(q[:,2].min()-.01);far=float(q[:,2].max()+.01)
    depths=np.full(len(boxes),far);tri=q[f]
    ids=np.flatnonzero((tri[:,:,:2].max(1)>=low[:2]).all(1)&(tri[:,:,:2].min(1)<=high[:2]).all(1))
    for i in ids:
        t=tri[i];poly=shapely.Polygon(t[:,:2]);normal=np.cross(t[1]-t[0],t[2]-t[0])
        if poly.area<1e-20:
            poly=shapely.LineString(t[:,:2]);hits=tree.query(poly,predicate='intersects')
            depths[hits]=np.minimum(depths[hits],t[:,2].min()-margin);continue
        hits=tree.query(poly,predicate='intersects')
        if not len(hits):continue
        pieces=shapely.intersection(boxes[hits],poly);xy,which=shapely.get_coordinates(pieces,return_index=True)
        if abs(normal[2])<1e-16*np.linalg.norm(normal):
            z=np.full(len(xy),t[:,2].min())
        else:z=t[0,2]-(xy-t[0,:2])@normal[:2]/normal[2]
        local=np.full(len(hits),np.inf);np.minimum.at(local,which,z-margin)
        depths[hits]=np.minimum(depths[hits],local)
    depth=depths.reshape(len(vs)-1,len(us)-1)
    h=np.full((len(vs),len(us)),far)
    for dy,dx in ((0,0),(0,1),(1,0),(1,1)):
        h[dy:dy+depth.shape[0],dx:dx+depth.shape[1]]=np.minimum(h[dy:dy+depth.shape[0],dx:dx+depth.shape[1]],depth)
    cv,cf=height_volume(us,vs,h-outside,2,[0,1],-1,outside);cv=cv@basis
    if np.linalg.det(basis)<0:cf=cf[:,[0,2,1]]
    return cv,cf,dict(step_m=step,margin_m=margin,angle_deg=angle,cells=int(dims.prod()),
        source_faces_considered=len(ids),basis=basis.tolist(),whole_original_occluders=True,
        rule='Triangle-cell clipping; incident minimum; independent native certificate required')


def selected_faces(v,f,low,high,all_corners=False):
    ids=[]
    for start in range(0,len(f),200000):
        t=np.asarray(v)[f[start:start+200000]]
        mask=((t>=low)&(t<=high)).all(2)
        hit=mask.all(1) if all_corners else mask.any(1)
        ids.extend((np.flatnonzero(hit)+start).tolist())
    return np.asarray(ids,dtype=np.int64)


def patch_loops(faces):
    edges=np.asarray(faces)[:,[0,1,1,2,2,0]].reshape(-1,2)
    keys=np.sort(edges,axis=1);_,inv,count=np.unique(keys,axis=0,return_inverse=True,return_counts=True)
    if (count>2).any():raise ValueError('Patch has nonmanifold edges')
    boundary=edges[count[inv]==1]
    if not len(boundary):return []
    if len(np.unique(boundary[:,0]))!=len(boundary) or len(np.unique(boundary[:,1]))!=len(boundary):
        raise ValueError('Patch boundary branches')
    nxt=dict(map(tuple,boundary));loops=[]
    while nxt:
        start=next(iter(nxt));cur=start;loop=[]
        while True:
            loop.append(int(cur))
            if cur not in nxt:raise ValueError('Open boundary chain')
            cur=nxt.pop(cur)
            if cur==start:break
        loops.append(np.array(loop,dtype=np.int64))
    return loops


def grow_faces(f,seed,rings):
    selected=np.zeros(len(f),bool);selected[seed]=True
    for _ in range(rings):
        vertices=np.unique(f[selected]);selected|=np.isin(f,vertices).any(1)
    return np.flatnonzero(selected)


def zipper(v,outer,inner):
    """Connect two already oriented corresponding boundary loops, without moving them."""
    outer=np.asarray(outer);inner=np.asarray(inner)
    first=np.argmin(np.linalg.norm(v[inner]-v[outer[0]],axis=1));inner=np.roll(inner,-int(first))
    def fractions(ids):
        length=np.linalg.norm(v[np.roll(ids,-1)]-v[ids],axis=1)
        if (length<=0).any():raise ValueError('Zero seam edge')
        return np.r_[0,np.cumsum(length)/length.sum()]
    a,b=fractions(outer),fractions(inner);i=j=0;out=[]
    while i<len(outer) or j<len(inner):
        oi=outer[i%len(outer)];ij=inner[j%len(inner)]
        if j==len(inner) or (i<len(outer) and a[i+1]<=b[j+1]):
            out.append((oi,outer[(i+1)%len(outer)],ij));i+=1
        else:out.append((oi,inner[(j+1)%len(inner)],ij));j+=1
    return np.asarray(out,dtype=np.int32)


def normals(v,f):
    n=np.cross(v[f[:,1]]-v[f[:,0]],v[f[:,2]]-v[f[:,0]])
    size=np.linalg.norm(n,axis=1);good=size>1e-20;n[good]/=size[good,None];n[~good]=0
    return n


def thin_shell(v,f,thickness):
    """Keep source surface fixed, add the inner sheet and oriented boundary walls."""
    if thickness not in (.0004,.0002,.0001):raise ValueError('Unplanned thickness')
    ids,inv=np.unique(f,return_inverse=True);faces=inv.reshape(-1,3);points=np.asarray(v[ids],float)
    n=normals(points,faces);vn=np.zeros_like(points)
    for k in range(3):np.add.at(vn,faces[:,k],n)
    size=np.linalg.norm(vn,axis=1)
    if (size<.1).any():raise ValueError('Thin-patch side is ambiguous')
    vn/=size[:,None];vertices=np.r_[points,points-vn*thickness];count=len(points)
    loops=patch_loops(faces);walls=[]
    for loop in loops:
        for a,b in zip(loop,np.roll(loop,-1)):walls.extend(((b,a,a+count),(b,a+count,b+count)))
    if not walls:raise ValueError('No open source patch to thicken')
    return vertices,np.concatenate((faces,faces[:,[0,2,1]]+count,np.asarray(walls,dtype=np.int32))),ids
