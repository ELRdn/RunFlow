"""Private surface-repair experiments; these never adopt a CFD surface."""
from pathlib import Path
import numpy as np
from runflow.shape_audit import file_sha
from runflow.shape_fullbody import read

RECIPES = {
    'nearest25': dict(method='bounded_nearest', fraction=.25, max_move_m=.0005),
    'normal50': dict(method='bounded_normal', fraction=.5, max_move_m=.0005),
    'detail_union': dict(method='original_detail_union', thickness_m=.0004,
                         selection_distance_m=.001, neighbour_rings=1,
                         solidify_mode='NON_MANIFOLD', thickness_mode='CONSTRAINTS',
                         boolean_solver='EXACT', use_self=True),
}


def bounded_delta(delta, fraction, max_move_m, normals=None):
    """No topology change; cap each displacement in metres, before binary32 export."""
    delta=np.array(delta,dtype=np.float64,copy=True)
    if delta.ndim!=2 or delta.shape[1]!=3 or not np.isfinite(delta).all():
        raise ValueError('Finite N x 3 displacements required')
    if not 0<fraction<1 or not 0<max_move_m<=.001:
        raise ValueError('Bounded fractional correction required')
    if normals is not None:
        normals=np.asarray(normals,dtype=np.float64)
        if normals.shape!=delta.shape or not np.isfinite(normals).all():
            raise ValueError('Finite matching normals required')
        lengths=np.linalg.norm(normals,axis=1)
        normals=normals/np.maximum(lengths[:,None],1e-30)
        delta=(delta*normals).sum(1)[:,None]*normals
    delta*=fraction
    length=np.linalg.norm(delta,axis=1)
    return delta*np.minimum(1.,max_move_m/np.maximum(length,1e-30))[:,None]


def distance_state(value, tolerance=.002):
    if not value: return 'UNVERIFIED'
    # A single measured lower bound can disprove a global criterion. It cannot prove it.
    if value.get('witness_lower_m',value.get('global_max_lower_m',0))>tolerance:
        return 'FAIL'
    if value.get('complete') and value.get('global_max_upper_m',float('inf'))<=tolerance:
        return 'PASS'
    return 'UNVERIFIED'


def gate(metrics, human_parts=None):
    ds=[distance_state(metrics.get(k)) for k in ('forward','reverse')]
    dist='FAIL' if 'FAIL' in ds else 'PASS' if ds==['PASS','PASS'] else 'UNVERIFIED'
    area=metrics.get('projection-front'); topo=metrics.get('topology')
    area_state=('PASS' if area['relative_change_abs']<=.01 else 'FAIL') if area and area.get('complete') else 'UNVERIFIED'
    topo_state=('PASS' if topo['closed'] else 'FAIL') if topo and topo.get('complete') else 'UNVERIFIED'
    intersection=metrics.get('self-intersections')
    si_state=('PASS' if intersection['intersection_free'] else 'FAIL') if intersection and intersection.get('complete') else 'UNVERIFIED'
    parts='PASS' if human_parts is True else 'FAIL' if human_parts is False else 'UNVERIFIED'
    checks=dict(distance_2mm=dist,frontal_area_1percent=area_state,closed_topology=topo_state,
                self_intersections=si_state,mandatory_parts_human_review=parts)
    verdict='FAIL' if 'FAIL' in checks.values() else 'PASS' if set(checks.values())=={'PASS'} else 'UNVERIFIED'
    return dict(checks=checks,verdict=verdict,scientific_status='UNAPPROVED',ranking_eligible=False,
                human_adoption=None,drag_N=None,Cd=None,CdA_m2=None)


def validate(request):
    if request.get('kind')!='fullbody_surface_repair_v1' or request.get('bases_um')!=[1000,900]:
        raise ValueError('Only saved 1mm and 0.9mm full bodies are authorized')
    if request.get('recipes')!=RECIPES: raise ValueError('Unknown repair recipe')
    if request.get('frame')!=0 or request.get('adoption')!='adopted-002': raise ValueError('Wrong frame/adoption')
    for item in request['inputs'].values():
        if file_sha(item['path'])!=item['sha256']: raise ValueError('Input hash mismatch: '+str(item['path']))
    source=read(request['inputs']['source']['path'])
    if source.get('unit')!='m' or source.get('coordinate_system')!='RF_X_FORWARD_Z_UP':
        raise ValueError('Metres and RF coordinates required')
    manifest=read(request['inputs']['manifest']['path'])
    frame=next((a for a in manifest['assets'] if a['path']=='unity-a/runflow_capture_f0000.snapshot.json'),None)
    if frame is None or frame['sha256']!=request['inputs']['source']['sha256']:
        raise ValueError('Source is not adopted frame 0')
    for base in request['bases_um']:
        cache=read(request['inputs'][f'v{base}-cache']['path'])
        for name in ('vertices','triangles'):
            if cache['output_hashes'][name+'.npy']!=request['inputs'][f'v{base}-{name}']['sha256']:
                raise ValueError('Base cache identity mismatch')
    return source


def identity(request,tool_pins):
    # Blender's bundled Python intentionally does not import CLI-only jsonschema.
    from runflow.core import digest
    config=dict(kind=request['kind'],adoption=request['adoption'],frame=request['frame'],
                bases_um=request['bases_um'],recipes=request['recipes'],
                input_hashes={k:v['sha256'] for k,v in request['inputs'].items()},tool_pins=tool_pins,
                regions=request.get('regions',[]),witnesses=request.get('witnesses',[]),
                thresholds=dict(distance_m=.002,frontal_area_relative=.01),
                global_cover_m=.001,local_cover_m=.0001,projection_grid_m=1e-9)
    return dict(study_id='rf-repair-'+digest(config),config=config)
