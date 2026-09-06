"""Blender diagnostic for the private PMX/VMD pilot, in source units only."""
from pathlib import Path
import argparse
import hashlib
import json
import sys
import bpy

root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/".tools/mmd/addons"),str(root/".tools/mmd/wheeldeps")]
import mmd_tools
from mmd_tools.core.model import FnModel
from mmd_tools.core import vmd


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--pmx",type=Path,required=True)
    p.add_argument("--vmd",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args(sys.argv[sys.argv.index("--")+1:])
    if not bpy.app.background or bpy.app.version[:2]!=(4,2):raise ValueError("Blender4.2 background required")
    if a.output.exists():raise ValueError("Fresh output required")
    mmd_tools.register()
    for ob in list(bpy.data.objects):bpy.data.objects.remove(ob,do_unlink=True)
    status=bpy.ops.mmd_tools.import_model(filepath=str(a.pmx.resolve()),types={"MESH","ARMATURE"},scale=1,
        clean_model=False,remove_doubles=False,fix_ik_links=False,rename_bones=False)
    if "FINISHED" not in status:raise ValueError("PMX import failed")
    arm=next(ob for ob in bpy.context.scene.objects if ob.type=="ARMATURE")
    model=FnModel.find_root_object(arm)
    parsed=vmd.File();parsed.load(filepath=str(a.vmd.resolve()))
    animation=parsed.boneAnimation
    names={bone.mmd_bone.name_j:bone.name for bone in arm.pose.bones}
    matched=sorted(set(animation)&set(names))
    unmatched=sorted(set(animation)-set(names))
    frames=sorted({key.frame_number for keys in animation.values() for key in keys})
    if not frames:raise ValueError("Empty VMD bone animation")
    bpy.ops.object.select_all(action="DESELECT")
    model.select_set(True);bpy.context.view_layer.objects.active=model
    bpy.context.scene.frame_set(1)
    status=bpy.ops.mmd_tools.import_vmd(filepath=str(a.vmd.resolve()),scale=1,margin=0)
    if "FINISHED" not in status:raise ValueError("VMD import failed")
    if bpy.context.scene.rigidbody_world:bpy.context.scene.rigidbody_world.enabled=False
    if not arm.animation_data or not arm.animation_data.action:raise ValueError("No armature animation")
    # Full frame series enables contact-event analysis later; no official clip phase is guessed.
    semantic={"hip":"Hip","left_foot":"Ankle_L","right_foot":"Ankle_R","left_knee":"Knee_L","right_knee":"Knee_R","head":"Head"}
    samples=[]
    for frame in range(frames[0]+1,frames[-1]+2):
        bpy.context.scene.frame_set(frame);bpy.context.view_layer.update()
        joints={k:list(arm.matrix_world @ arm.pose.bones[n].head) for k,n in semantic.items()}
        samples.append({"blender_frame":frame,"joints_source_units":joints})
    def sha(path):
        with path.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()
    binding_ok=bool(matched) and not unmatched
    report={"schema_version":"1","status":"CANDIDATE_BINDING_PASS" if binding_ok else "CANDIDATE_BINDING_FAIL",
        "blender":bpy.app.version_string,"pmx_sha256":sha(a.pmx),"vmd_sha256":sha(a.vmd),
        "vmd_frame_range":[frames[0],frames[-1]],"vmd_bone_track_count":len(animation),
        "matched_tracks":matched,"unmatched_tracks":unmatched,"bone_mapping":names,
        "source_clip_start_s":None,"physical_scale_verified":False,"canonical_verified":False,
        "recording_step_s":0.03333,"recording_step_source":"pinned UnityHumanoidVMDRecorder.FPSs",
        "samples":samples}
    a.output.mkdir(parents=True)
    (a.output/"diagnostic.json").write_text(json.dumps(report,ensure_ascii=False,allow_nan=False),encoding="utf-8")
    bpy.ops.wm.save_as_mainfile(filepath=str((a.output/"candidate.blend").resolve()))
    print(report["status"],len(animation),"VMD tracks",len(matched),"matched",len(unmatched),"unmatched",len(samples),"frames")
    if not binding_ok:raise SystemExit(2)


if __name__=="__main__":main()
