"""Private CFD surface candidate. Run with pinned Blender, not ordinary Python.

Certification uses the 1-Lipschitz property of distance to a triangle surface:
distance(center, target) + max(distance(center, triangle vertices)) bounds the
whole source triangle. A failed/incomplete bound never passes as a sampled maximum.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import bpy
import bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def save(path, value):
    path.write_text(json.dumps(value, sort_keys=True, allow_nan=False), encoding='utf-8')


def topology(mesh):
    mesh.calc_loop_triangles()
    bm=bmesh.new(); bm.from_mesh(mesh)
    result=dict(vertices=len(bm.verts), polygons=len(bm.faces), triangles=len(mesh.loop_triangles),
        boundary_edges=sum(e.is_boundary for e in bm.edges),
        nonmanifold_edges=sum(not e.is_manifold for e in bm.edges),
        nonmanifold_vertices=sum(not v.is_manifold for v in bm.verts),
        inconsistent_edges=sum(e.is_manifold and not e.is_contiguous for e in bm.edges),
        degenerate_faces=sum(t.area < 1e-16 for t in mesh.loop_triangles))
    result['closed']=bool(bm.faces) and all(result[key]==0 for key in
        ('nonmanifold_edges','nonmanifold_vertices','inconsistent_edges','degenerate_faces'))
    bm.free()
    return result


def repair_voxel_degeneracy(mesh, weld_m):
    """Weld only vertices touching an emitted degenerate triangle, once.

    Each replacement is an existing vertex within the original 1 micrometre
    allowance. Direct-to-target distances prevent transitive cluster drift.
    No smoothing, face filling, second voxel pass, or general decimation.
    """
    mesh.calc_loop_triangles()
    bad=[t for t in mesh.loop_triangles if t.area < 1e-16]
    ids=sorted({i for t in bad for i in t.vertices})
    record=dict(method='local_degenerate_triangle_weld_v1',weld_m=weld_m,
        degenerate_triangles_before=len(bad),affected_vertices=len(ids),
        merged_vertices=0,max_vertex_shift_m=0.,replacements=[],removed_unused_vertices=[])
    if not bad: return record
    bm=bmesh.new(); bm.from_mesh(mesh); bm.verts.ensure_lookup_table()
    kept=[]; targets={}
    for index in ids:
        vertex=bm.verts[index]
        target=next((i for i in kept if (bm.verts[i].co-vertex.co).length<=weld_m),None)
        if target is None:
            kept.append(index); continue
        distance=(bm.verts[target].co-vertex.co).length
        targets[vertex]=bm.verts[target]
        record['replacements'].append(dict(vertex_index=index,target_index=target,
            original_m=list(vertex.co),target_m=list(bm.verts[target].co),distance_m=distance))
        record['max_vertex_shift_m']=max(record['max_vertex_shift_m'],distance)
    if targets:
        record['merged_vertices']=len(targets)
        bmesh.ops.weld_verts(bm,targetmap=targets)
        # Collapsing a zero-area isolated component can leave a vertex with no
        # edge or face. It is not part of the triangle surface being certified.
        unused=[v for v in bm.verts if not v.link_edges and not v.link_faces]
        record['removed_unused_vertices']=[list(v.co) for v in unused]
        bmesh.ops.delete(bm,geom=unused,context='VERTS')
        bm.to_mesh(mesh); mesh.update()
    bm.free()
    return record


def arrays(mesh):
    mesh.calc_loop_triangles()
    return [tuple(v.co) for v in mesh.vertices], [tuple(t.vertices) for t in mesh.loop_triangles]


def bounded_distance(vertices, triangles, target_v, target_f, tolerance, cover, deadline):
    tree=BVHTree.FromPolygons(target_v,target_f,all_triangles=True,epsilon=0)
    peak=0.; upper=0.; queries=0; certified=0
    for face in triangles:
        stack=[tuple(Vector(vertices[i]) for i in face)]
        while stack:
            if time.monotonic()>deadline:
                return dict(passed=False, complete=False, reason='distance verification time limit', queries=queries)
            a,b,c=stack.pop(); center=(a+b+c)/3
            radius=max((v-center).length for v in (a,b,c))
            hit=tree.find_nearest(center); queries+=1
            if hit[0] is None:
                return dict(passed=False,complete=False,reason='empty nearest-surface result')
            distance=hit[3]; peak=max(peak,distance)
            if distance>tolerance:
                return dict(passed=False,complete=False,reason='measured surface distance exceeds tolerance',
                    witness_m=distance,witness_point=list(center),queries=queries)
            bound=distance+radius+2e-6  # conservative binary32/BVH numerical allowance, in metres
            if bound<=tolerance:
                upper=max(upper,bound); certified+=1; continue
            if radius<=cover:
                return dict(passed=False,complete=False,reason='conservative distance bound exceeds tolerance',
                    measured_m=distance,upper_bound_m=bound,witness_point=list(center),queries=queries)
            # Four subtriangles cover the entire parent, including its edges.
            ab=(a+b)/2; bc=(b+c)/2; ca=(c+a)/2
            stack.extend(((a,ab,ca),(ab,b,bc),(ca,bc,c),(ab,bc,ca)))
    return dict(passed=True,complete=True,max_measured_m=peak,max_upper_bound_m=upper,
        queries=queries,certified_subtriangles=certified)


def render(source, candidate, output):
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob,do_unlink=True)
    for col,(name,mesh) in enumerate((('Original',source),('CFD candidate',candidate))):
        for row,angle in enumerate((0,math.pi/2)):
            ob=bpy.data.objects.new(name,mesh); bpy.context.collection.objects.link(ob)
            ob.location=(col*2.4,0,row*2.4); ob.rotation_euler.z=angle
            ob.color=(.28,.53,.68,1) if col==0 else (.7,.4,.22,1)
            font=bpy.data.curves.new(name,'FONT'); font.body=name+(' | side' if row==0 else ' | rear')
            font.size=.13; font.align_x='CENTER'
            label=bpy.data.objects.new(name+' label',font); bpy.context.collection.objects.link(label)
            label.location=(col*2.4,-.5,row*2.4-.3); label.rotation_euler.x=math.pi/2
            label.color=(.1,.1,.1,1)
    cam=bpy.data.cameras.new('Comparison'); cam.type='ORTHO'; cam.ortho_scale=5.1
    ob=bpy.data.objects.new('Comparison',cam); bpy.context.collection.objects.link(ob)
    ob.location=(1.2,-12,1.9); ob.rotation_euler=(Vector((1.2,0,1.9))-ob.location).to_track_quat('-Z','Y').to_euler()
    scene=bpy.context.scene; scene.camera=ob; scene.render.engine='BLENDER_WORKBENCH'
    scene.render.resolution_x=1500; scene.render.resolution_y=1500; scene.render.resolution_percentage=100
    scene.display.shading.color_type='OBJECT'; scene.display.shading.light='STUDIO'
    scene.display.shading.show_cavity=True; scene.world.color=(.8,.8,.8)
    scene.render.filepath=str(output/'comparison.png'); bpy.ops.render.render(write_still=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--request',type=Path,required=True)
    args=p.parse_args(sys.argv[sys.argv.index('--')+1:])
    request=json.loads(args.request.read_text(encoding='utf-8-sig'))
    source=Path(request['source']); output=Path(request['output']); settings=request['geometry']
    if bpy.app.version!=(4,2,23): raise ValueError('Wrong Blender version')
    if hashlib.sha256(source.read_bytes()).hexdigest()!=request['source_sha256']: raise ValueError('Source hash mismatch')
    snapshot=json.loads(source.read_text(encoding='utf-8-sig'))
    started=time.monotonic(); deadline=started+request['timeout_s']-10
    original=bpy.data.meshes.new('original'); original.from_pydata(snapshot['vertices'],[],snapshot['triangles']); original.update()
    cleaned=original.copy(); bm=bmesh.new(); bm.from_mesh(cleaned)
    bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=settings['weld_m'])
    bm.verts.index_update(); seen=set(); remove=[]
    for f in bm.faces:
        key=tuple(sorted(v.index for v in f.verts))
        if key in seen or f.calc_area()<1e-16: remove.append(f)
        else: seen.add(key)
    bmesh.ops.delete(bm,geom=remove,context='FACES_ONLY')
    bmesh.ops.delete(bm,geom=[e for e in bm.edges if not e.link_faces],context='EDGES')
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces)); bm.to_mesh(cleaned); bm.free(); cleaned.update()
    before=topology(cleaned); candidate=cleaned
    history=['weld at 1 micrometre','remove duplicate/degenerate faces','consistent face normals']
    local_repair=None
    if not before['closed']:
        for ob in list(bpy.data.objects): bpy.data.objects.remove(ob,do_unlink=True)
        ob=bpy.data.objects.new('CFD candidate',cleaned.copy()); bpy.context.collection.objects.link(ob)
        bpy.context.view_layer.objects.active=ob; ob.select_set(True)
        ob.data.remesh_voxel_size=settings['voxel_m']; ob.data.remesh_voxel_adaptivity=0
        ob.data.use_remesh_preserve_volume=False
        bpy.ops.object.voxel_remesh()
        candidate=ob.data.copy(); history.append('one 1 mm voxel remesh; no smoothing or preserve-volume correction')
        local_repair=repair_voxel_degeneracy(candidate,settings['weld_m'])
        history.append('one local weld of vertices touching degenerate output triangles; at most 1 micrometre')
        print('LOCAL_DEGENERACY_REPAIR',json.dumps(local_repair),flush=True)
    v,f=arrays(candidate); sv,sf=arrays(original)
    repaired=topology(candidate)
    payload={**snapshot,'vertices':v,'triangles':f}
    save(output/'candidate.snapshot.json',payload)
    with (output/'candidate.obj').open('w',encoding='ascii') as stream:
        stream.write('g oguri\n')
        for x,y,z in v: stream.write(f'v {x:.9g} {y:.9g} {z:.9g}\n')
        for a,b,c in f: stream.write(f'f {a+1} {b+1} {c+1}\n')
    # Always leave an inspectable candidate, including when a gate fails.
    render(original,candidate,output)
    if repaired['closed']:
        forward=bounded_distance(sv,sf,v,f,settings['max_distance_m'],settings['max_cover_radius_m'],deadline)
        reverse=bounded_distance(v,f,sv,sf,settings['max_distance_m'],settings['max_cover_radius_m'],deadline) if forward['passed'] else dict(passed=False,complete=False,reason='forward bound failed')
    else:
        forward=reverse=dict(passed=False,complete=False,reason='candidate is not closed')
    report=dict(schema_version='phase1-1',blender_version=bpy.app.version_string,
        source_sha256=request['source_sha256'],candidate_sha256=hashlib.sha256((output/'candidate.snapshot.json').read_bytes()).hexdigest(),
        cleaned_topology=before,candidate_topology=repaired,preprocessing=history,
        local_degeneracy_repair=local_repair,
        source_to_candidate=forward,candidate_to_source=reverse,
        parts_basis='Complete bidirectional surface coverage of the human-reviewed input; no new human review.',
        distance_passed=forward['passed'] and reverse['passed'],self_intersection_verified=False,
        elapsed_s=time.monotonic()-started)
    save(output/'geometry.json',report)
    print('GEOMETRY_CANDIDATE_SAVED',report['distance_passed'],flush=True)


if __name__=='__main__': main()
