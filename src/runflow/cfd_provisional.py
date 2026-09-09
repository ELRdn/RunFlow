"""Explicitly authorized provisional geometry, using the existing bounded CFD path."""
from datetime import datetime,timezone
from pathlib import Path
import shutil
import sys
import time
import subprocess
from jsonschema import Draft202012Validator
from .core import read,write,file_hash,digest,canonical,validate_manifest
from .contracts import obj,HASH,TEXT,validate as validate_phase0,PARTS
from .cfd_contracts import validate,PROVISIONAL_VERSION,fixed
from . import cfd

AUTHORIZATION=obj({'decision':fixed('MEASURE_CURRENT_GEOMETRY_BEFORE_FURTHER_FIDELITY_WORK'),
    'actor':fixed('user'),'instruction':TEXT,'candidate_cache_sha256':HASH,'source_snapshot_sha256':HASH,
    'scope':fixed('ONE_POSE_20M_S_PROVISIONAL_CFD'),
    'scientific_approval':fixed(None),'required_parts_new_review':fixed(None),
    'fidelity_gate':fixed('DEFERRED_BY_USER_FOR_PROVISIONAL_MEASUREMENT')})
RECEIPT=obj({'schema_version':fixed('provisional-input-1'),'study_path':TEXT,'study_ledger_sha256':HASH,
    'candidate':{'type':'string','pattern':'^[a-zA-Z0-9_-]+$'},'candidate_cache_sha256':HASH,
    'asset_root':TEXT,'adoption_manifest_sha256':HASH,'source_snapshot_sha256':HASH,'authorization':AUTHORIZATION})


def verify_authorization(receipt):
    canonical(receipt)
    errors=list(Draft202012Validator(RECEIPT).iter_errors(receipt))
    if errors:raise ValueError('Invalid provisional receipt: '+errors[0].message)
    a=receipt['authorization']
    if a['candidate_cache_sha256']!=receipt['candidate_cache_sha256'] or a['source_snapshot_sha256']!=receipt['source_snapshot_sha256']:
        raise ValueError('Authorization is for a different surface/input')


def receipt_identity(receipt):
    verify_authorization(receipt)
    return digest({k:v for k,v in receipt.items() if k not in ('study_path','asset_root')})


def study_inputs(receipt):
    from .shape_fullbody import private_root
    verify_authorization(receipt)
    study=private_root(receipt['study_path'],cfd.REPO,existing=True)
    if file_hash(study/'artifact-sha256.json')!=receipt['study_ledger_sha256']:raise ValueError('Study ledger changed')
    ledger=read(study/'artifact-sha256.json')['files']
    candidate=receipt['candidate'];relative='candidates/'+candidate+'/candidate'
    def checked(name):
        if name not in ledger:raise ValueError('Missing study evidence: '+name)
        path=study/name
        if file_hash(path)!=ledger[name]['sha256'] or path.stat().st_size!=ledger[name]['bytes']:raise ValueError('Study evidence changed: '+name)
        return path
    files=['request.json','execution.json','review/summary.json','review/reproducibility.json',
        relative+'/cache.json',relative+'/vertices.npy',relative+'/triangles.npy',
        'verification/'+candidate+'/'+candidate+'/metrics/projection-front.json']
    paths={name:checked(name) for name in files}
    if file_hash(paths[relative+'/cache.json'])!=receipt['candidate_cache_sha256']:raise ValueError('Candidate cache changed')
    if not read(paths['execution.json']).get('finished'):raise ValueError('Source campaign is not frozen')
    review=read(paths['review/summary.json'])
    if review['selected_for_detailed_measurement']!=candidate:raise ValueError('Wrong measured candidate')
    repro=read(paths['review/reproducibility.json'])
    if not all(repro.get(k) is True for k in ('complete','input_configuration_ids_match','arrays_sha256_match','generation_code_pins_match','tool_pins_match')):
        raise ValueError('Candidate reproduction incomplete')
    if read(paths['request.json'])['old_inputs']['source']['sha256']!=receipt['source_snapshot_sha256']:
        raise ValueError('Study original does not match adopted source')
    area=read(paths[files[-1]])
    if not area.get('complete') or area['axes']!=[1,2] or area['precision_grid_m']!=1e-9:raise ValueError('Original reference area is not established')
    return study/relative,area,review,{name:file_hash(path) for name,path in paths.items()}


