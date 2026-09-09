"""Phase 1 contracts are separate from the immutable Phase 0 contracts."""
from jsonschema import Draft202012Validator
from .contracts import obj, HASH, TEXT, NUM
from .core import canonical
from copy import deepcopy


def fixed(value):
    return {"const": value}


PROTOCOL = obj({
    "schema_version": fixed("1"), "protocol_id": fixed("RF-CFD-P1-SMOKE-001"),
    "solver": fixed("OpenFOAM Foundation 14/incompressibleFluid"), "package_version": fixed("20260724"),
    "frame": fixed(0), "reference_height_m": fixed(1.67), "inlet_direction": fixed([-1,0,0]),
    "speed_m_s": fixed(20), "air_density_kg_m3": fixed(1.2), "kinematic_viscosity_m2_s": fixed(1.5e-5),
    "turbulence_model": fixed("kOmegaSST"), "turbulence_intensity": fixed(.01),
    "turbulence_length_height_ratio": fixed(.01), "ground_condition": fixed("none"),
    "geometry": obj({k: fixed(v) for k,v in dict(weld_m=1e-6,voxel_m=.001,max_distance_m=.002,max_area_relative=.01,max_cover_radius_m=.00025).items()}),
    "domain": obj({k: fixed(v) for k,v in dict(upstream_H=5,downstream_H=15,lateral_H=5,vertical_H=5).items()}),
    "mesh": obj({k: fixed(v) for k,v in dict(background_H=.25,surface_level=5,wake_level=2,layers=3,first_layer_fraction=.2,layer_expansion=1.2,max_cells=1000000).items()}),
    "limits": obj({k: fixed(v) for k,v in dict(geometry_s=600,mesh_s=1200,solver_s=1500,report_s=300,total_s=3600,processes=4,memory_bytes=12*1024**3,output_bytes=10*1024**3).items()}),
    "convergence": obj({k: fixed(v) for k,v in dict(min_iterations=300,max_iterations=2000,window=100,pressure_residual=1e-4,other_residual=1e-5,mean_drag_relative=.01,drag_range_relative=.02,flux_relative=.001).items()})
})
RESULT = obj({"schema_version": fixed("phase1-1"), "experiment_id": TEXT,
    "execution_status": {"enum":["PREPARED","PASS","FAIL","BLOCKED","TIMEOUT","NOT_CONVERGED"]},
    "scientific_status": fixed("UNVALIDATED_SMOKE"), "ranking_eligible": fixed(False),
    "drag_N": {"type":["number","null"]}, "Cd": {"type":["number","null"]}, "CdA_m2": {"type":["number","null"]},
    "reason": TEXT, "stage": TEXT, "evidence": {"type":"object"}})
RESULT['allOf']=[{'if':{'properties':{'execution_status':fixed('PASS')}},
    'then':{'properties':{key:{'type':'number','exclusiveMinimum':0} for key in ('drag_N','Cd','CdA_m2')}},
    'else':{'properties':{key:{'type':'null'} for key in ('drag_N','Cd','CdA_m2')}}}]
EXPERIMENT = obj({"schema_version": fixed("phase1-1"), "experiment_id": TEXT, "config_sha256": HASH,
    "config": obj({"source_snapshot_sha256": HASH, "source_manifest_sha256": HASH,
        "surface_sha256": HASH, "protocol": PROTOCOL, "frame_time_s": NUM,
        "clip_phase_s": NUM, "source_area_m2": {'type':'number','exclusiveMinimum':0}, "repaired_area_m2": {'type':'number','exclusiveMinimum':0},
        "source_bbox": {"type":"array","minItems":2,"maxItems":2,'items':{'type':'array','minItems':3,'maxItems':3,'items':NUM}},
        "tool_hashes": {"type":"object","additionalProperties":HASH}})})

