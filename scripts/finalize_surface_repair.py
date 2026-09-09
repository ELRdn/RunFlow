"""Consolidated private review; preserves failed initial runs and successful supplements."""
import argparse
from pathlib import Path
import shutil
import textwrap
import numpy as np
from runflow.core import digest
from runflow.shape_audit import file_sha,load_surface
from runflow.shape_fullbody import read,write
from runflow.shape_repair import gate,validate

VARIANTS=['base','nearest25','normal50','detail_union','manifold','raycarve2']
LABELS={'base':'Saved base','nearest25':'Nearest 25%','normal50':'Normal 50%',
        'detail_union':'Blender Exact union','manifold':'Manifold union','raycarve2':'Observed-air subtraction'}
STATES=['execution.json','supplemental-manifold/generate-execution.json','supplemental-manifold/measure-execution.json',
        'supplemental-raycarve/execution.json','supplemental-raycarve2/execution.json','supplemental-sections/execution.json']


def maybe(path): return read(path) if path.exists() else None


def collect(root,final=False):
    request=read(root/'request.json'); records=[]; states={}
    for name in STATES:
        value=maybe(root/name); states[name]=value
        if value:
            records += [dict(**r,execution_file=name) for r in value['records']]
    good={r['stage'] for r in records if r.get('returncode')==0 and not r.get('reason') and r.get('termination_verified')}
    finished=all(x and x.get('finished') for x in states.values())
    if final and not finished: raise ValueError('Processing still active; only preview is permitted')
    results={}
    for base in (1000,900):
        for variant in VARIANTS:
            case=f'v{base}'+('' if variant=='base' else '-'+variant); folder=root/case; metrics=folder/'metrics'
            generation=maybe(folder/'generation.json'); cache=maybe(folder/'candidate/cache.json')
            generated=bool(cache and (variant=='base' or case+'-generate' in good and generation and generation.get('complete')))
            m={}; reference_metrics={}
            keys=['forward','reverse','forward-witness','projection-front','projection-side','projection-top','external-distances','topology','views','sections']
            keys += [r['id']+'-'+d for r in request['regions'] for d in ('forward','reverse','projection')]
            for key in keys:
                value=maybe(metrics/(key+'.json'))
                suffix='measure' if key in ('forward-witness','external-distances','topology') else 'distance-'+key if key in ('forward','reverse') else key
                if any(key==r['id']+'-'+d for r in request['regions'] for d in ('forward','reverse')): suffix='distance-local'
                if any(key==r['id']+'-projection' for r in request['regions']):
                    roi=next(r for r in request['regions'] if key==r['id']+'-projection')
                    suffix='projection-'+{(0,1):'top',(0,2):'side',(1,2):'front'}[tuple(roi['axes'])]
                reference=variant=='base' and key in ('forward','reverse','views','projection-front','projection-side','projection-top')
                m[key]=value if generated and (reference or case+'-'+suffix in good) else None
                # Recover already-measured ROI projections from the exact saved base.
                # Do not regenerate geometry or infer a missing measurement from a picture.
                old_cache=request['inputs'].get(case+'-cache') if variant=='base' else None
                if generated and old_cache and key.endswith('-projection') and not m[key]:
                    prior_case=Path(old_cache['path']).parent.parent
                    prior_request=read(prior_case.parent/'request.json')
                    if prior_request['regions']!=request['regions']: raise ValueError('Reference ROI definitions differ')
                    if read(old_cache['path'])['output_hashes']!=cache['output_hashes']: raise ValueError('Reference base differs')
                    roi=next(r for r in request['regions'] if key==r['id']+'-projection')
                    plane={(0,1):'top',(0,2):'side',(1,2):'front'}[tuple(roi['axes'])]
                    plane_file=prior_case/'metrics'/('projection-'+plane+'.json'); roi_file=prior_case/'metrics'/(key+'.json')
                    if roi_file.exists() and read(plane_file).get('complete'):
                        if file_sha(plane_file)!=request['presentation'][case+'/projection-'+plane+'.json']['sha256']:
                            raise ValueError('Reference projection pin changed')
                        m[key]=read(roi_file); reference_metrics[key]=dict(path=str(roi_file),sha256=file_sha(roi_file),
                            reference_request_sha256=file_sha(prior_case.parent/'request.json'),plane_sha256=file_sha(plane_file),
                            base_cache_sha256=file_sha(old_cache['path']),reused_measurement=True)
            if not m['forward'] and m['forward-witness']: m['forward']=m['forward-witness']
            check=maybe(metrics/'self-intersections.json')
            if check and cache and check.get('input',{}).get('candidate_cache_sha256')!=file_sha(folder/'candidate/cache.json'):
                raise ValueError('Independent validation belongs to a different candidate')
            m['self-intersections']=check if generated and check and check.get('termination_verified') and check.get('complete') else None
            runs=[r for r in records if r['stage'].startswith(case+'-') and
                (variant!='base' or r['stage'] in [case+'-'+x for x in ('probe','measure','sections')])]
            gr=[r for r in runs if r['stage']==case+'-generate']
            failures=[dict(stage=r['stage'],reason=r.get('reason') or 'exit '+str(r.get('returncode')),
                launched=r.get('launched'),execution_file=r['execution_file'],
                later_independent_measurement_available=r['stage'] in good) for r in runs if r.get('reason') or r.get('returncode')!=0]
            required=['forward','reverse','projection-front','projection-side','projection-top','external-distances','topology','views','sections']
            if variant!='base': required += [r['id']+'-'+d for r in request['regions'] for d in ('forward','reverse')]
            entry=dict(case=case,base_um=base,variant=variant,generation_complete=generated,metrics=m,gates=gate(m),
                measurement_complete=bool(generated and all(m[k] and m[k].get('complete') for k in required)),
                generation_seconds=sum(r['elapsed_s'] for r in gr),
                generation_peak_commit_bytes=max((r.get('peak_private_commit_bytes',0) for r in gr),default=0),
                processing_seconds=sum(r['elapsed_s'] for r in runs),
                peak_commit_bytes=max((r.get('peak_private_commit_bytes',0) for r in runs),default=0),
                generation=generation,cache=cache,failures=failures,runs=runs,human_parts_review=None,
                independent_validation_history={p.parent.name:read(p) for p in sorted(folder.glob('selfcheck*/result.json'))},
                reference_metrics=reference_metrics,
                scientific_status='UNAPPROVED',ranking_eligible=False,drag_N=None,Cd=None,CdA_m2=None)
            if generated:
                # Use content and processing pins, never operational paths/timestamps.
                if variant in ('base','nearest25','normal50','detail_union'): pins=read(root/'tool-pins-compare.json')
                elif variant=='manifold': pins=read(root/'supplemental-manifold/pins-generate.json')
                else: pins=read(root/'supplemental-raycarve2/tool-pins.json')
                cfg=dict(source_sha256=request['inputs']['source']['sha256'],base_um=base,
                    base_hashes=read(root/f'v{base}/candidate/cache.json')['output_hashes'],candidate_hashes=cache['output_hashes'],
                    method=variant,tool_pins=pins,thresholds=dict(distance_m=.002,frontal_area_relative=.01),
                    regions=request.get('regions',[]),witnesses=request.get('witnesses',[]),
                    whole_original_surface_gate=True)
                entry['configuration_id']='rf-repair-reviewed-'+digest(cfg); entry['configuration']=cfg
            results[case]=entry
    return dict(finished=finished,results=results,execution_files={k:file_sha(root/k) for k,v in states.items() if v},
        completed_generated_candidates=sum(r['generation_complete'] for r in results.values() if r['variant']!='base'),
        completed_candidate_measurements=sum(r['measurement_complete'] for r in results.values() if r['variant']!='base'),
        requested_method_slots=10,scientific_status='UNAPPROVED',ranking_eligible=False,human_adoption=None,
        drag_N=None,Cd=None,CdA_m2=None,cfds_run=0)


