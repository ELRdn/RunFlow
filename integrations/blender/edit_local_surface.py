"""Native Blender proportional vertex edit of an explicitly recorded small patch."""
import argparse
import json
from pathlib import Path
import sys
import bpy
import bmesh
import numpy as np
from mathutils import Vector


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True)
    a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);root=a.root
    if bpy.app.version!=(4,2,23) or not bpy.app.background:raise ValueError('Dedicated pinned Blender required')
    config=json.loads((root/'edit.json').read_text());data=np.load(root/'patch.npz')
    vertices=data['vertices'];faces=data['faces'];center=np.array(config['center_m']);radius=config['radius_m']
    move=np.array(config['translation_m']);axis=config['view_axis'];axes=config['view_axes'];sign=config['view_sign']
    for ob in list(bpy.data.objects):bpy.data.objects.remove(ob,do_unlink=True)
    def mesh(name,v,f,color,offset=0):
        m=bpy.data.meshes.new(name);m.from_pydata(v,[],f);m.update()
        ob=bpy.data.objects.new(name,m);bpy.context.collection.objects.link(ob)
        ob.color=(*color,1);ob.location[axes[0]]=offset
        return ob
    original=mesh('Original source patch',data['source_vertices'],data['source_faces'],(.25,.55,.8),-.044)
    base=mesh('Qualified 0.9 mm before edit',vertices,faces,(.75,.55,.24))
    edited=mesh('Assistant proportional edit - unapproved',vertices,faces,(.3,.7,.5),.044)
    before=np.empty(len(vertices)*3,dtype=np.float32);edited.data.vertices.foreach_get('co',before)
    bm=bmesh.new();bm.from_mesh(edited.data);bm.verts.ensure_lookup_table()
    weights=[]
    for vertex in bm.verts:
        distance=float(np.linalg.norm(vertices[vertex.index]-center))
        weight=(.5+.5*np.cos(np.pi*distance/radius)) if distance<radius else 0.
        weights.append(weight)
        if weight:vertex.co+=Vector(move*weight)
    bm.to_mesh(edited.data);bm.free();edited.data.update()
    after=np.empty_like(before);edited.data.vertices.foreach_get('co',after)
    # Export displacements only. The parent adds them to original binary64 values.
    delta=after.reshape(-1,3).astype(float)-before.reshape(-1,3).astype(float)
    delta[np.asarray(weights)==0]=0
    np.save(root/'blender-delta.npy',delta)
    vg=edited.vertex_groups.new(name='Proportional influence (assistant selection)')
    for i,w in enumerate(weights):
        if w:vg.add([i],float(w),'REPLACE')
    camera=bpy.data.cameras.new('Comparison camera');camera.type='ORTHO';camera.ortho_scale=.145
    ob=bpy.data.objects.new('Comparison camera',camera);bpy.context.collection.objects.link(ob)
    target=Vector(center);position=target.copy();position[axis]+=sign*.2
    ob.location=position;ob.rotation_euler=(target-position).to_track_quat('-Z','Y').to_euler()
    # Set camera up to the second plotted coordinate, without changing mesh coordinates.
    from mathutils import Matrix
    right=Vector([0.,0.,0.]);right[axes[0]]=1
    up=Vector([0.,0.,0.]);up[axes[1]]=1
    back=right.cross(up)
    if back[axis]*sign<0:up=-up;back=right.cross(up)
    ob.rotation_euler=Matrix((right,up,back)).transposed().to_euler()
    scene=bpy.context.scene;scene.camera=ob;scene.render.engine='BLENDER_WORKBENCH'
    scene.display.shading.light='STUDIO';scene.display.shading.color_type='OBJECT'
    scene.display.shading.show_shadows=True;scene.display.shading.show_cavity=True
    scene.display.shading.background_type='WORLD';scene.world.color=(.08,.08,.08)
    scene.render.resolution_x=1500;scene.render.resolution_y=650;scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG';scene.render.filepath=str(root/'native-blender-comparison.png')
    scene.unit_settings.system='METRIC';scene.unit_settings.scale_length=1
    bpy.context.view_layer.objects.active=edited;edited.select_set(True)
    bpy.ops.wm.save_as_mainfile(filepath=str(root/'local-edit.blend'))
    bpy.ops.render.render(write_still=True)
    (root/'blender-edit.json').write_text(json.dumps(dict(blender=bpy.app.version_string,
        moved_vertices=int(np.count_nonzero(np.linalg.norm(delta,axis=1))),
        max_displacement_m=float(np.linalg.norm(delta,axis=1).max()),
        display_columns=['original source patch','qualified 0.9 mm','proportional edit'],
        full_body_roundtrip=False,human_approval=None,scientific_approval=None)),encoding='utf-8')
    print('NATIVE_BLENDER_EDIT_COMPLETE',flush=True)


if __name__=='__main__':main()