def make_receipt(study_path,asset_root,instruction):
    study=Path(study_path).resolve();asset=cfd.private(asset_root)
    candidate=read(study/'review/summary.json')['selected_for_detailed_measurement']
    source=asset/'unity-a/runflow_capture_f0000.snapshot.json'
    cache_hash=file_hash(study/'candidates'/candidate/'candidate/cache.json')
    source_hash=file_hash(source)
    receipt=dict(schema_version='provisional-input-1',study_path=str(study),study_ledger_sha256=file_hash(study/'artifact-sha256.json'),
        candidate=candidate,candidate_cache_sha256=cache_hash,asset_root=str(asset),
        adoption_manifest_sha256=file_hash(asset/'configuration-final-002/manifest.json'),source_snapshot_sha256=source_hash,
        authorization=dict(decision='MEASURE_CURRENT_GEOMETRY_BEFORE_FURTHER_FIDELITY_WORK',actor='user',instruction=instruction,
            candidate_cache_sha256=cache_hash,source_snapshot_sha256=source_hash,scope='ONE_POSE_20M_S_PROVISIONAL_CFD',
            scientific_approval=None,required_parts_new_review=None,fidelity_gate='DEFERRED_BY_USER_FOR_PROVISIONAL_MEASUREMENT'))
    verify_authorization(receipt);return receipt


