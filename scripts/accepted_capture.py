"""Bind explicit human decisions to a private capture and portable experiment identity."""
import argparse
import math
from pathlib import Path
import shutil
import subprocess
import sys

from runflow.core import read, write, file_hash, digest, validate_manifest, sample

MOTION = '3d/motion/racemain/body/type01/anm_rac_type01_run02_base'
REPO = Path(__file__).resolve().parents[1]
PINNED_GAME_INPUTS = dict(
    meta_sha256='c2787d66ac972fa4edf3d063db1d387ac1150a29bc881a8e886aeaacc802611c',
    master_sha256='d80ece1873af2c88d7dc25ac2b54f34551b260bbcef70bc3e6157c9d1e107b3c')


def verify_game_version(inputs):
    if any(inputs.get(key) != value for key, value in PINNED_GAME_INPUTS.items()):
        raise ValueError('Game data differs from the adopted Steam build snapshot; new intake record required')


def prepare(adoption, parts, output):
    decision, review = read(adoption), read(parts)
    for record in (decision, review):
        if (record['character_id'], record['costume_id']) != ('1006', '100602'):
            raise ValueError('Wrong reviewed target')
    phase, scale = decision['phase'], decision['scale']
    if (decision['motion_id'] != MOTION or phase['research_reference_accepted'] is not True
            or phase['reference_foot'] != 'right' or not math.isfinite(phase['phase_s'])
            or not 0 <= phase['phase_s'] < .61):
        raise ValueError('Explicit right-foot phase adoption required')
    if (scale['research_scale_accepted'] is not True or scale['meters_per_unity_world_unit'] != 1
            or scale['additional_scale_factor'] != 1 or scale['detailed_body_height_measurement_waived'] is not True):
        raise ValueError('Explicit original-scale adoption required')
    if review['judgment'] != 'ACCEPTED_WITH_NOTED_INTERSECTION':
        raise ValueError('Parts review with recorded exception required')
    if file_hash(adoption.parent/'analysis.json') != decision['measurement_analysis_sha256']:
        raise ValueError('Measurement evidence hash mismatch')
    if output.exists():
        raise ValueError('Fresh preparation output required')
    write(output, dict(decision=decision, parts_review=review,
        adoption_sha256=file_hash(adoption), parts_review_sha256=file_hash(parts)))


def verify_timing(values, provenance, phase):
    first = provenance[0]
    dt = first['simulation_dt_s']
    stride = first['simulation_steps_per_sample']
    warmup = round(first['warmup_seconds']/dt)
    if abs(first['requested_start_phase_s']-phase) > 1e-12 or abs(first['effective_start_phase_s']-phase) > 1e-7:
        raise ValueError('Adopted phase was not applied')
    timing_errors = []
    for i, (v, p) in enumerate(zip(values, provenance)):
        for key in ('simulation_dt_s', 'simulation_steps_per_sample', 'requested_start_phase_s',
                    'effective_start_phase_s', 'warmup_seconds', 'clip_length_s'):
            if p[key] != first[key]:
                raise ValueError('Time settings changed within the cycle')
        expected = first['effective_start_phase_s']+(warmup+i*stride)*dt
        if abs(v['time_s']-expected) > 1e-9 or p['time_s'] != v['time_s']:
            raise ValueError('Capture time schedule mismatch')
        error = abs(p['animator_normalized_time']*p['clip_length_s']-expected)
        if error > dt/10:
            raise ValueError('Animator time drift exceeds one tenth of a simulation step')
        timing_errors.append(error)
    return timing_errors, dt, stride, warmup


