"""Pinned-Blender geometry regression harness, called by pytest."""
import importlib.util
from pathlib import Path

import bpy

repo = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('surface', repo/'integrations/blender/prepare_cfd_surface.py')
surface = importlib.util.module_from_spec(spec); spec.loader.exec_module(surface)


def make(vertices, faces):
    mesh = bpy.data.meshes.new('fixture'); mesh.from_pydata(vertices, [], faces); mesh.update()
    return mesh


# One quad has nonzero polygon area but emits a zero-area triangle.
quad = make([(0,0,0),(0,0,0),(1,1,0),(0,1,0)], [(0,1,2,3)])
assert surface.topology(quad)['degenerate_faces'] == 1, 'Exported triangle degeneracy was missed'

# Split a cube edge with two coincident vertices, producing a zero-width quad.
vertices = [(0,0,0),(1,0,0),(1,1,0),(0,1,0),
            (0,0,1),(1,0,1),(1,1,1),(0,1,1),(0,0,0),(0,0,1)]
faces = [(0,3,2,1,8),(4,9,5,6,7),(8,1,5,9),(1,2,6,5),
         (2,3,7,6),(3,0,4,7),(0,8,9,4)]
closed = make(vertices, faces)
before = surface.topology(closed)
assert before['nonmanifold_edges'] == 0 and not before['closed']
record = surface.repair_voxel_degeneracy(closed, 1e-6)
after = surface.topology(closed)
assert record['merged_vertices'] == 2 and record['max_vertex_shift_m'] == 0
assert after['closed'] and after['degenerate_faces'] == 0
assert set(tuple(v.co) for v in closed.vertices) == set(vertices)

# A very thin but long degenerate face must not justify a large collapse.
long_sliver = make([(0,0,0),(.001,0,0),(.002,0,0)], [(0,1,2)])
record = surface.repair_voxel_degeneracy(long_sliver, 1e-6)
assert record['merged_vertices'] == 0 and len(long_sliver.vertices) == 3
assert not surface.topology(long_sliver)['closed']

# A valid closed mesh is exactly unchanged; a hole is not silently filled.
unchanged = surface.arrays(closed)
assert surface.repair_voxel_degeneracy(closed, 1e-6)['merged_vertices'] == 0
assert surface.arrays(closed) == unchanged
hole = make(vertices[:8], [(0,3,2,1),(4,5,6,7)])
surface.repair_voxel_degeneracy(hole, 1e-6)
assert not surface.topology(hole)['closed']

# Two otherwise closed tetrahedra meeting at one vertex have manifold edges,
# but the shared vertex has two disjoint fans and is not a valid CFD surface.
pinch = make([(0,0,0),(1,0,0),(0,1,0),(0,0,1),
              (-1,0,0),(0,-1,0),(0,0,-1)],
             [(0,2,1),(0,1,3),(0,3,2),(1,2,3),
              (0,4,5),(0,6,4),(0,5,6),(4,6,5)])
check = surface.topology(pinch)
assert check['boundary_edges'] == 0 and check['nonmanifold_edges'] == 0
assert check['degenerate_faces'] == 0 and check['nonmanifold_vertices'] == 1
assert not check['closed'], 'A pinched vertex must not pass the geometry gate'

# An isolated flat tetrahedron collapses entirely at submicrometre scale;
# the remaining unreferenced vertex must be removed, without removing surfaces.
collapsed = make([(0,0,0),(0,0,0),(1e-7,0,0),(1e-7,0,0)],
                 [(0,2,1),(0,1,3),(0,3,2),(1,2,3)])
record = surface.repair_voxel_degeneracy(collapsed, 1e-6)
assert len(record['removed_unused_vertices']) == 1
assert len(collapsed.vertices) == 0 and len(collapsed.polygons) == 0
assert not surface.topology(collapsed)['closed'], 'An empty surface cannot pass'
print('BLENDER_CFD_GEOMETRY_PASS', flush=True)
