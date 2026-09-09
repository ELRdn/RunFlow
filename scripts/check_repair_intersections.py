"""Binary STL + independent OpenFOAM surface check, with Windows/WSL liveness guards."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import time

REPO=Path(__file__).resolve().parents[1]


def save(path,value):
    tmp=path.with_suffix('.tmp'); tmp.write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8'); tmp.replace(path)


def intersection_result(log):
    free='Surface is not self-intersecting' in log
    found=re.search(r'Surface is self-intersecting at (\d+) locations\.',log)
    if free and found: return None, None
    if free: return True, 0
    if found and int(found[1])>0: return False, int(found[1])
    return None, None


def linux_check(root,seconds,local_io=False):
    from cfd_worker import descendants,kill_group
    deadline=time.monotonic()+seconds; known={}; reason=None; peak=0; verified=False
    exported=subprocess.check_output(['bash','-c','source /opt/openfoam14/etc/bashrc >/dev/null && env -0'],timeout=20)
    environment={entry.split(b'=',1)[0].decode():entry.split(b'=',1)[1].decode(errors='surrogateescape')
                 for entry in exported.split(b'\0') if b'=' in entry}
    tool=Path(shutil.which('surfaceCheck',path=environment['PATH'])).resolve()
    scratch=Path(tempfile.mkdtemp(prefix='runflow-selfcheck-')) if local_io else root
    if local_io:
        # Bulk-copy the exact input. Only diagnostic I/O moves to the Linux filesystem.
        if shutil.disk_usage(scratch).free<20*1024**3: raise ValueError('Linux scratch disk reserve')
        shutil.copyfile(root/'surface.stl',scratch/'surface.stl')
        with (scratch/'surface.stl').open('rb') as stream: copied=hashlib.file_digest(stream,'sha256').hexdigest()
        if copied!=json.loads((root/'input.json').read_text())['surface_sha256']: raise ValueError('Scratch input hash mismatch')
        save(root/'scratch.json',dict(path=str(scratch),input_sha256=copied,disposable_owned_directory=True))
    output_size=0; next_disk_check=0
    with (root/'surfaceCheck.log').open('wb') as output:
        process=subprocess.Popen([str(tool),'-checkSelfIntersection',str(scratch/'surface.stl')],
            cwd=scratch,stdout=output,stderr=subprocess.STDOUT,start_new_session=True,env=environment)
        save(root/'linux-process.json',dict(pid=process.pid,pgid=process.pid))
        try:
            while process.poll() is None:
                peak=max(peak,sum(x['rss'] for x in descendants(process.pid,known).values()))
                if time.monotonic()>=next_disk_check:
                    output_size=sum(p.stat().st_size for p in scratch.rglob('*') if p.is_file())
                    next_disk_check=time.monotonic()+5
                if time.monotonic()>=deadline: reason='Linux surface-check timeout'
                elif peak>12*1024**3: reason='Linux checker RSS limit'
                elif output_size>10*1024**3: reason='Linux diagnostic output limit'
                elif local_io and shutil.disk_usage(scratch).free<20*1024**3: reason='Linux scratch disk reserve'
                elif (root/'stop').exists(): reason='Windows guard requested stop'
                elif time.time()-(root/'heartbeat').stat().st_mtime>10: reason='Windows launcher heartbeat lost'
                if reason:
                    kill_group(process,known); break
                time.sleep(.25)
            code=process.wait()
            if descendants(process.pid,known): kill_group(process,known)
            verified=not descendants(process.pid,known)
        except BaseException as exc:
            reason=f'{type(exc).__name__}: {exc}'; kill_group(process,known); code=process.poll()
            verified=not descendants(process.pid,known)
    log=(root/'surfaceCheck.log').read_text(errors='replace')
    success=code==0 and reason is None and verified
    free,count=intersection_result(log)
    # A missing result sentence is not itself evidence of an intersection.
    result=dict(execution_success=success,returncode=code,reason=reason,termination_verified=verified,
        peak_rss_bytes=peak,tool_sha256=hashlib.file_digest(tool.open('rb'),'sha256').hexdigest(),
        complete=bool(success and free is not None),
        intersection_free=free if success else None,intersection_locations=count if success else None,
        closed_reported='Surface is closed. All edges connected to two faces.' in log,
        local_linux_io=local_io,peak_scratch_bytes=output_size,
        scope='OpenFOAM Foundation 14 checkSelfIntersection on the recorded binary32 surface')
    save(root/'linux-result.json',result)
    if local_io and verified:
        # Keep the complete diagnostics privately, using sequential bulk I/O to E:.
        archive=scratch/'diagnostics.tar'
        with tarfile.open(archive,'w') as output:
            for path in sorted(scratch.iterdir()):
                if path.name not in ('surface.stl','diagnostics.tar'): output.add(path,arcname=path.name)
        shutil.copyfile(archive,root/'diagnostics.tar')
        with (root/'diagnostics.tar').open('rb') as stream: sha=hashlib.file_digest(stream,'sha256').hexdigest()
        result['diagnostics']=dict(file='diagnostics.tar',sha256=sha,bytes=archive.stat().st_size)
        save(root/'linux-result.json',result)
        if scratch.parent!=Path(tempfile.gettempdir()).resolve() or not scratch.name.startswith('runflow-selfcheck-'):
            raise ValueError('Unexpected cleanup target')
        shutil.rmtree(scratch)
    print('SURFACE_CHECK_DONE',result['complete'],result['intersection_free'],reason,flush=True)
    return 0 if success else 2


def binary_stl(folder,path):
    import numpy as np
    sys.path.insert(0,str(REPO/'src'))
    from runflow.shape_audit import load_surface,file_sha
    v,f=load_surface(folder)
    dtype=np.dtype([('normal','<f4',3),('corners','<f4',(3,3)),('attribute','<u2')])
    if dtype.itemsize!=50 or len(f)>=2**32: raise ValueError('Unsupported binary STL')
    maximum=0.
    with path.open('xb') as stream:
        stream.write(b'RunFlow PRIVATE independent surface validation'.ljust(80,b' ')); stream.write(struct.pack('<I',len(f)))
        for i in range(0,len(f),100000):
            corners=np.asarray(v)[f[i:i+100000]]; block=np.zeros(len(corners),dtype=dtype); block['corners']=corners
            maximum=max(maximum,float(np.linalg.norm(corners.astype(float)-block['corners'].astype(float),axis=2).max(initial=0)))
            block.tofile(stream)
    if maximum>2e-6: raise ValueError('STL conversion exceeds numerical margin')
    return dict(surface_sha256=file_sha(path),candidate_cache_sha256=file_sha(Path(folder)/'cache.json'),
        triangles=len(f),maximum_corner_rounding_m=maximum,unit='m',format='binary STL, float32')


def windows_check(root,case,seconds,attempt,local_io=False):
    import psutil
    sys.path.insert(0,str(REPO/'src'))
    from runflow.shape_fullbody import LIMITS
    from runflow.shape_resources import system_resources,limit_reason
    folder=root/case/('selfcheck' if attempt==1 else 'selfcheck'+str(attempt)); folder.mkdir(exist_ok=False)
    start=time.monotonic(); record=binary_stl(root/case/'candidate',folder/'surface.stl')
    save(folder/'input.json',record); beat=folder/'heartbeat'; beat.touch()
    def linux(path):
        path=Path(path).resolve(); return '/mnt/'+path.drive[0].lower()+'/'+path.as_posix()[3:]
    budget=seconds-(time.monotonic()-start)-15
    if budget<=0: raise ValueError('Surface-check budget exhausted during export')
    command=['wsl','-d','Ubuntu','--','python3',linux(Path(__file__)),
             '--linux','--root',linux(folder),'--timeout',str(budget)]
    if local_io: command+=['--local-io']
    reason=None
    with (folder/'launcher.log').open('wb') as stream:
        process=subprocess.Popen(command,stdout=stream,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        while process.poll() is None:
            beat.touch(); state=system_resources()
            state.update(private_commit_bytes=0,disk_free_bytes={d:psutil.disk_usage(d).free for d in LIMITS['disk_free_bytes']})
            # Binary export and Linux execution share this stage deadline. Linux has its own RSS/heartbeat guard.
            reason=limit_reason(state,LIMITS,time.monotonic()-start,seconds,record['triangles']*50+84)
            if reason:
                (folder/'stop').touch()
                try: process.wait(timeout=12)
                except subprocess.TimeoutExpired: process.terminate(); process.wait(timeout=3)
                break
            time.sleep(.5)
        code=process.wait()
    # The Linux side must confirm owned-child termination; Windows exit alone is insufficient.
    proof=folder/'linux-result.json'
    result=json.loads(proof.read_text()) if proof.exists() else dict(complete=False,intersection_free=None,termination_verified=False)
    if code!=0 or reason: result.update(complete=False,intersection_free=None)
    result.update(windows_returncode=code,windows_reason=reason,elapsed_s=time.monotonic()-start,input=record)
    save(folder/'result.json',result)
    metrics=root/case/'metrics'; metrics.mkdir(exist_ok=True)
    save(metrics/'self-intersections.json',result)
    print('INDEPENDENT_SELF_CHECK',case,result['complete'],result['intersection_free'],result['termination_verified'],flush=True)
    return 0 if result['termination_verified'] else 2


def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True); p.add_argument('--case')
    p.add_argument('--linux',action='store_true'); p.add_argument('--timeout',type=float,default=600)
    p.add_argument('--attempt',type=int,choices=[1,2,3],default=1)
    p.add_argument('--local-io',action='store_true'); a=p.parse_args()
    if a.linux: return linux_check(a.root,a.timeout,a.local_io)
    root=a.root.resolve()
    if not any(root.is_relative_to(x.resolve()) for x in [REPO/'private',Path('E:/RunFlowPrivate')]): raise ValueError('Private root required')
    if not a.case or (root/a.case).resolve().parent!=root: raise ValueError('Single private case required')
    state=json.loads((root/'execution.json').read_text())
    from datetime import datetime
    left=datetime.fromisoformat(state['comparison_started']).timestamp()+43200-time.time()
    if left<=0: raise ValueError('Original study deadline exhausted')
    return windows_check(root,a.case,min(a.timeout,left),a.attempt,a.local_io)


if __name__=='__main__': raise SystemExit(main())
