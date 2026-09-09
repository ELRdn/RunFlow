"""Private Japanese review and plots; partial measurements never become PASS."""
import argparse
from pathlib import Path
import numpy as np
from runflow.shape_fullbody import read,write,VOXELS,PLANES,study_profile
from runflow.shape_audit import file_sha,load_surface


def maybe(path): return read(path) if path.exists() else None


def verify_generation_checkpoint(root,case,path):
    """Accept complete data with a recorded cleanup warning, never a timed-out payload."""
    root=Path(root).resolve(); path=Path(path).resolve()
    if not path.is_relative_to(root): raise ValueError('Checkpoint must stay inside the study')
    proof=read(path); execution=root/(case+'-remesh.execution.json')
    run=read(execution); gen_path=root/case/'generation.json'; repair_path=root/case/'remesh.json'
    gen=read(gen_path); repair=read(repair_path)
    required=('complete','artifact_usable','execution_warning_preserved','no_new_remesh')
    if not all(proof.get(k) is True for k in required) or proof.get('original_execution_success') is not False:
        raise ValueError('Unverified generation checkpoint')
    if run.get('returncode')!=0 or run.get('reason')!='launcher left live descendants' or not run.get('termination_verified'):
        raise ValueError('Only a completed payload with verified termination can use this checkpoint')
    for field,file in [('original_execution_sha256',execution),('generation_sha256',gen_path),('remesh_sha256',repair_path)]:
        if proof.get(field)!=file_sha(file): raise ValueError('Checkpoint hash mismatch: '+field)
    if not gen.get('complete') or not repair.get('complete') or gen.get('passes')!=1 or not gen.get('whole_input'):
        raise ValueError('Whole generation is not complete')
    if gen.get('voxel_um')!=int(case[1:]) or gen.get('adaptivity')!=0 or gen.get('preserve_volume') is not False:
        raise ValueError('Generation settings changed')
    shift=repair['repair']['max_vertex_shift_m']
    if not np.isfinite(shift) or not 0<=shift<=1e-6: raise ValueError('Cleanup tolerance changed')
    if gen['cleaned_input_hashes']!=read(root/'cleaned/cache.json')['output_hashes']:
        raise ValueError('Common input changed')
    for folder in ('cleaned',case+'/generated',case+'/candidate'): load_surface(root/folder)
    if gen['output_hashes']!=read(root/case/'generated/cache.json')['output_hashes']:
        raise ValueError('Generated array hashes changed')
    if proof['candidate_hashes']!=read(root/case/'candidate/cache.json')['output_hashes']:
        raise ValueError('Candidate hashes changed')
    if 'FULLBODY_REMESH_COMPLETE '+case[1:] not in (root/(case+'-remesh.log')).read_text():
        raise ValueError('Payload completion marker missing')
    return dict(proof_file=path.relative_to(root).as_posix(),proof_sha256=file_sha(path),
        artifact_complete=True,original_execution_success=False,warning=run['reason'])


