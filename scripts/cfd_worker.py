"""WSL process-group supervisor for generated RunFlow cases. Standard library only."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import sys
import time
import tempfile

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))


def save(path,value):
    temp=path.with_suffix('.tmp'); temp.write_text(json.dumps(value,sort_keys=True,allow_nan=False)); temp.replace(path)


def process_table():
    table={}
    for path in Path('/proc').glob('[0-9]*/stat'):
        try:
            parts=path.read_text().split(') ',1)[1].split()
            table[int(path.parent.name)]=dict(parent=int(parts[1]),state=parts[0],
                start=int(parts[19]),rss=int(parts[21])*os.sysconf('SC_PAGE_SIZE'))
        except (FileNotFoundError,ProcessLookupError,PermissionError): pass
    return table


def descendants(pid,known):
    table=process_table()
    owned={p for p,start in known.items() if p in table and table[p]['start']==start}
    if pid in table and (pid not in known or table[pid]['start']==known[pid]): owned.add(pid)
    while True:
        more={p for p,item in table.items() if item['parent'] in owned}-owned
        if not more: break
        owned.update(more)
    known.update({p:table[p]['start'] for p in owned})
    return {p:table[p] for p in owned if table[p]['state'] not in ('Z','X')}


def disk_bytes(root):
    total=0
    for p in root.rglob('*'):
        try:
            if p.is_file(): total+=p.stat().st_size
        except FileNotFoundError: pass
    return total


def kill_group(process,known):
    # MPI ranks may establish independent sessions; retain ancestry + start time
    # so reparented ranks are still covered without touching reused process IDs.
    for sig in (signal.SIGTERM,signal.SIGKILL):
        for pid in sorted(descendants(process.pid,known),key=lambda pid:pid==process.pid):
            try: os.kill(pid,sig)
            except ProcessLookupError: pass
        try: process.wait(timeout=2)
        except subprocess.TimeoutExpired: continue
    process.wait(timeout=5)
    deadline=time.monotonic()+2
    while descendants(process.pid,known) and time.monotonic()<deadline: time.sleep(.05)
    if descendants(process.pid,known): raise RuntimeError('MPI descendant termination unverified')
    return True


def flux_history(case):
    tables=[]
    for name in ('inletFlux','outletFlux'):
        files=list((case/'postProcessing'/name).rglob('*.dat'))
        if len(files)!=1: return []
        values={}
        for line in files[0].read_text().splitlines():
            if not line.strip() or line.lstrip().startswith('#'): continue
            cols=line.split()
            if len(cols)!=2: return []
            t,v=map(float,cols)
            if not math.isfinite(t) or not math.isfinite(v) or t in values: return []
            values[t]= -v if name=='inletFlux' else v
        tables.append(values)
    return [dict(iteration=t,inflow=tables[0][t],outflow=tables[1][t]) for t in sorted(tables[0].keys() & tables[1].keys())]


def evaluation(root):
    from runflow.cfd_metrics import read_forces,read_residuals,assess
    case=root/'case'; files=list((case/'postProcessing'/'forces').rglob('forces.dat'))
    if len(files)!=1: return dict(converged=False,reasons=['force history missing/ambiguous'])
    try:
        return assess(read_forces(files[0]),read_residuals(root/'foamRun.log'),flux_history(case))
    except (ValueError,IndexError,KeyError,OSError):
        return dict(converged=False,reasons=['incomplete live trace'])


def command(args,root,deadline,limits,log,monitor=False,cwd=None,extra_roots=()):
    start=time.monotonic(); peak=0; peak_disk=0; reason=None; stop_requested=False; known={}
    with (root/log).open('wb') as output:
        process=subprocess.Popen(args,cwd=cwd or root/'case',stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
        save(root/'worker-process.json',dict(pid=process.pid,pgid=process.pid,command=args))
        try:
            while process.poll() is None:
                peak=max(peak,sum(item['rss'] for item in descendants(process.pid,known).values()))
                peak_disk=max(peak_disk,disk_bytes(root)+sum(disk_bytes(p) for p in extra_roots))
                if (root/'cancel-request.txt').exists(): reason='supervisor cancellation'
                elif time.monotonic()>=deadline: reason='stage timeout'
                elif peak>limits['memory_bytes']: reason='memory limit'
                elif peak_disk>limits['output_bytes']: reason='output size limit'
                elif any(p.exists() and shutil.disk_usage(p).free<20*1024**3 for p in extra_roots): reason='Linux scratch disk reserve'
                if not reason:
                    from runflow.cfd_paths import reserve_reason
                    reason=reserve_reason(root)
                if reason:
                    kill_group(process,known); break
                if monitor and not stop_requested and evaluation(root)['converged']:
                    control=root/'case/system/controlDict'
                    text=control.read_text()
                    if text.count('stopAt endTime;')!=1:
                        reason='Unexpected runtime stop control'; kill_group(process,known); break
                    control.write_text(text.replace('stopAt endTime;','stopAt writeNow;'))
                    save(root/'stop-request.json',dict(reason='convergence criteria met',elapsed_s=time.monotonic()-start))
                    stop_requested=True
                time.sleep(.5)
        except BaseException:
            kill_group(process,known)
            raise
        code=process.wait()
        if descendants(process.pid,known):
            kill_group(process,known); reason=reason or 'Child survived command completion'
    peak_disk=max(peak_disk,disk_bytes(root)+sum(disk_bytes(p) for p in extra_roots))
    if not reason and time.monotonic()>=deadline: reason='stage timeout'
    if not reason and peak_disk>limits['output_bytes']: reason='output size limit'
    result=dict(command=args,returncode=code,elapsed_s=time.monotonic()-start,peak_rss_bytes=peak,
        peak_output_bytes=peak_disk,reason=reason,termination_verified=True)
    return result


def surface_command(root,deadline,limits):
    scratch=Path(tempfile.mkdtemp(prefix='runflow-cfd-surface-')).resolve()
    save(root/'surface-scratch.json',dict(path=str(scratch),owned=True,retained=True))
    args=[sys.executable,str(REPO/'scripts/cfd_surface_io.py'),
          '--source',str(root/'geometry/candidate.obj'),'--root',str(root),'--scratch',str(scratch)]
    try:
        return command(args,root,deadline,limits,'surface-io-launcher.log',cwd=scratch,extra_roots=(scratch,))
    finally:
        # An interrupted archive is not complete evidence. Keep its owned files
        # in place; never extend the expired budget to archive or delete them.
        save(root/'surface-scratch.json',dict(path=str(scratch),owned=True,retained=scratch.exists(),
             retained_bytes=disk_bytes(scratch)))


def labels(path):
    text=path.read_text(); text=text[text.index('}')+1:]
    uniform=re.search(r'(\d+)\s*\{\s*([+-]?\d+)\s*\}',text)
    if uniform: return [int(uniform[2])]*int(uniform[1])
    found=re.search(r'(\d+)\s*\(\s*([\s\d+-]*)\)',text)
    if not found: raise ValueError('Missing ASCII label list: '+str(path))
    result=[int(x) for x in found[2].split()]
    if len(result)!=int(found[1]): raise ValueError('Truncated label list')
    return result


def mesh_evidence(case,required_level):
    partitions=sorted(case.glob('processor[0-9]*'))
    cells=0; wall_faces=0; levels=[]
    for partition in partitions:
        p=partition/'constant/polyMesh'; owner=labels(p/'owner'); cell_level=labels(p/'cellLevel')
        cells+=len(cell_level)
        text=(p/'boundary').read_text()
        for match in re.finditer(r'(oguri\w*)\s*\{([^{}]+)\}',text):
            n=int(re.search(r'nFaces\s+(\d+)',match[2])[1]); start=int(re.search(r'startFace\s+(\d+)',match[2])[1])
            wall_faces+=n; levels.extend(cell_level[owner[i]] for i in range(start,start+n))
    return dict(cells=cells,body_faces=wall_faces,min_body_cell_level=min(levels) if levels else None,
        refinement_reached=bool(levels) and min(levels)>=required_level)


def reference(root):
    base=Path('/opt/openfoam14'); tutorial=base/'tutorials/incompressibleFluid/motorBikeSteady'
    files={}
    for name in ('system/fvSchemes','system/fvSolution','system/snappyHexMeshDict','system/meshQualityDict','system/surfaceFeaturesDict','constant/momentumTransport','constant/physicalProperties','0/U.orig','0/p','0/k','0/omega','0/nut'):
        files['tutorial/'+name]=(tutorial/name).read_text()
    for name in ('caseDicts/mesh/generation/meshQualityDict','caseDicts/functions/forces/forces.cfg','caseDicts/functions/forces/forcesIncompressible.cfg'):
        files['etc/'+name]=(base/'etc'/name).read_text()
    wall_source='src/MomentumTransportModels/momentumTransportModels/derivedFvPatchFields/wallFunctions/omegaWallFunctions/omegaWallFunction/omegaWallFunctionFvPatchScalarField.'
    for suffix in ('C','H'):
        name=wall_source+suffix;files[name]=(base/name).read_text()
    binaries={}
    for name in ('mpirun','blockMesh','surfaceFeatures','surfaceCheck','decomposePar','snappyHexMesh','checkMesh','foamRun','foamToVTK'):
        path=Path(shutil.which(name)).resolve()
        binaries[name]=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    save(root/'upstream.json',dict(package_version='20260724',files=files,binaries=binaries,
        hashes={k:hashlib.sha256(v.encode()).hexdigest() for k,v in files.items()}))


def region_refinement_evidence(text,protocol):
    selection=re.findall(r'Selected for internal refinement\s*:\s*(\d+) cells',text)
    complete=bool(selection) and int(selection[-1])==0
    evidence=dict(remaining_internal_refinement_cells=int(selection[-1]) if selection else None,
        wake_refinement_reached=complete)
    if 'diagnostic_refinement' in protocol:
        level=protocol['diagnostic_refinement']['level']
        recognized=re.findall(r'Refinement level (\d+) for all cells inside coatTip\b',text)
        evidence.update(diagnostic_refinement_level=level,
            diagnostic_refinement_reached=complete and recognized==[str(level)])
    return evidence


def verify_upstream(root):
    archive=root/'upstream.json'
    if not archive.exists(): return
    saved=json.loads(archive.read_text())
    for key,sha in saved['hashes'].items():
        path=Path('/opt/openfoam14')/('tutorials/incompressibleFluid/motorBikeSteady/'+key[9:] if key.startswith('tutorial/') else key)
        if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:
            raise ValueError('Upstream reference changed: '+key)
    for name,item in saved.get('binaries',{}).items():
        path=Path(shutil.which(name)).resolve()
        if hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            raise ValueError('Runtime binary changed: '+name)


def solver_stage_commands(protocol, mpi):
    """Return the recorded initialization and steady-solver commands.

    Existing Phase 0/provisional protocols omit solver_initialization and
    therefore retain their original single foamRun command. Cycle protocols
    opt into the pinned motorBike-style potential-flow initialization.
    """
    commands=[]
    initialization=protocol.get('solver_initialization')
    if initialization is not None:
        if not isinstance(initialization,dict) or initialization.get('method')!='potentialFoam':
            raise ValueError('Unsupported solver initialization')
        if initialization.get('write_phi') is not False or initialization.get('write_pressure') is not False:
            raise ValueError('Cycle potentialFoam initialization flags are not pinned')
        commands.append((mpi+['potentialFoam','-parallel'],'potentialFoam.log'))
    commands.append((mpi+['foamRun','-parallel'],'foamRun.log'))
    return commands


def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True)
    p.add_argument('--stage',choices=['reference','surface','mesh','solver','fields'],required=True)
    p.add_argument('--timeout',type=float,required=True); args=p.parse_args()
    root=args.root.resolve()
    from runflow.cfd_paths import is_private
    if not is_private(root) and not root.is_relative_to(REPO/'.cache'):
        raise ValueError('Private generated case required')
    protocol=json.loads((root/'protocol.json').read_text()); limits=protocol['limits']
    # CPU-only CFD: do not contact a stale WSL X server during hwloc GL discovery.
    # This affects this worker and its descendants only, not WSL/global settings.
    os.environ['HWLOC_COMPONENTS']='-gl'
    package=subprocess.check_output(['dpkg-query','-W','-f=${Version}','openfoam14'],text=True).strip()
    if package!='20260724' or os.environ.get('WM_PROJECT_VERSION')!='14': raise ValueError('Solver pin mismatch')
    deadline=time.monotonic()+args.timeout; records=[]; error=None
    (root/'case').mkdir(exist_ok=True)
    try:
        if args.stage=='reference': reference(root)
        else:
            verify_upstream(root)
            mpi=['mpirun','-np',str(limits['processes'])]
            stages={
                'surface':[(['surfaceCheck','-checkSelfIntersection',str(root/'geometry/candidate.obj')],'surfaceCheck.log')],
                'mesh':[(['blockMesh'],'blockMesh.log'),(['surfaceFeatures'],'surfaceFeatures.log'),
                    (['decomposePar','-copyZero'],'decomposePar.log'),
                    (mpi+['snappyHexMesh','-parallel','-overwrite'],'snappyHexMesh.log'),
                    (mpi+['checkMesh','-parallel'],'checkMesh.log')],
                'solver':solver_stage_commands(protocol,mpi),
                # Binary arrays avoid hundreds of thousands of tiny writes through
                # the WSL Windows-drive bridge. Plots use internal cell values only.
                'fields':[(mpi+['foamToVTK','-parallel','-latestTime','-noPointValues',
                    '-noLinks','-excludePatches','(".*")','-noFaceZones','-useTimeName','-fields','(U p)'],'foamToVTK.log')]
            }
            if args.stage=='mesh' and (root/'restart.json').exists():
                from runflow.cfd_restart import verify
                verify(root)
                stages['mesh']=[(mpi+['checkMesh','-parallel'],'checkMesh.log')]
            for cmd,log in stages[args.stage]:
                item=surface_command(root,deadline,limits) if args.stage=='surface' else command(cmd,root,deadline,limits,log,monitor=args.stage=='solver')
                records.append(item)
                if item['reason'] or item['returncode']!=0: raise ValueError(item['reason'] or 'command failed: '+log)
            if args.stage=='surface':
                text=(root/'surfaceCheck.log').read_text()
                if 'Surface is closed. All edges connected to two faces.' not in text or 'Surface is not self-intersecting' not in text:
                    raise ValueError('Surface closure/self-intersection success not confirmed')
            if args.stage=='mesh':
                text=(root/'checkMesh.log').read_text()
                evidence=mesh_evidence(root/'case',protocol['mesh']['surface_level'])
                evidence.update(region_refinement_evidence((root/'snappyHexMesh.log').read_text(),protocol))
                save(root/'mesh-evidence.json',evidence)
                if 'Mesh OK' not in text or re.search(r'Failed \d+ mesh checks',text): raise ValueError('Mesh quality failed')
                if not evidence['refinement_reached'] or not evidence['wake_refinement_reached'] or not evidence.get('diagnostic_refinement_reached',True) or evidence['cells']>protocol['mesh']['max_cells']:
                    raise ValueError('Mesh refinement/cell gate failed')
    except Exception as exc: error=str(exc)
    if args.stage=='solver':
        try: save(root/'flux-history.json',flux_history(root/'case'))
        except (OSError,ValueError) as exc:
            error=error or str(exc)
        if not error and (root/'restart.json').exists():
            try:
                from runflow.cfd_restart import initial_force_check
                save(root/'restart-initial-force-check.json',initial_force_check(root))
            except (OSError,ValueError) as exc:error=str(exc)
    record=dict(execution_status='FAIL' if error else 'PASS',error=error,commands=records)
    if args.stage=='mesh' and (root/'restart.json').exists():record['mode']='MESH_REUSED_AND_RECHECKED'
    save(root/(args.stage+'-worker.json'),record)
    if error: print(error,file=sys.stderr); return 2
    return 0


if __name__=='__main__': raise SystemExit(main())