def finalize(root, output=None):
    from compare_direct_capture import verify_inputs, frames
    root = root.resolve()
    if not root.resolve().is_relative_to(REPO/'private'):
        raise ValueError('Private capture required')
    output = (output or root/'configuration').resolve()
    if not output.is_relative_to(root.resolve()) or output.exists():
        raise ValueError('Fresh configuration directory inside capture root required')
    completed, comparison = read(root/'completed.json'), read(root/'comparison.json')
    if completed.get('research_conditions_adopted') is not True or comparison['execution_status'] != 'PASS':
        raise ValueError('Adopted capture and transport PASS required')
    verification = verify_inputs(root)
    verify_game_version(read(root/'inputs-0.json'))
    adoption = read(root/'adoption-input.json')
    decision = adoption['decision']
    if decision['motion_id'] != MOTION:
        raise ValueError('Wrong motion')
    paths, values = frames(root/'unity-a')
    provenance = [read(p.with_name(p.name.replace('.snapshot.json', '.provenance.json'))) for p in paths]
    first = provenance[0]
    phase = decision['phase']['phase_s']
    timing_errors, dt, stride, warmup = verify_timing(values, provenance, phase)
    manifest = read(REPO/'configs/manifest.pilot.template.json')
    manifest['source'].update(game_version='Steam JP build 25072715', motion_id=MOTION)
    manifest['tools']['capture_version'] = 'adopted-phase-v1; Unity 2022.3.62f1_4af31df58517; scripts='+digest(read(root/'inputs-0.json')['capture_scripts'])
    manifest.update(height_m=decision['scale']['reference_height_m'],
        height_source='Profile reference 167 cm; local master scale=167; user adoption '+adoption['adoption_sha256'],
        height_measurement='Detailed scalp/barefoot measurement waived by user. Reference height only; original Unity world scale retained without refitting.')
    manifest['transform'].update(source_to_rf=first['source_to_rf'], meters_per_source_unit=1,
        reflection=False, scale_evidence='User adopted 1 Unity world unit = 1 m; existing BodyScale 1.03886151; no independent physical calibration.')
    manifest['gait'].update(start_s=values[0]['time_s'], end_s=values[0]['time_s']+16*stride*dt,
        contact_event='Right shoe downward neutral support-plane crossing; user-adopted phase '+str(phase)+' s; actual race ground unverified',
        recording_step_s=dt, warmup_steps=warmup)
    assets = []
    for item in read(root/'inputs-0.json')['assets']:
        source = item['source_path']
        role = 'motion' if source == MOTION else 'model' if source.endswith('/pfb_bdy1006_02') else 'other'
        assets.append(dict(id=source, role=role, path='source-assets/'+item['sha256'], sha256=item['sha256']))
    # Metadata, adopted decisions and actual sampled geometry are all identity inputs.
    for name in ('inputs-0.json', 'adoption-input.json'):
        assets.append(dict(id=name, role='reference', path=name, sha256=file_hash(root/name)))
    for p in paths:
        assets.append(dict(id=p.stem, role='reference', path=p.relative_to(root).as_posix(), sha256=file_hash(p)))
    processing_files = ['scripts/accepted_capture.py', 'scripts/compare_direct_capture.py',
        'integrations/blender/runflow_capture.py', 'src/runflow/core.py', 'src/runflow/contracts.py',
        'src/runflow/cli.py', 'src/runflow/__init__.py', 'configs/toolchain.lock.json', 'uv.lock']
    project = '.tools/umaviewer-project/UmaViewer-d50b28379337b507751a7df705a10afeab2c37ce'
    spring = project+'/Assets/Scripts/DynamicBone/Scripts/DynamicBone.cs'
    if file_hash(REPO/spring) != 'c0e7de5a3d585a3547d8726a75bd827584b3e2ca1269a8471d94e848789356f6':
        raise ValueError('Pinned DynamicBone integration changed')
    processing_files.append(spring)
    for item in read(root/'inputs-0.json')['capture_scripts']:
        relative = 'integrations/unity/'+item['name']
        if file_hash(REPO/relative) != item['sha256']:
            raise ValueError('Capture source changed since Unity ran: '+item['name'])
        processing_files.append(relative)
    for relative in processing_files:
        destination = output/'processing-sources'/relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and file_hash(destination) != file_hash(REPO/relative):
            raise ValueError('Archived processing source differs: '+relative)
        if not destination.exists():
            shutil.copyfile(REPO/relative, destination)
        assets.append(dict(id='runflow-tool/'+relative, role='other',
            path=destination.relative_to(root).as_posix(), sha256=file_hash(destination)))
    manifest['assets'] = assets
    manifest['preprocessing'] = [
        'Unity baked visible meshes; manual DynamicBone reset and fixed steps; normalized phase initialization then five warmup cycles.',
        'Original trajectory retained; subtract forward X from mesh/joints only; preserve vertical and lateral motion.',
        'Human-selected normal-race pilot; exact official animation composition remains unverified.',
        'Prior multiview parts review accepted with costume-leg intersection; all 16 poses not separately human reviewed.',
        'Blender OBJ transport only; joint metadata shared with Unity, not independent PMX/VMD validation.',
        'Missing Gallop.CharaTransformProcessData warning retained as source compatibility limitation.'
    ]
    validate_manifest(manifest, root)
    for expected, actual in zip(sample(manifest)['samples'], values):
        if abs(expected['time_s']-actual['time_s']) > 1e-9:
            raise ValueError('Generated sample times differ from capture')
    output.mkdir(parents=True, exist_ok=True)
    write(output/'manifest.json', manifest)
    for suffix in ('a', 'b'):
        subprocess.run([sys.executable, '-m', 'runflow.cli', 'generate', str(output/'manifest.json'),
            '--asset-root', str(root), '--output', str(output/('experiment-'+suffix))], check=True)
    a, b = [read(output/('experiment-'+suffix)/'experiment.json') for suffix in ('a', 'b')]
    if a != b:
        raise ValueError('Experiment configurations differ')
    report = dict(execution_status='PASS', research_conditions_adopted=True,
        input_verification=verification, config_sha256=a['config_sha256'], experiment_files_identical=True,
        requested_start_phase_s=phase, effective_start_phase_s=first['effective_start_phase_s'],
        max_animator_time_error_s=max(timing_errors), sampling_matches_capture=True,
        source_bundle_count=len(read(root/'inputs-0.json')['assets']),
        comparison_sha256=file_hash(root/'comparison.json'), adoption_input_sha256=file_hash(root/'adoption-input.json'),
        manifest_sha256=file_hash(output/'manifest.json'), scientific_status='PENDING_HUMAN_REVIEW', ranking_eligible=False)
    write(output/'accepted-verification.json', report)
    print('PASS adopted phase, original scale, 16 samples and duplicate experiment identity')


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare')
    for key in ('adoption', 'parts', 'output'):
        prep.add_argument('--'+key, type=Path, required=True)
    final = sub.add_parser('finalize')
    final.add_argument('--root', type=Path, required=True)
    final.add_argument('--output', type=Path)
    args = p.parse_args()
    if args.command == 'prepare':
        prepare(args.adoption, args.parts, args.output)
    else:
        finalize(args.root, args.output)


if __name__ == '__main__':
    main()
