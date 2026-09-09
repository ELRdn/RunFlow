"""Nested phase schedules and complete-cycle aggregates; no missing-pose means."""
import math


def nested_indices(count):
    if count not in (8,16,32):raise ValueError('Only planned 8/16/32 schedules are supported')
    return list(range(0,32,32//count))


def aggregate(rows, count):
    expected=nested_indices(count)
    by_index={row['phase_index']:row for row in rows}
    if len(by_index)!=len(rows):raise ValueError('Duplicate phase result')
    missing=[i for i in expected if i not in by_index or by_index[i].get('execution_status')!='PASS']
    if missing:
        return dict(status='INCOMPLETE',samples=count,missing_or_failed=missing,mean_drag_N=None,mean_CdA_m2=None,
                    effective_Cd=None,mean_area_m2=None,scientific_approval=None,ranking_eligible=False)
    selected=[by_index[i] for i in expected]
    families={row['comparison_family_sha256'] for row in selected}
    if len(families)!=1:raise ValueError('Cycle cannot mix numerical/physical protocols')
    for row in selected:
        for key in ('drag_N','CdA_m2','source_area_m2'):
            value=row[key]
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
                raise ValueError('Finite positive cycle data required')
    drag=math.fsum(row['drag_N'] for row in selected)/count
    cda=math.fsum(row['CdA_m2'] for row in selected)/count
    area=math.fsum(row['source_area_m2'] for row in selected)/count
    return dict(status='COMPLETE_NUMERICAL_ONLY',samples=count,missing_or_failed=[],mean_drag_N=drag,
        mean_CdA_m2=cda,mean_area_m2=area,effective_Cd=cda/area,
        Cd_definition='mean_CdA / mean_original_area; not the mean of per-pose Cd',
        endpoint_excluded=True,weights=[1/count]*count,phase_indices=expected,
        scientific_approval=None,ranking_eligible=False)


def sampling_comparison(rows):
    values={str(n):aggregate(rows,n) for n in (8,16,32)}
    differences={}
    for small,large in ((8,16),(16,32)):
        a,b=values[str(small)],values[str(large)]
        differences[f'{small}_vs_{large}']=(abs(a['mean_CdA_m2']/b['mean_CdA_m2']-1)
            if a['mean_CdA_m2'] is not None and b['mean_CdA_m2'] is not None else None)
    return dict(aggregates=values,relative_CdA_differences=differences,working_target_rel=.02,
        numerical_target_met=all(v is not None and v<=.02 for v in differences.values()),
        scientific_approval=None,ranking_eligible=False)
