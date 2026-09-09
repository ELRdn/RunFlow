"""Triangle-plane intersections for comparative evidence, not solid classification."""
import numpy as np


def section_segments(vertices,triangles,axis,value,chunk_size=100000):
    if axis not in (0,1,2) or not np.isfinite(value): raise ValueError('Invalid plane')
    segments=[]; coplanar=0
    for start in range(0,len(triangles),chunk_size):
        t=np.asarray(vertices)[np.asarray(triangles[start:start+chunk_size])]
        distance=t[:,:,axis]-value
        coplanar+=int(np.all(distance==0,axis=1).sum())
        crossed=(distance.min(axis=1)<0)&(distance.max(axis=1)>=0)
        t=t[crossed]; distance=distance[crossed]
        if not len(t): continue
        hit=np.empty((len(t),2,3)); count=np.zeros(len(t),dtype=np.int8)
        for a,b in ((0,1),(1,2),(2,0)):
            mask=(distance[:,a]<0)!=(distance[:,b]<0)
            ids=np.flatnonzero(mask)
            factor=distance[mask,a]/(distance[mask,a]-distance[mask,b])
            hit[ids,count[ids]]=t[mask,a]+factor[:,None]*(t[mask,b]-t[mask,a])
            count[ids]+=1
        valid=(count==2)&(np.linalg.norm(hit[:,0]-hit[:,1],axis=1)>1e-12)
        if valid.any(): segments.append(hit[valid])
    return (np.concatenate(segments) if segments else np.empty((0,2,3))),coplanar
