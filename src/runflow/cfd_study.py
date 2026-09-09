"""Hash-bound Phase 1 studies on completed private geometry, with fresh cases."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from . import cfd
from .core import read, write, file_hash, digest
from .cfd_contracts import validate
from .cfd_study_contracts import VERSION, ADVECTIONS
from .cfd_paths import reserve_reason

BASE_NUMERICS = 'standard-simple-upwind-damped-nonorth'


def verify_authorization(value):
    if (value.get('schema_version') != 'phase1-study-authorization-1'
            or value.get('scope') != 'PHASE1_SENSITIVITY_AND_FULL_GAIT'
            or value.get('actor') != 'user' or not value.get('instruction')
            or value.get('scientific_approval') is not None
            or value.get('ranking_eligible') is not False
            or value.get('trial_limit_s') != 3600
            or value.get('campaign_limit_s') not in (21600, 43200, 86400)):
        raise ValueError('Explicit Phase 1 study scope and bounded budget required')


def verify_source(source, expected_result):
    source = cfd.private(source)
    if file_hash(source / 'result.json') != expected_result:
        raise ValueError('Study source result changed')
    result = read(source / 'result.json'); exp = read(source / 'experiment.json')
    validate('result', result); validate('experiment', exp)
    state = read(source / 'state.json')
    if result['execution_status'] != 'PASS' or state.get('completed_epoch', 0) <= state['started_epoch']:
        raise ValueError('Study source must be completed and converged')
    if result['experiment_id'] != exp['experiment_id'] or digest(exp['config']) != exp['config_sha256']:
        raise ValueError('Study source experiment identity mismatch')
    config = exp['config']
    for name, key in [('source.snapshot.json', 'source_snapshot_sha256'),
                      ('source-manifest.json', 'source_manifest_sha256'),
                      ('geometry/candidate.obj', 'surface_sha256')]:
        if file_hash(source / name) != config[key]:
            raise ValueError('Study source input changed: ' + name)
    for name, expected in config['tool_hashes'].items():
        if name.startswith('run:'):
            path = (source / name[4:]).resolve()
            if not path.is_relative_to(source) or file_hash(path) != expected:
                raise ValueError('Study source evidence changed: ' + name)
        elif name.startswith('case:'):
            path = (source / 'case' / name[5:]).resolve()
            if not path.is_relative_to(source / 'case'):
                raise ValueError('Escaping case source')
            if name == 'case:system/controlDict':
                normalized = path.read_text().replace('stopAt writeNow;', 'stopAt endTime;')
                import hashlib
                hashes = [hashlib.sha256(normalized.encode()).hexdigest(),
                          hashlib.sha256(normalized.replace('\n', '\r\n').encode()).hexdigest()]
                if expected not in hashes:
                    raise ValueError('Source runtime control differs beyond verified stop request')
            elif file_hash(path) != expected:
                raise ValueError('Study case source changed: ' + name)
        elif name.startswith('repo:') and not name.lower().endswith('.exe'):
            path = (source / 'tool-sources' / name[5:]).resolve()
            if not path.is_relative_to(source / 'tool-sources') or file_hash(path) != expected:
                raise ValueError('Archived source changed: ' + name)
    for stage in ('mesh', 'solver', 'fields'):
        record = read(source / (stage + '-worker.json'))
        if record['execution_status'] != 'PASS' or not record['commands'] or any(
                row['returncode'] or row['reason'] or not row['termination_verified'] for row in record['commands']):
            raise ValueError('Source process completion unverified')
    geometry = read(source / 'geometry/geometry.json')
    if not geometry['candidate_topology']['closed_manifold'] or not geometry['exact_intersections']['intersection_free']:
        raise ValueError('Source geometry not qualified')
    if geometry['surface_sha256'] != config['surface_sha256']:
        raise ValueError('Source geometry record mismatch')
    return exp


def protocol_for(source_protocol, source_result_sha256, authorization, *, purpose, advection, mesh_scale=1, domain_scale=1):
    verify_authorization(authorization)
    p = deepcopy(source_protocol)
    p.update(schema_version=VERSION, protocol_id='RF-CFD-P1-STUDY-001')
    p['mesh']['background_H'] = .25 * mesh_scale
    p['domain'] = {name: base * domain_scale for name, base in
                   [('upstream_H', 5), ('downstream_H', 15), ('lateral_H', 5), ('vertical_H', 5)]}
    p['study'] = dict(purpose=purpose, advection=advection, mesh_scale=mesh_scale,
                      domain_scale=domain_scale, source_result_sha256=source_result_sha256,
                      authorization_sha256=digest(authorization))
    validate('protocol', p)
    return p


def build_case(case, snapshot, protocol, upstream):
    from .cfd_case import build
    validate('protocol', protocol)
    design = build(case, snapshot, protocol, upstream, numerics=BASE_NUMERICS, wall_treatment='reference-switching')
    advection = protocol['study']['advection']
    target = {'upwind': 'upwind', 'linearUpwindV': 'linearUpwindV grad(U)', 'limitedLinearV': 'limitedLinearV 1'}[advection]
    path = Path(case) / 'system/fvSchemes'
    text, count = re.subn(r'div\(phi,U\)\s+bounded Gauss upwind;', 'div(phi,U) bounded Gauss ' + target + ';', path.read_text())
    if count != 1:
        raise ValueError('Study needs the pinned velocity advection entry')
    if advection != 'upwind':
        path.write_text(text, encoding='ascii')
    design['numerics'].update(profile='study-simple-' + advection, advection='bounded Gauss ' + target,
        spatial_accuracy_note='SPATIAL_SENSITIVITY_UNVALIDATED', base_iteration_profile=BASE_NUMERICS)
    design['study'] = protocol['study']
    return design


def verify_prepared_study(root, config):
    authority = read(root / 'study-authorization.json')
    verify_authorization(authority)
    if digest(authority) != config['study_authorization_sha256'] or digest(authority) != config['protocol']['study']['authorization_sha256']:
        raise ValueError('Study authorization changed')
    descriptor = read(root / 'study-source.json')
    if digest(descriptor) != config['study_source_sha256']:
        raise ValueError('Study source descriptor changed')
    if descriptor['surface_sha256'] != config['surface_sha256'] or descriptor['source_snapshot_sha256'] != config['source_snapshot_sha256']:
        raise ValueError('Study source target differs')
    for name, expected in read(root / 'runtime-evidence-hashes.json').items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or file_hash(path) != expected:
            raise ValueError('Study runtime provenance changed')


def prepare(source, protocol_path, authority_path, qualification, output, distro='Ubuntu'):
    root = cfd.private(output); source = cfd.private(source)
    if root.exists():
        raise ValueError('Fresh study output required')
    p = read(protocol_path); validate('protocol', p)
    if p['schema_version'] != VERSION:
        raise ValueError('Phase 1 study protocol required')
    authority = read(authority_path); verify_authorization(authority)
    if digest(authority) != p['study']['authorization_sha256']:
        raise ValueError('Study authorization differs from plan')
    began = time.time(); started = time.monotonic()
    blocked = reserve_reason(root)
    if blocked:
        raise ValueError(blocked)
    root.mkdir(parents=True)
    write(root / 'protocol.json', p); write(root / 'study-authorization.json', authority)
    write(root / 'state.json', dict(started_epoch=began, started_utc=datetime.fromtimestamp(began, timezone.utc).isoformat(),
          status='PREPARING', stage='geometry', distro=distro))
    evidence = {}
    try:
        exp = verify_source(source, p['study']['source_result_sha256']); old = exp['config']
        if p['frame'] != old['protocol']['frame'] or p['geometry'] != old['protocol']['geometry']:
            raise ValueError('Study cannot silently replace adopted geometry or pose')
        if p.get('diagnostic_refinement') != old['protocol'].get('diagnostic_refinement'):
            raise ValueError('Study must preserve the diagnosed refinement region')
        descriptor = dict(experiment_id=exp['experiment_id'], result_sha256=p['study']['source_result_sha256'],
            source_snapshot_sha256=old['source_snapshot_sha256'], surface_sha256=old['surface_sha256'],
            source_manifest_sha256=old['source_manifest_sha256'], source_config_sha256=exp['config_sha256'],
            initialization='FRESH_UNIFORM_FLOW', mesh_reused=False, geometry_regenerated=False)
        write(root / 'study-source.json', descriptor)
        write(root / 'study-source-runtime.json', dict(source_root=str(source)))
        names = ['source.snapshot.json', 'source-manifest.json', 'geometry/candidate.obj',
                 'geometry/candidate.rfmesh', 'geometry/geometry.json', 'geometry/intersections.json',
                 'geometry/quality-after.json', 'geometry/topology.json', 'areas.json', 'fidelity-review.json']
        for name in names:
            if cfd.remaining(root, 'geometry', started) <= 0:
                raise ValueError('geometry stage timeout')
            if reserve_reason(root):
                raise ValueError(reserve_reason(root))
            target = root / name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, target)
            if file_hash(target) != file_hash(source / name):
                raise ValueError('Source copy changed: ' + name)
        sources = [*sorted((cfd.REPO/'src/runflow').glob('cfd*.py')), cfd.REPO/'src/runflow/core.py',
                   cfd.REPO/'src/runflow/contracts.py', cfd.REPO/'scripts/cfd_worker.py',
                   cfd.REPO/'scripts/cfd_report.py', cfd.REPO/'scripts/qualify_cfd_surface.py',
                   cfd.REPO/'scripts/run_phase1_study.py', cfd.REPO/'uv.lock']
        pins = {}
        for path in sources:
            name = path.relative_to(cfd.REPO).as_posix(); pins['repo:' + name] = file_hash(path)
            target = root / 'tool-sources' / name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        write(root / 'tool-pins.json', pins)
        cfd.worker(root, 'reference', cfd.remaining(root, 'geometry', started), distro)
        cfd.guarded(root, [sys.executable, str(cfd.REPO/'scripts/qualify_cfd_surface.py'),
                    '--qualification', str(qualification), '--root', str(root)],
                    'qualification.log', cfd.remaining(root, 'geometry', started))
        case = root / 'case'; (case / 'constant/geometry').mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root/'geometry/candidate.obj', case/'constant/geometry/oguri.obj')
        upstream = read(root / 'upstream.json')
        design = build_case(case, read(root/'source.snapshot.json'), p, upstream)
        write(root/'case-design.json', design)
        if p['study']['mesh_scale'] == 1 and p['study']['domain_scale'] == 1:
            # The only dictionary change for a scheme trial is velocity advection.
            for name in ('system/blockMeshDict','system/snappyHexMeshDict','system/surfaceFeaturesDict',
                         'system/fvSolution','system/meshQualityDict','system/decomposeParDict',
                         'constant/physicalProperties','constant/momentumTransport', *('0/'+f for f in ('U','p','k','omega','nut'))):
                if file_hash(case/name) != old['tool_hashes'].get('case:'+name):
                    raise ValueError('Advection comparison changed another input: '+name)
        tools = dict(pins)
        tools.update({'upstream:'+k:v for k,v in upstream['hashes'].items()})
        tools.update({'binary:'+k:v['sha256'] for k,v in upstream['binaries'].items()})
        tools.update({'case:'+path.relative_to(case).as_posix():file_hash(path) for path in case.rglob('*') if path.is_file()})
        for name in ['study-source.json', 'areas.json', 'fidelity-review.json', 'case-design.json',
                     'surface-qualification.json', 'geometry/geometry.json', 'geometry/intersections.json',
                     'geometry/quality-after.json', 'geometry/topology.json']:
            tools['run:'+name] = file_hash(root/name)
        runtime = ['study-authorization.json','study-source-runtime.json','surface-worker.json','surface-qualification-reuse.json']
        write(root/'runtime-evidence-hashes.json', {name:file_hash(root/name) for name in runtime})
        config = {key:deepcopy(old[key]) for key in ('source_snapshot_sha256','source_manifest_sha256','surface_sha256',
                  'frame_time_s','clip_phase_s','source_area_m2','repaired_area_m2','repaired_area_bounds_m2','source_bbox','fidelity_status')}
        config.update(protocol=p,tool_hashes=tools,study_source_sha256=digest(descriptor),study_authorization_sha256=digest(authority))
        sha = digest(config)
        experiment = dict(schema_version=VERSION, experiment_id='rf-p1s-'+sha, config_sha256=sha, config=config)
        validate('experiment',experiment); write(root/'experiment.json',experiment)
        if cfd.remaining(root,'geometry',started)<=0:
            raise ValueError('geometry stage timeout')
        return cfd.result(root,'PREPARED','geometry','Qualified surface copied; sensitivity inputs fixed',evidence)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        return cfd.result(root,'TIMEOUT' if 'timeout' in str(exc) else 'FAIL','geometry',str(exc),evidence)
