"""Private evidence-based review of surface repair, including failed/incomplete cases."""
import argparse
from pathlib import Path
import textwrap
import numpy as np
from runflow.core import digest
from runflow.shape_audit import file_sha
from runflow.shape_fullbody import read,write
from runflow.shape_repair import gate,RECIPES


def maybe(path): return read(path) if path.exists() else None


def summarize(root):
    request=read(root/'request.json'); state=read(root/'execution.json'); results={}
    good={r['stage'] for r in state['records'] if r.get('returncode')==0 and not r.get('reason') and r.get('termination_verified')}
    pins=read(root/'tool-pins-compare.json')
    for base in request['bases_um']:
        for recipe in ['base']+list(RECIPES):
            case=f'v{base}' if recipe=='base' else f'v{base}-{recipe}'
            folder=root/case; metrics=folder/'metrics'
            gen=maybe(folder/'generation.json'); cleanup=maybe(folder/'cleanup.json'); cache=maybe(folder/'candidate/cache.json')
            generated=recipe=='base' or (case+'-generate' in good and gen and gen.get('complete') and cleanup and cleanup.get('complete'))
            values={}; diagnostics={}
            for key in ['forward','reverse','forward-witness','projection-front','projection-side','projection-top',
                        'external-distances','topology','views','self-intersections']:
                value=maybe(metrics/(key+'.json')); diagnostics[key]=value
                if recipe=='base' and key in ['forward','reverse','projection-front','projection-side','projection-top','views']:
                    values[key]=value  # Pinned previous complete measurements, not a new execution claim.
                else:
                    suffix='measure' if key in ['forward-witness','external-distances','topology'] else 'distance-'+key if key in ['forward','reverse'] else key
                    values[key]=value if case+'-'+suffix in good and generated else None
            # A completed fixed-point counterexample is valid rejection evidence, not a measured global max.
            if not values.get('forward') and values.get('forward-witness'):
                values['forward']=values['forward-witness']
            checks=gate(values)
            runs=[r for r in state['records'] if r['stage'].startswith(case+'-') and
                  (recipe!='base' or r['stage'] in (case+'-probe',case+'-measure'))]
            result=dict(case=case,base_um=base,recipe=recipe,generation_complete=bool(generated),metrics=values,
                diagnostic_outputs=diagnostics,gates=checks,human_parts_review=None,
                measurement_complete=bool(generated and all(values.get(k) and values[k].get('complete') for k in
                    ['forward','reverse','projection-front','projection-side','projection-top','views','external-distances','topology'])),
                seconds=sum(r['elapsed_s'] for r in runs),peak_rss_bytes=max((r.get('peak_rss_bytes',0) for r in runs),default=0),
                peak_private_commit_bytes=max((r.get('peak_private_commit_bytes',0) for r in runs),default=0),
                failures=[dict(stage=r['stage'],reason=r.get('reason') or ('exit '+str(r.get('returncode')))) for r in runs
                          if r.get('reason') or r.get('returncode')!=0],
                cache=cache if generated else None,generation=gen,cleanup=cleanup,
                scientific_status='UNAPPROVED',ranking_eligible=False,drag_N=None,Cd=None,CdA_m2=None)
            if generated:
                configuration=dict(base_hashes=read(root/f'v{base}/candidate/cache.json')['output_hashes'],
                    output_hashes=cache['output_hashes'],source_sha256=request['inputs']['source']['sha256'],
                    recipe=None if recipe=='base' else RECIPES[recipe],tool_pins=pins)
                result['configuration_id']='rf-repair-case-'+digest(configuration)
                result['configuration']=configuration
            write(folder/'result.json',result); results[case]=result
    value=dict(results=results,study_finished=state.get('finished',False),
        six_repairs_comparison_complete=all(v['measurement_complete'] for v in results.values() if v['recipe']!='base'),
        inputs_unchanged=state.get('inputs_unchanged'),processing_code_unchanged=state.get('processing_code_unchanged'),
        scientific_status='UNAPPROVED',ranking_eligible=False,human_adoption=None,drag_N=None,Cd=None,CdA_m2=None)
    write(root/'summary.json',value); return value


