"""Blender measurement figures; mesh geometry stays unchanged, output private."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector


def clear():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob,do_unlink=True)


def mesh(name,vertices,triangles,color,offset=(0,0,0),angle=0):
    data=bpy.data.meshes.new(name)
    data.from_pydata(vertices,[],triangles);data.update()
    for p in data.polygons:p.use_smooth=True
    ob=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(ob)
    ob.color=(*color,1);ob.location=offset;ob.rotation_euler.z=angle


def label(text,x,z,size=.08,color=(.1,.12,.15)):
    font=bpy.data.curves.new(text,'FONT');font.body=text;font.size=size
    ob=bpy.data.objects.new(text,font);bpy.context.collection.objects.link(ob)
    ob.location=(x,-.6,z);ob.rotation_euler.x=math.pi/2;ob.color=(*color,1)


def line(x0,x1,z,color):
    data=bpy.data.curves.new('measurement line','CURVE');data.dimensions='3D';data.bevel_depth=.0015
    spl=data.splines.new('POLY');spl.points.add(1)
    spl.points[0].co=(x0,-.45,z,1);spl.points[1].co=(x1,-.45,z,1)
    ob=bpy.data.objects.new('measurement line',data);bpy.context.collection.objects.link(ob);ob.color=(*color,1)


def render(path,center,scale,width,height):
    cam=bpy.data.cameras.new('Camera');cam.type='ORTHO';cam.ortho_scale=scale
    ob=bpy.data.objects.new('Camera',cam);bpy.context.collection.objects.link(ob)
    ob.location=(center[0],-10,center[1]);ob.rotation_euler=(Vector((center[0],0,center[1]))-ob.location).to_track_quat('-Z','Y').to_euler()
    s=bpy.context.scene;s.camera=ob;s.render.engine='BLENDER_WORKBENCH'
    s.render.resolution_x=width;s.render.resolution_y=height;s.render.resolution_percentage=100
    sh=s.display.shading;sh.light='STUDIO';sh.color_type='OBJECT';sh.show_shadows=True;sh.show_cavity=True
    sh.background_type='WORLD';s.world.color=(.85,.85,.85);s.view_settings.view_transform='Standard'
    s.render.image_settings.file_format='PNG';s.render.filepath=str(path);bpy.ops.render.render(write_still=True)


p=argparse.ArgumentParser();p.add_argument('--measurement-root',type=Path,required=True)
p.add_argument('--output',type=Path)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);root=a.measurement_root.resolve()
if not root.is_relative_to(Path(__file__).resolve().parents[1]/'private'):raise ValueError('Private root required')
out=a.output.resolve() if a.output else root/'figures'
if not out.is_relative_to(Path(__file__).resolve().parents[1]/'private'):raise ValueError('Private figure output required')
out.mkdir(exist_ok=False)
n=json.loads((root/'neutral-0.json').read_text());f=json.loads((root/'feet-0.json').read_text())
analysis=json.loads((root/'analysis.json').read_text())
clear()
for x,angle in ((0,-math.pi/2),(1.65,0)):
    for m in n['meshes']:
        color=(.3,.56,.68) if m['name']=='M_Hair' else (.62,.68,.70)
        mesh(m['name'],m['vertices'],m['triangles'],color,(x,0,0),angle)
ground=analysis['neutral_support_plane_z']
full_top=max(b['max_z'] for b in analysis['neutral_mesh_bounds'].values())
for z,color in ((ground,(.17,.45,.28)),(1.67,(.72,.32,.16)),(full_top,(.25,.35,.65))):
    line(-.8,2.25,z,color)
label('Neutral bind pose | original scale',-.8,2.0,.10)
label(f'{full_top:.4f}: full mesh top (ears/hair included)',-.8,-.28,.085)
label('1.6700: profile reference IF 1 world unit = 1 m',-.8,-.41,.085,(.65,.28,.12))
label('0: neutral shoe support plane | scalp not identified',-.8,-.54,.085)
render(out/'neutral-scale.png',(.65,.77),3.75,1500,1200)

clear()
body=next(m for m in n['meshes'] if m['name']=='M_Body')
ids=f['right_vertex_indices'];local={v:i for i,v in enumerate(ids)}
triangles=[[local[v] for v in t] for t in body['triangles'] if all(v in local for v in t)]
indices=(248,250,251,252,253,256,258,272)
for cell,i in enumerate(indices):
    sample=f['samples'][i];col=cell%4;row=1-cell//4
    vertices=sample['right_vertices'];ankle=sample['right_ankle']
    offset=(col*.85-ankle[0],0,row*.65)
    mesh(f'right shoe {i}',vertices,triangles,(.32,.56,.72),offset)
    line(col*.85-.36,col*.85+.36,ground+row*.65,(.7,.15,.13))
    label(f'{i} | {sample["phase_s"]:.5f} s',col*.85-.33,row*.65-.14,.065)
label('Right shoe | red = neutral support plane, NOT verified race ground',-.33,1.22,.075)
label('Forward translation aligned for display; height/shape unchanged',-.33,-.34,.068)
render(out/'right-contact.png',(1.28,.48),3.8,2000,1050)
(out/'evidence.json').write_text(json.dumps(dict(neutral='neutral-0.json',feet='feet-0.json',
    input_sha256={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ('neutral-0.json','feet-0.json','analysis.json')},
    right_foot_frames=list(indices),neutral_model_deformation=False,
    foot_display='ankle forward translation aligned; neutral plane shown; no terrain claim'),indent=2))
