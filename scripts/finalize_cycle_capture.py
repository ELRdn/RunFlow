"""Bind 32 directly captured phases to the adopted 16, keeping old manifests intact."""
import argparse
from pathlib import Path
import shutil
import sys
REPO=Path(__file__).resolve().parents[1];sys.path.insert(0,str(REPO/'src'))
from runflow.core import read,write,file_hash,digest,validate_manifest
from runflow.gait_cycle import nested_indices
from compare_direct_capture import frames,verify_inputs
from accepted_capture import verify_timing,verify_game_version


def intake_equivalence(root,reference):
    """New intake evidence; never relabel a changed metadata database as identical."""
    a=read(root/'inputs-0.json');b=read(reference/'inputs-0.json')
    verify_game_version(b)
    if any(a[key]!=b[key] for key in ('master_sha256','assets')):
        raise ValueError('Materialized game inputs changed; source equivalence unavailable')
    records=('inventory-0.json','transforms-0.json','adoption-input.json')
    matched={name:file_hash(root/name)==file_hash(reference/name) for name in records}
    if not all(matched.values()):raise ValueError('Runtime model, scale, or adoption conditions changed')
    return dict(schema_version='phase1-cycle-intake-equivalence-1',
        previous_meta_sha256=b['meta_sha256'],captured_meta_sha256=a['meta_sha256'],
        metadata_database_identical=a['meta_sha256']==b['meta_sha256'],
        master_database_identical=True,materialized_assets_identical=True,asset_count=len(a['assets']),
        matched_runtime_records=matched,
        scope='The same archived materialized model/motion inputs and runtime settings; not whole-database equivalence',
        metadata_change_cause='UNVERIFIED',current_client_build='UNVERIFIED',
        scientific_approval=None,human_review=None)


def finalize(root,reference,binding='cycle'):
    root=root.resolve();reference=reference.resolve()
    if not all(p.is_relative_to(REPO/'private') for p in (root,reference)):
        raise ValueError('Private capture paths required')
    if Path(binding).name!=binding or not binding.startswith('cycle'):raise ValueError('Local cycle binding name required')
    output=root/binding;output.mkdir(exist_ok=False)
    completion=read(root/'completed.json');comparison=read(root/'comparison.json')
    if completion.get('samples_per_run')!=32 or not completion.get('research_conditions_adopted') or comparison['execution_status']!='PASS':
        raise ValueError('32 directly captured and compared phases required')
    verification=verify_inputs(root);inputs=read(root/'inputs-0.json');old_inputs=read(reference/'inputs-0.json')
    intake=intake_equivalence(root,reference)
    write(output/'intake-equivalence.json',intake)
    old_manifest=reference/'configuration-final-002/manifest.json'
    validate_manifest(read(old_manifest),reference)
    old_accepted=read(old_manifest.parent/'accepted-verification.json')
    if old_accepted['execution_status']!='PASS' or old_accepted['manifest_sha256']!=file_hash(old_manifest):
        raise ValueError('Adopted source manifest is not verified')
    if read(root/'adoption-input.json')!=read(reference/'adoption-input.json'):
        raise ValueError('Phase/scale/parts decision changed')
    paths,values=frames(root/'unity-a',32);repeat_paths,repeat=frames(root/'unity-b',32)
    previous_paths,previous=frames(reference/'unity-a',16)
    provenance=[read(path.with_name(path.name.replace('.snapshot.json','.provenance.json'))) for path in paths]
    phase=read(root/'adoption-input.json')['decision']['phase']['phase_s']
    errors,dt,stride,warmup=verify_timing(values,provenance,phase)
    if stride!=8 or warmup!=1280:raise ValueError('Dense schedule changed fixed stepping/warmup')
    same=[file_hash(paths[2*i])==file_hash(previous_paths[i]) for i in range(16)]
    duplicate=[file_hash(a)==file_hash(b) for a,b in zip(paths,repeat_paths)]
    evidence=dict(all_32_repeat_identical=all(duplicate),all_16_even_snapshots_identical=all(same),
                  repeated_by_phase=duplicate,adopted_even_by_phase=same,max_animator_time_error_s=max(errors),
                  simulation_dt_s=dt,steps_per_sample=stride,warmup_steps=warmup)
    write(output/'verification.json',evidence)
    if not all(same) or not all(duplicate):raise ValueError('Dense capture differs from adopted poses or repeated capture')
    records=[]
    for i,path in enumerate(paths):
        records.append(dict(index=i,phase_fraction=i/32,time_s=values[i]['time_s'],weight=1/32,
            snapshot=path.relative_to(root).as_posix(),sha256=file_hash(path),
            repeat_sha256=file_hash(repeat_paths[i]),source_area_pending=True))
    pins={}
    for relative in ['scripts/finalize_cycle_capture.py','scripts/compare_direct_capture.py','scripts/accepted_capture.py',
                     'src/runflow/gait_cycle.py',*('integrations/unity/'+item['name'] for item in inputs['capture_scripts'])]:
        source=REPO/relative;sha=file_hash(source)
        if relative.startswith('integrations/unity/'):
            expected=next(item['sha256'] for item in inputs['capture_scripts'] if item['name']==source.name)
            if sha!=expected:raise ValueError('Capture source changed since Unity ran')
        target=output/'processing-sources'/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target);pins[relative]=sha
    config=dict(schema_version='phase1-cycle-input-1',character_id='1006',costume_id='100602',
        source_manifest_sha256=file_hash(old_manifest),adoption_input_sha256=file_hash(root/'adoption-input.json'),
        comparison_sha256=file_hash(root/'comparison.json'),input_record_sha256=verification['input_record_sha256'],
        intake_equivalence_sha256=file_hash(output/'intake-equivalence.json'),
        whole_metadata_database_identical=intake['metadata_database_identical'],
        frames=records,schedules={str(n):nested_indices(n) for n in (8,16,32)},endpoint_excluded=True,
        source_period_s=32*stride*dt,simulation_dt_s=dt,processing_hashes=pins,
        newly_reviewed_parts=None,scientific_approval=None,ranking_eligible=False,
        geometry_fidelity='CFD surfaces are not yet generated/qualified for all phases')
    write(output/'manifest.json',dict(config=config,config_sha256=digest(config),execution_status='PASS'))
    print('PASS: 32 phases twice; even phases exactly match adopted 16; no CFD acceptance')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--reference',type=Path,required=True)
    p.add_argument('--binding',default='cycle')
    a=p.parse_args();finalize(a.root,a.reference,a.binding)