def plots(root,summary):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    import matplotlib.patches as patches
    reference=read(root/'source-metrics/views.json')['views']
    output=root/'figures'; output.mkdir(exist_ok=True)
    for base in [1000,900]:
        cases=['source',f'v{base}']+[f'v{base}-{r}' for r in RECIPES]
        for label,keys in [('whole-body',['front+','front-','side+','side-','top+','top-']),
                           ('details',[k for k in reference if k.startswith(('face-','hair-'))])]:
            fig,axes=plt.subplots(len(keys),len(cases),figsize=(17,3.1*len(keys)),layout='constrained',squeeze=False)
            for row,key in enumerate(keys):
                info=reference[key]; original=np.load(root/'source-metrics'/(key+'-depth.npy'))
                finite=original[np.isfinite(original)]; lo,hi=float(finite.min()),float(finite.max())
                for col,case in enumerate(cases):
                    ax=axes[row,col]; result=summary['results'].get(case)
                    valid=case=='source' or bool(result['metrics']['views'] and result['metrics']['views'].get('complete'))
                    folder=root/'source-metrics' if case=='source' else root/case/'metrics'
                    if not valid:
                        reason='No completed image measurement'
                        if result['failures']: reason+='\n'+result['failures'][0]['reason']
                        ax.text(.5,.5,textwrap.fill(reason,35),ha='center',va='center',transform=ax.transAxes); ax.axis('off')
                    else:
                        depth=np.load(folder/(key+'-depth.npy')); mask=np.isfinite(depth)
                        image=np.ones((*depth.shape,4)); tone=.6+.35*np.nan_to_num((depth-lo)/max(hi-lo,1e-7),nan=0.)
                        color=np.array([.20,.42,.62] if case=='source' else [.73,.41,.14] if case==f'v{base}' else [.18,.53,.43])
                        image[mask,:3]=np.clip(tone[mask,None]*color,0,1); image[:,:,3]=1
                        ax.imshow(image,origin='lower',extent=info['extent_m'],interpolation='nearest'); ax.set_aspect('equal')
                        if case!='source':
                            lost=np.isfinite(original)&~mask; added=~np.isfinite(original)&mask
                            overlay=np.zeros((*depth.shape,4)); overlay[lost]=[.95,.1,.25,.9]; overlay[added]=[.02,.7,.9,.9]
                            ax.imshow(overlay,origin='lower',extent=info['extent_m'],interpolation='nearest')
                        ax.tick_params(labelsize=6)
                    if row==0: ax.set_title(case.replace('v1000','1mm').replace('v900','0.9mm'),fontsize=10)
                    if col==0: ax.set_ylabel(key,fontsize=9)
            fig.suptitle(f'Saved {base/1000:g} mm full body + surface repairs | Red: lost / Cyan: added\nSame original views and scale. Pixel masks are diagnostics, not continuous distance certification.',fontsize=12)
            fig.savefig(output/f'{base}-{label}.png',dpi=150); plt.close(fig)


