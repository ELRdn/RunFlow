"""Analyze repeatable neutral/foot measurements without certifying a ground plane."""
import argparse
import math
from pathlib import Path

from runflow.core import read, write, digest, file_hash


def approaches(times, heights, plane, clearance=.03, min_airborne_s=.1):
    """First downward plane crossing after sustained clearance; suppress heel/toe chatter."""
    events = []
    clear_start = None
    armed = False
    for i, (time, height) in enumerate(zip(times, heights)):
        if not math.isfinite(time) or not math.isfinite(height):
            raise ValueError('Non-finite measurement')
        if i and time <= times[i-1]:
            raise ValueError('Times must increase')
        if height > plane + clearance:
            if clear_start is None:
                clear_start = time
            if time-clear_start >= min_airborne_s:
                armed = True
        else:
            clear_start = None
        if armed and i and heights[i-1] > plane >= height:
            alpha = (heights[i-1]-plane)/(heights[i-1]-height)
            events.append(dict(time_s=times[i-1]+alpha*(time-times[i-1]),
                bracket_indices=[i-1, i], bracket_s=[times[i-1], time]))
            armed = False
    return events


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--measurement-root', type=Path, required=True)
    a = p.parse_args()
    root = a.measurement_root.resolve()
    if not root.is_relative_to(Path(__file__).resolve().parents[1]/'private'):
        raise ValueError('Private measurements required')
    output = root/'analysis.json'
    if output.exists():
        raise ValueError('Analysis must use a fresh output')
    if read(root/'completed.json')['execution_status'] != 'MEASURED':
        raise ValueError('Measurement not complete')
    hashes = {}
    for kind in ('neutral', 'feet', 'neutral-inputs', 'motion-inputs'):
        first, second = read(root/f'{kind}-0.json'), read(root/f'{kind}-1.json')
        if digest(first) != digest(second):
            raise ValueError('Repeated measurements or inputs differ: '+kind)
        hashes[kind] = digest(first)
    neutral = read(root/'neutral-0.json')
    motion = read(root/'feet-0.json')
    samples = motion['samples']
    if len(samples) != 513 or motion['samples_per_cycle'] != 256:
        raise ValueError('Two dense cycles including endpoint required')
    times = [s['phase_s'] for s in samples]
    body = next(m for m in neutral['meshes'] if m['name']=='M_Body')
    ground = sum(min(body['vertices'][i][2] for i in neutral['feet'][side+'_vertex_indices'])
                 for side in ('left', 'right'))/2
    feet = {}
    for side in ('left', 'right'):
        heights = [min(v[2] for v in s[side+'_vertices']) for s in samples]
        offsets = {}
        for offset in (-.005, 0, .005):
            offsets[str(offset)] = approaches(times, heights, ground+offset)
        central = offsets['0']
        if len(central) != 2:
            raise ValueError('Expected two separate approaches per foot')
        feet[side] = dict(min_z=min(heights), max_z=max(heights),
            penetration_below_neutral_support_plane=max(0, ground-min(heights)),
            crossings_by_plane_offset=offsets,
            observed_period_s=central[1]['time_s']-central[0]['time_s'])
    bounds = {}
    for mesh in neutral['meshes']:
        bounds[mesh['name']] = dict(min_z=min(v[2] for v in mesh['vertices']),
            max_z=max(v[2] for v in mesh['vertices']))
    hair = next(m for m in neutral['meshes'] if m['name']=='M_Hair')
    hair_bounds = {}
    for cutoff in (0, .01, .1, .5):
        vertices = [v for v, w in zip(hair['vertices'], hair['ear_skin_weights']) if w <= cutoff]
        hair_bounds[str(cutoff)] = max(v[2] for v in vertices)-ground
    period = motion['clip_length_s']
    phase = feet['right']['crossings_by_plane_offset']['0'][0]['time_s'] % period
    result = dict(schema_version='1',execution_status='PASS',repeated_measurements_identical=True,
        repeated_input_records_identical=True,canonical_digests=hashes,
        evidence_file_sha256={name:file_hash(root/name) for name in ('neutral-0.json','feet-0.json','completed.json')},
        analyzer_sha256=file_hash(Path(__file__)),
        unit='nominal_unity_world_unit',neutral_support_plane_z=ground,
        support_plane_definition='mean of left/right neutral shoe lowest selected vertex; not verified game terrain',
        db_scale=neutral['db_scale'],body_scale=neutral['body_scale'],
        neutral_mesh_bounds=bounds,hair_top_without_ear_weight_by_cutoff=hair_bounds,
        scalp_point_identified=False,physical_scale_approved=False,
        feet=feet,reference_foot='right',contact_phase_verified=False,
        contact_candidate_phase_s=phase,
        candidate_sampling=dict(status='PROPOSED_GEOMETRIC_PROXY_ONLY',samples=16,endpoint_included=False,
            absolute_times_s=[5*period+phase+i*period/16 for i in range(16)]),
        scientific_status='PENDING_HUMAN_REVIEW',ranking_eligible=False)
    write(output,result)
    print('PASS measurements repeated; right-foot geometric candidate:',phase,'s; ground/scale approval pending')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
