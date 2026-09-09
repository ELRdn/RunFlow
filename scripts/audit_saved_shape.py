"""Bounded, private diagnosis of an existing surface. Never runs CFD or repair."""
import argparse
import json
from pathlib import Path
import shutil
import re
import sys
import time

from runflow.shape_audit import cache_surface,file_sha
from runflow.cfd_guard import run

REPO=Path(__file__).resolve().parents[1]
BLENDER=REPO/'.tools/blender/blender-4.2.23-windows-x64/blender.exe'


def write(path,value): path.write_text(json.dumps(value,indent=2,sort_keys=True),encoding='utf-8')


def main():
    p=argparse.ArgumentParser(); p.add_argument('--trial',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--provenance',type=Path)
    p.add_argument('--attempt',default='',help='Explicit label for a corrected failed diagnostic stage; no automatic retry')
    p.add_argument('--projection-view',choices=['front','side','top'])
    p.add_argument('--projection-grid-m',type=float,default=0.)
    p.add_argument('--stage',choices=['cache','distance','projection','views','sections','witnesses'],required=True)
    args=p.parse_args(); root=args.output.resolve(); trial=args.trial.resolve()
    if args.attempt and not re.fullmatch(r'[A-Za-z0-9_-]+',args.attempt): raise ValueError('Invalid attempt label')
    if not root.is_relative_to(REPO/'private') or not trial.is_relative_to(REPO/'private'):
        raise ValueError('Audit inputs and outputs must stay private')
    if args.stage=='cache':
        if root.exists(): raise ValueError('Fresh audit output required')
        root.mkdir(parents=True)
        geometry=json.loads((trial/'geometry/geometry.json').read_text())
        identity=json.loads((trial/'attempt-identity.json').read_text())
        inputs={
            'source':{'path':str(trial/'source.snapshot.json'),'sha256':geometry['source_sha256']},
            'candidate':{'path':str(trial/'geometry/candidate.obj'),
                         'sha256':identity['inputs']['geometry/candidate.obj']}}
        write(root/'request.json',dict(kind='saved_surface_audit',inputs=inputs,
            distance_cover_m=.001,distance_timeout_s=1200,projection_timeout_s=1200,
            memory_bytes=12*1024**3,output_bytes=10*1024**3,
            scientific_status='DIAGNOSTIC_ONLY',ranking_eligible=False,
            note='New user-requested read-only diagnosis; does not reopen or reset the CFD trial budget'))
        for name,item in inputs.items(): cache_surface(item['path'],root/name,item['sha256'])
        labels=args.provenance.resolve() if args.provenance else None
        # Renderer names are evidence only: no fabricated per-triangle part labels.
        if labels:
            if not labels.is_relative_to(REPO/'private'): raise ValueError('Private provenance required')
            shutil.copyfile(labels,root/'source-provenance.json')
        print('AUDIT_CACHE_READY',root,flush=True); return
    request=json.loads((root/'request.json').read_text())
    for item in request['inputs'].values():
        if file_sha(item['path'])!=item['sha256']: raise ValueError('Audit input changed')
    jobs=[]
    if args.stage=='distance':
        for direction in ('source-to-candidate','candidate-to-source'):
            jobs.append((direction,[str(BLENDER),'--background','--factory-startup','--threads','4',
                '--python-exit-code','2','--python',str(REPO/'integrations/blender/audit_surface_distance.py'),
                '--','--root',str(root),'--direction',direction,'--cover-m',str(request['distance_cover_m']),
                '--timeout',str(request['distance_timeout_s'])],request['distance_timeout_s']))
    elif args.stage=='projection':
        command=[sys.executable,str(REPO/'scripts/audit_shape_projection.py'),'--root',str(root)]
        name='projection'
        if args.projection_view:
            command.extend(['--view',args.projection_view]); name+='-'+args.projection_view
        if args.projection_grid_m: command.extend(['--grid-m',str(args.projection_grid_m)])
        jobs=[(name,command,request['projection_timeout_s'])]
    elif args.stage=='sections':
        jobs=[('sections',[sys.executable,str(REPO/'scripts/audit_shape_sections.py'),'--root',str(root)],300)]
    elif args.stage=='witnesses':
        jobs=[('witnesses',[str(BLENDER),'--background','--factory-startup','--threads','4','--python-exit-code','2',
            '--python',str(REPO/'integrations/blender/audit_surface_witnesses.py'),'--','--root',str(root)],300)]
    else:
        jobs=[('views',[str(BLENDER),'--background','--factory-startup','--threads','4','--python-exit-code','2',
            '--python',str(REPO/'integrations/blender/audit_surface_views.py'),'--','--root',str(root)],1200)]
    for name,command,timeout in jobs:
        if args.attempt:
            prior=json.loads((root/(name+'.execution.json')).read_text())
            if prior['returncode']==0 and not prior['reason']:
                raise ValueError('Cannot retry an already successful stage')
        record_name=name+('-'+args.attempt if args.attempt else '')
        if (root/(record_name+'.execution.json')).exists(): raise ValueError('Stage already attempted; inspect evidence')
        paths=[Path(__file__).resolve(),REPO/'src/runflow/shape_audit.py',REPO/'src/runflow/cfd_guard.py',REPO/'uv.lock']
        paths += [Path(arg) for arg in command if arg.endswith('.py') and Path(arg).is_file()]
        if args.stage=='projection': paths.append(REPO/'src/runflow/shape_projection.py')
        if args.stage=='sections': paths.append(REPO/'src/runflow/shape_sections.py')
        pins={}
        for path in set(paths):
            relative=path.relative_to(REPO)
            target=root/'tool-sources'/record_name/relative
            target.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(path,target)
            pins[relative.as_posix()]=file_sha(path)
        pins['runtime']=file_sha(command[0]); write(root/(record_name+'.tool-pins.json'),pins)
        print('AUDIT_STAGE_START',record_name,flush=True)
        record=run(command,root=root,log=root/(record_name+'.log'),timeout=timeout,
                   memory_bytes=request['memory_bytes'],output_bytes=request['output_bytes'],cwd=REPO)
        write(root/(record_name+'.execution.json'),record)
        if record['returncode']!=0 or record['reason']: raise RuntimeError(str(record))
        print('AUDIT_STAGE_DONE',name,record['elapsed_s'],flush=True)


if __name__=='__main__': main()