def figures(root,summary,prefix,output_root=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    reference=read(root/'source-metrics/views.json')['views']; out=(output_root or root)/(prefix+'-figures'); out.mkdir(exist_ok=False)
    cmap=LinearSegmentedColormap.from_list('error',['#f0faf4','#86c6a0','#ffd46a','#d72849']); cmap.set_bad('white')
    for base in (1000,900):
        cases=['source']+[f'v{base}'+('' if v=='base' else '-'+v) for v in VARIANTS]
        for page,keys,error_map in [('whole-body',['front+','front-','side+','side-','top+','top-'],False),
                                  ('details',['face-visible','hair-visible','hair-gap'],False),
                                  ('visible-errors',['face-visible','hair-visible','hair-gap'],True)]:
            fig,axs=plt.subplots(len(keys),len(cases),figsize=(22,3.2*len(keys)),layout='constrained',squeeze=False)
            for row,key in enumerate(keys):
                info=reference[key]; src=np.load(root/'source-metrics'/(key+'-depth.npy')); mask=np.isfinite(src)
                lo=float(np.nanmin(src)); hi=float(np.nanmax(src))
                for col,case in enumerate(cases):
                    ax=axs[row,col]; result=summary['results'].get(case)
                    required='external-distances' if error_map else 'views'
                    valid=case=='source' or bool(result['metrics'].get(required) and result['metrics'][required].get('complete'))
                    folder=root/'source-metrics' if case=='source' else root/case/'metrics'
                    if not valid:
                        message='Not measured'
                        if result and result['failures']:
                            failure=result['failures'][0]; message=('Not launched: ' if failure['launched'] is False else 'Stopped: ')+failure['reason']
                        ax.text(.5,.5,textwrap.fill(message,23),ha='center',va='center',transform=ax.transAxes,fontsize=9); ax.axis('off')
                    elif error_map:
                        data=np.where(mask,0.,np.nan) if case=='source' else np.load(folder/(key+'-external-nearest.npy'))*1000
                        artist=ax.imshow(data,origin='lower',extent=info['extent_m'],interpolation='nearest',vmin=0,vmax=2,cmap=cmap)
                        if col==len(cases)-1: fig.colorbar(artist,ax=ax,shrink=.75,label='mm (clipped at 2)')
                    else:
                        depth=src if case=='source' else np.load(folder/(key+'-depth.npy')); finite=np.isfinite(depth)
                        tone=.65+.3*np.clip(np.nan_to_num((depth-lo)/max(hi-lo,1e-9)),0,1)
                        color=np.array([.22,.44,.66] if case=='source' else [.74,.43,.16] if result['variant']=='base' else [.20,.52,.41])
                        image=np.ones((*depth.shape,4)); image[finite,:3]=tone[finite,None]*color
                        ax.imshow(image,origin='lower',extent=info['extent_m'],interpolation='nearest')
                        if case!='source':
                            overlay=np.zeros((*depth.shape,4)); overlay[mask&~finite]=[.91,.1,.27,.9]; overlay[~mask&finite]=[.01,.65,.87,.9]
                            ax.imshow(overlay,origin='lower',extent=info['extent_m'],interpolation='nearest')
                    ax.set_aspect('equal'); ax.tick_params(labelsize=6)
                    if row==0: ax.set_title('Original' if case=='source' else LABELS[result['variant']],fontsize=9)
                    if col==0: ax.set_ylabel(key,fontsize=9)
            message='Visible-point distance only; same 0.1mm ROI lattice. Not continuous global maxima.' if error_map else 'Identical views and scale. Red: lost silhouette; cyan: added silhouette. Depth shading.'
            fig.suptitle(f'{base/1000:g} mm saved full-body base | {message}',fontsize=11)
            fig.savefig(out/f'{base}-{page}.png',dpi=150); plt.close(fig)
        # Compare the same selected planes, including the unmodified original.
        from matplotlib.collections import LineCollection
        sections=read(root/'source-metrics/sections.json')['sections']
        fig,axs=plt.subplots(2,3,figsize=(14,8),layout='constrained')
        colors={'source':'#344b6f',f'v{base}':'#b97929',f'v{base}-manifold':'#915d98',f'v{base}-raycarve2':'#119e8d'}
        for ax,(label,info) in zip(axs.flat,sections.items()):
            for case,color in colors.items():
                folder=root/'source-metrics' if case=='source' else root/case/'metrics'
                if case!='source' and not summary['results'][case]['metrics'].get('sections'): continue
                raw=np.load(folder/(label+'-section.npy')); axes=[i for i in range(3) if i!=info['axis']]
                lines=raw[:,:,axes] if raw.shape[-1]==3 else raw
                ax.add_collection(LineCollection(lines,colors=color,linewidths=.55,alpha=.8))
                ax.plot([],[],color=color,label='Original' if case=='source' else LABELS[summary['results'][case]['variant']])
            ax.autoscale(); ax.set_aspect('equal'); ax.set_title(label+' | plane '+str(info['value_m'])+' m')
            ax.tick_params(labelsize=8)
        handles,labels=axs.flat[0].get_legend_handles_labels()
        fig.legend(handles,labels,loc='outside lower center',ncol=4,fontsize=9,frameon=False)
        fig.suptitle(f'{base/1000:g} mm saved full-body base | Selected cross-sections; not a full 3D connectivity test')
        fig.savefig(out/f'{base}-sections.png',dpi=150); plt.close(fig)
    return out.name


def report(root,summary,prefix,figdir,output_root=None):
    rows=['# 1mm・0.9mm 全身候補の修正比較','',
        '**今回試した方法では、従来の2mm・1%等の全条件を満たす候補は得られていない。**',
        '微小移動2方法、元の細部を足す結合2方式、元の観測空間を切り戻す方法を比較した。0.8mm以下も含め、新しいボクセル再生成はしていない。',
        '未着手・資源停止と、形状の不合格を区別する。科学的承認・人間による候補採用・CFDは実施しておらず、正式なDrag/Cd/CdAはnull。','',
        f"生成完成は{summary['completed_generated_candidates']}候補、全身と局所の計測完了は{summary['completed_candidate_measurements']}候補。設定した方法の枠は5方法×2基準の10枠。",' ',
        '## 数値の比較','',
        '|基準|方法|正面面積差|全原本→候補 最大 mm|可視点 最大 mm|閉じた構造|形状判定|',
        '|---|---|---:|---:|---:|---|---|']
    for r in summary['results'].values():
        m=r['metrics']; area=m['projection-front']; d=m['forward']; ext=m['external-distances']
        at=f"{area['relative_change']*100:+.4f}%" if area and area.get('complete') else '未計測'
        dt=f"{d['global_max_lower_m']*1000:.3f}–{d['global_max_upper_m']*1000:.3f}" if d and d.get('complete') else '未完了'
        ev='未計測'
        if ext and ext.get('complete'): ev=f"{max(v['max_sampled_m'] for k,v in ext['views'].items() if k.endswith(('+','-')))*1000:.3f}"
        rows.append(f"|{r['base_um']/1000:g}mm|{LABELS[r['variant']]}|{at}|{dt}|{ev}|{r['gates']['checks']['closed_topology']}|{r['gates']['verdict']}|")
    rows += ['', '最大距離の範囲には全三角形の被覆幅と2µmの数値余裕を含む。外から見えない面・重なった面も原本側の判定対象に残す。可視点の最大は6方向・2mm格子の標本値であり、連続した全外形の最大ではない。',
        '', '### 見えている問題領域の変化','',
        '|基準・方法|顔周辺 可視標本の最大 mm|顔周辺 2mm超 %|髪 可視標本の最大 mm|髪 2mm超 %|固定した髪の隙間の埋まり %|',
        '|---|---:|---:|---:|---:|---:|']
    for r in summary['results'].values():
        ext=r['metrics'].get('external-distances'); gap=r['metrics'].get('hair-gap-projection')
        if not ext: continue
        face=ext['views']['face-visible']; hair=ext['views']['hair-visible']
        gt=f"{gap['gap_filled_fraction']*100:.2f}" if gap and 'gap_filled_fraction' in gap else '未計測'
        rows.append(f"|{r['base_um']/1000:g}mm {LABELS[r['variant']]}|{face['max_sampled_m']*1000:.3f}|{face['fraction_over_2mm']*100:.3f}|{hair['max_sampled_m']*1000:.3f}|{hair['fraction_over_2mm']*100:.3f}|{gt}|")
    rows += ['', '可視標本は同じ0.1mmの2D格子を使う。割合は投影画素数を基準とし、三角形の面積重み付き分布とは異なる。髪の隙間の埋まりは、原本の固定した2D背景領域を基準とする。基準候補の局所投影は保存済み測定を参照し、領域・候補SHA・全体投影の固定SHAを照合した。',
        '', '## 確認点の改善と限界','',
        '|基準・処理|顔周辺の既知点 mm|髪の既知点 mm|',
        '|---|---:|---:|']
    for base in (1000,900):
        original=read(root/f'v{base}/metrics/probe.json')['witnesses']
        mapping={x['id']:x['candidate_distance_m'] for x in original}
        rows.append(f"|{base/1000:g}mm 保存済み|{mapping['face-visible']*1000:.3f}|{mapping['hair-visible']*1000:.3f}|")
        for variant in ('manifold','raycarve2'):
            r=summary['results'][f'v{base}-{variant}']; witness=r['metrics'].get('forward-witness')
            if witness:
                mapping={x['id']:x['distance_m'] for x in witness['witnesses']}
                rows.append(f"|{base/1000:g}mm {LABELS[variant]}|{mapping['face-visible']*1000:.3f}|{mapping['hair-visible']*1000:.3f}|")
    rows += ['', 'この表は既知の2点の比較。顔・髪の全範囲が2mm以内に入ったことを意味しない。全範囲の距離・分位点・超過面積率は結果JSONに別記する。',
        '元データでは見える顔・髪の面が、保存済み候補の固体内部に入っていた。薄い面を作って足しても、和集合では固体内部の面が消える。観測された空き空間を切り戻す方法はその一部を改善するが、保守的な奥行き処理の影響も残る。',
        '既知の大差には6方向では直接見えない面も含まれる。6方向で見えないだけでは密閉された内部とは断定できない。今回もその面を合否から除外していない。',
        '', '## 方法と実行費用','',
        '|基準|方法|生成 秒|生成の最大コミット GiB|状態|',
        '|---|---|---:|---:|---|']
    for r in summary['results'].values():
        if r['variant']=='base': continue
        status='生成完了' if r['generation_complete'] else '未実行' if r['runs'] and all(x.get('launched') is False for x in r['runs']) else '停止'
        rows.append(f"|{r['base_um']/1000:g}mm|{LABELS[r['variant']]}|{r['generation_seconds']:.2f}|{r['generation_peak_commit_bytes']/1024**3:.2f}|{status}|")
    rows += ['', '- Nearest 25%：最寄りの元の面へ25%移動。上限0.5mm。',
        '- Normal 50%：差を頂点法線方向へ分解し50%移動。上限0.5mm。',
        '- Blender Exact union：元の可視欠落候補を0.4mmの薄い立体にして全身へ結合。急なメモリ確保により停止。0.9mm側はその直後のC容量条件で未起動。',
        '- Manifold union：同じ閉じた薄い立体をManifold 3.5.2で結合。生成自体は高速で低メモリだったが、従来の1µm整理後には接続不良・退化面が残り、内部に埋まる面も戻らなかった。',
        '- Observed-air subtraction：顔・髪の固定2領域で、元の全身へ向けた光線の最初の面までの空間を差し引く。0.1mmの奥行き格子、0.2mmの手前余裕、3×3の浅い側への制限を固定した。ボクセル生成ではない。Manifoldの1µm以内の簡略化とbinary32再取り込みで接続を保持し、出力を独立に検査した。',
        'この1µmはライブラリが示す面の移動上限。独立に全域を1µm以内と証明した値ではない。最終候補には元の2mm・1%判定を適用した。',
        '旧監視は0.5秒ごとの計測だったため、大きな確保が80GiB設定を超えて観測された。追加試行にはOSのJob Objectによる80GiB制限を付け、合成試験で割当て拒否を確認した。C容量低下は回復し、未起動だった計測だけを別実行記録で追加した。元の停止記録は残した。',
        '追加試行にも最初の比較開始から12時間の期限を適用した。別方式に変えたことを理由に時間枠を延長していない。CPUは同じ24論理コア、投影は8プロセス。',
        '', '## 図と隙間の確認','',
        f'[1mm 全身]({figdir}/1000-whole-body.png) / [0.9mm 全身]({figdir}/900-whole-body.png)',
        f'[1mm 拡大]({figdir}/1000-details.png) / [0.9mm 拡大]({figdir}/900-details.png)',
        f'[1mm 可視点の誤差]({figdir}/1000-visible-errors.png) / [0.9mm 可視点の誤差]({figdir}/900-visible-errors.png)',
        f'[1mm 選定断面]({figdir}/1000-sections.png) / [0.9mm 選定断面]({figdir}/900-sections.png)',
        '全身図は同じ視点・縮尺。赤は失われた投影部分、水色は追加部分。誤差図は同じ色範囲で2mm以上を赤に飽和させている。',
        '投影上の隙間の埋まり・拡大・外への開放は、各候補の projection-*.json と問題領域の *-projection.json に個別保存する。2Dの穴を3Dの通気性と同一視しない。必須部位・隙間の最終人間レビューは未実施。',
        '', '## 独立検査','']
    for r in summary['results'].values():
        if r['variant']!='raycarve2' and r['case']!='v900': continue
        c=r['metrics'].get('self-intersections')
        rows.append(f"- {r['base_um']/1000:g}mm {LABELS[r['variant']]}："+('OpenFOAMの自己交差検査 '+('PASS' if c['intersection_free'] else 'FAIL')+f"、検出 {c['intersection_locations']}件、{c['elapsed_s']:.2f}秒。" if c else '自己交差は未確認。接続の検査だけでは合格にしない。'))
    rows += ['', '同じ検査で0.9mmの基準にも交差を検出したが、補修後の検出座標は基準の検出座標と異なる。補修後の複数の検出は出力精度では同じ座標であり、別々の交差箇所と数えない。件数の減少だけで残りを許容せず、FAILを維持する。',
        'この検査のPASSは、記録したbinary32形状に対してFoundation 14の辺と三角形の検査が交差を検出しなかったことを表す。数学的な完全証明や科学的承認ではない。',
        '最初はWSLからEへのASCII領域図の書き出し中に時間切れとなった。同じ入力SHAと実行ファイルでWSL内の専用領域へ一時出力することで検査まで完了した。過去の失敗・途中ファイルを残し、各 selfcheck*/result.json と最終の検査記録を区別している。']
    rows += ['', '## 調査した根拠','',
        '- [Blender 4.2 Shrinkwrap](https://docs.blender.org/manual/en/4.2/modeling/modifiers/deform/shrinkwrap.html)：頂点を面へ近づける方法と、鋭角等での内外判定の限界。',
        '- [Blender 4.2 Solidify](https://docs.blender.org/manual/en/4.2/modeling/modifiers/generate/solidify.html) / [Boolean](https://docs.blender.org/manual/en/4.2/modeling/modifiers/generate/booleans.html)：薄い立体化とExact結合。指定厚さ・非多様体入力の結果は無条件に保証されない。',
        '- [Blender 4.2.23 の実装](https://github.com/blender/blender/blob/d0cbe84903e8550c66247e96f9703f60e4b7c3b7/source/blender/makesrna/intern/rna_modifier.cc)：版と使用設定を照合。',
        '- [Manifold 3.5.2](https://github.com/elalish/manifold/releases/tag/v3.5.2) / [作者による入力条件の説明](https://github.com/elalish/manifold/discussions/471)：未処理の開いた原本ではなく、閉じた基準とSolidify済みのパッチを渡す。公式wheelをSHA固定し、プロセス専用の読み込み先へ分離した。',
        '- [CGAL Alpha Wrapping](https://doc.cgal.org/latest/Alpha_wrap_3/index.html)：頑健な閉じた包絡面の別方式を調査。今回の保存済み候補の微修正では使わず、内部面まで近いことを保証する方式ともみなさない。',
        '- [Curless–Levoy, SIGGRAPH 1996](https://graphics.stanford.edu/papers/volrange/)：奥行き観測と空き空間を区別する考え方の参考。今回の局所切削は独自の2.5D表面Boolean試験で、この論文のボクセル統合アルゴリズムを実装したものではない。',
        '調査はagent-reachのExaとGitHub CLIを使用。特定の修復ソフトやAIに元形状を丸投げした処理ではない。',
        '', '## 引き渡し','',
        'この試験で、面積の一致、欠落の回復、接続の正しさ、自己交差の有無は別々に確認する必要があると分かった。微小移動だけで大きな欠落を戻すことは難しく、足し戻しと空き空間の復元も別の操作になる。',
        '次は、外から見える凹部の連続した形状をより正確に保つ局所補修と、原本中の内部・重複・露出面の識別が必要。許容差や判定対象の変更は今回採用していない。',
        '入力・処理コード・出力SHA、設定ID、段階の費用と失敗は統合JSONと各実行ログへ保存。旧結果を上書きせず、全結果は非公開。公開・commit・pushは実施していない。',
        '欠落 Gallop.CharaTransformProcessData の役割と公式との完全一致は引き続き未確認。']
    ((output_root or root)/(prefix+'-REVIEW.md')).write_text('\n'.join(rows)+'\n',encoding='utf-8')


def verify_and_inventory(root,summary,output_root=None):
    import psutil
    request=read(root/'request.json'); validate(request)
    checked=[]; active=[]
    for name in ['source','cleaned']+[r['case']+'/candidate' for r in summary['results'].values() if r['generation_complete']]:
        load_surface(root/name); checked.append(name)
    for name in STATES:
        for r in read(root/name)['records']:
            for owned in r.get('owned_processes',[]):
                try:
                    p=psutil.Process(owned['pid'])
                    if p.is_running() and abs(p.create_time()-owned['created_at'])<.01: active.append(owned)
                except psutil.NoSuchProcess: pass
    if active: raise ValueError('Recorded owned processes are still running')
    if summary['human_adoption'] is not None or any(summary[k] is not None for k in ('drag_N','Cd','CdA_m2')):
        raise ValueError('Review may not adopt a candidate or populate CFD values')
    output_root=output_root or root
    repo=Path(__file__).resolve().parents[1]; archive=output_root/'final-validation/tool-sources'; archive.mkdir(parents=True,exist_ok=False)
    paths=[Path(__file__).resolve(),repo/'scripts/check_repair_intersections.py',repo/'scripts/cfd_worker.py',
           repo/'src/runflow/shape_repair.py']
    for p in paths:
        target=archive/p.relative_to(repo); target.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(p,target)
    collect_again=collect(root,final=True)
    if digest(collect_again)!=digest(summary): raise ValueError('Results changed during reporting')
    write(output_root/'final-verification.json',dict(inputs_unchanged=True,verified_binary_caches=checked,
        summary_stable=True,recorded_owned_processes_alive=active,
        latest_independent_checks_terminated=all(c.get('termination_verified') for r in summary['results'].values()
            if (c:=r['metrics'].get('self-intersections'))),
        original_cfd_result_unchanged=True,scientific_status='UNAPPROVED',ranking_eligible=False,
        human_adoption=None,drag_N=None,Cd=None,CdA_m2=None))
    entries={}; total=0; roots={'data':root}
    if output_root!=root: roots['review']=output_root
    for role,directory in roots.items():
        for p in sorted(directory.rglob('*')):
            if not p.is_file() or 'scratch' in p.relative_to(directory).parts or p.name=='final-artifact-sha256.json': continue
            before=p.stat(); sha=file_sha(p); after=p.stat()
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns): raise ValueError('Artifact changed during inventory')
            entries[role+'/'+p.relative_to(directory).as_posix()]=dict(sha256=sha,bytes=after.st_size); total+=after.st_size
    write(output_root/'final-artifact-sha256.json',dict(files=entries,bytes=total,scientific_status='UNAPPROVED',
        operational_roots={k:str(v) for k,v in roots.items()},
        exclusions=['scratch/','final-artifact-sha256.json'],
        prior_manifests='Historical inventories are preserved as snapshots of their recording time'))


def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True); p.add_argument('--preview',action='store_true')
    p.add_argument('--report-output',type=Path); a=p.parse_args()
    a.root=a.root.resolve()
    if not a.root.is_relative_to(Path('E:/RunFlowPrivate').resolve()): raise ValueError('Private review root required')
    output=a.report_output.resolve() if a.report_output else a.root
    private_roots=[Path(__file__).resolve().parents[1]/'private',Path('E:/RunFlowPrivate').resolve()]
    if not any(output.is_relative_to(p) for p in private_roots): raise ValueError('Private report output required')
    if output!=a.root: output.mkdir(parents=True,exist_ok=False)
    prefix='preview' if a.preview else 'final'
    if (output/(prefix+'-summary.json')).exists(): raise ValueError('Review already exists; preserve earlier report')
    summary=collect(a.root,final=not a.preview); write(output/(prefix+'-summary.json'),summary)
    figdir=figures(a.root,summary,prefix,output); report(a.root,summary,prefix,figdir,output)
    if not a.preview: verify_and_inventory(a.root,summary,output)
    print('REPAIR_CONSOLIDATED_REVIEW',prefix,summary['completed_candidate_measurements'],flush=True)


if __name__=='__main__': main()