def summarize(root, *, state=None, generation_checkpoints=None, output_suffix=""):
    if output_suffix not in ('','-verified'): raise ValueError('Unsupported report output suffix')
    if generation_checkpoints and output_suffix!='-verified': raise ValueError('Checkpoint review needs separate outputs')
    state=read(root/'execution-summary.json') if state is None else state
    records=state['records']; results={}; generation_checkpoints=generation_checkpoints or {}
    voxels,_=study_profile(read(root/'request.json'))
    if set(generation_checkpoints)-{f'v{x}' for x in voxels}: raise ValueError('Unknown checkpoint case')
    if output_suffix and any(p.exists() for p in [root/('study-summary'+output_suffix+'.json')]+[root/f'v{x}'/('result'+output_suffix+'.json') for x in voxels]):
        raise ValueError('Verified report outputs already exist')
    for voxel in voxels:
        case=f'v{voxel}'; folder=root/case; metrics=folder/'metrics'
        generation=maybe(folder/'generation.json'); remesh=maybe(folder/'remesh.json')
        entries={k:maybe(metrics/(k+'.json')) for k in ['projection-front','projection-side','projection-top',
            'forward','reverse','views','sections','topology','render']}
        roi=read(root/'request.json').get('regions',[])
        for r in roi:
            for suffix in ('forward','reverse','projection'):
                key=r['id']+'-'+suffix; entries[key]=maybe(metrics/(key+'.json'))
        runs=[r for r in records if r['stage'].startswith(case+'-')]
        successful={r['stage'] for r in runs if r.get('returncode')==0 and not r.get('reason') and r.get('termination_verified')}
        for key in list(entries):
            if key in ('forward','reverse'): stage=case+'-distance-'+key
            elif any(key==r['id']+'-'+d for r in roi for d in ('forward','reverse')): stage=case+'-distance-local'
            elif key.endswith('-projection') and not key.startswith('projection-'):
                region=next(r for r in roi if key==r['id']+'-projection')
                view={(1,2):'front',(0,2):'side',(0,1):'top'}[tuple(region['axes'])]
                stage=case+'-projection-'+view
            else: stage=case+'-'+key
            if stage not in successful: entries[key]=None
        generation_execution_ok=any(r['stage']==case+'-remesh' and r.get('returncode')==0 and not r.get('reason') and r.get('termination_verified') for r in runs)
        checkpoint=None
        if case in generation_checkpoints:
            checkpoint=verify_generation_checkpoint(root,case,generation_checkpoints[case])
        generation_ok=(generation_execution_ok or checkpoint is not None) and bool(generation and generation.get('complete') and remesh and remesh.get('complete'))
        required=['projection-front','projection-side','projection-top','forward','reverse','views','sections']
        required += [r['id']+'-'+d for r in roi for d in ('forward','reverse')]
        complete=generation_ok and all(entries[k] and entries[k].get('complete') for k in required)
        complete=complete and bool(entries['topology'] and entries['topology'].get('edge_checks_complete'))
        result=dict(generation=generation,remesh=remesh,metrics=entries,runs=runs,
            generation_complete=bool(generation_ok),generation_execution_success=bool(generation_execution_ok),
            generation_checkpoint=checkpoint,measurement_complete=bool(complete),human_review=None,
            elapsed_s=sum(r.get('elapsed_s',0) for r in runs),
            peak_rss_bytes=max((r.get('peak_rss_bytes',0) for r in runs),default=0),
            peak_private_commit_bytes=max((r.get('peak_private_commit_bytes',0) for r in runs),default=0),
            reasons=[r['reason'] for r in runs if r.get('reason') and not r.get('superseded_by')],scientific_status='UNAPPROVED',
            ranking_eligible=False,drag_N=None,Cd=None,CdA_m2=None)
        write(folder/('result'+output_suffix+'.json'),result); results[case]=result
    value=dict(study_id=state['study_id'],results=results,comparison_complete=bool(state.get('inputs_unchanged')) and all(r['measurement_complete'] for r in results.values()),
        study_finished=True,scientific_status='UNAPPROVED',human_adoption=None,ranking_eligible=False,
        cfd_admission='UNCHANGED_BLOCKED',inputs_unchanged=state.get('inputs_unchanged'),
        note='A finished bounded study is not proof that four comparisons or geometry certification completed.')
    write(root/('study-summary'+output_suffix+'.json'),value); return value


