"""Render private multiview intake evidence from unchanged Unity snapshots.

Run inside Blender. Smooth shading changes normals only; no subdivision or repair.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector


p = argparse.ArgumentParser()
p.add_argument('--capture-root', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
repo = Path(__file__).resolve().parents[1]
root, output = a.capture_root.resolve(), a.output.resolve()
if not all(path.is_relative_to(repo / 'private') for path in (root, output)):
    raise ValueError('Input and output must remain private')
paths = sorted((root / 'unity-a').glob('*.snapshot.json'))
if len(paths) != 16:
    raise ValueError('Exactly 16 input snapshots required')
output.mkdir(parents=True, exist_ok=False)
for ob in list(bpy.data.objects):
    bpy.data.objects.remove(ob, do_unlink=True)

evidence = []
views = [('Front (+X)', -math.pi / 2), ('View from -Y', 0),
         ('Back (-X)', math.pi / 2), ('View from +Y', math.pi)]
for row, index in enumerate((0, 4)):
    path = paths[index]
    raw = path.read_bytes()
    snap = json.loads(raw)
    evidence.append(dict(frame_index=index, input_sha256=hashlib.sha256(raw).hexdigest(),
        time_s=snap['time_s'], vertices=len(snap['vertices']), triangles=len(snap['triangles'])))
    for col, (label, angle) in enumerate(views):
        mesh = bpy.data.meshes.new(f'frame-{index}-view-{col}')
        mesh.from_pydata(snap['vertices'], [], snap['triangles'])
        mesh.update()
        for face in mesh.polygons:
            face.use_smooth = True
        ob = bpy.data.objects.new(mesh.name, mesh)
        bpy.context.collection.objects.link(ob)
        ob.location = (col * 2.8, 0, (1-row) * 2.6)
        ob.rotation_euler.z = angle
        ob.color = (.34, .58, .73, 1)
        font = bpy.data.curves.new(f'label-{index}-{col}', 'FONT')
        font.body = f'{index:02d} | {label}'
        font.size = .15
        font.align_x = 'CENTER'
        text = bpy.data.objects.new(font.name, font)
        bpy.context.collection.objects.link(text)
        text.location = (col * 2.8, -.5, (1-row) * 2.6 - .28)
        text.rotation_euler.x = math.pi / 2
        text.color = (.08, .10, .12, 1)

cam = bpy.data.cameras.new('Review camera')
cam.type = 'ORTHO'
cam.ortho_scale = 11.5
camera = bpy.data.objects.new(cam.name, cam)
bpy.context.collection.objects.link(camera)
camera.location = (4.2, -12, 2.05)
camera.rotation_euler = (Vector((4.2, 0, 2.05)) - camera.location).to_track_quat('-Z', 'Y').to_euler()
scene = bpy.context.scene
scene.camera = camera
scene.render.engine = 'BLENDER_WORKBENCH'
scene.render.resolution_x = 2400
scene.render.resolution_y = 1200
scene.render.resolution_percentage = 100
scene.display.shading.light = 'STUDIO'
scene.display.shading.color_type = 'OBJECT'
scene.display.shading.show_shadows = True
scene.display.shading.show_cavity = True
scene.display.shading.background_type = 'WORLD'
scene.world.color = (.8, .8, .8)
scene.view_settings.view_transform = 'Standard'
scene.render.image_settings.file_format = 'PNG'
scene.render.filepath = str(output / 'parts-review.png')
bpy.ops.render.render(write_still=True)
(output / 'render-evidence.json').write_text(json.dumps(dict(
    schema_version='1', blender_version=bpy.app.version_string, snapshots=evidence,
    script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    geometry_modified=False, presentation='rigid rotation and layout; smooth normals; no textures',
    body_height_measurement=None, ground_contact_verified=False,
    human_review_status='NOT_YET_REVIEWED'), indent=2), encoding='utf-8')
