"""Blender 4.2 capture. Invoke in a fresh --background --factory-startup process.

Matrix already includes scale. Direct OBJ snapshots are already in RF metres;
their sibling snapshot JSON supplies evaluated joints and original RF root.
No physics, rig fitting, silent repair, or preference saving occurs.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

PARTS = {"head", "torso", "left_arm", "right_arm", "left_leg", "right_leg", "ears", "hair", "tail", "costume"}
JOINTS = {"head", "hip", "left_hand", "right_hand", "left_knee", "right_knee", "left_foot", "right_foot"}
IDENTITY = [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]


def load(path):
    def bad(value):
        raise ValueError("Non-finite number: " + value)
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), parse_constant=bad)


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":"), allow_nan=False)+"\n", encoding="utf-8")


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_manifest(m, base):
    dense = m.get('schema_version') == 'phase1-cycle-adapter-1'
    if m.get("schema_version") not in {"1", 'phase1-cycle-adapter-1'} or m.get("route") not in {"mmd_tools_pmx_vmd", "obj_sequence"}:
        raise ValueError("Unsupported manifest version/route")
    if dense and m.get('route')!='obj_sequence':raise ValueError('Dense phase capture requires direct baked input')
    matrix = m["source_to_rf"]
    scale = m["meters_per_source_unit"]
    if len(matrix) != 4 or any(len(row) != 4 for row in matrix) or matrix[3] != [0,0,0,1]:
        raise ValueError("Expected affine 4x4 transform")
    if not math.isfinite(scale) or scale <= 0 or not all(math.isfinite(v) for row in matrix for v in row):
        raise ValueError("Invalid scale/transform")
    for i in range(3):
        for j in range(3):
            dot = sum(matrix[k][i]*matrix[k][j] for k in range(3))
            if not math.isclose(dot, scale*scale if i == j else 0, abs_tol=1e-10):
                raise ValueError("Transform scale mismatch or nonuniform deformation")
    times = m["samples"]
    expected_count=32 if dense else 16
    if len(times) != expected_count or any(not math.isfinite(t["time_s"]) for t in times):
        raise ValueError(f"Exactly {expected_count} finite sample times required")
    if any(b["time_s"] <= a["time_s"] for a,b in zip(times,times[1:])):
        raise ValueError("Sample times must increase")
    if not m.get("parts_review_reference"):
        raise ValueError("Recorded human part-presence review required")
    if m["route"] == "obj_sequence":
        if matrix != IDENTITY or scale != 1:
            raise ValueError("Direct Unity output is already RF metres: use identity transform")
        for sample in times:
            for key in ("obj", "snapshot"):
                p = base / sample[key]
                if not p.is_file() or sha(p) != sample[key+"_sha256"]:
                    raise ValueError("Missing or changed direct capture: " + str(p))
    else:
        if not JOINTS.issubset(m["joints"]):
            raise ValueError("Required semantic joint mappings missing")
        if not m.get("armature_name") or not m.get("root_bone"):
            raise ValueError("Explicit armature and root bone required")
        if set(m["part_objects"]) != PARTS or any(not values for values in m["part_objects"].values()):
            raise ValueError("Map every required part to source object names")
        for key in ("pmx", "vmd"):
            p = base/m[key]
            if not p.is_file() or sha(p) != m[key+"_sha256"]:
                raise ValueError("Missing or changed input: " + str(p))
        for key in ("vmd_fps", "vmd_start_frame"):
            if not math.isfinite(m[key]):
                raise ValueError("Invalid VMD timing")
        if m["vmd_fps"] <= 0:
            raise ValueError("Invalid VMD FPS")
        if not math.isfinite(m["recording_start_clip_s"]):
            raise ValueError("Recording offset required")
    return m


def transform(matrix, point):
    return [sum(matrix[i][j]*point[j] for j in range(3))+matrix[i][3] for i in range(3)]


def normalize_x(vertices, joints, root):
    return ([[v[0]-root[0],v[1],v[2]] for v in vertices],
            {name:[v[0]-root[0],v[1],v[2]] for name,v in joints.items()})


def check_vmd_bindings(track_names, source_names):
    missing = sorted(set(track_names)-set(source_names))
    if not track_names or missing:
        raise ValueError("Unbound VMD tracks; reviewed mapping or direct Unity capture required: "+str(missing))


def capture(m, base, output):
    import bpy
    if bpy.app.version[:2] != (4,2):
        raise ValueError("This adapter is pinned to Blender 4.2.x")
    if m['schema_version']=='phase1-cycle-adapter-1' and bpy.app.version[:3]!=(4,2,23):
        raise ValueError('Dense phase transport requires Blender 4.2.23')
    if not bpy.app.background:
        raise ValueError("Run in dedicated background process; interactive scenes are not modified")
    output.mkdir(parents=True, exist_ok=False)
    # Only the fresh background scene is cleared, never a saved user scene.
    for item in list(bpy.data.objects):
        bpy.data.objects.remove(item, do_unlink=True)
    arm = None
    if m["route"] == "mmd_tools_pmx_vmd":
        addon = m.get("mmd_tools_parent")
        if addon:
            sys.path.insert(0, str((base/addon).resolve()))
        wheels = m.get("mmd_wheel_dependencies")
        if wheels:
            sys.path.insert(0,str((base/wheels).resolve()))
        import mmd_tools
        # Fresh process registration; errors abort instead of hiding bad installs.
        mmd_tools.register()
        status = bpy.ops.mmd_tools.import_model(filepath=str((base/m["pmx"]).resolve()),
                                                types={"MESH","ARMATURE"}, scale=1.0,
                                                clean_model=False,remove_doubles=False,fix_ik_links=False,rename_bones=False)
        if "FINISHED" not in status:
            raise ValueError("PMX import cancelled")
        arm = bpy.data.objects.get(m["armature_name"])
        if arm is None or arm.type != "ARMATURE":
            raise ValueError("Configured armature missing")
        from mmd_tools.core import vmd
        motion = vmd.File()
        motion.load(filepath=str((base/m["vmd"]).resolve()))
        check_vmd_bindings(motion.boneAnimation.keys(),[b.mmd_bone.name_j for b in arm.pose.bones])
        bpy.ops.object.select_all(action="DESELECT")
        from mmd_tools.core.model import FnModel
        model_root = FnModel.find_root_object(arm)
        if model_root is None:
            raise ValueError("MMD model root missing; cannot import morph animation")
        model_root.select_set(True)
        bpy.context.view_layer.objects.active = model_root
        bpy.context.scene.frame_set(m["vmd_start_frame"])
        status = bpy.ops.mmd_tools.import_vmd(filepath=str((base/m["vmd"]).resolve()), scale=1.0, margin=0)
        if "FINISHED" not in status:
            raise ValueError("VMD import cancelled")
        if bpy.context.scene.rigidbody_world:
            bpy.context.scene.rigidbody_world.enabled = False
    inventory = []
    for index, sample in enumerate(m["samples"]):
        source_snapshot = None
        if arm is None:
            for item in list(bpy.data.objects):
                bpy.data.objects.remove(item, do_unlink=True)
            bpy.ops.wm.obj_import(filepath=str((base/sample["obj"]).resolve()),
                                  forward_axis="Y", up_axis="Z")
            source_snapshot = load(base/sample["snapshot"])
            if (source_snapshot.get("unit") != "m" or source_snapshot.get("coordinate_system") != "RF_X_FORWARD_Z_UP"
                or set(source_snapshot["parts"]) != PARTS or not JOINTS.issubset(source_snapshot["joints"])
                or abs(source_snapshot["time_s"]-sample["time_s"]) > 1e-7):
                raise ValueError("Direct capture metadata mismatch")
            joints = source_snapshot["joints"]
            root = source_snapshot["root_position"]
        else:
            frame = m["vmd_start_frame"]+(sample["time_s"]-m["recording_start_clip_s"])*m["vmd_fps"]
            bpy.context.scene.frame_set(math.floor(frame), subframe=frame-math.floor(frame))
            bpy.context.view_layer.update()
            for names in m["part_objects"].values():
                for name in names:
                    ob = bpy.data.objects.get(name)
                    if ob is None or ob.type != "MESH" or ob.hide_render or len(ob.data.vertices) == 0:
                        raise ValueError("Required part mesh missing/hidden: " + name)
            def joint(name):
                bone = arm.pose.bones.get(name)
                if bone is None:
                    raise ValueError("Missing source bone: " + name)
                return transform(m["source_to_rf"], arm.matrix_world @ bone.head)
            joints = {name:joint(source) for name,source in m["joints"].items()}
            root = joint(m["root_bone"])
        deps = bpy.context.evaluated_depsgraph_get()
        vertices, triangles = [], []
        for ob in sorted(bpy.context.scene.objects, key=lambda o:o.name):
            if ob.type != "MESH" or ob.hide_render:
                continue
            evaluated = ob.evaluated_get(deps)
            mesh = evaluated.to_mesh()
            try:
                offset = len(vertices)
                mesh.calc_loop_triangles()
                vertices.extend(transform(m["source_to_rf"], evaluated.matrix_world @ v.co) for v in mesh.vertices)
                triangles.extend([offset+i for i in tri.vertices] for tri in mesh.loop_triangles)
            finally:
                evaluated.to_mesh_clear()
        if not vertices or not triangles:
            raise ValueError("Empty geometry")
        if arm is not None:
            vertices,joints = normalize_x(vertices,joints,root)
        snapshot = {"schema_version":"1","time_s":sample["time_s"],"vertices":vertices,"triangles":triangles,
                    "joints":joints,"parts":sorted(PARTS),"root_position":root,
                    "unit":"m","coordinate_system":"RF_X_FORWARD_Z_UP"}
        filename = f"frame-{index:02d}.snapshot.json"
        save(output/filename,snapshot)
        inventory.append({"path":filename,"sha256":sha(output/filename),"time_s":sample["time_s"]})
    save(output/"capture.json",{"schema_version":"1","route":m["route"],"blender":bpy.app.version_string,
                              "parts_review_reference":m["parts_review_reference"],"frames":inventory,
                              "scientific_status":"PENDING_HUMAN_REVIEW"})


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--manifest",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--validate-only",action="store_true")
    a=p.parse_args(argv)
    m=validate_manifest(load(a.manifest),a.manifest.resolve().parent)
    if not a.validate_only:
        capture(m,a.manifest.resolve().parent,a.output.resolve())


if __name__ == "__main__":
    try:
        main(sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else sys.argv[1:])
    except Exception as error:
        print("BLOCKED:",error,file=sys.stderr)
        raise SystemExit(2)
