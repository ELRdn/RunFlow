import importlib.util
from pathlib import Path

import pytest
from runflow.core import write, read, file_hash

spec = importlib.util.spec_from_file_location('accepted_capture', Path(__file__).resolve().parents[1]/'scripts/accepted_capture.py')
accepted = importlib.util.module_from_spec(spec)
spec.loader.exec_module(accepted)


@pytest.fixture
def evidence(tmp_path):
    write(tmp_path/'analysis.json', {'test_measurement': True})
    decision = dict(character_id='1006', costume_id='100602', motion_id=accepted.MOTION,
        phase=dict(research_reference_accepted=True, reference_foot='right', phase_s=.589),
        scale=dict(research_scale_accepted=True, meters_per_unity_world_unit=1,
            additional_scale_factor=1, detailed_body_height_measurement_waived=True),
        measurement_analysis_sha256=file_hash(tmp_path/'analysis.json'))
    write(tmp_path/'decision.json', decision)
    write(tmp_path/'parts.json', dict(character_id='1006', costume_id='100602', judgment='ACCEPTED_WITH_NOTED_INTERSECTION'))
    return tmp_path


def test_adoption_carries_original_human_decision_and_hash(evidence):
    accepted.prepare(evidence/'decision.json', evidence/'parts.json', evidence/'prepared.json')
    assert read(evidence/'prepared.json')['adoption_sha256'] == file_hash(evidence/'decision.json')
    assert read(evidence/'prepared.json')['decision'] == read(evidence/'decision.json')


@pytest.mark.parametrize('section,key,value', [
    ('phase', 'research_reference_accepted', False), ('phase', 'reference_foot', 'left'),
    ('scale', 'research_scale_accepted', False), ('scale', 'meters_per_unity_world_unit', None),
    ('scale', 'additional_scale_factor', .95)])
def test_unapproved_or_changed_conditions_stop(evidence, section, key, value):
    decision = read(evidence/'decision.json')
    decision[section][key] = value
    write(evidence/'decision.json', decision)
    with pytest.raises(ValueError):
        accepted.prepare(evidence/'decision.json', evidence/'parts.json', evidence/'prepared.json')
    assert not (evidence/'prepared.json').exists()


def test_changed_measurement_stops(evidence):
    write(evidence/'analysis.json', {'test_measurement': 'changed'})
    with pytest.raises(ValueError, match='hash mismatch'):
        accepted.prepare(evidence/'decision.json', evidence/'parts.json', evidence/'prepared.json')


def test_time_record_must_use_the_actual_binary32_simulation_step():
    actual_dt = .0023437500931322575
    phase = .5894130940998821
    time = phase+1280*actual_dt
    record = dict(simulation_dt_s=actual_dt, simulation_steps_per_sample=16,
        warmup_seconds=3, requested_start_phase_s=phase, effective_start_phase_s=phase,
        time_s=time, animator_normalized_time=time/.6, clip_length_s=.6)
    accepted.verify_timing([dict(time_s=time)], [record], phase)
    # Observed Mono inline-expression precision differs from the stored float passed to Unity.
    record['simulation_dt_s'] = .0023437500558793557
    with pytest.raises(ValueError, match='schedule mismatch'):
        accepted.verify_timing([dict(time_s=time)], [record], phase)


def test_game_update_cannot_reuse_adopted_build_label():
    accepted.verify_game_version(accepted.PINNED_GAME_INPUTS)
    changed = dict(accepted.PINNED_GAME_INPUTS, master_sha256='0'*64)
    with pytest.raises(ValueError, match='Game data differs'):
        accepted.verify_game_version(changed)
