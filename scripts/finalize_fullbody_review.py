"""Create a reviewed presentation from completed measurements, preserving raw renders.

The initial HIP camera used local Z as up for front and side views and produced
a 180-degree roll. Correct only the figure display orientation. Geometry and
numeric evidence remain immutable. Original PNG files remain available.
New resolutions come from request voxel_sizes_um. Frozen references are
display-only and never enter costs, summary completion, or new measurements.
"""
import argparse
from pathlib import Path
import shutil
import time
import numpy as np
from runflow.shape_fullbody import read, write, study_profile
from runflow.shape_audit import file_sha


def presentation_pixels(pixels, view, render_info):
    legacy = render_info.get('camera_up_axis') != 'Y'
    return np.rot90(pixels, 2) if legacy and not view.startswith('top') else pixels


def depth_change(source, candidate, step_m):
    if source.shape != candidate.shape or not step_m > 0:
        raise ValueError('Common view grid required')
    a = np.isfinite(source)
    b = np.isfinite(candidate)
    common = a & b
    differences = np.abs(source[common].astype(float) - candidate[common].astype(float))
    return dict(source_covered_pixels=int(a.sum()), candidate_covered_pixels=int(b.sum()),
        lost_pixels=int((a & ~b).sum()), added_pixels=int((~a & b).sum()), common_pixels=int(common.sum()),
        step_m=step_m, lost_coverage_estimate_m2=float((a & ~b).sum() * step_m ** 2),
        added_coverage_estimate_m2=float((~a & b).sum() * step_m ** 2),
        common_first_hit_mean_abs_m=float(differences.mean()) if len(differences) else None,
        common_first_hit_p95_abs_m=float(np.quantile(differences, .95)) if len(differences) else None,
        common_first_hit_sampled_max_abs_m=float(differences.max()) if len(differences) else None,
        method='Sampled first-hit depth. May switch visible surfaces. Not nearest distance.')


def _requested_voxels(request):
    return list(study_profile(request)[0])


def _reason_to_ja(reason):
    if reason is None:
        return ''
    s = str(reason).strip()
    if not s:
        return ''
    low = s.lower()
    if 'physical' in low and 'reserve' in low:
        return '空きメモリ条件で停止'
    if 'private commit' in low:
        return 'コミット上限で停止'
    if 'system commit' in low:
        return 'システムコミット余裕不足で停止'
    if 'output size' in low:
        return '出力容量上限で停止'
    if low.startswith('disk reserve'):
        return 'ディスク空き不足で停止'
    if s == 'stage timeout':
        return '時間切れで停止'
    if 'corner overflow' in low:
        return '予測コーナー数上限のため未実行'
    if 'predicted resource overrun' in low:
        return '粗い条件の停止を受けて予測停止'
    if s == 'generation not complete':
        return '生成未完了のため未計測'
    if s == 'common preparation failed':
        return '共通準備失敗のため未実行'
    if s == 'time allocation exhausted':
        return '割当時間切れのため未実行'
    if 'live descendants' in low:
        return '子プロセス残存のため停止'
    if low.startswith('guard failure'):
        return '監視異常で停止'
    if len(s) <= 60:
        return s
    return s[:57] + '...'


def _short_ja_list(reasons):
    out = []
    for r in (reasons or []):
        if r is None:
            continue
        ja = _reason_to_ja(r)
        if ja and ja not in out:
            out.append(ja)
    return out


