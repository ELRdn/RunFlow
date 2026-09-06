"""Validate real diagnostic capture, import its OBJ sequence, and compare transport fidelity.

This does not establish contact phase, physical scale, or independent joint fidelity.
"""
import argparse
import math
from pathlib import Path
import subprocess
from runflow.core import read, write, file_hash, digest
from runflow.contracts import validate
from runflow.geometry import area


def verify_inputs(root):
    records=[read(root/f'inputs-{i}.json') for i in range(2)]
    for record in records:
        for key in ('meta_sha256','master_sha256'):
            if len(record[key])!=64 or any(c not in '0123456789abcdef' for c in record[key]):
                raise ValueError('Invalid input SHA-256')
        if not record['assets'] or not record['capture_scripts']:
            raise ValueError('Input and capture-script provenance required')
        for item in record['assets']+record['capture_scripts']:
            sha=item['sha256']
            if len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha):
                raise ValueError('Invalid input SHA-256')
    if records[0]!=records[1]:
        raise ValueError('Inputs or capture scripts differ between Unity runs')
    return dict(identical=True,loaded_asset_bundles=len(records[0]['assets']),
        input_record_sha256=digest(records[0]))


def frames(directory):
    paths=sorted(directory.glob('*.snapshot.json'))
    if len(paths)!=16: raise ValueError('Exactly 16 real snapshots required: '+str(directory))
    values=[read(p) for p in paths]
    for v in values: validate('snapshot',v)
    if any(a['time_s']>=b['time_s'] for a,b in zip(values,values[1:])):
        raise ValueError('Capture timestamps must increase')
    for foot in ('left_foot','right_foot'):
        relative=[tuple(round(x-y,6) for x,y in zip(v['joints'][foot],v['joints']['hip'])) for v in values]
        if len(set(relative))<2:
            raise ValueError('Static leg sequence is not a running-motion capture')
    return paths,values


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--capture-root',type=Path,required=True)
    p.add_argument('--blender',type=Path,required=True)
    a=p.parse_args()
    root=a.capture_root.resolve()
    repo=Path(__file__).resolve().parents[1]
    if not root.is_relative_to(repo/'private'): raise ValueError('Private capture required')
    if read(root/'completed.json')['execution_status']!='CAPTURED': raise ValueError('Capture did not complete')
    input_verification=verify_inputs(root)
    paths,first=frames(root/'unity-a')
    _,second=frames(root/'unity-b')
    samples=[]
    for path,value in zip(paths,first):
        obj=path.with_name(path.name.replace('.snapshot.json','.obj'))
        samples.append(dict(time_s=value['time_s'],obj=obj.relative_to(root).as_posix(),
            snapshot=path.relative_to(root).as_posix(),obj_sha256=file_hash(obj),snapshot_sha256=file_hash(path)))
    adapter=root/'diagnostic-adapter.json'
    candidate=root/'blender'
    if candidate.exists() or adapter.exists(): raise ValueError('Comparison requires a fresh output location')
    write(adapter,dict(schema_version='1',route='obj_sequence',source_to_rf=[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]],
        meters_per_source_unit=1,parts_review_reference='UNREVIEWED diagnostic transport only; no human approval',samples=samples))
    with (root/'blender.log').open('w',encoding='utf-8') as log:
        result=subprocess.run([str(a.blender.resolve()),'--background','--factory-startup','--python-exit-code','2',
            '--python',str(repo/'integrations/blender/runflow_capture.py'),'--','--manifest',str(adapter),'--output',str(candidate)],
            stdout=log,stderr=subprocess.STDOUT,timeout=600)
    if result.returncode: raise ValueError('Blender import failed; see private blender.log')
    _,imported=frames(candidate)
    checks=[]
    for reference,repeat,blender in zip(first,second,imported):
        if abs(reference['time_s']-blender['time_s'])>1e-7: raise ValueError('Import time mismatch')
        ra,ba=area(reference),area(blender)
        area_error=abs(ba-ra)/ra
        count_match=len(reference['vertices'])==len(blender['vertices'])
        # Importer order must match for this strict transport test; fail instead of hiding a reorder.
        vertex_error=max(math.dist(x,y) for x,y in zip(reference['vertices'],blender['vertices'])) if count_match else None
        repeated=digest(reference)==digest(repeat)
        checks.append(dict(time_s=reference['time_s'],unity_repeat_identical=repeated,
            reference_sha256=digest(reference),repeat_sha256=digest(repeat),blender_sha256=digest(blender),
            relative_area_error=area_error,reference_area_nominal_m2=ra,blender_area_nominal_m2=ba,
            vertex_count_match=count_match,max_ordered_vertex_error_nominal_m=vertex_error,
            shared_joints_preserved=reference['joints']==blender['joints'],
            passed=repeated and count_match and vertex_error<=1e-5 and area_error<=0.01
                and reference['joints']==blender['joints']))
    report=dict(schema_version='1',execution_status='PASS' if all(x['passed'] for x in checks) else 'FAIL',
        input_verification=input_verification,
        route='unity_baked_obj_transport',scientific_status='PENDING_HUMAN_REVIEW',ranking_eligible=False,
        canonical_verified=False,contact_phase_verified=False,physical_scale_reviewed=False,
        independent_joint_comparison=False,parts_human_reviewed=False,
        note='Shared Unity joints are transport metadata. This is not independent PMX/VMD or official-game fidelity validation.',checks=checks)
    write(root/'comparison.json',report)
    print(report['execution_status'],'16 frames; scientific/contact/scale/parts approval pending')
    return 0 if report['execution_status']=='PASS' else 2


if __name__=='__main__': raise SystemExit(main())
