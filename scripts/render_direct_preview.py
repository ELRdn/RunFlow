"""Blender-only private diagnostic view of four captured poses; no texture reconstruction."""
import argparse
import json
from pathlib import Path
import sys
import math
import bpy
from mathutils import Vector

p=argparse.ArgumentParser()
p.add_argument('--capture-root',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
if a.output.exists(): raise ValueError('Fresh preview path required')
for ob in list(bpy.data.objects): bpy.data.objects.remove(ob,do_unlink=True)
paths=sorted((a.capture_root/'unity-a').glob('*.snapshot.json'))
if len(paths)!=16: raise ValueError('16 real captures required')
start=json.loads(paths[0].read_text())['time_s']
for n,index in enumerate([0,4,8,12]):
    snap=json.loads(paths[index].read_text())
    mesh=bpy.data.meshes.new(f'capture-{index}')
    mesh.from_pydata(snap['vertices'],[],snap['triangles']);mesh.update()
    ob=bpy.data.objects.new(f'pose-{index}',mesh);bpy.context.collection.objects.link(ob)
    ob.location.x=n*2;ob.color=(.33,.60,.77,1)
    font=bpy.data.curves.new(f'label-{index}','FONT');font.body=f'{snap["time_s"]-start:.3f} s';font.size=.15
    label=bpy.data.objects.new(f'label-{index}',font);bpy.context.collection.objects.link(label)
    label.location=(n*2-.32,0,-.22);label.rotation_euler=(math.pi/2,0,0);label.color=(.15,.15,.15,1)
cam=bpy.data.cameras.new('Side');cam.type='ORTHO';cam.ortho_scale=8.2
camera=bpy.data.objects.new('Side',cam);bpy.context.collection.objects.link(camera)
camera.location=(3,-10,.8);camera.rotation_euler=(Vector((3,0,.8))-camera.location).to_track_quat('-Z','Y').to_euler()
scene=bpy.context.scene;scene.camera=camera;scene.render.engine='BLENDER_WORKBENCH'
scene.render.resolution_x=1800;scene.render.resolution_y=600;scene.render.resolution_percentage=100
scene.display.shading.light='STUDIO';scene.display.shading.color_type='OBJECT'
scene.display.shading.show_shadows=True;scene.display.shading.show_cavity=True
scene.display.shading.background_type='WORLD';scene.world.color=(.8,.8,.8)
scene.view_settings.view_transform='Standard'
scene.render.image_settings.file_format='PNG';scene.render.filepath=str(a.output.resolve())
bpy.ops.render.render(write_still=True)