def figures(root,summary, *, output_suffix=""):
    if output_suffix not in ("", "-verified"): raise ValueError("Unsupported figure output suffix")
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    from matplotlib.colors import ListedColormap
    voxels,_=study_profile(read(root/'request.json'))
    cases=['source']+[f'v{x}' for x in voxels]
    folders=[root/'source-metrics']+[root/c/'metrics' for c in cases[1:]]
    figures=root/('figures'+output_suffix); figures.mkdir(exist_ok=True)
    reference=maybe(folders[0]/'views.json')
    if reference and not reference.get('complete'): reference=None
    if reference:
        keys=list(reference['views'])
        for page,viewkeys in [('whole-body',['front+','front-','side+','side-','top+','top-']),
                              ('problem-regions',[k for k in keys if k not in ['front+','front-','side+','side-','top+','top-']])]:
            if not viewkeys: continue
            fig,axes=plt.subplots(len(viewkeys),5,figsize=(17,3.1*len(viewkeys)),layout='constrained',squeeze=False)
            for row,key in enumerate(viewkeys):
                info=reference['views'][key]; a=np.load(folders[0]/(key+'-depth.npy')); am=np.isfinite(a)
                for col,(case,folder) in enumerate(zip(cases,folders)):
                    ax=axes[row,col]; path=folder/(key+'-depth.npy')
                    if path.exists():
                        b=np.load(path); bm=np.isfinite(b)
                        rgb=np.zeros(a.shape,dtype=np.uint8); rgb[am&bm]=1; rgb[am&~bm]=2; rgb[~am&bm]=3
                        ax.imshow(rgb,origin='lower',extent=info['extent_m'],interpolation='nearest',
                            cmap=ListedColormap(['#ffffff','#66899e','#d43b5b','#e7a02a']),vmin=0,vmax=3)
                    else: ax.text(.5,.5,'Unavailable',transform=ax.transAxes,ha='center')
                    ax.set_title(('Original' if case=='source' else case[1:]+' um')+' | '+key)
                    ax.set_aspect('equal'); ax.set_xlabel('m'); ax.set_ylabel('m')
            fig.suptitle('Full body retained | red: lost coverage; amber: new coverage | not a CFD certificate')
            fig.savefig(figures/(page+'.png'),dpi=150); plt.close(fig)
        # Fixed source-relative crops. Labels denote review regions, not automatic part recognition.
        crops=[('head / ears / hair',.60,1.0),('torso / arms / costume',.38,.82),('legs / shoes',0,.65)]
        fig,axes=plt.subplots(6,5,figsize=(17,18),layout='constrained')
        for view_i,key in enumerate(['front+','side+']):
            info=reference['views'][key]; a=np.load(folders[0]/(key+'-depth.npy')); am=np.isfinite(a)
            x0,x1,z0,z1=info['extent_m']
            for band,(label,lo,hi) in enumerate(crops):
                row=view_i*3+band
                for col,(case,folder) in enumerate(zip(cases,folders)):
                    ax=axes[row,col]; path=folder/(key+'-depth.npy')
                    if path.exists():
                        b=np.load(path); bm=np.isfinite(b); rgb=np.zeros(a.shape,dtype=np.uint8)
                        rgb[am&bm]=1; rgb[am&~bm]=2; rgb[~am&bm]=3
                        ax.imshow(rgb,origin='lower',extent=info['extent_m'],interpolation='nearest',
                            cmap=ListedColormap(['#ffffff','#66899e','#d43b5b','#e7a02a']),vmin=0,vmax=3)
                    ax.set_xlim(x0,x1); ax.set_ylim(z0+lo*(z1-z0),z0+hi*(z1-z0))
                    ax.set_title(case+' | '+key+' | '+label,fontsize=9); ax.set_aspect('equal')
        fig.savefig(figures/'parts-review.png',dpi=150); plt.close(fig)
        # Numeric first-hit depth change for external evidence, not nearest distance.
        fig,axes=plt.subplots(3,4,figsize=(16,12),layout='constrained')
        for row,key in enumerate(['front+','side+','top+']):
            a=np.load(folders[0]/(key+'-depth.npy'))
            for col,folder in enumerate(folders[1:]):
                ax=axes[row,col]; path=folder/(key+'-depth.npy')
                if path.exists():
                    b=np.load(path); d=np.abs(b.astype(float)-a)*1000
                    im=ax.imshow(d,origin='lower',extent=reference['views'][key]['extent_m'],vmin=0,vmax=2,cmap='magma',interpolation='nearest')
                    fig.colorbar(im,ax=ax,label='First-hit difference [mm], clipped at 2')
                ax.set_title(cases[col+1]+' | '+key)
        fig.savefig(figures/'external-depth.png',dpi=130); plt.close(fig)
    # HIP renders keep the actual generated mesh; depth panels cover missing renders.
    fig,axes=plt.subplots(3,5,figsize=(17,11),layout='constrained')
    for row,key in enumerate(['front+','side+','top+']):
        for col,(case,folder) in enumerate(zip(cases,folders)):
            ax=axes[row,col]; path=folder/(key+'-hip.png')
            if path.exists(): ax.imshow(plt.imread(path))
            else: ax.text(.5,.5,'HIP render unavailable\nSee measured depth panels',ha='center',transform=ax.transAxes)
            ax.set_title(('Original' if case=='source' else case[1:]+' um')+' | '+key); ax.axis('off')
    fig.savefig(figures/'shaded-comparison.png',dpi=150); plt.close(fig)
    fig,axes=plt.subplots(len(PLANES),4,figsize=(16,17),layout='constrained')
    for row,(label,axis,value) in enumerate(PLANES):
        remaining=[a for a in range(3) if a!=axis]
        for col,folder in enumerate(folders[1:]):
            ax=axes[row,col]
            for location,color in [(folders[0],'#2676ab'),(folder,'#e6a02a')]:
                path=location/(label+'-section.npy')
                if path.exists(): ax.add_collection(LineCollection(np.load(path)[:,:,remaining],colors=color,linewidths=.4))
            ax.autoscale(); ax.set_aspect('equal'); ax.set_title(cases[col+1]+' | '+label)
    fig.savefig(figures/'sections.png',dpi=120); plt.close(fig)


