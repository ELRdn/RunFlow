"""Attribute numeric intersections and document every source component without exclusions."""
from pathlib import Path
import numpy as np
from local_surface_worker import surface_ref,REPO
from runflow.shape_audit import load_surface,file_sha
from runflow.shape_fullbody import read,write
from runflow.shape_sections import section_segments


def ray_hits(point,direction,tri):
    """Diagnostic rays only: absence of hits in finitely many directions is not topology."""
    a=tri[:,0];e1=tri[:,1]-a;e2=tri[:,2]-a;h=np.cross(direction,e2);det=np.einsum('ij,ij->i',e1,h)
    valid=np.abs(det)>1e-15;inv=np.zeros_like(det);inv[valid]=1/det[valid]
    s=point-a;u=np.einsum('ij,ij->i',s,h)*inv;q=np.cross(s,e1);v=q@direction*inv;t=np.einsum('ij,ij->i',e2,q)*inv
    hit=valid&(u>=-1e-9)&(v>=-1e-9)&(u+v<=1+1e-9)&(t>2e-6)
    idx=np.flatnonzero(hit)
    return None if not len(idx) else int(idx[np.argmin(t[idx])])


def diagnose(root,folder):
    atlas_path=root/'runs/source-defect-atlas/defect-atlas.json';atlas=read(atlas_path)
    v,f=load_surface(surface_ref(root,'source'));tri=np.asarray(v)[f]
    dirs=np.array([p for p in __import__('itertools').product((-1,0,1),repeat=3) if p!=(0,0,0)],float)
    dirs/=np.linalg.norm(dirs,axis=1)[:,None]
    points=[];records=[]
    labels=np.load(root/'runs/source-defect-atlas/source-components.npy')
    for rec in atlas['components']:
        if not rec['definite_counterexample_faces']:continue
        rec=rec.copy();face=rec['witness_source_face'];p=tri[face].mean(0)
        occluders=[ray_hits(p,d,tri) for d in dirs]
        visible=[i for i,t in enumerate(occluders) if t is None]
        faceids=np.flatnonzero(labels==rec['id']);np.save(folder/f'component-{rec["id"]}-source-faces.npy',faceids)
        rec.update(witness_ray_directions=dirs.tolist(),witness_occluding_source_faces=occluders,
            sampled_exterior_sight_lines=visible,
            visibility_class='VISIBLE_ON_TESTED_RAY' if visible else 'OCCLUDED_ON_26_RAYS_INTERIOR_UNPROVEN',
            repair_class='HUMAN_CLASSIFICATION_REQUIRED',excluded_from_metric=False)
        points.append(p);records.append(rec)
    write(folder/'classified-atlas.json',dict(complete=True,components=records,source_atlas_sha256=file_sha(atlas_path),
        note='Classifications attach to witnesses only. No source face is excluded. Occlusion is not a sealed-interior certificate.'))
    precision=[]
    for label in ('base900','raw_carve64','raw-import64','simplified64','rounded32','old_carve32','reimport32'):
        matches=[p for p in (root/'runs').glob('*/result.json') if read(p).get('surface')==label]
        if not matches:continue
        p=matches[-1];r=read(p);pairs=np.fromfile(p.parent/'intersection.pairs.bin',dtype='<u8').reshape(-1,2)
        sv,sf=load_surface(surface_ref(root,label));info=[]
        for pair in pairs:
            t=np.asarray(sv)[sf[pair.astype(int)]];info.append(dict(faces=pair.tolist(),centers_m=t.mean(1).tolist(),bbox_m=[t.min((0,1)).tolist(),t.max((0,1)).tolist()]))
        precision.append(dict(surface=label,inspection=r,pairs=info))
    av,af=load_surface(surface_ref(root,'simplified64'));bv,bf=load_surface(surface_ref(root,'rounded32'))
    same=np.array_equal(af,bf);shift=float(np.linalg.norm(np.asarray(av)-np.asarray(bv),axis=1).max()) if len(av)==len(bv) else None
    write(folder/'precision-attribution.json',dict(complete=True,stages=precision,rounding_same_faces=same,
        maximum_corresponding_vertex_rounding_m=shift,rounding_surface_bound_valid=same and shift is not None,
        historical_in_memory_boolean_state_recreated=False,
        conclusion='This diagnostic replay isolates simplification and rounding. Historical unsaved intermediates are not claimed identical.'))
    # Cross-sections expose the fixed global counterexample in context.
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    worst=np.array(atlas['components'][0]['witness_center_m'])
    cv,cf=load_surface(surface_ref(root,'base900'))
    fig,axes=plt.subplots(1,3,figsize=(15,5));cols=['#146db0','#e48318']
    for ax,axis in zip(axes,range(3)):
        other=[i for i in range(3) if i!=axis]
        for (vv,ff),color,label in zip(((v,f),(cv,cf)),cols,('Original','Saved 0.9 mm')):
            seg,_=section_segments(vv,ff,axis,float(worst[axis]));np.save(folder/f'witness-section-{axis}-{label.split()[0]}.npy',seg)
            from matplotlib.collections import LineCollection
            ax.add_collection(LineCollection(seg[:,:,other],colors=color,linewidths=.65,label=label))
        ax.scatter(*worst[other],s=45,c='black',marker='x',label='Source witness');ax.set_xlim(worst[other[0]]-.1,worst[other[0]]+.1)
        ax.set_ylim(worst[other[1]]-.1,worst[other[1]]+.1);ax.set_aspect('equal');ax.set_title('Section '+str(axis)+'; metres');ax.grid(alpha=.2)
    axes[0].legend(fontsize=8);fig.suptitle('Fixed original-surface counterexample (no source faces excluded)')
    fig.tight_layout();fig.savefig(folder/'counterexample-sections.png',dpi=170);plt.close(fig)
    print('DIAGNOSTICS_COMPLETE',len(records),flush=True)