def _resolve_reference(root, spec):
    folder_value = spec.get('folder')
    if not folder_value:
        raise ValueError('Reference case folder missing')
    relative = Path(folder_value)
    if relative.is_absolute() or '..' in relative.parts or not relative.parts or relative.parts[0] != 'references':
        raise ValueError('Reference folder must stay under references/')
    ref_root = root / relative
    voxel_um = int(spec.get('voxel_um'))
    raw_label = spec.get('label')
    if raw_label:
        label = str(raw_label)
    else:
        label = ('%g mm' % (voxel_um / 1000.0))
    metrics_dir = ref_root / 'metrics'
    try:
        is_dir = metrics_dir.is_dir()
    except OSError:
        is_dir = False
    if not is_dir:
        metrics_dir = ref_root
    views_path = metrics_dir / 'views.json'
    render_path = metrics_dir / 'render.json'
    views_data = read(views_path) if views_path.exists() else None
    render_data = read(render_path) if render_path.exists() else None
    result_data = None
    for candidate in (ref_root / 'result.json', metrics_dir / 'result.json'):
        try:
            exists = candidate.exists()
        except OSError:
            exists = False
        if exists:
            result_data = read(candidate)
            break
    return dict(voxel_um=voxel_um, label=label, ref_root=ref_root,
        metrics_dir=metrics_dir, views=views_data, render=render_data, result=result_data)


def _views_complete(metrics_or_views):
    if not metrics_or_views:
        return False
    target = metrics_or_views.get('views', metrics_or_views) if isinstance(metrics_or_views, dict) else None
    if target is None:
        return False
    if isinstance(metrics_or_views, dict) and 'views' in metrics_or_views:
        return bool(metrics_or_views.get('complete'))
    if isinstance(metrics_or_views, dict) and 'complete' in metrics_or_views:
        return bool(metrics_or_views.get('complete'))
    return False


def _render_complete(render_info):
    return bool(render_info and render_info.get('complete'))


def _missing_text_new(result):
    if result is None:
        return '未生成'
    reasons = result.get('reasons') or []
    first_ja = ''
    for r in reasons:
        first_ja = _reason_to_ja(r)
        if first_ja:
            break
    metrics = result.get('metrics') or {}
    views = metrics.get('views')
    views_ok = bool(views and views.get('complete'))
    if not result.get('generation_complete'):
        base = '未生成'
    elif not views_ok:
        base = '計測未完了'
    else:
        base = '未描画'
    if first_ja and base != '未描画':
        return base + chr(10) + first_ja
    return base


def _image_state(metrics):
    if not metrics:
        return 'UNAVAILABLE'
    if _render_complete(metrics.get('render')):
        return 'HIP_COMPLETE'
    if _views_complete(metrics.get('views')):
        return 'MEASURED_DEPTH_FALLBACK'
    return 'UNAVAILABLE'


def _mm_label(voxel_um):
    return '%g mm' % (voxel_um / 1000.0)