def prepare(receipt_path,protocol_path,output,distro='Ubuntu',reuse_proof=None,surface_qualification=None,numerics='motorbike-simplec',restart_from=None,wall_treatment='reference-switching'):
    from .cfd_numerics import description
    description(numerics)
    from .cfd_case import wall_record
    wall_record(wall_treatment)
    began=time.time();started=time.monotonic();root=cfd.private(output)
    if root.exists():raise ValueError('Fresh provisional CFD output required')
    protocol=read(protocol_path);validate('protocol',protocol)
    if protocol['schema_version']!=PROVISIONAL_VERSION:raise ValueError('Provisional protocol required')
    receipt=read(receipt_path);verify_authorization(receipt)
    if protocol.get('diagnostic_refinement',{}).get('source_snapshot_sha256',receipt['source_snapshot_sha256'])!=receipt['source_snapshot_sha256']:
        raise ValueError('Local fluid-grid diagnostic is for a different adopted snapshot')
    root.mkdir(parents=True);write(root/'protocol.json',protocol);write(root/'provisional-receipt.json',receipt)
    write(root/'state.json',dict(started_epoch=began,started_utc=datetime.fromtimestamp(began,timezone.utc).isoformat(),
        status='PREPARING',stage='geometry',distro=distro))
    evidence={}
    try:
        candidate,area,review,study_hashes=study_inputs(receipt)
        asset=cfd.private(receipt['asset_root']);manifest=asset/'configuration-final-002/manifest.json'
        source=asset/'unity-a/runflow_capture_f0000.snapshot.json'
        if file_hash(manifest)!=receipt['adoption_manifest_sha256'] or file_hash(source)!=receipt['source_snapshot_sha256']:
            raise ValueError('Adopted source changed')
        m=validate_manifest(read(manifest),asset)
        accepted=read(manifest.parent/'accepted-verification.json')
        if accepted['execution_status']!='PASS' or accepted['manifest_sha256']!=file_hash(manifest):raise ValueError('Adoption verification mismatch')
        expected=[a['sha256'] for a in m['assets'] if a['path']==source.relative_to(asset).as_posix()]
        if expected!=[file_hash(source)]:raise ValueError('Source frame not bound to adopted manifest')
        snapshot=read(source);validate_phase0('snapshot',snapshot)
        if set(snapshot['parts'])!=set(PARTS) or abs(snapshot['time_s']-m['gait']['start_s'])>1e-9:raise ValueError('Wrong adopted pose or missing source parts')
        shutil.copyfile(source,root/'source.snapshot.json');shutil.copyfile(manifest,root/'source-manifest.json')
        write(root/'fidelity-review.json',dict(original_gate=review['selected_gate'],authorization=receipt['authorization'],
            original_projection=area,original_visible=review['comparison']['current_visible'],
            scientific_status='UNVALIDATED_PROVISIONAL_GEOMETRY',ranking_eligible=False))
        write(root/'source-study-hashes.json',study_hashes)
        pins={}
        sources=[cfd.REPO/'scripts/cfd_worker.py',cfd.REPO/'scripts/cfd_surface_io.py',cfd.REPO/'scripts/cfd_report.py',cfd.REPO/'scripts/prepare_provisional_surface.py',
            cfd.REPO/'scripts/qualify_cfd_surface.py',cfd.REPO/'scripts/prepare_cfd_restart.py',
            cfd.REPO/'uv.lock',*sorted((cfd.REPO/'src/runflow').glob('cfd*.py')),
            cfd.REPO/'src/runflow/local_geometry.py',cfd.REPO/'src/runflow/shape_fullbody.py',cfd.REPO/'src/runflow/shape_audit.py',
            cfd.REPO/'.tools/local-geometry-6.2.1/build.json',cfd.REPO/'.tools/local-geometry-6.2.1/native-build/Release/runflow_inspect.exe']
        for path in sources:
            relative=path.relative_to(cfd.REPO);pins['repo:'+relative.as_posix()]=file_hash(path)
            if path.suffix!='.exe':
                dest=root/'tool-sources'/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,dest)
        write(root/'tool-pins.json',pins)
        command=[sys.executable,str(cfd.REPO/'scripts/prepare_provisional_surface.py'),
                 '--root',str(root),'--source',str(candidate)]
        if reuse_proof is not None:
            shutil.copyfile(reuse_proof,root/'surface-reuse-proof.json')
            command+=['--reuse-proof',str(root/'surface-reuse-proof.json')]
        evidence['surface']=cfd.guarded(root,command,'surface-prepare.log',cfd.remaining(root,'geometry',started))
        geometry=read(root/'geometry/geometry.json');evidence['geometry']=geometry
        delta=geometry['area_change_bound']['absolute_area_change_upper_m2'];nominal=area['candidate_m2'];reference=area['source_m2']
        bounds=[nominal-delta,nominal+delta]
        if bounds[0]<=0 or max(abs(x/reference-1) for x in bounds)>.01:raise ValueError('Projection area bound exceeds 1%')
        areas=dict(source_area_m2=reference,candidate_area_m2=nominal,candidate_area_bounds_m2=bounds,
            candidate_area_is_pre_cleanup_nominal=True,change_bound_m2=delta,source_area_reused_with_hash_verification=True)
        write(root/'areas.json',areas)
        if surface_qualification is None:
            cfd.worker(root,'surface',cfd.remaining(root,'geometry',started),distro)
            cfd.worker(root,'reference',cfd.remaining(root,'geometry',started),distro)
        else:
            cfd.worker(root,'reference',cfd.remaining(root,'geometry',started),distro)
            evidence['exact_qualification']=cfd.guarded(root,[sys.executable,str(cfd.REPO/'scripts/qualify_cfd_surface.py'),
                '--qualification',str(surface_qualification),'--root',str(root)],'qualification.log',cfd.remaining(root,'geometry',started))
        from .cfd_case import build
        case=root/'case';(case/'constant/geometry').mkdir(parents=True,exist_ok=True)
        shutil.copyfile(root/'geometry/candidate.obj',case/'constant/geometry/oguri.obj')
        upstream=read(root/'upstream.json');design=build(case,snapshot,protocol,upstream,numerics=numerics,wall_treatment=wall_treatment);write(root/'case-design.json',design)
        if restart_from is not None:
            evidence['restart']=cfd.guarded(root,[sys.executable,str(cfd.REPO/'scripts/prepare_cfd_restart.py'),
                '--source',str(cfd.private(restart_from)),'--root',str(root)],'restart-copy.log',cfd.remaining(root,'geometry',started))
        tools=dict(pins);tools.update({'upstream:'+k:v for k,v in upstream['hashes'].items()})
        tools.update({'binary:'+k:v['sha256'] for k,v in upstream['binaries'].items()})
        tools.update({'case:'+p.relative_to(case).as_posix():file_hash(p) for p in case.rglob('*') if p.is_file()})
        for name in ('geometry/geometry.json','geometry/quality-after.json','geometry/intersections.json','geometry/topology.json',
                     'areas.json','fidelity-review.json','source-study-hashes.json','case-design.json'):
            tools['run:'+name]=file_hash(root/name)
        if (root/'surface-qualification.json').exists():tools['run:surface-qualification.json']=file_hash(root/'surface-qualification.json')
        if (root/'restart.json').exists():tools['run:restart.json']=file_hash(root/'restart.json')
        # Logs and runtime locations are checked for integrity separately; their
        # timestamps and absolute paths must not change the experiment identity.
        runtime_names=['provisional-receipt.json','surface-worker.json','surfaceCheck.log','surface-io.json',
                       'surface-diagnostics.tar','surface-scratch.json','surface-reuse-proof.json','geometry-reuse.json','surface-qualification-reuse.json',
                       'restart-runtime.json','snappyHexMesh.log']
        write(root/'runtime-evidence-hashes.json',{name:file_hash(root/name) for name in runtime_names if (root/name).exists()})
        config=dict(source_snapshot_sha256=file_hash(source),source_manifest_sha256=file_hash(manifest),surface_sha256=file_hash(root/'geometry/candidate.obj'),
            protocol=protocol,frame_time_s=snapshot['time_s'],clip_phase_s=.5894131075056082,source_area_m2=reference,repaired_area_m2=nominal,
            repaired_area_bounds_m2=bounds,source_bbox=design['source_bbox'],tool_hashes=tools,
            provisional_authorization_sha256=digest(receipt['authorization']),input_receipt_sha256=receipt_identity(receipt),
            fidelity_status=receipt['authorization']['fidelity_gate'])
        sha=digest(config);experiment=dict(schema_version=PROVISIONAL_VERSION,experiment_id='rf-p1p-'+sha,config_sha256=sha,config=config)
        validate('experiment',experiment);write(root/'experiment.json',experiment)
        if cfd.remaining(root,'geometry',started)<=0:raise ValueError('geometry stage timeout')
        return cfd.result(root,'PREPARED','geometry','Provisional fidelity explicitly authorized; numerical surface checks passed',evidence)
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:
        return cfd.result(root,'TIMEOUT' if 'timeout' in str(exc) else 'FAIL','geometry',str(exc),evidence)
