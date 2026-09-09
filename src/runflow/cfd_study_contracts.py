"""Phase 1 sensitivity contracts; Phase 0 and the smoke contracts stay fixed."""
from copy import deepcopy
from .contracts import obj, HASH, TEXT
from .cfd_contracts import PROVISIONAL_PROTOCOL, PROVISIONAL_EXPERIMENT, PROVISIONAL_RESULT, fixed

VERSION = 'phase1-study-1'
ADVECTIONS = ('upwind', 'linearUpwindV', 'limitedLinearV')
PROTOCOL = deepcopy(PROVISIONAL_PROTOCOL)
PROTOCOL['properties'].update(schema_version=fixed(VERSION), protocol_id=fixed('RF-CFD-P1-STUDY-001'))
PROTOCOL['properties']['mesh']['properties']['background_H'] = {'enum': [.3125, .25, .2]}
for key, base in [('upstream_H', 5), ('downstream_H', 15), ('lateral_H', 5), ('vertical_H', 5)]:
    PROTOCOL['properties']['domain']['properties'][key] = {'enum': [base, base*1.25, base*1.5]}
PROTOCOL['properties']['study'] = obj({
    'purpose': {'enum': ['advection', 'mesh', 'domain', 'baseline']},
    'advection': {'enum': list(ADVECTIONS)}, 'mesh_scale': {'enum': [1.25, 1, .8]},
    'domain_scale': {'enum': [1, 1.25, 1.5]},
    'source_result_sha256': HASH, 'authorization_sha256': HASH})
PROTOCOL['required'].append('study')

EXPERIMENT = deepcopy(PROVISIONAL_EXPERIMENT)
EXPERIMENT['properties']['schema_version'] = fixed(VERSION)
config = EXPERIMENT['properties']['config']
config['properties']['protocol'] = PROTOCOL
for name in ('input_receipt_sha256', 'provisional_authorization_sha256'):
    del config['properties'][name]
    config['required'].remove(name)
config['properties'].update(study_source_sha256=HASH, study_authorization_sha256=HASH)
config['required'] += ['study_source_sha256', 'study_authorization_sha256']
RESULT = deepcopy(PROVISIONAL_RESULT)
RESULT['properties'].update(schema_version=fixed(VERSION), scientific_status=fixed('UNVALIDATED_PHASE1_STUDY'))


def semantic_check(p):
    if not p:
        return
    study = p['study']
    if p['mesh']['background_H'] != .25 * study['mesh_scale']:
        raise ValueError('Study mesh scale does not match generated spacing')
    for key, base in [('upstream_H', 5), ('downstream_H', 15), ('lateral_H', 5), ('vertical_H', 5)]:
        if p['domain'][key] != base * study['domain_scale']:
            raise ValueError('Study domain scale must apply to every outer boundary')
    if study['purpose'] in ('advection', 'baseline') and (study['mesh_scale'] != 1 or study['domain_scale'] != 1):
        raise ValueError('Advection comparison must preserve mesh and domain')
    if study['purpose'] == 'mesh' and study['domain_scale'] != 1:
        raise ValueError('Mesh comparison cannot change the domain')
    if study['purpose'] == 'domain' and study['mesh_scale'] != 1:
        raise ValueError('Domain comparison must preserve local spacing')
