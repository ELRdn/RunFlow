"""Pinned-runtime local comparison on a closed synthetic cube."""
import importlib.util
import json
from pathlib import Path
import sys
import numpy as np

repo=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('local',repo/'integrations/blender/local_voxel_compare.py')
local=importlib.util.module_from_spec(spec); spec.loader.exec_module(local)
root=Path(sys.argv[-1]); root.mkdir()
audit=root/'audit'; audit.mkdir()
v=np.array([[-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1],[-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]],float)*.02
f=np.array([[0,2,1],[0,3,2],[4,5,6],[4,6,7],[0,1,5],[0,5,4],[1,2,6],[1,6,5],[2,3,7],[2,7,6],[3,0,4],[3,4,7]])
local.save_arrays(audit/'source',v,f); local.save_arrays(audit/'candidate',v,f)
before=local.file_sha(audit/'source/vertices.npy')
roi=dict(id='cube',low_m=[.015,-.004,-.004],high_m=[.025,.004,.004],axes=[1,2],view_axis=0,view_sign=1,witness_m=[.02,0,0])
request=dict(audit_root=str(audit),regions=[roi],halos_m=[.03],measurement_timeout_s=30,cover_m=.00025,ray_step_m=.001)
local.prepare(root,request)
local.measure(root,request,roi,'global')
for voxel in (1000,500):
    local.remesh(root,request,roi,30000,voxel)
    case=f'h30-v{voxel}'
    local.measure(root,request,roi,case)
    record=json.loads((root/'cube'/case/'measurement.json').read_text())
    assert record['complete'] and record['witness']['distance_m']<.001
    assert record['forward']['max_cover_radius_m']<=.00025001
    assert np.isfinite(record['reverse']['measured_max_m'])
assert local.file_sha(audit/'source/vertices.npy')==before
print('BLENDER_LOCAL_VOXEL_PASS',flush=True)