def review(root,summary, *, output_suffix=""):
    if output_suffix not in ("", "-verified"): raise ValueError("Unsupported review output suffix")
    voxels,_=study_profile(read(root/'request.json'))
    rows=['# 全身ボクセル比較レビュー','',
        '元の全身を保持した4解像度の診断。科学的承認・CFD用形状の採用は未実施。',
        '',f"4条件の計測完了: {summary['comparison_complete']}",'',
        '| 解像度 | 生成 | 計測 | 正面面積差 | 最大コミット | 実処理時間 |',
        '|---|---|---|---|---|---|']
    for voxel in voxels:
        r=summary['results'][f'v{voxel}']; p=r['metrics']['projection-front']
        area=f"{p['relative_change']*100:+.5f}%" if p and p.get('complete') else '未計測'
        rows.append(f"| {voxel/1000:g} mm | {'完了' if r['generation_complete'] else '未完了'} | {'完了' if r['measurement_complete'] else '部分／未完了'} | {area} | {r['peak_private_commit_bytes']/1024**3:.2f} GiB | {r['elapsed_s']/60:.1f} 分 |")
    rows+=['','## 比較画像','','![全身](figures/whole-body.png)','',
        '![描画](figures/shaded-comparison.png)','','![部位レビュー](figures/parts-review.png)','',
        '![問題領域](figures/problem-regions.png)','',
        '赤は投影上で消えた部分、黄は新しく覆われた部分。灰青は共通部分。面積の正味差だけで採否を決めない。',
        '', '## 条件別の記録','']
    for voxel in voxels:
        r=summary['results'][f'v{voxel}']; rows += [f'### {voxel/1000:g} mm','']
        rows += ['- '+reason for reason in r['reasons']] or ['- 実行エラー記録なし。']
        for name in ['forward','reverse']:
            d=r['metrics'][name]
            if d and d.get('complete'):
                rows.append(f"- {name}: 面積重み平均 {d['area_weighted_mean_m']*1000:.4f} mm、最大範囲 {d['global_max_lower_m']*1000:.4f}–{d['global_max_upper_m']*1000:.4f} mm。内部・重複面も含む。")
        rows+=['']
    rows+=['## 判断の限界・次の作業','',
        '- 部位保持と候補採用の人間レビュー欄は未入力。自己交差と頂点周辺の完全な多様体検証も未完了。',
        '- 6方向は2mm、問題領域は0.1mm間隔の視線。奥行き差は別部位への切り替わりを含み、最近接距離とは異なる。',
        '- 隙間は元の投影領域を追跡している。外側との接続や周囲の形状消失を、隙間保持の改善と取り違えない。',
        '- 資源不足・時間切れの条件は採否判定できない。別方式や追加予算は今回自動で導入していない。',
        '- 細かい候補の完走が必要なら、実測したメモリと面数を基に省メモリ方式を別途検討する。',
        '- CFD結果・2mm/1%の基準は変更していない。Drag/Cd/CdAはnull、ランキング対象外。','']
    (root/('REVIEW'+output_suffix+'.md')).write_text('\n'.join(rows).replace('figures/','figures'+output_suffix+'/'),encoding='utf-8')


def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True); args=p.parse_args(); root=args.root
    summary=summarize(root); figures(root,summary); review(root,summary)
    hashes={str(p.relative_to(root)).replace('\\','/'):file_sha(p) for p in root.rglob('*')
        if p.is_file() and p.name not in ('artifact-sha256.json',) and not p.name.endswith(('.log','.jsonl','.tmp'))}
    write(root/'artifact-sha256.json',hashes)
    print('FULLBODY_REVIEW_COMPLETE',summary['comparison_complete'],flush=True)


if __name__=='__main__': main()
