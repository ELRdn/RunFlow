"""Numerical comparisons with input identity and convergence checked independently."""
from copy import deepcopy
import math
from itertools import combinations
from pathlib import Path

from .core import read, file_hash, digest
from .cfd_metrics import read_forces, read_residuals, assess, coefficients


def positive(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value > 0


def richardson_equal_ratio(values, ratio, *, systematic_refinement_verified=False):
    """Fine/middle/coarse values. No GCI from unverified adaptive-grid families."""
    result=dict(status='UNQUALIFIED',observed_order=None,fine_GCI_rel=None,extrapolated=None,
                systematic_refinement_verified=systematic_refinement_verified)
    if len(values)!=3 or not all(positive(x) for x in values) or not positive(ratio) or ratio<1.1:
        raise ValueError('Three finite positive values and refinement ratio >= 1.1 required')
    fine,middle,coarse=values; e21=middle-fine; e32=coarse-middle
    if e21==0 or e32==0:
        return dict(result,reason='Indistinguishable differences cannot establish observed order')
    if e21*e32<=0 or abs(e32)<=abs(e21):
        return dict(result,reason='Not monotonic convergence toward the fine grid')
    order=math.log(abs(e32/e21))/math.log(ratio)
    if not systematic_refinement_verified:
        return dict(result,reason='Systematic effective spacing and wall-layer refinement not verified',
                    nominal_observed_order_diagnostic=order)
    denominator=ratio**order-1
    return dict(result,status='CONDITIONAL_NUMERICAL_ESTIMATE',observed_order=order,
        fine_GCI_rel=1.25*abs(e21/fine)/denominator,extrapolated=fine-e21/denominator,
        safety_factor=1.25,reason='Three-grid estimate; physical/model/geometry errors excluded')


def read_case(root):
    root=Path(root);result=read(root/'result.json');exp=read(root/'experiment.json')
    config=exp['config'];protocol=config['protocol']
    if digest(config)!=exp['config_sha256'] or result['experiment_id']!=exp['experiment_id']:
        raise ValueError('Experiment identity mismatch')
    for name,key in [('source.snapshot.json','source_snapshot_sha256'),('geometry/candidate.obj','surface_sha256')]:
        if file_hash(root/name)!=config[key]:raise ValueError('Study shape input changed')
    design=read(root/'case-design.json')
    out=dict(root_name=root.name,result_sha256=file_hash(root/'result.json'),experiment_sha256=file_hash(root/'experiment.json'),
        status=result['execution_status'],reason=result.get('reason'),config=config,design=design,
        drag_N=None,CdA_m2=None,Cd=None,convergence=None,
        mesh=read(root/'mesh-evidence.json') if (root/'mesh-evidence.json').exists() else None)
    if result['execution_status']!='PASS':
        if any(result[key] is not None for key in ('drag_N','CdA_m2','Cd')):raise ValueError('Failed result exposes formal coefficients')
        return out
    # Recheck archived inputs and source geometry, without trusting a PASS label alone.
    from .cfd_study import verify_source
    verify_source(root,file_hash(root/'result.json'))
    force_files=list((root/'case/postProcessing/forces').rglob('forces.dat'))
    if len(force_files)!=1:raise ValueError('Force history missing or ambiguous')
    check=assess(read_forces(force_files[0]),read_residuals(root/'foamRun.log'),read(root/'flux-history.json'))
    if not check['converged']:raise ValueError('Saved PASS does not independently converge')
    coeff=coefficients(check['window_mean_drag_N'],protocol['air_density_kg_m3'],protocol['speed_m_s'],config['source_area_m2'])
    for key in ('drag_N','CdA_m2','Cd'):
        if not positive(result[key]) or not math.isclose(result[key],coeff[key],rel_tol=1e-10,abs_tol=1e-12):
            raise ValueError('Saved coefficient does not match force history: '+key)
        out[key]=result[key]
    out['convergence']=check
    return out


def invariant(case, purpose):
    c=case['config'];p=deepcopy(c['protocol'])
    for key in ('schema_version','protocol_id','study'):p.pop(key,None)
    if purpose=='mesh':p['mesh'].pop('background_H')
    elif purpose=='domain':p.pop('domain')
    elif purpose!='advection':raise ValueError('Unsupported comparison purpose')
    n=deepcopy(case['design']['numerics'])
    for key in ('profile','base_iteration_profile','spatial_accuracy_note','reference'):n.pop(key,None)
    if purpose=='advection':n.pop('advection',None)
    return dict(protocol=p,numerics=n,wall_treatment=case['design']['wall_treatment'],
                shape={k:c[k] for k in ('source_snapshot_sha256','surface_sha256','source_area_m2')},
                binaries={k:v for k,v in c['tool_hashes'].items() if k.startswith(('binary:','upstream:'))})


def compare(cases,purpose,working_target):
    if len(cases)<2 or not positive(working_target):raise ValueError('Comparison needs two or more cases and a target')
    signatures={digest(invariant(c,purpose)) for c in cases}
    if len(signatures)!=1:raise ValueError('Comparison mixes geometry, physics, tools, or unrelated numerical settings')
    failed=[c['root_name'] for c in cases if c['status']!='PASS']
    pairs=[]
    for left,right in combinations(cases,2):
        difference=(abs(left['CdA_m2']/right['CdA_m2']-1) if left['status']==right['status']=='PASS' else None)
        pairs.append(dict(left=left['root_name'],right=right['root_name'],relative_CdA_difference=difference))
    complete=not failed
    return dict(purpose=purpose,status='COMPLETE_NUMERICAL_ONLY' if complete else 'INCOMPLETE',
        comparison_invariant_sha256=next(iter(signatures)),failed_or_unconverged=failed,
        pairs=pairs,working_target_relative=working_target,
        numerical_target_met=complete and all(p['relative_CdA_difference']<=working_target for p in pairs),
        evidence=[{k:c[k] for k in ('root_name','result_sha256','experiment_sha256','status','reason','drag_N','CdA_m2','Cd','mesh')} for c in cases],
        scientific_approval=None,ranking_eligible=False)
