import importlib.util
from pathlib import Path
import numpy as np
import pytest
from runflow.shape_fullbody import read, write


def _mod():
    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('final_review', repo / 'scripts' / 'finalize_fullbody_review.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _case(voxel_um):
    return 'v' + str(voxel_um)


def _grid():
    step = .002
    extent = [float(0), float(1), float(0), float(1)]
    return {
        'front+': dict(axis=0, axes=[1, 2], sign=1, step_m=step, extent_m=list(extent)),
        'side+': dict(axis=1, axes=[0, 2], sign=1, step_m=step, extent_m=list(extent)),
        'top+': dict(axis=2, axes=[0, 1], sign=1, step_m=step, extent_m=list(extent)),
    }


def _depth_array(fill):
    arr = np.full((4, 4), float(fill), dtype=np.float32)
    arr[0, 0] = np.nan
    return arr


def _write_metrics(metrics_dir, grid, complete=True, render_complete=False):
    metrics_dir.mkdir(parents=True, exist_ok=True)
    write(metrics_dir / 'views.json', dict(complete=complete, views=dict(grid)))
    for key in grid:
        np.save(metrics_dir / (key + '-depth.npy'), _depth_array(2))
    write(metrics_dir / 'render.json', dict(complete=render_complete, camera_up_axis='Y'))


def _result_entry(grid, generation=True, measurement=True, reasons=None, render_complete=False):
    metrics = {}
    metrics['views'] = dict(complete=measurement, views=dict(grid)) if measurement else dict(complete=False, views={})
    metrics['render'] = dict(complete=render_complete) if render_complete else None
    for view in ('front', 'side', 'top'):
        if measurement:
            metrics['projection-' + view] = dict(complete=True, relative_change=float(0), lost_m2=float(0), added_m2=float(0), original_holes=[])
        else:
            metrics['projection-' + view] = None
    if measurement:
        metrics['forward'] = dict(complete=True, area_weighted_mean_m=float(0), global_max_lower_m=float(0), global_max_upper_m=float(0), area_weighted_quantiles_m={'0.5': float(0), '0.95': float(0), '0.99': float(0)})
        metrics['reverse'] = dict(complete=True, area_weighted_mean_m=float(0), global_max_lower_m=float(0), global_max_upper_m=float(0), area_weighted_quantiles_m={'0.5': float(0), '0.95': float(0), '0.99': float(0)})
        metrics['topology'] = dict(boundary_edges=0, nonmanifold_edges=0, inconsistent_edges=0, degenerate_faces=0, edge_checks_complete=True)
    else:
        metrics['forward'] = None
        metrics['reverse'] = None
        metrics['topology'] = None
    return dict(generation_complete=generation, measurement_complete=measurement, metrics=metrics, reasons=list(reasons or []), elapsed_s=float(60), peak_rss_bytes=1024 ** 3, peak_private_commit_bytes=1024 ** 3, runs=[])
def _build_root(tmp_path, voxels, with_refs=True, mismatch_case=None):
    grid = _grid()
    root = Path(tmp_path) / 'study'
    root.mkdir()
    voxels_sorted = sorted(list(voxels), reverse=True)
    ref_specs = []
    if with_refs:
        for vu, lab in ((1000, 'pre 1 mm'), (500, 'pre half mm')):
            folder = 'references' + '/' + _case(vu)
            ref_specs.append(dict(voxel_um=vu, label=lab, folder=folder))
    write(root / 'request.json', dict(kind='fullbody_voxel_comparison_v1', voxel_sizes_um=list(voxels_sorted), regions=[], reference_cases=ref_specs))
    results = {}
    for vu in voxels_sorted:
        if vu == 900:
            reasons = ['stage timeout']
            entry = _result_entry(grid, generation=False, measurement=False, reasons=reasons, render_complete=False)
        elif vu == 800:
            reasons = ['generation not complete']
            entry = _result_entry(grid, generation=True, measurement=False, reasons=reasons, render_complete=False)
        else:
            entry = _result_entry(grid, generation=True, measurement=True, reasons=[], render_complete=False)
        if mismatch_case is not None and vu == mismatch_case:
            bad = dict(grid)
            bad['front+'] = dict(bad['front+'])
            bad['front+']['step_m'] = float(9)
            entry['metrics']['views'] = dict(complete=True, views=bad)
        results[_case(vu)] = entry
        metrics_dir = root / _case(vu) / 'metrics'
        if mismatch_case is not None and vu == mismatch_case:
            _write_metrics(metrics_dir, bad, complete=True, render_complete=False)
        else:
            ok = entry['metrics']['views'].get('complete', False)
            _write_metrics(metrics_dir, grid, complete=bool(ok), render_complete=False)
        cand = root / _case(vu) / 'candidate'
        cand.mkdir(parents=True, exist_ok=True)
        write(cand / 'cache.json', dict(vertices=10, triangles=8, bbox_m=[[0, 0, 0], [1, 1, 1]]))
    write(root / 'study-summary.json', dict(study_id='synthetic', results=results, comparison_complete=False))
    write(root / 'source-metrics' / 'views.json', dict(complete=True, views=dict(grid)))
    src_metrics = root / 'source-metrics'
    src_metrics.mkdir(parents=True, exist_ok=True)
    write(src_metrics / 'views.json', dict(complete=True, views=dict(grid)))
    for key in grid:
        np.save(src_metrics / (key + '-depth.npy'), _depth_array(1))
    write(root / 'view-bounds.json', dict(low_m=[0, 0, 0], high_m=[1, 1, 1]))
    write(root / 'source' / 'cache.json', dict(bbox_m=[[0, 0, 0], [1, 1, 1]]))
    if with_refs:
        for spec in ref_specs:
            ref_root = root / spec['folder']
            ref_metrics = ref_root / 'metrics'
            _write_metrics(ref_metrics, grid, complete=True, render_complete=False)
            write(ref_root / 'result.json', dict(generation_complete=True, measurement_complete=True, metrics=dict(views=dict(complete=True, views=dict(grid))), reasons=[], elapsed_s=float(60), peak_rss_bytes=1024 ** 3, peak_private_commit_bytes=1024 ** 3))
    return root, grid


def test_requested_display_order_refs_display_only(tmp_path):
    mod = _mod()
    assert mod.presentation_pixels is not None and mod.depth_change is not None
    root, grid = _build_root(tmp_path, [900, 800, 700, 600], with_refs=True)
    out = mod.create(root)
    folder = root / 'review-final'
    for name in ('comparison.png', 'hip-comparison.png', 'side-comparison.png', 'parts-comparison.png'):
        assert (folder / name).exists()
    text = (root / 'FINAL_REVIEW.md').read_text(encoding='utf-8')
    assert '参照' in text
    costs = read(folder / 'costs.json')
    assert sorted(costs.keys()) == sorted([_case(v) for v in (900, 800, 700, 600)])
    states = read(folder / 'condition-states.json')
    assert sorted(states.keys()) == sorted([_case(v) for v in (900, 800, 700, 600)])
    prov = read(folder / 'provenance.json')
    assert prov['new_cases_only_for_costs_and_completion'] is True
    assert len(prov['reference_provenance']) == 2
    assert all(r['display_only'] for r in prov['reference_provenance'])
    ext = read(folder / 'external-depth-summary.json')
    assert sorted(ext.keys()) == sorted([_case(v) for v in (700, 600)])
    order = [e['case'] for e in prov['display_order']]
    assert order[0] == 'source'
def test_grid_mismatch_raises(tmp_path):
    mod = _mod()
    root, grid = _build_root(tmp_path, [900, 800, 700, 600], with_refs=False, mismatch_case=900)
    with pytest.raises(ValueError, match='View parameters changed'):
        mod.create(root)


def test_derived_failure_messages(tmp_path):
    mod = _mod()
    root, grid = _build_root(tmp_path, [900, 800, 700, 600], with_refs=False)
    mod.create(root)
    text = (root / 'FINAL_REVIEW.md').read_text(encoding='utf-8')
    assert '時間切れ' in text
    assert '生成未完了' in text
    states = read(root / 'review-final' / 'condition-states.json')
    key900 = _case(900)
    assert states[key900]['raw_reasons'] == ['stage timeout']
    assert '時間切れ' in states[key900]['reason_summaries_ja'][0]
    key800 = _case(800)
    assert states[key800]['generation'] == 'COMPLETE'
    assert states[key800]['measurements'] == 'INCOMPLETE'


def test_fallback_and_fresh_requirement(tmp_path):
    mod = _mod()
    vals = mod._requested_voxels({})
    assert vals == [1000, 500, 250, 100]
    root, grid = _build_root(tmp_path, [900, 800, 700, 600], with_refs=False)
    mod.create(root)
    with pytest.raises(OSError):
        mod.create(root)


def test_precise_states_no_adoption_cfd(tmp_path):
    mod = _mod()
    root, grid = _build_root(tmp_path, [900, 800, 700, 600], with_refs=True)
    mod.create(root)
    states = read(root / 'review-final' / 'condition-states.json')
    for v in (700, 600):
        s = states[_case(v)]
        assert s['images'] == 'MEASURED_DEPTH_FALLBACK'
        assert s['human_review'] is None
        assert s['scientific_status'] == 'UNAPPROVED'
        assert s['ranking_eligible'] is False
        assert s['drag_N'] is None and s['Cd'] is None and s['CdA_m2'] is None
    for v in (900, 800):
        s = states[_case(v)]
        assert s['images'] == 'UNAVAILABLE'
    prov = read(root / 'review-final' / 'provenance.json')
    assert prov['scientific_status'] == 'UNAPPROVED'
    assert prov['drag_N'] is None and prov['human_adoption'] is None
    assert prov['ranking_eligible'] is False
    text = (root / 'FINAL_REVIEW.md').read_text(encoding='utf-8')
    assert 'null' in text
    assert 'UNAPPROVED' not in text or '未承認' in text or '承認' in text
