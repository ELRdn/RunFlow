"""Synthetic full-coverage distance test under the pinned Blender runtime."""
import importlib.util
from pathlib import Path
import sys
import numpy as np

repo=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('audit',repo/'integrations/blender/audit_surface_distance.py')
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
root=Path(sys.argv[-1]); root.mkdir(exist_ok=True)
v=np.array([[0.,0,0],[.004,0,0],[0,.004,0]])
f=np.array([[0,1,2]],dtype=np.int32)
import time
result=module.audit(v,f,v+[0,0,.003],f,root/'test',.001,time.monotonic()+10)
assert result['complete'] and result['samples']>1
assert abs(result['area_weighted_mean_m']-.003)<2e-8
assert abs(result['total_triangle_area_m2']-.000008)<1e-10
assert result['global_max_lower_m']<.003<result['global_max_upper_m']
assert result['max_cover_radius_m']<=.001000001
print('BLENDER_SHAPE_AUDIT_PASS',flush=True)