def review(root,summary):
    lines=['# 全身候補の微修正試験：1mm・0.9mm','',
        '採用済みオグリキャップ adopted-002 / frame 0。新しいボクセル生成は行わず、保存済み全身2候補に各3方法を適用した。',
        '科学的承認・候補採用は未実施。ランキング対象外。CFDは実行せず、正式なDrag・Cd・CdAはnullのまま。','',
        '## 判定','',
        '|候補|正面面積差|全原本→候補 最大距離の範囲 mm|6方向の可視点 最大 mm|閉じた構造|判定|処理 分|最大コミット GiB|',
        '|---|---:|---:|---:|---|---|---:|---:|']
    for case,r in summary['results'].items():
        m=r['metrics']; area=m.get('projection-front'); distance=m.get('forward'); ext=m.get('external-distances')
        area_text=f"{area['relative_change']*100:+.4f}%" if area and area.get('complete') else '未計測'
        dist='未完了'
        if distance and distance.get('complete'):
            dist=f"{distance['global_max_lower_m']*1000:.3f}–{distance['global_max_upper_m']*1000:.3f}"
        elif distance and distance.get('witness_lower_m'):
            dist=f"少なくとも {distance['witness_lower_m']*1000:.3f}（反例）"
        visible='未計測'
        if ext and ext.get('complete'):
            visible=f"{max(v['max_sampled_m'] for k,v in ext['views'].items() if k in ['front+','front-','side+','side-','top+','top-'])*1000:.3f}"
        checks=r['gates']['checks']
        lines.append(f"|{case}|{area_text}|{dist}|{visible}|{checks['closed_topology']}|{r['gates']['verdict']}|{r['seconds']/60:.2f}|{r['peak_private_commit_bytes']/1024**3:.2f}|")
    lines+=['','最大距離の範囲は面の細分化による被覆幅と2µmの数値余裕を含む。既存全身監査と同じ1mm被覆、問題領域は0.1mm被覆。範囲が2mmをまたぐ場合は未認証。',
        '頭部の既知の大差は、6方向から直接見えない原本の面も含む。6方向から見えないことだけで、完全に閉ざされた内部や空気との接触なしとは断定できない。',
        '今回も全原本の面を距離判定に含める。可視点だけの改善や正面面積だけの合格を、全体の合格に読み替えない。',
        '自己交差は独立した検査記録がない限り未確認。必須部位と隙間の最終確認は人間レビュー待ち。','','## 試した方法','',
        '- nearest25：各頂点を元の最寄り面へ25%だけ戻す。移動上限0.5mm。面の接続を保持。',
        '- normal50：元の最寄り面との差を候補の頂点法線方向へ分解し、50%だけ戻す。移動上限0.5mm。横滑りを抑える。',
        '- detail_union：元の頂点・面中心が候補から1mm超離れ、6方向のいずれかで原本の最初の面として見える三角形を選び、隣接1周を追加。元の面の中央に0.4mm厚の薄い立体を作り、全身候補とExact Booleanの和集合を取る。',
        '0.4mmは復元する薄い面の厚みであり、ボクセル解像度ではない。元の面を根拠にした追加で、平滑化や体格変更・部位の省略はしていない。厚みの指定自体は精度保証ではなく、出力を測定する。',
        '各方法の出力は別保存し、退化面周辺のみ従来の1µm整理を適用した。全身を切り出して再生成する操作はない。','','## 比較画像','',
        '[1mm 全身](figures/1000-whole-body.png) / [0.9mm 全身](figures/900-whole-body.png)',
        '[1mm 問題部位](figures/1000-details.png) / [0.9mm 問題部位](figures/900-details.png)',
        '元の表示方向・縮尺・深度格子を共用。赤は失われた投影部分、水色は追加部分。元の面の色は青、基準候補は茶、修正候補は緑。',
        '隙間の埋まり・外側への開放・周辺の消失は、各候補 metrics/projection-*.json の original_holes と問題領域の *-projection.json に個別保存。これは2D背景領域の比較であり3D通気性の認定ではない。',
        '', '## 根拠と採否','',
        '- [Blender 4.2 Shrinkwrap](https://docs.blender.org/manual/en/4.2/modeling/modifiers/deform/shrinkwrap.html)：元の面へ頂点を寄せる手法の根拠。鋭角・開いた形状の内外判定には不安定さがあるため、今回の微小移動を体積の保証として使わない。',
        '- [Blender 4.2 Solidify](https://docs.blender.org/manual/en/4.2/modeling/modifiers/generate/solidify.html)：ComplexとConstraintsによる薄い立体化。指定した厚さは近似で、交差や体形保持を保証しない。',
        '- [Blender 4.2 Boolean](https://docs.blender.org/manual/en/4.2/modeling/modifiers/generate/booleans.html)：Exactと自己交差対応を使用。開いた入力や非多様体の結果は無条件に信頼できないため別検査する。',
        '- [固定版の設定実装](https://github.com/blender/blender/blob/d0cbe84903e8550c66247e96f9703f60e4b7c3b7/source/blender/makesrna/intern/rna_modifier.cc)：使用版4.2.23のコミットと設定名を確認。新しいBlenderのManifold Solverを4.2の機能と混同しない。',
        '- [CGAL Alpha Wrapping](https://doc.cgal.org/latest/Alpha_wrap_3/index.html)：壊れた三角形群を閉じた包絡面で包む別方式も調査した。ただし新たな全身包絡面の生成になり、内部面の保持や今回の両方向2mmを自動的に保証しない。今回の保存済み候補の局所修正には採用していない。',
        '- [Manifold作者による入力条件の説明](https://github.com/elalish/manifold/discussions/471)：高速Booleanも非多様体の原本をそのまま受け入れる万能修復ではない。まず体積の内外を定義できる面の構造が必要になるため、今回の代替実装には追加していない。',
        '調査にはagent-reachのExaとGitHub CLIを使用。Blender資料は4.2に限定し、現在版CGALは代替方式の特性調査にのみ使用した。Jinaの取得はホストのTLS資格情報エラーで失敗した。',
        '', '## 実行と追跡','',
        '入力・候補・処理コード・実行ファイルをSHA-256で関連付ける。設定IDに絶対パスや実行日時は含めない。原本の変更は停止条件。',
        '上限は実処理合計12時間、生成は各30分、計測は各75分。最大80GiBのプライベートコミット、空きRAM8GiB、コミット余裕16GiB、E50/C20/D15GiBの空き容量を監視。今回のCPU上限24論理コア。',
        '上限到達は失敗として記録し、自動再試行しない。生成・計測・画像・人間承認を分け、未完了はnull/UNVERIFIEDとする。',
        '詳細は summary.json、各候補 result.json、execution.json、*.resources.jsonl、artifact-sha256.json を参照。',
        'Eドライブの形状・画像・数値は非公開。実装の初期セットアップで止まった fullbody-repair-001/002 では修正形状を生成しておらず、記録を残している。']
    for case,r in summary['results'].items():
        if r['failures']:
            lines+=['',f'### {case} の実行制限・失敗']+[f"- {x['stage']}: {x['reason']}" for x in r['failures']]
    (root/'REVIEW.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True); a=p.parse_args()
    summary=summarize(a.root); plots(a.root,summary); review(a.root,summary)
    # Exclude live controller outputs from this stable artifact manifest.
    paths=[p for p in a.root.rglob('*') if p.is_file() and not any(s in p.parts for s in ('scratch',)) and
           p.name not in ['artifact-sha256.json','execution.json','report.log','report.resources.jsonl']]
    write(a.root/'artifact-sha256.json',dict(files={p.relative_to(a.root).as_posix():file_sha(p) for p in paths},
        exclusions=['execution.json','report.log','report.resources.jsonl','scratch/'],scientific_status='UNAPPROVED'))
    print('REPAIR_REVIEW_COMPLETE',flush=True)


if __name__=='__main__': main()
