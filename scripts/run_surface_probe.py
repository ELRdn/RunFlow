"""Bounded Linux diagnostic, separate from CFD attempts and their terminal results."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from cfd_worker import command,save
REPO=Path(__file__).resolve().parents[1]
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def job(root,source,scratch):
    request=json.loads((root/'request.json').read_text());tool=REPO/'.tools/openfoam-surface-probe/surfaceProbe'
    assert sha(tool)==request['probe_sha256'] and sha(source)==request['source_sha256']
    shutil.copyfile(source,scratch/'candidate.obj');assert sha(scratch/'candidate.obj')==request['source_sha256']
    subprocess.run([str(tool),str(scratch/'candidate.obj'),str(scratch/'probe')],cwd=scratch,check=True)
    for name in ('probe.rfmesh','probe.hits.csv'):
        shutil.copyfile(scratch/name,root/name);assert sha(scratch/name)==sha(root/name)
    save(root/'probe-evidence.json',dict(complete=True,loaded_mesh_sha256=sha(root/'probe.rfmesh'),
        loaded_mesh_matches_original=sha(root/'probe.rfmesh')==request['expected_rfmesh_sha256'],
        hits_sha256=sha(root/'probe.hits.csv'),source_sha256=request['source_sha256'],probe_sha256=request['probe_sha256']))
    if scratch.parent!=Path(tempfile.gettempdir()).resolve() or not scratch.name.startswith('runflow-cfd-surface-'):
        raise ValueError('Unexpected owned scratch')
    shutil.rmtree(scratch)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--source',type=Path,required=True)
    p.add_argument('--expected-rfmesh-sha');p.add_argument('--job',action='store_true');p.add_argument('--scratch',type=Path)
    a=p.parse_args();root=a.output.resolve();source=a.source.resolve()
    if not root.is_relative_to(REPO/'private') or not source.is_relative_to(REPO/'private'):raise ValueError('Private paths required')
    if a.job:job(root,source,a.scratch);raise SystemExit(0)
    assert os.environ.get('WM_PROJECT_VERSION')=='14'
    root.mkdir(exist_ok=False,parents=True);(root/'case').mkdir()
    request=dict(source_sha256=sha(source),expected_rfmesh_sha256=a.expected_rfmesh_sha,
        probe_sha256=sha(REPO/'.tools/openfoam-surface-probe/surfaceProbe'),timeout_s=600,
        resource_limits=dict(memory_bytes=12*1024**3,output_bytes=10*1024**3))
    save(root/'request.json',request);shutil.copyfile(REPO/'.tools/openfoam-surface-probe/build.json',root/'probe-build.json')
    scratch=Path(tempfile.mkdtemp(prefix='runflow-cfd-surface-')).resolve();start=time.monotonic()
    args=[sys.executable,str(Path(__file__).resolve()),'--job','--output',str(root),'--source',str(source),'--scratch',str(scratch)]
    record=command(args,root,start+600,request['resource_limits'],'probe.log',cwd=scratch,extra_roots=(scratch,))
    save(root/'execution.json',dict(command=record,scratch_retained=scratch.exists(),elapsed_s=time.monotonic()-start))
    print('SURFACE_PROBE',record['returncode'],record['reason'],flush=True)
    raise SystemExit(0 if record['returncode']==0 and not record['reason'] else 2)
