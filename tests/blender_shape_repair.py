"""Pinned-Blender checks for bounded repair helpers on synthetic meshes only.

Run inside Blender (background, factory startup). Covers solidify_patch on a
thin open quad, bounded_delta capping, and an EXACT boolean where an
overlapping-cube plus thin restored patch survives union while a nested
internal surface stays measurably far from the union (a distance failure).
No real or private assets are read or written.
"""
import gc
import importlib.util
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils.bvhtree import BVHTree

repo = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo / "src"))
sys.path.insert(0, str(repo / "integrations/blender"))

from runflow.shape_repair import bounded_delta

spec = importlib.util.spec_from_file_location(
    "repair_fullbody_surface", repo / "integrations/blender/repair_fullbody_surface.py")
repair_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair_module)

voxel_spec = importlib.util.spec_from_file_location(
    "fullbody_voxel_compare", repo / "integrations/blender/fullbody_voxel_compare.py")
voxel_module = importlib.util.module_from_spec(voxel_spec)
voxel_spec.loader.exec_module(voxel_module)

prep_spec = importlib.util.spec_from_file_location(
    "prepare_cfd_surface", repo / "integrations/blender/prepare_cfd_surface.py")
prep_module = importlib.util.module_from_spec(prep_spec)
prep_spec.loader.exec_module(prep_module)

root = Path(sys.argv[-1])
root.mkdir(parents=True, exist_ok=True)


def release():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for mesh in list(bpy.data.meshes):
        if not mesh.users:
            bpy.data.meshes.remove(mesh)
    gc.collect()


def mesh_bounds(mesh):
    n = len(mesh.vertices)
    coords = np.empty(n * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", coords)
    return coords.reshape(-1, 3)


def mesh_faces(mesh):
    mesh.calc_loop_triangles()
    tris = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("vertices", tris)
    return tris.reshape(-1, 3)


def check_bounded_edits():
    delta = np.array([[0.01, 0.0, 0.0], [0.0001, 0.0, 0.0], [0.0, 0.0, 0.0]])
    out = bounded_delta(delta, 0.5, 0.0005)
    norms = np.linalg.norm(out, axis=1)
    assert (norms <= 0.0005 + 2e-6).all(), norms
    assert abs(norms[0] - 0.0005) < 1e-9
    assert abs(norms[1] - 0.00005) < 1e-9
    assert (out[2] == 0).all()
    tangential = bounded_delta(
        np.array([[0.002, 0.002, 0.002]]), 0.5, 0.0005, np.array([[0.0, 0.0, 1.0]]))
    assert abs(tangential[0, 0]) < 1e-12 and abs(tangential[0, 1]) < 1e-12
    assert abs(np.linalg.norm(tangential) - 0.0005) < 1e-9


def check_solidify_thin_open_patch():
    release()
    v = np.array([
        [0.0, 0.0, 0.0], [0.004, 0.0, 0.0],
        [0.004, 0.004, 0.0], [0.0, 0.004, 0.0],
    ])
    f = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int32)
    patch = repair_module.solidify_patch(v, f, 0.0004)
    try:
        assert patch.data is not None and len(patch.data.vertices) > 4
        assert len(mesh_faces(patch.data)) > 2
        coords = mesh_bounds(patch.data)
        zmin, zmax = float(coords[:, 2].min()), float(coords[:, 2].max())
        # Centered thickness: shell must extend to both sides of the mid-surface,
        # stay bounded well under 1mm, and never be trusted as an exact value.
        assert zmin < -1e-5 and zmax > 1e-5, (zmin, zmax)
        assert (zmax - zmin) < 0.001, (zmin, zmax)
        assert np.isfinite(coords).all()
        info = voxel_module.export_mesh(patch.data, root / "patch-shell")
        assert info["triangles"] > 2
        topo = prep_module.topology(patch.data)
        assert topo["triangles"] == info["triangles"]
    finally:
        release()


def cube_arrays(size=0.01):
    s = float(size)
    v = np.array([
        [0, 0, 0], [s, 0, 0], [s, s, 0], [0, s, 0],
        [0, 0, s], [s, 0, s], [s, s, s], [0, s, s],
    ])
    f = np.array([
        [0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7],
        [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5],
        [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7],
    ], dtype=np.int32)
    return v, f


def check_boolean_restoration_and_nested_failure():
    release()
    base_v, base_f = cube_arrays(0.01)
    quad_v = np.array([
        [0.003, 0.003, 0.01], [0.007, 0.003, 0.01],
        [0.007, 0.007, 0.01], [0.003, 0.007, 0.01],
        [0.003, 0.003, 0.005], [0.007, 0.003, 0.005],
        [0.007, 0.007, 0.005], [0.003, 0.007, 0.005],
    ])
    quad_f = np.array([[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7]], dtype=np.int32)
    patch = repair_module.solidify_patch(quad_v, quad_f, 0.0004)
    patch_tree=BVHTree.FromPolygons(mesh_bounds(patch.data),mesh_faces(patch.data),all_triangles=True,epsilon=0)
    assert patch_tree.find_nearest((0.005,0.005,0.005))[3]<0.0003
    patch_topology = prep_module.topology(patch.data)
    base_mesh = voxel_module.mesh_from_arrays(base_v, base_f, "synthetic base cube")
    base = repair_module.attach(base_mesh, "synthetic base cube")
    patch.select_set(False)
    mod = base.modifiers.new("Restore synthetic detail", "BOOLEAN")
    mod.operation = "UNION"
    mod.solver = "EXACT"
    mod.object = patch
    mod.use_self = True
    mod.use_hole_tolerant = not patch_topology["closed"]
    bpy.ops.object.modifier_apply(modifier=mod.name)
    try:
        assert len(base.data.vertices) > 8
        union_v = mesh_bounds(base.data)
        union_f = mesh_faces(base.data)
        assert len(union_f) > 0 and np.isfinite(union_v).all()
        tree = BVHTree.FromPolygons(
            [tuple(p) for p in union_v.tolist()],
            [tuple(map(int, tri)) for tri in union_f.tolist()],
            all_triangles=True, epsilon=0)
        restored = tree.find_nearest((0.005, 0.005, 0.0102))
        assert restored[0] is not None
        assert restored[3] <= 0.0005, restored[3]
        # A nested quad at the cube centre is fully interior, so union removes
        # it: the centre stays about 5mm from the outer skin, i.e. a distance
        # failure rather than silent interior deletion.
        interior = tree.find_nearest((0.005, 0.005, 0.005))
        assert interior[0] is not None
        assert interior[3] > 0.002, interior[3]
        voxel_module.export_mesh(base.data, root / "union")
    finally:
        release()


def main():
    if bpy.app.version != (4, 2, 23):
        raise ValueError("Pinned Blender 4.2.23 required, got %r" % (bpy.app.version,))
    check_bounded_edits()
    check_solidify_thin_open_patch()
    check_boolean_restoration_and_nested_failure()
    print("BLENDER_SHAPE_REPAIR_PASS", flush=True)


main()
