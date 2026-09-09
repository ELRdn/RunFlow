"""Reuse a completed numerical surface from a terminal attempt, without editing it."""
import shutil
from pathlib import Path
from .core import read, write, file_hash
from . import cfd

FILES = ('geometry.json', 'candidate.obj', 'candidate.rfmesh', 'native-tools.json',
         'quality-before.json', 'quality-after.json', 'area-change-bound.json',
         'intersections.json', 'topology.json', 'surface-cache/cache.json',
         'surface-cache/vertices.npy', 'surface-cache/triangles.npy', 'surface-cache/repair.json')


def seal(previous):
    previous = cfd.private(previous)
    state = read(previous / 'state.json')
    if state.get('status') not in ('FAIL', 'TIMEOUT') or not state.get('completed_epoch'):
        raise ValueError('Only a completed failed attempt can supply a reusable surface')
    record = read(previous / 'geometry/geometry.json')
    if not record.get('complete') or not record['candidate_topology']['closed_manifold'] or not record['exact_intersections']['intersection_free']:
        raise ValueError('Prior numerical surface verification incomplete')
    if record['quality']['near_degenerate_triangles'] or record['remesh_passes'] != 0:
        raise ValueError('Unexpected reusable surface qualification')
    if file_hash(previous / 'geometry/candidate.obj') != record['surface_sha256']:
        raise ValueError('Prior surface changed')
    if file_hash(previous / 'geometry/candidate.rfmesh') != record['exchange']['sha256']:
        raise ValueError('Prior exact-predicate input changed')
    if file_hash(previous / 'geometry/surface-cache/cache.json') != record['candidate_cache_sha256']:
        raise ValueError('Prior surface cache changed')
    from .shape_audit import load_surface
    load_surface(previous / 'geometry/surface-cache')
    return dict(schema_version='cfd-surface-reuse-1', previous_root=str(previous),
                previous_records={name: file_hash(previous / name) for name in
                                  ('state.json', 'result.json', 'provisional-receipt.json', 'tool-pins.json')},
                input_cache_sha256=record['input_cache_sha256'],
                files={name: file_hash(previous / 'geometry' / name) for name in FILES})


def reuse(root, proof_path, expected_input_hash):
    proof = read(proof_path)
    previous = cfd.private(proof['previous_root'])
    if previous == Path(root).resolve():
        raise ValueError('Fresh output required for reuse')
    if seal(previous) != proof or proof['input_cache_sha256'] != expected_input_hash:
        raise ValueError('Reusable surface proof/input changed')
    destination = Path(root) / 'geometry'
    destination.mkdir(exist_ok=False)
    for name, expected in proof['files'].items():
        target = destination / name
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(previous / 'geometry' / name, target)
        if file_hash(target) != expected:
            raise ValueError('Reused surface copy changed: ' + name)
    write(Path(root) / 'geometry-reuse.json', dict(proof=proof, regenerated=False,
          copied_and_verified=True, previous_attempt_preserved=True))
