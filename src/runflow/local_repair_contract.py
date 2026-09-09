"""Fail-closed contracts for a bounded, private local-repair campaign."""
import math
import re
from runflow.core import digest

STAGE_LIMITS={'diagnosis':7200,'precision':7200,'repair':18000,'verification':9000,'report':1800}
TOTAL_LIMIT=43200
SETTINGS=dict(kind='local_surface_repair_v2',adoption='adopted-002',frame=0,unit='m',
    coordinate_system='RF_X_FORWARD_Z_UP',primary_base_um=900,reference_base_um=1000,
    max_candidates=24,voxel_remesh_passes=0,numeric_cleanup_m=1e-6,distance_m=.002,
    frontal_area_relative=.01,scientific_status='UNAPPROVED',ranking_eligible=False,human_adoption=None)

def validate_settings(settings):
    if set(settings)!=set(SETTINGS): raise ValueError('Unknown or missing setting')
    for key,expected in SETTINGS.items():
        value=settings[key]
        if key=='max_candidates':
            if type(value) is not int or not 1<=value<=24: raise ValueError('Candidate limit')
        elif key=='numeric_cleanup_m':
            if type(value) not in (int,float) or not math.isfinite(value) or not 0<value<=1e-6: raise ValueError('Cleanup tolerance')
        elif type(value) is not type(expected) or value!=expected:
            raise ValueError('Fixed setting mismatch: '+key)
    return settings

def remaining_budget(records,stage):
    if stage not in STAGE_LIMITS: raise ValueError('Unknown stage')
    total=used=0.
    for item in records:
        s=item['stage']; elapsed=item['elapsed_s']
        if s not in STAGE_LIMITS or type(elapsed) not in (int,float) or not math.isfinite(elapsed) or elapsed<0:
            raise ValueError('Invalid budget record')
        total+=elapsed
        if s==stage: used+=elapsed
    return max(0.,min(TOTAL_LIMIT-total,STAGE_LIMITS[stage]-used))

def configuration_id(settings,input_hashes,tool_hashes,recipes=None):
    validate_settings(settings)
    for values in (input_hashes,tool_hashes):
        if not values or any(not isinstance(k,str) or not isinstance(v,str) or not re.fullmatch('[0-9a-f]{64}',v) for k,v in values.items()):
            raise ValueError('SHA-256 pins required')
    return 'rf-local-repair-'+digest(dict(settings=settings,inputs=input_hashes,tools=tool_hashes,recipes=recipes or []))

def candidate_verdict(checks,human_parts=None):
    if human_parts is not None and type(human_parts) is not bool: raise ValueError('Explicit human decision required')
    states={k:checks.get(k,'UNVERIFIED') for k in ('distance','area','topology','intersection','outside_region')}
    if any(v not in ('PASS','FAIL','UNVERIFIED') for v in states.values()): raise ValueError('Invalid check state')
    states['parts']='PASS' if human_parts is True else 'FAIL' if human_parts is False else 'UNVERIFIED'
    verdict='FAIL' if 'FAIL' in states.values() else 'PASS' if set(states.values())=={'PASS'} else 'UNVERIFIED'
    return dict(verdict=verdict,checks=states,scientific_status='UNAPPROVED',ranking_eligible=False,
        human_adoption=None,drag_N=None,Cd=None,CdA_m2=None)
