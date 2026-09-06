"""Blender background PMX import smoke and private inventory (no validity claim)."""
from pathlib import Path
import sys
import json
import bpy

root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/".tools/mmd/addons"),str(root/".tools/mmd/wheeldeps")]
import mmd_tools
mmd_tools.register()
for ob in list(bpy.data.objects):bpy.data.objects.remove(ob,do_unlink=True)
pmx=root/"private/oguri/pmx/oguri-1006-100602.pmx"
status=bpy.ops.mmd_tools.import_model(filepath=str(pmx),types={"MESH","ARMATURE"},scale=1.0,
                                    clean_model=False,remove_doubles=False,fix_ik_links=False,rename_bones=False)
if "FINISHED" not in status:raise RuntimeError("PMX import did not finish")
inventory={"blender":bpy.app.version_string,"status":"IMPORT_ONLY_NOT_FIDELITY_VALIDATED",
 "objects":[{"name":o.name,"type":o.type,"vertices":len(o.data.vertices) if o.type=="MESH" else None,
             "bones":[b.name for b in o.data.bones] if o.type=="ARMATURE" else None}
            for o in bpy.context.scene.objects]}
(root/"private/oguri/pmx-inventory.json").write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding="utf-8")
print("PMX_IMPORT_PASS",sum(o["vertices"] or 0 for o in inventory["objects"]),"vertices")