def create(root, *, output_suffix=""):
    if output_suffix not in ("", "-verified"): raise ValueError("Unsupported review output suffix")
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['font.family'] = ['Yu Gothic', 'DejaVu Sans']
    root = Path(root)
    summary_path = root / ('study-summary'+output_suffix+'.json')
    summary = read(summary_path)
    request = read(root / 'request.json')
    folder = root / ('review-final'+output_suffix)
    folder.mkdir(exist_ok=False)
    voxels = _requested_voxels(request)
    ordered_voxels = sorted(voxels, reverse=True)
    regions = request.get('regions') or []
    ref_specs = request.get('reference_cases') or []
    source_dir = root / 'source-metrics'
    source_views = None
    source_views_path = source_dir / 'views.json'
    if source_views_path.exists():
        source_views = read(source_views_path)
    source_grid = None
    if source_views and source_views.get('complete'):
        source_grid = source_views.get('views')
    new_entries = []
    for voxel_um in ordered_voxels:
        case = 'v' + str(voxel_um)
        if case not in summary.get('results', {}):
            raise ValueError('Missing result for requested resolution: ' + case)
        result = summary['results'][case]
        metrics = result.get('metrics') or {}
        directory = root / case / 'metrics'
        views = metrics.get('views')
        if source_grid is not None and views and views.get('complete'):
            if views.get('views') != source_grid:
                raise ValueError('View parameters changed: ' + case)
        new_entries.append(dict(kind='new', case=case, voxel_um=voxel_um,
            name=_mm_label(voxel_um), directory=directory, result=result, metrics=metrics))
    ref_entries = []
    for spec in ref_specs:
        ref = _resolve_reference(root, spec)
        if source_grid is not None and ref['views'] and ref['views'].get('complete'):
            if ref['views'].get('views') != source_grid:
                raise ValueError('View parameters changed: reference ' + ref['label'])
        ref_entries.append(dict(kind='reference', case='ref' + str(ref['voxel_um']),
            voxel_um=ref['voxel_um'], name=ref['label'] + ' [参照]', directory=ref['metrics_dir'],
            result=ref['result'], metrics=dict(views=ref['views'], render=ref['render']), ref=ref))
    combined = sorted(new_entries + ref_entries, key=lambda e: (-int(e['voxel_um']), 0 if e['kind'] == 'new' else 1))
    display = [dict(kind='source', case='source', voxel_um=None, name='原本',
        directory=source_dir, result=None, metrics=dict(views=source_views))] + combined
    ncols = len(display)
    external = {}
    if source_grid is not None:
        for entry in new_entries:
            views = entry['metrics'].get('views')
            if not views or not views.get('complete'):
                continue
            case = entry['case']
            external[case] = {}
            for key, info in source_grid.items():
                if info != (views.get('views') or {}).get(key):
                    raise ValueError('View parameters changed: ' + case + '/' + key)
                src_path = source_dir / (key + '-depth.npy')
                dst_path = entry['directory'] / (key + '-depth.npy')
                external[case][key] = depth_change(np.load(src_path), np.load(dst_path), info['step_m'])
    write(folder / 'external-depth-summary.json', external)
    applied = []
    main_views = [('front+', '正面'), ('side+', '側面'), ('top+', '上面')]
    width = max(10.0, 3.4 * float(ncols) + 1.0)
    fig, axes = plt.subplots(3, ncols, figsize=(width, 11.0), layout='constrained', squeeze=False)
    for row, (view, label) in enumerate(main_views):
        for col, entry in enumerate(display):
            ax = axes[row][col]
            directory = entry['directory']
            render_path = directory / 'render.json'
            image_path = directory / (view + '-hip.png')
            ax.set_facecolor('#f3f5f7')
            shown = False
            if render_path.exists() and image_path.exists():
                try:
                    info = read(render_path)
                except OSError:
                    info = None
            else:
                info = None
            render_ok = False
            if entry['kind'] == 'source':
                render_ok = bool(info and info.get('complete'))
            elif entry['kind'] == 'new':
                render_ok = _render_complete((entry['result'].get('metrics') or {}).get('render')) and bool(info and info.get('complete'))
            else:
                render_ok = _render_complete(entry['metrics'].get('render')) and bool(info and info.get('complete'))
            if render_ok:
                pixels = plt.imread(image_path)
                ax.imshow(presentation_pixels(pixels, view, info))
                applied.append(dict(case=entry['case'], view=view, source_sha256=file_sha(image_path),
                    display_rotation_degrees=180 if info.get('camera_up_axis') != 'Y' and row < 2 else 0))
                shown = True
            if not shown:
                depth_path = directory / (view + '-depth.npy')
                depth_ok = False
                if entry['kind'] == 'source':
                    depth_ok = bool(source_views and source_views.get('complete')) and depth_path.exists()
                elif entry['kind'] == 'new':
                    depth_ok = _views_complete((entry['result'].get('metrics') or {}).get('views')) and depth_path.exists()
                else:
                    depth_ok = _views_complete(entry['metrics'].get('views')) and depth_path.exists()
                if depth_ok:
                    data = np.load(depth_path)
                    ax.imshow(np.where(np.isfinite(data), 1, np.nan), origin='lower', cmap='Blues', vmin=0, vmax=1)
                    ax.text(.5, .02, '深度図', ha='center', transform=ax.transAxes)
                else:
                    if entry['kind'] == 'new':
                        label_text = _missing_text_new(entry['result'])
                    elif entry['kind'] == 'reference':
                        label_text = '参照なし'
                    else:
                        label_text = '未描画'
                    ax.text(.5, .5, label_text, ha='center', va='center', transform=ax.transAxes)
            ax.set_title(entry['name'] + '｜' + label)
            ax.axis('off')
    if ref_entries:
        fig.suptitle('全身から生成した形状の比較｜原本：青、候補：黄褐色、[参照]は前回結果の表示のみ', fontsize=14)
    else:
        fig.suptitle('全身から生成した形状の比較｜原本：青、候補：黄褐色', fontsize=14)
    fig.savefig(folder / 'hip-comparison.png', dpi=170)
    plt.close(fig)


    from matplotlib.colors import LinearSegmentedColormap
    maps = [LinearSegmentedColormap.from_list('original', ['#173a50', '#8ac0d8']),
        LinearSegmentedColormap.from_list('candidate', ['#593916', '#e7bd73'])]
    bounds = read(root / 'view-bounds.json')
    low_list = bounds['low_m']
    high_list = bounds['high_m']
    step_text = ''
    if source_grid is not None and 'front+' in source_grid:
        step_value = source_grid['front+'].get('step_m')
        if step_value:
            step_text = '共通グリッド（正面+は' + ('%g' % (float(step_value) * 1000.0)) + 'mm間隔）'
    if not step_text:
        step_text = '共通グリッド'
    def draw_depth(ax, entry, view):
        info = (source_grid or {}).get(view) if source_grid else None
        path = entry['directory'] / (view + '-depth.npy')
        ok = False
        if info is not None and path.exists():
            if entry['kind'] == 'source':
                ok = bool(source_views and source_views.get('complete'))
            elif entry['kind'] == 'new':
                ok = _views_complete((entry['result'].get('metrics') or {}).get('views'))
            else:
                ok = _views_complete(entry['metrics'].get('views'))
        if ok:
            data = np.load(path)
            axis = int(info['axis'])
            ax.imshow(np.ma.masked_invalid(data), origin='lower', extent=info['extent_m'],
                interpolation='nearest', cmap=maps[0 if entry['kind'] == 'source' else 1],
                vmin=float(low_list[axis]), vmax=float(high_list[axis]))
        else:
            if entry['kind'] == 'new':
                label_text = _missing_text_new(entry['result'])
            elif entry['kind'] == 'reference':
                label_text = '参照なし'
            else:
                label_text = '未描画'
            ax.text(.5, .5, label_text, ha='center', va='center', transform=ax.transAxes)
        if info is not None:
            x0, x1, y0, y1 = info['extent_m']
            ax.set_xlim(x0, x1)
            ax.set_ylim(y0, y1)
        ax.set_aspect('equal')
        ax.axis('off')
    fig, axes = plt.subplots(3, ncols, figsize=(width, 12.0), layout='constrained', squeeze=False)
    for row, (view, label) in enumerate(main_views):
        for col, entry in enumerate(display):
            ax = axes[row][col]
            draw_depth(ax, entry, view)
            ax.set_title(entry['name'] + '｜' + label)
    fig.suptitle('全身比較｜' + step_text + 'の深度図。青：原本、黄褐色：候補、濃淡：奥行き', fontsize=13)
    fig.savefig(folder / 'comparison.png', dpi=170)
    plt.close(fig)
    fig, axes = plt.subplots(1, ncols, figsize=(max(10.0, 3.6 * float(ncols)), 6.0), layout='constrained', squeeze=False)
    for col, entry in enumerate(display):
        ax = axes[0][col]
        draw_depth(ax, entry, 'side+')
        ax.set_title(entry['name'])
    fig.suptitle('同じ視線・縮尺の深度図｜細い形状は元の拡大図・投影面積と併読', fontsize=13)
    fig.savefig(folder / 'side-comparison.png', dpi=180)
    plt.close(fig)
    windows = [('顔・頭部', (.02, .00, .35, .27)), ('耳', (.03, -.02, .32, .12)),
        ('髪', (.12, .02, .55, .42)), ('尻尾', (.40, .27, 1.02, .51)),
        ('衣装・胴体', (.18, .23, .68, .83)), ('手・腕', (-.03, .26, .57, .49)),
        ('脚・靴', (.05, .44, .83, 1.02))]
    windows_record = []
    cache_path = root / 'source' / 'cache.json'
    if source_grid is not None and cache_path.exists():
        cache_info = read(cache_path)
        low, high = cache_info['bbox_m']
        bbox_low = [float(v) for v in low]
        bbox_high = [float(v) for v in high]
        width_m = bbox_high[0] - bbox_low[0]
        height_m = bbox_high[2] - bbox_low[2]
        fig, axes = plt.subplots(len(windows), ncols, figsize=(max(10.0, 3.2 * float(ncols)), 3.0 * float(len(windows))), layout='constrained', squeeze=False)
        for row, (label, (left, top, right, bottom)) in enumerate(windows):
            box = [bbox_high[0] - right * width_m, bbox_high[0] - left * width_m, bbox_high[2] - bottom * height_m, bbox_high[2] - top * height_m]
            windows_record.append(dict(label=label, view='side+', world_XZ_bounds_m=box))
            for col, entry in enumerate(display):
                ax = axes[row][col]
                draw_depth(ax, entry, 'side+')
                ax.set_xlim(box[0], box[1])
                ax.set_ylim(box[2], box[3])
                ax.set_title(entry['name'] + '｜' + label)
                ax.axis('off')
        fig.suptitle('部位ごとの確認窓｜全身候補を生成した後の画像拡大。保持の自動認定ではない。', fontsize=13)
        fig.savefig(folder / 'parts-comparison.png', dpi=160)
        plt.close(fig)


    rows = ['# 全身ボクセル比較・最終レビュー', '']
    rows.append('同一の全身入力から生成した比較。元の姿勢・尺度を維持。CFDの実行・科学的承認・候補の採用はしていない。')
    rows.append('')
    if summary.get('comparison_complete'):
        rows.append(str(len(ordered_voxels)) + '条件すべての比較は完了。未取得の数値は推定で補わない。')
    else:
        rows.append(str(len(ordered_voxels)) + '条件すべての比較は未完了。未取得の数値は推定で補わない。')
    rows.append('')
    if ref_entries:
        rows.append('前回結果の参照表示を含む。参照は表示のみで、費用・完了判定・新規計測に含めない。')
        rows.append('')
    rows.append('主図は' + step_text + 'の深度図を共通軸・共通縮尺で並べた。青は原本、黄褐色は候補。')
    rows.append('')
    rows.append('![全身比較](review-final/comparison.png)')
    rows.append('')
    rows.append('| 解像度 | 候補生成 | 計測 | 正面面積差 | 側面面積差 | 上面面積差 |')
    rows.append('|---|---|---|---|---|---|')
    for voxel_um in ordered_voxels:
        case = 'v' + str(voxel_um)
        r = summary['results'][case]
        metrics = r.get('metrics') or {}
        values = []
        for view in ('front', 'side', 'top'):
            p = metrics.get('projection-' + view)
            if p and p.get('complete') and p.get('relative_change') is not None:
                values.append('%+.4f%%' % (float(p['relative_change']) * 100.0))
            else:
                values.append('未計測')
        gen_text = '完了（出力再検証）' if r.get('generation_checkpoint') else '完了' if r.get('generation_complete') else '未完了'
        meas_text = '完了' if r.get('measurement_complete') else '部分／未完了'
        rows.append('| ' + _mm_label(voxel_um) + ' | ' + gen_text + ' | ' + meas_text + ' | ' + ' | '.join(values) + ' |')
    if any(r.get('generation_checkpoint') for r in summary['results'].values()):
        rows += ['', '出力再検証の条件は、元の実行警告を保持した上で、生成完了記録・入力と出力SHA・子プロセス終了を再確認し、未着手の計測だけを実施した。再メッシュの再試行ではなく、元の実行を成功へ変更していない。', '']
    rows += ['', '## 形状と隙間', '']
    for voxel_um in ordered_voxels:
        case = 'v' + str(voxel_um)
        r = summary['results'][case]
        metrics = r.get('metrics') or {}
        rows += ['### ' + _mm_label(voxel_um), '']
        for view, label in [('front', '正面'), ('side', '側面'), ('top', '上面')]:
            p = metrics.get('projection-' + view)
            if not p or not p.get('complete'):
                continue
            lost = float(p.get('lost_m2', 0.0)) * 1000000.0
            added = float(p.get('added_m2', 0.0)) * 1000000.0
            rows.append('- ' + label + '：失われた投影 ' + ('%.2f' % lost) + ' mm2、追加された投影 ' + ('%.2f' % added) + ' mm2。')
            holes = p.get('original_holes', []) or []
            if holes:
                filled = sum(float(h.get('filled_mm2', 0.0)) for h in holes)
                opened = sum(float(h.get('opened_to_exterior_mm2', 0.0)) for h in holes)
                rows.append('- ' + label + 'の元の隙間：' + str(len(holes)) + '領域、埋まり ' + ('%.4f' % filled) + ' mm2、外側への接続 ' + ('%.4f' % opened) + ' mm2。')
        for region in regions:
            rid = region.get('id')
            if not rid:
                continue
            p = metrics.get(rid + '-projection')
            if p and 'gap_filled_fraction' in p:
                rows.append('- 既存の髪の隙間領域の充填率：' + ('%.4f' % (float(p['gap_filled_fraction']) * 100.0)) + '%。周囲の表面消失と合わせて判断する。')
        for direction, label in [('forward', '原本→候補'), ('reverse', '候補→原本')]:
            d = metrics.get(direction)
            if d and d.get('complete'):
                mean_mm = float(d['area_weighted_mean_m']) * 1000.0
                lo_mm = float(d['global_max_lower_m']) * 1000.0
                hi_mm = float(d['global_max_upper_m']) * 1000.0
                rows.append('- ' + label + '：面積重み平均 ' + ('%.4f' % mean_mm) + ' mm、最大値の範囲 ' + ('%.3f' % lo_mm) + '-' + ('%.3f' % hi_mm) + ' mm。内部面・重複面を含む。')
                q = d['area_weighted_quantiles_m']
                rows.append('- ' + label + 'の面積重み付き分位点：中央値 ' + ('%.4f' % (float(q['0.5']) * 1000.0)) + ' mm、95%点 ' + ('%.4f' % (float(q['0.95']) * 1000.0)) + ' mm、99%点 ' + ('%.4f' % (float(q['0.99']) * 1000.0)) + ' mm。')
        if case in external:
            rows.append('- 外部からの見え方は、最初に当たる面の深度と被覆の消失・追加を別計測した。方向別・局所領域の統計はreview-final/external-depth-summary.json。深度差は別の部位への切り替わりを含み、最近接距離や全身の最大外形差とは異なる。')
        else:
            rows.append('- 外部の深度・被覆は未取得。部位保持や外形差を評価できない。')
        ja_list = _short_ja_list(r.get('reasons'))
        if ja_list:
            for ja in ja_list:
                rows.append('- ' + ja + '。')
        else:
            rows.append('- 実行エラー記録なし。')
        rows.append('')
    rows += ['## 表面の構造', '']
    rows.append('| 解像度 | 開いた境界辺 | 非多様体辺（境界を含む） | 向きの不一致辺 | 退化面 |')
    rows.append('|---|---|---|---|---|')
    for voxel_um in ordered_voxels:
        case = 'v' + str(voxel_um)
        topology = (summary['results'][case].get('metrics') or {}).get('topology')
        if topology:
            vals = [str(topology.get(k, '未確認')) for k in ('boundary_edges', 'nonmanifold_edges', 'inconsistent_edges', 'degenerate_faces')]
        else:
            vals = ['未確認'] * 4
        rows.append('| ' + _mm_label(voxel_um) + ' | ' + ' | '.join(vals) + ' |')
    rows += ['', '辺検査だけでは閉じた立体を保証しない。自己交差と頂点周辺の完全な多様体検証は未確認。', '']
    if ref_entries:
        rows += ['## 参照表示（前回結果・表示のみ）', '']
        rows.append('以下の参照は凍結表示であり、新規の費用・完了判定・形状計測に含めない。数値の再掲ではなく表示位置の案内である。')
        rows.append('')
        for entry in sorted(ref_entries, key=lambda e: -int(e['voxel_um'])):
            ref = entry['ref']
            rows.append('- ' + entry['name'] + '：フォルダ ' + str(ref['ref_root'].relative_to(root) if ref['ref_root'].is_relative_to(root) else ref['ref_root']) + '。由来ハッシュはreview-final/provenance.json。')
        rows.append('')
    rows += ['## 実行費用と未完了項目', '']
    rows.append('| 解像度 | 記録された実処理時間 | 観測最大RSS | 観測最大コミット | 候補の頂点 / 三角形 | 条件別保存容量 |')
    rows.append('|---|---|---|---|---|---|')
    costs = {}
    for voxel_um in ordered_voxels:
        case = 'v' + str(voxel_um)
        r = summary['results'][case]
        cache_path_case = root / case / 'candidate' / 'cache.json'
        counts = {}
        try:
            if cache_path_case.exists():
                counts = read(cache_path_case)
        except OSError:
            counts = {}
        size_bytes = 0
        for p in (root / case).rglob('*'):
            try:
                if p.is_file():
                    size_bytes += p.stat().st_size
            except OSError:
                continue
        log_bytes = 0
        for p in root.glob(case + '-*'):
            try:
                if p.is_file():
                    log_bytes += p.stat().st_size
            except OSError:
                continue
        if counts and counts.get('vertices') is not None:
            count_text = str(counts.get('vertices')) + ' / ' + str(counts.get('triangles'))
        else:
            count_text = '未生成'
        rows.append('| ' + _mm_label(voxel_um) + ' | ' + ('%.2f' % (float(r.get('elapsed_s', 0.0)) / 60.0)) + ' 分 | ' + ('%.2f' % (float(r.get('peak_rss_bytes', 0)) / float(1024 ** 3))) + ' GiB | ' + ('%.2f' % (float(r.get('peak_private_commit_bytes', 0)) / float(1024 ** 3))) + ' GiB | ' + count_text + ' | ' + ('%.3f' % (float(size_bytes) / float(1024 ** 3))) + ' GiB |')
        costs[case] = dict(vertices=counts.get('vertices'), triangles=counts.get('triangles'), case_directory_bytes=size_bytes, root_stage_log_bytes=log_bytes, elapsed_s=r.get('elapsed_s'), peak_rss_bytes=r.get('peak_rss_bytes'), peak_private_commit_bytes=r.get('peak_private_commit_bytes'), memory_peak_method='Maximum observed process-tree sum at short polling intervals')
    rows += ['', '- 条件別の費用には共通入力の準備・原本の描画・最終集計を含めない。保存容量は条件フォルダ内の生成直後・整理後・途中計測も含む。段階ログ容量はreview-final/costs.jsonに別記録。', '- メモリは観測した処理群の合計の最大値。観測間隔より短い瞬間的なピークは捉えきれない。', '- [HIP描画の参考図](review-final/hip-comparison.png)はカメラの上下を表示時に補正した。原PNG、形状、数値計測は変更していない。補正とコードのSHAはreview-final/provenance.jsonに記録。', '- 必須部位の人間レビュー、自己交差、頂点周辺の完全な多様体検証は未承認／未確認。', '- [部位拡大](review-final/parts-comparison.png)は全身から生成した候補の表示窓。顔・耳・髪・尻尾・衣装・手・脚を共通範囲で確認できる。', '- 6方向の深度・問題部位・断面の追加図は元の[詳細レビュー](REVIEW.md)を参照。元の描画図の上下は、この最終レビューで補正済み。', '- 原本を保持し、CFDの基準を維持。Drag/Cd/CdAはnull、ランキング対象外。候補の採用はしていない。', '']
    (root / ('FINAL_REVIEW'+output_suffix+'.md')).write_text(chr(10).join(rows).replace('review-final/',folder.name+'/').replace('(REVIEW.md)','(REVIEW'+output_suffix+'.md)'), encoding='utf-8')
    shutil.copyfile(__file__, folder / Path(__file__).name)
    write(folder / 'costs.json', costs)
    states = {}
    for voxel_um in ordered_voxels:
        case = 'v' + str(voxel_um)
        r = summary['results'][case]
        metrics = r.get('metrics') or {}
        states[case] = dict(generation='COMPLETE' if r.get('generation_complete') else 'INCOMPLETE', measurements='COMPLETE' if r.get('measurement_complete') else 'INCOMPLETE', images=_image_state(metrics), human_review=None, scientific_status='UNAPPROVED', ranking_eligible=False, missing_global_metrics=[k for k in ('projection-front', 'projection-side', 'projection-top', 'forward', 'reverse') if not metrics.get(k)], raw_reasons=list(r.get('reasons') or []), reason_summaries_ja=_short_ja_list(r.get('reasons')), drag_N=None, Cd=None, CdA_m2=None, human_adoption=None, cfd_admission='UNCHANGED_BLOCKED')
    write(folder / 'condition-states.json', states)
    ref_prov = []
    for entry in sorted(ref_entries, key=lambda e: -int(e['voxel_um'])):
        ref = entry['ref']
        hashes = {}
        for name in ('result.json', 'views.json'):
            for cand in (ref['ref_root'] / name, ref['metrics_dir'] / name):
                try:
                    found = cand.exists()
                except OSError:
                    found = False
                if found:
                    try:
                        rel = cand.relative_to(root).as_posix()
                    except ValueError:
                        rel = cand.as_posix()
                    hashes[name + '@' + rel] = file_sha(cand)
                    break
        for view in ('front+', 'side+', 'top+'):
            p = ref['metrics_dir'] / (view + '-depth.npy')
            try:
                found = p.exists()
            except OSError:
                found = False
            if found:
                try:
                    rel = p.relative_to(root).as_posix()
                except ValueError:
                    rel = p.as_posix()
                hashes[(view + '-depth.npy') + '@' + rel] = file_sha(p)
        try:
            folder_rel = ref['ref_root'].relative_to(root).as_posix()
        except ValueError:
            folder_rel = ref['ref_root'].as_posix()
        ref_prov.append(dict(voxel_um=ref['voxel_um'], label=ref['label'], folder=folder_rel, display_name=entry['name'], display_only=True, file_hashes=hashes))
    provenance = dict(parent_study_id=summary.get('study_id'), script_sha256=file_sha(__file__), source_summary_sha256=file_sha(summary_path), orientation_corrections=applied, geometry_changed=False, metric_values_changed=False, scientific_status='UNAPPROVED', review_windows=windows_record, window_semantics='Human review windows only; no automatic part recognition', primary_presentation='Same measured depth grids for all conditions; common axis bounds and scale', requested_voxel_um=list(ordered_voxels), display_order=[dict(case=e['case'], name=e['name'], kind=e['kind'], voxel_um=e['voxel_um']) for e in display], new_cases_only_for_costs_and_completion=True, reference_provenance=ref_prov, drag_N=None, Cd=None, CdA_m2=None, human_adoption=None, ranking_eligible=False)
    write(folder / 'provenance.json', provenance)
    return provenance


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output-suffix', choices=('', '-verified'), default='')
    args = parser.parse_args()
    start = time.monotonic()
    create(args.root, output_suffix=args.output_suffix)
    print('FINAL_REVIEW_READY', time.monotonic() - start, flush=True)
