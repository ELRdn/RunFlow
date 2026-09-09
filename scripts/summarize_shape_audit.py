"""Join completed audit evidence without changing CFD admission or human decisions."""
import argparse
import json
from pathlib import Path
import shutil
from runflow.shape_audit import file_sha
from runflow.core import digest


def read(path): return json.loads(path.read_text(encoding='utf-8'))


def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True); args=p.parse_args()
    root=args.root; request=read(root/'request.json'); projection=read(root/'projections.json')
    if not projection['complete']:
        values=dict(projection['views']); stages={k:'projection (completed view before later failure)' for k in values}
        for view in ('front','side','top'):
            if view in values: continue
            part=read(root/('projection-'+view+'.json'))
            if not part['complete']: raise ValueError('Incomplete '+view+' projection')
            values.update(part['views']); stages[view]='projection-'+view
        if set(values)!={'front','side','top'}: raise ValueError('Projection views incomplete')
        archive=root/'projection-ungridded-partial.json'
        if not archive.exists(): shutil.copyfile(root/'projections.json',archive)
        projection=dict(views=values,complete=True,stages=stages,
            note='Front retained from completed ungridded substage; side/top explicitly use 1nm 2D precision. Failed logs retained.')
        (root/'projections.json').write_text(json.dumps(projection,indent=2),encoding='utf-8')
    distances={key:read(root/(key+'.json')) for key in ('source-to-candidate','candidate-to-source')}
    if not all(d['complete'] for d in distances.values()): raise ValueError('Distance coverage incomplete')
    external=read(root/'external-distances.json'); views=read(root/'views.json'); sections=read(root/'sections.json')
    if not views['complete'] or not sections['complete']: raise ValueError('Visual evidence incomplete')
    for item in request['inputs'].values():
        if file_sha(item['path'])!=item['sha256']: raise ValueError('Original audit input changed')
    evidence_files=['projections.json','source-to-candidate.json','candidate-to-source.json',
        'external-distances.json','views.json','sections.json','witness-visibility.json',
        'source-components.json','cache-integrity-verification.json']
    if (root/'part-review.json').exists(): evidence_files.append('part-review.json')
    identity=dict(input_sha256={k:v['sha256'] for k,v in request['inputs'].items()},
        distance_cover_m=request['distance_cover_m'],view_ray_step_m=.002,
        evidence_sha256={name:file_sha(root/name) for name in evidence_files},
        code_pin_records={p.name:file_sha(p) for p in root.glob('*.tool-pins.json')})
    resources={p.name:read(p) for p in root.glob('*.execution.json')}
    summary=dict(schema_version='shape-audit-1',audit_id='rf-shape-'+digest(identity),identity=identity,
        diagnostic_status='COMPLETE',scientific_status='DIAGNOSTIC_ONLY',human_adoption=None,
        ranking_eligible=False,cfd_admission='UNCHANGED_BLOCKED',drag_N=None,Cd=None,CdA_m2=None,
        distances=distances,projections=projection,external_surface_samples=external,
        part_review=read(root/'part-review.json') if (root/'part-review.json').exists() else None,
        resources={name:{k:r[k] for k in ('elapsed_s','peak_rss_bytes','peak_output_bytes','returncode','reason','termination_verified')} for name,r in resources.items()})
    (root/'audit-summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print('SHAPE_AUDIT_COMPLETE',summary['audit_id'],flush=True)


if __name__=='__main__': main()
