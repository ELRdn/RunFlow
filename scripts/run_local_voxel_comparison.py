"""Guarded local-only resolution study; separate from the closed CFD trial."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import time
from runflow.cfd_guard import run,directory_bytes
from runflow.shape_audit import file_sha

REPO=Path(__file__).resolve().parents[1]
BLENDER=REPO/'.tools/blender/blender-4.2.23-windows-x64/blender.exe'


def main():
    p=argparse.ArgumentParser(); p.add_argument('--request',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True); args=p.parse_args()
    root=args.output.resolve(); request=json.loads(args.request.read_text(encoding='utf-8-sig'))
    if not root.is_relative_to(REPO/'private') or root.exists(): raise ValueError('Fresh private output required')
    root.mkdir(parents=True); (root/'request.json').write_text(json.dumps(request,indent=2),encoding='utf-8')
    paths=['scripts/run_local_voxel_comparison.py','integrations/blender/local_voxel_compare.py',
        'integrations/blender/prepare_cfd_surface.py','integrations/blender/audit_surface_distance.py',
        'src/runflow/shape_audit.py','src/runflow/shape_local.py','src/runflow/cfd_guard.py','uv.lock']
    pins={'blender':file_sha(BLENDER),'python':file_sha(sys.executable)}
    for name in paths:
        target=root/'tool-sources'/name; target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(REPO/name,target); pins[name]=file_sha(target)
    (root/'tool-pins.json').write_text(json.dumps(pins,indent=2),encoding='utf-8')
    started=time.monotonic(); deadline=started+request['total_processing_s']; records=[]
    command=[str(BLENDER),'--background','--factory-startup','--threads','4','--python-exit-code','2',
        '--python',str(REPO/'integrations/blender/local_voxel_compare.py'),'--','--root',str(root)]
    jobs=[('prepare',command+['--stage','prepare'],request['prepare_timeout_s'])]
    for roi in request['regions']:
        for halo in request['halos_m']:
            for voxel in request['voxel_sizes_m']:
                case=f'h{round(halo*1000)}-v{round(voxel*1e6)}'; label=roi['id']+'-'+case
                jobs.append((label+'-remesh',command+['--stage','remesh','--region',roi['id'],
                    '--halo-um',str(round(halo*1e6)),'--voxel-um',str(round(voxel*1e6))],request['remesh_timeout_s']))
    # All requested candidates are attempted before measuring, so an expensive
    # diagnostic cannot consume the entire budget before finer levels start.
    for roi in request['regions']:
        cases=['global']+[f'h{round(h*1000)}-v{round(v*1e6)}' for h in request['halos_m'] for v in request['voxel_sizes_m']]
        for case in cases:
            jobs.append((roi['id']+'-'+case+'-measure',command+['--stage','measure','--region',roi['id'],'--case',case],request['measurement_timeout_s']))
    for label,cmd,cap in jobs:
        remaining=deadline-time.monotonic()
        if remaining<=0: records.append(dict(stage=label,skipped='total diagnostic time limit')); break
        if directory_bytes(root)>request['output_bytes']:
            records.append(dict(stage=label,skipped='total output limit')); break
        print('LOCAL_JOB_START',label,flush=True)
        record=run(cmd,root=root,log=root/(label+'.log'),timeout=min(cap,remaining),
            memory_bytes=request['memory_bytes'],output_bytes=request['output_bytes'],cwd=REPO)
        (root/(label+'.execution.json')).write_text(json.dumps(record,indent=2),encoding='utf-8')
        records.append(dict(stage=label,**record))
        print('LOCAL_JOB_END',label,record['returncode'],round(record['elapsed_s'],2),record['reason'],flush=True)
        if label=='prepare' and (record['returncode']!=0 or record['reason']): break
        if not record['termination_verified'] or record['reason']=='output size limit': break
    for item in request['inputs'].values():
        if file_sha(item['path'])!=item['sha256']: raise ValueError('Original changed during comparison')
    (root/'execution-summary.json').write_text(json.dumps(dict(records=records,elapsed_s=time.monotonic()-started,
        expected_jobs=len(jobs),inputs_unchanged=True,scientific_status='LOCAL_DIAGNOSTIC_ONLY',
        cfd_admission='UNCHANGED_BLOCKED',ranking_eligible=False),indent=2),encoding='utf-8')
    print('LOCAL_COMPARISON_FINISHED',len(records),len(jobs),flush=True)


if __name__=='__main__': main()