def classify_sides(root,folder):
    from local_surface_worker import native_surface
    from runflow.local_geometry import native
    source_path=root/'runs/fullbody-diagnosis/classified-atlas.json';atlas=read(source_path)
    records=atlas['components'];points=np.array([r['witness_center_m'] for r in records],dtype='<f8')
    points.tofile(folder/'queries.bin')
    native('inspect',['inside',native_surface(root,'base900'),folder/'queries.bin',folder/'sides.bin'])
    sides=np.fromfile(folder/'sides.bin',dtype=np.int8)
    if len(sides)!=len(records):raise ValueError('Partial side classification')
    proposed=[]
    for rec,side,p in zip(records,sides,points):
        rec['witness_side_of_closed_base']=int(side)
        visible=rec['sampled_exterior_sight_lines']
        rec['repair_class']=('OBSERVED_FILLED_SPACE_CANDIDATE' if side==1 else 'MISSING_SOURCE_SURFACE_CANDIDATE') if visible else 'HUMAN_CLASSIFICATION_REQUIRED'
        if visible and side==1:
            directions=np.array(rec['witness_ray_directions'])
            axial=[i for i in visible if np.count_nonzero(directions[i])==1]
            if not axial:continue
            direction=directions[axial[0]];axis=int(np.argmax(abs(direction)));axes=[i for i in range(3) if i!=axis]
            proposed.append(dict(id='atlas-'+str(rec['id']),source_component=rec['id'],witness_source_face=rec['witness_source_face'],
                low_m=(p-.012).tolist(),high_m=(p+.012).tolist(),view_axis=axis,axes=axes,view_sign=int(direction[axis]),
                reason='Source witness exceeds distance threshold, is visible on an axial diagnostic ray, and lies inside closed saved base',
                semantic_part=None,source_atlas_sha256=file_sha(source_path)))
    write(folder/'classified-sides.json',dict(complete=True,components=records,
        note='Base inside/outside is exact-predicate classification; source visibility remains sampled and no internal source face is excluded.'))
    write(folder/'proposed-regions.json',dict(regions=proposed[:3],unselected_region_count=max(0,len(proposed)-3),
        selection_rule='First three eligible largest lower-bound witnesses; 12mm half-width, plus existing 5mm collar',
        source_atlas_sha256=file_sha(source_path)))
    print('DEFECT_SIDES',len(records),'PROPOSED',len(proposed[:3]),flush=True)
