"""Process-local registration smoke; never writes Blender preferences."""
import sys
from pathlib import Path
import bpy

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/".tools/mmd/addons"))
sys.path.insert(0,str(root/".tools/mmd/wheeldeps"))
import mmd_tools
mmd_tools.register()
for op in (bpy.ops.mmd_tools.import_model,bpy.ops.mmd_tools.import_vmd):
    print("OPERATOR",op.get_rna_type().identifier)
print("MMD_REGISTRATION_PASS",bpy.app.version_string)
mmd_tools.unregister()
