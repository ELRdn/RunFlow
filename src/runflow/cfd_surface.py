"""Minimal numerical cleanup of a saved surface; no fidelity optimization."""
from pathlib import Path
import numpy as np
from .core import read,write,file_hash
from .shape_audit import load_surface
from .shape_fullbody import repair_binary
from .local_geometry import export_cache,inspect,native,tools_manifest


def quality(vertices,faces):
    count=0;minimum=float('inf')
    for i in range(0,len(faces),100000):
        t=np.asarray(vertices)[faces[i:i+100000]]
        a=np.linalg.norm(np.cross(t[:,1]-t[:,0],t[:,2]-t[:,0]),axis=1)*.5
        if not np.isfinite(t).all() or not np.isfinite(a).all():raise ValueError('Nonfinite surface')
        count+=int((a<1e-16).sum());minimum=min(minimum,float(a.min(initial=float('inf'))))
    return dict(triangles=len(faces),near_degenerate_triangles=count,minimum_area_m2=minimum,complete=bool(len(faces)))


def changed_area_bound(vertices,faces,replacements):
    """A union's area change is bounded by all old/new affected projections.

    Deliberately conservative, including overlaps. This avoids claiming an exact
    repaired area from the old projection after cleanup. Cd uses original Aref.
    """
    remap=np.arange(len(vertices),dtype=np.int32)
    for item in replacements:remap[item['vertex_index']]=item['target_index']
    bound=0.;affected=[]
    for i in range(0,len(faces),100000):
        old=np.asarray(faces[i:i+100000]);new=remap[old];mask=np.any(old!=new,axis=1)
        if not mask.any():continue
        affected.extend((np.flatnonzero(mask)+i).tolist())
        for batch in (old[mask],new[mask]):
            p=np.asarray(vertices)[batch][:,:,[1,2]]
            a=p[:,1]-p[:,0];b=p[:,2]-p[:,0]
            bound+=float((np.abs(a[:,0]*b[:,1]-a[:,1]*b[:,0])*.5).sum())
    return dict(absolute_area_change_upper_m2=bound,affected_source_face_ids=affected,
        scope='Sum of old/new affected projected triangle areas, including overlaps; not an exact new union area.')


def obj64(path,vertices,faces):
    """17 significant digits round-trip binary64. No STL/binary32 intermediate."""
    with Path(path).open('x',encoding='ascii',newline='\n',buffering=1024*1024) as stream:
        stream.write('# RunFlow PRIVATE RF metres; binary64 round-trip decimal\n')
        for i in range(0,len(vertices),50000):np.savetxt(stream,vertices[i:i+50000],fmt='v %.17g %.17g %.17g')
        stream.write('g oguri\n')
        for i in range(0,len(faces),50000):np.savetxt(stream,np.asarray(faces[i:i+50000],dtype=np.int64)+1,fmt='f %d %d %d')
    return file_hash(path)


def prepare_surface(root,source):
    root=Path(root);geometry=root/'geometry';geometry.mkdir(exist_ok=False)
    v,f=load_surface(source)
    if v.dtype!=np.dtype('float64'):raise ValueError('Saved binary64 input required')
    before=quality(v,f);write(geometry/'quality-before.json',before)
    if before['near_degenerate_triangles']>16:raise ValueError('Minimum numerical cleanup scope exceeded; stop without a new repair search')
    repair=repair_binary(source,geometry/'surface-cache',1e-6)
    if repair['max_vertex_shift_m']>1e-6:raise ValueError('Numerical cleanup displacement exceeded')
    bound=changed_area_bound(v,f,repair['replacements']);write(geometry/'area-change-bound.json',bound)
    cv,cf=load_surface(geometry/'surface-cache');after=quality(cv,cf);write(geometry/'quality-after.json',after)
    if not after['complete'] or after['near_degenerate_triangles']:raise ValueError('Minimum triangle area gate failed after one local cleanup')
    binary=geometry/'candidate.rfmesh';exchange=export_cache(geometry/'surface-cache',binary)
    write(geometry/'native-tools.json',tools_manifest())
    intersections=inspect(binary,geometry/'intersections')
    native('inspect',['topology',binary,geometry/'topology.json']);topology=read(geometry/'topology.json')
    if not intersections['intersection_free'] or not topology['closed_manifold']:raise ValueError('Exact intersection / closed-manifold gate failed')
    surface_hash=obj64(geometry/'candidate.obj',cv,cf)
    record=dict(complete=True,surface_sha256=surface_hash,input_cache_sha256=file_hash(Path(source)/'cache.json'),
        candidate_cache_sha256=file_hash(geometry/'surface-cache/cache.json'),repair=repair,quality=after,
        candidate_topology=topology,exact_intersections=intersections,area_change_bound=bound,exchange=exchange,
        fidelity_status='DEFERRED_BY_USER_FOR_PROVISIONAL_MEASUREMENT',distance_passed=False,
        remesh_passes=0,scientific_status='UNVALIDATED_PROVISIONAL_GEOMETRY')
    write(geometry/'geometry.json',record)