# A separately labelled lane records the user's decision to measure the current
# surface. The existing fidelity-gated protocol remains immutable.
PROVISIONAL_VERSION='phase1-provisional-1'
PROVISIONAL_PROTOCOL=deepcopy(PROTOCOL)
PROVISIONAL_PROTOCOL['properties'].update(schema_version=fixed(PROVISIONAL_VERSION),protocol_id=fixed('RF-CFD-P1-PROVISIONAL-001'),
    geometry=obj({'mode':fixed('saved_0.9mm_local_repair'),'local_weld_m':fixed(1e-6),
        'min_triangle_area_m2':fixed(1e-16),'voxel_remesh_passes':fixed(0),
        'fidelity_gate':fixed('DEFERRED_BY_USER_FOR_PROVISIONAL_MEASUREMENT')}))
# Optional volume-grid diagnostic; the original protocol and its existing
# values/gates remain immutable. It never regenerates the character surface.
PROVISIONAL_PROTOCOL['properties']['diagnostic_refinement']=obj({
    'reason_id':fixed('oguri_coat_tip_flow_reversal_001'),'source_snapshot_sha256':HASH,
    'box_min_m':{'type':'array','minItems':3,'maxItems':3,'items':NUM},
    'box_max_m':{'type':'array','minItems':3,'maxItems':3,'items':NUM},
    'level':{'enum':[6,7]}})
PROVISIONAL_RESULT=deepcopy(RESULT)
PROVISIONAL_RESULT['properties'].update(schema_version=fixed(PROVISIONAL_VERSION),
    scientific_status=fixed('UNVALIDATED_PROVISIONAL_GEOMETRY'),geometry_qualification=fixed('PROVISIONAL_USER_AUTHORIZED'))
PROVISIONAL_RESULT['required'].append('geometry_qualification')
PROVISIONAL_EXPERIMENT=deepcopy(EXPERIMENT)
PROVISIONAL_EXPERIMENT['properties']['schema_version']=fixed(PROVISIONAL_VERSION)
_config=PROVISIONAL_EXPERIMENT['properties']['config']
_config['properties']['protocol']=PROVISIONAL_PROTOCOL
_config['properties'].update(provisional_authorization_sha256=HASH,input_receipt_sha256=HASH,
    fidelity_status=fixed('DEFERRED_BY_USER_FOR_PROVISIONAL_MEASUREMENT'),
    repaired_area_bounds_m2={'type':'array','minItems':2,'maxItems':2,'items':{'type':'number','exclusiveMinimum':0}})
_config['required']+=['provisional_authorization_sha256','input_receipt_sha256','fidelity_status','repaired_area_bounds_m2']


def validate(kind, value):
    canonical(value)
    if value.get('schema_version')=='phase1-study-1':
        from . import cfd_study_contracts as study
        schemas={'protocol':study.PROTOCOL,'experiment':study.EXPERIMENT,'result':study.RESULT}
    else:
        schemas=({'protocol':PROVISIONAL_PROTOCOL,'result':PROVISIONAL_RESULT,'experiment':PROVISIONAL_EXPERIMENT}
        if value.get('schema_version')==PROVISIONAL_VERSION else {"protocol":PROTOCOL,"result":RESULT,"experiment":EXPERIMENT})
    errors=list(Draft202012Validator(schemas[kind]).iter_errors(value))
    if errors:
        raise ValueError('; '.join(e.message for e in errors[:5]))
    p=value if kind=='protocol' else value.get('config',{}).get('protocol',{})
    if value.get('schema_version')=='phase1-study-1':study.semantic_check(p)
    diagnostic=p.get('diagnostic_refinement')
    if diagnostic and any(a>=b for a,b in zip(diagnostic['box_min_m'],diagnostic['box_max_m'])):
        raise ValueError('Local fluid-grid bounds must have positive extent')
    if kind=='experiment' and diagnostic and diagnostic['source_snapshot_sha256']!=value['config']['source_snapshot_sha256']:
        raise ValueError('Local fluid-grid diagnostic source does not match experiment')
