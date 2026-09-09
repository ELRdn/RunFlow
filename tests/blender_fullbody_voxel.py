"""Real pinned-runtime test: four whole-input runs including thin/gapped geometry."""
import importlib.util
import json
from pathlib import Path
import sys
import os
import numpy as np
import bpy

repo=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('full',repo/'integrations/blender/fullbody_voxel_compare.py')
full=importlib.util.module_from_spec(spec); spec.loader.exec_module(full)
from mathutils import Vector
for direction in [Vector(d) for d in [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]]:
    rotation=full.camera_rotation(direction).to_matrix()
    assert (rotation@Vector((0,0,-1))).dot(direction)>.99999
    if direction.z==0:
        assert (rotation@Vector((0,1,0))).dot(Vector((0,0,1)))>.99999, 'Front/side view was rolled upside down'
root=Path(sys.argv[-1]).resolve(); root.mkdir()
# Two separated closed small boxes and a thin open triangle; every resolution receives all three.
cube=np.array([[-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1],[-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]],float)*.003
faces=np.array([[0,2,1],[0,3,2],[4,5,6],[4,6,7],[0,1,5],[0,5,4],[1,2,6],[1,6,5],[2,3,7],[2,7,6],[3,0,4],[3,4,7]],np.int32)
v=np.concatenate([cube+[-.006,0,0],cube+[.006,0,0],np.array([[0,0,.006],[.002,0,.006],[0,.002,.006]])])
f=np.concatenate([faces,faces+8,[[16,17,18]]])
path=root/'input.json'; path.write_text(json.dumps(dict(vertices=v.tolist(),triangles=f.tolist(),unit='m',coordinate_system='RF_X_FORWARD_Z_UP')))
request=dict(inputs={'source':dict(path=str(path),sha256=full.module('audit',repo/'src/runflow/shape_audit.py').file_sha(path))})
full.prepare(root,request); before=full.read(root/'cleaned/cache.json')['output_hashes']
voxels=[int(v) for v in os.environ.get('RUNFLOW_TEST_VOXELS_UM','1000,500,250,100').split(',')]
for voxel in voxels:
    full.remesh(root,voxel)
    info=full.read(root/f'v{voxel}/generation.json')
    assert info['whole_input'] and info['cleaned_input_hashes']==before
    a,b=full.load_surface(root/f'v{voxel}/candidate')
    assert a[:,0].min()<-.008 and a[:,0].max()>.008
    assert np.isfinite(a).all() and len(b)>0
    assert full.read(root/'cleaned/cache.json')['output_hashes']==before
full.write(root/'view-bounds.json',dict(low_m=[-.02,-.02,-.02],high_m=[.02,.02,.02]))
request['regions']=[]
case=f'v{voxels[0]}'
full.views(root,'source',request); full.views(root,case,request)
full.distances(root,case,'forward',request,30)
full.distances(root,case,'reverse',request,30)
assert full.read(root/case/'metrics/forward.json')['complete']
assert full.read(root/case/'metrics/reverse.json')['complete']
if os.environ.get('RUNFLOW_TEST_HIP')=='1':
    full.render_hip(root,'source')
    assert full.read(root/'source-metrics/render.json')['camera_up_axis']=='Y'
full.write(root/'request.json',request)
print('BLENDER_FULLBODY_PASS',flush=True)
