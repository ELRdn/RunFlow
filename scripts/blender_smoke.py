"""Generate ONLY original synthetic geometry for a Blender adapter smoke test."""
import json
import hashlib
from pathlib import Path
import argparse


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    parts=["head","torso","left_arm","right_arm","left_leg","right_leg","ears","hair","tail","costume"]
    joints={j:[0,0,1] for j in ["head","hip","left_hand","right_hand","left_knee","right_knee","left_foot","right_foot"]}
    samples=[]
    for i in range(16):
        obj=f"frame-{i:02d}.obj"
        snap=f"frame-{i:02d}.snapshot.json"
        (a.output/obj).write_text('o synthetic\nv 0 0 0\nv 0 1 0\nv 0 1 1\nv 0 0 1\nf 1 2 3\nf 1 3 4\n')
        (a.output/snap).write_text(json.dumps({"schema_version":"1","time_s":1+i/16,
            "joints":joints,"parts":parts,"vertices":[[0,0,0],[0,1,0],[0,1,1],[0,0,1]],
            "triangles":[[0,1,2],[0,2,3]],"root_position":[i/16,0,0.1*i/16],
            "unit":"m","coordinate_system":"RF_X_FORWARD_Z_UP"}))
        samples.append({"time_s":1+i/16,"obj":obj,"snapshot":snap,
                        "obj_sha256":hashlib.sha256((a.output/obj).read_bytes()).hexdigest(),
                        "snapshot_sha256":hashlib.sha256((a.output/snap).read_bytes()).hexdigest()})
    (a.output/"adapter.json").write_text(json.dumps({"schema_version":"1","route":"obj_sequence",
        "source_to_rf":[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]],"meters_per_source_unit":1,
        "parts_review_reference":"SYNTHETIC test labels only; not a character or human-reviewed game asset", "samples":samples}))


if __name__=="__main__":
    main()
