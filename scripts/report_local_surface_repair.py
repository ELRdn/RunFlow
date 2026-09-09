"""Private Japanese handoff; no geometry/metrics enter public output."""
import argparse
import html
from pathlib import Path
import sys
import shutil
import numpy as np
REPO=Path(__file__).resolve().parents[1];sys.path.insert(0,str(REPO/'src'))
from runflow.shape_fullbody import read,write
from runflow.shape_audit import file_sha,load_surface
from runflow.local_repair_contract import candidate_verdict


def option(record,key):
    args=record.get('command',[])
    return args[args.index(key)+1] if key in args else None


def maybe(path):return read(path) if path.exists() else None


def measurement_record(root,selected,record):
    path=root/'runs'/record['label']/'result.json'
    part=option(record,'--part')
    if part in ('views','sections'):
        path=root/'verification'/selected/selected/'metrics'/(part+'.json')
    value=maybe(path)
    return dict(stage_complete=bool(record.get('complete')),result=value if record.get('complete') else None,
        diagnostic_partial_result=value if not record.get('complete') else None)


def collect(root,selected):
    execution=read(root/'execution.json');request=read(root/'request.json');results=[]
    for path in sorted((root/'candidates').glob('*/recipe.json')):
        folder=path.parent;name=folder.name;state=read(folder/'state.json');runs=[r for r in execution['records'] if r.get('label')==name]
        inspection=maybe(folder/'intersections.json');screen=maybe(folder/'screening.json');topology=maybe(folder/'topology.json')
        # Early stage state files recorded the native result alone. The consolidated
        # report always retains the independent OpenFOAM cross-check as pending.
        checks=dict(state.get('checks',{}))
        if checks.get('intersection')=='PASS':checks['intersection']='UNVERIFIED'
        results.append(dict(name=name,recipe=read(path),state=state,checks=checks,
            generation_stage_complete=any(r.get('complete') for r in runs),inspection=inspection,screening=screen,topology=topology,
            seconds=sum(r['elapsed_s'] for r in runs),peak_rss_bytes=max((r.get('peak_rss_bytes',0) for r in runs),default=0),
            peak_private_commit_bytes=max((r.get('peak_private_commit_bytes',0) for r in runs),default=0),
            source_and_result_hashes=maybe(folder/'candidate/cache.json'),openfoam_cross_check='NOT_RUN_WSL_ACCESS_UNAVAILABLE'))
    measurements={}
    for r in execution['records']:
        if r.get('task')!='verify' or option(r,'--candidate')!=selected:continue
        key='-'.join(x for x in (option(r,'--part'),option(r,'--direction'),option(r,'--region')) if x)
        measurements[key]=measurement_record(root,selected,r)
    metrics=root/'verification'/selected/selected/'metrics'
    for view in ('front','side','top'):
        p=metrics/('projection-'+view+'.json')
        valid=any(r.get('complete') and r.get('task')=='verify' and option(r,'--candidate')==selected and option(r,'--part')=='projection' for r in execution['records'])
        measurements['projection-'+view]=maybe(p) if valid else None
    precision=read(root/'runs/fullbody-diagnosis/precision-attribution.json')
    classified=read(root/'runs/defect-sides/classified-sides.json')
    chosen=next(c for c in results if c['name']==selected)
    checks=dict(chosen['checks'])
    evidence_complete=any(r.get('complete') and r.get('task')=='finish-evidence' and option(r,'--selected')==selected for r in execution['records'])
    comparison=maybe(root/'runs/final-comparison-evidence/comparison.json') if evidence_complete else None
    outside=maybe(root/'runs/final-comparison-evidence/outside-region.json') if evidence_complete else None
    checks['outside_region']='PASS' if outside and outside.get('continuous_cross_boundary_fragments_verified') and outside.get('outside_faces_identical') and outside.get('outside_vertices_identical') else 'UNVERIFIED'
    area=measurements.get('projection-front')
    checks['area']='PASS' if area and area.get('complete') and abs(area['relative_change'])<=.01 else 'FAIL' if area and area.get('complete') else 'UNVERIFIED'
    quality=measurements.get('quality',{}).get('result')
    if quality and quality.get('complete') and quality['existing_area_quality_gate']=='FAIL':checks['topology']='FAIL'
    forward=measurements.get('distance-forward',{}).get('result');reverse=measurements.get('distance-reverse',{}).get('result')
    if forward and reverse and forward.get('complete') and reverse.get('complete'):
        checks['distance']='FAIL' if max(forward['global_max_lower_m'],reverse['global_max_lower_m'])>.002 else 'PASS' if max(forward['global_max_upper_m'],reverse['global_max_upper_m'])<=.002 else 'UNVERIFIED'
    ca=read(root/'candidates/combined-repro-a/candidate/cache.json');cb=read(root/'candidates/combined-repro-b/candidate/cache.json')
    ea=read(root/'runs/combined-repro-a/execution.json');eb=read(root/'runs/combined-repro-b/execution.json')
    reproduction=dict(arrays_sha256_match=ca['output_hashes']==cb['output_hashes'],
        configuration_ids_match=read(root/'candidates/combined-repro-a/recipe.json')['configuration_id']==read(root/'candidates/combined-repro-b/recipe.json')['configuration_id'],
        generation_code_pins_match=ea['code_pins']==eb['code_pins'],tool_pins_match=ea['tool_pins']==eb['tool_pins'],
        both_runs_complete=ea['complete'] and eb['complete'])
    result=dict(selected_for_detailed_measurement=selected,selection_is_not_adoption=True,candidates=results,
        selected_gate=candidate_verdict(checks),reproduction=reproduction,
        measurements=measurements,precision=precision,defect_components=classified['components'],comparison=comparison,outside_region=outside,
        elapsed_s=sum(r['elapsed_s'] for r in execution['records']),
        peak_rss_bytes=max((r.get('peak_rss_bytes',0) for r in execution['records']),default=0),
        peak_private_commit_bytes=max((r.get('peak_private_commit_bytes',0) for r in execution['records']),default=0),
        configuration_id=request['configuration_id'],scientific_status='UNAPPROVED',ranking_eligible=False,
        human_adoption=None,drag_N=None,Cd=None,CdA_m2=None,
        pending=['OpenFOAM independent checker disagreement and new candidate recheck',
            'Human source-part and seam selections', 'Unprocessed original-surface defect regions',
            'Visible sampled distance over 2mm', 'Near-degenerate triangle quality', 'Continuous cross-boundary fragments',
            'Final E-drive delivery until hash-verified copy'])
    return result


def plots(root,out,selected):
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    old=Path(read(root/'request.json')['source_study']);meta=read(old/'source-metrics/views.json')['views']
    folders=[old/'source-metrics',old/'v900/metrics',root/'verification'/selected/selected/'metrics']
    names=['Original','Saved 0.9 mm',selected]
    for filename,keys in [('whole-body.png',['front+','front-','side+','side-','top+','top-']),
            ('details.png',['face-visible','hair-visible','hair-gap'])]:
        fig,axes=plt.subplots(len(keys),3,figsize=(12,3.5*len(keys)),layout='constrained',squeeze=False)
        for row,key in enumerate(keys):
            info=meta[key];original=np.load(folders[0]/(key+'-depth.npy'));lo=np.nanmin(original);hi=np.nanmax(original)
            for col,(folder,name) in enumerate(zip(folders,names)):
                ax=axes[row,col];path=folder/(key+'-depth.npy')
                if not path.exists():ax.text(.5,.5,'No completed view',ha='center',transform=ax.transAxes);ax.axis('off');continue
                depth=np.load(path);mask=np.isfinite(depth);rgb=np.ones((*depth.shape,4))
                shade=.6+.35*np.nan_to_num((depth-lo)/max(float(hi-lo),1e-7),nan=0)
                color=np.array([[.20,.42,.62],[.73,.41,.14],[.18,.53,.43]][col]);rgb[mask,:3]=np.clip(shade[mask,None]*color,0,1)
                ax.imshow(rgb,origin='lower',extent=info['extent_m'],interpolation='nearest')
                if col:
                    overlay=np.zeros((*depth.shape,4));overlay[np.isfinite(original)&~mask]=[.95,.1,.25,.9];overlay[~np.isfinite(original)&mask]=[.02,.7,.9,.9]
                    ax.imshow(overlay,origin='lower',extent=info['extent_m'],interpolation='nearest')
                ax.set_aspect('equal');ax.set_title(name if row==0 else key,fontsize=9);ax.tick_params(labelsize=7)
                if col==0:ax.set_ylabel(key)
        fig.suptitle('Fixed whole-body views | Red: lost silhouette / Cyan: added silhouette\nDepth measurements; no smoothing or image-generated geometry',fontsize=12)
        fig.savefig(out/filename,dpi=160);plt.close(fig)


def report(root,selected):
    root=Path(root).resolve();out=root/'review';out.mkdir(exist_ok=False)
    summary=collect(root,selected);plots(root,out,selected)
    shutil.copyfile(root/'runs/fullbody-diagnosis/counterexample-sections.png',out/'counterexample-sections.png')
    candidates=summary['candidates'];generated=[x for x in candidates if x['state'].get('generation')=='COMPLETE']
    selected_result=next(x for x in candidates if x['name']==selected)
    comparison=summary['comparison'];visible=comparison['current_visible']['views'];before=comparison['base_visible']['views']
    whole_views=('front+','front-','side+','side-','top+','top-')
    visible_before=max(before[k]['max_sampled_m'] for k in whole_views)*1000
    visible_after=max(visible[k]['max_sampled_m'] for k in whole_views)*1000
    gap_before=comparison['baseline_gap']['gap_filled_fraction']*100
    gap_after=comparison['current_gap']['gap_filled_fraction']*100
    front=summary['measurements']['projection-front']['relative_change']*100
    lines=['# 0.9mm全身・局所修正の検証結果','',
        '**現行の許容範囲には未到達。CFD用形状の採用は行っていない。**',
        '新しいボクセル再生成はせず、保存済み0.9mmを使って局所操作を比較した。0.8mm以下の再生成、CFD、許容差変更、公開・pushは行っていない。','',
        f'修正試行 {len(candidates)} 件、全身候補の生成・スクリーニング完了 {len(generated)} 件。詳しい比較対象は `{selected}`。これは調査対象の選択で、候補採用ではない。','',
        f"二重生成：配列SHA一致={summary['reproduction']['arrays_sha256_match']}、設定ID一致={summary['reproduction']['configuration_ids_match']}、処理コード一致={summary['reproduction']['generation_code_pins_match']}、ツール一致={summary['reproduction']['tool_pins_match']}。",'',
        '## 判断に必要な比較','',
        '|項目|保存済み0.9mm → 今回の修正候補|判定・範囲|',
        '|---|---|---|',
        f'|全身6方向で見える原本面の距離・観測最大|{visible_before:.3f} → {visible_after:.3f} mm|改善したが2mm超過。外面全体の連続最大値ではない|',
        f'|顔の拡大観測・最大|{before["face-visible"]["max_sampled_m"]*1000:.3f} → {visible["face-visible"]["max_sampled_m"]*1000:.3f} mm|2mm超過|',
        f'|髪の拡大観測・最大|{before["hair-visible"]["max_sampled_m"]*1000:.3f} → {visible["hair-visible"]["max_sampled_m"]*1000:.3f} mm|2mm超過|',
        f'|調査中の髪の隙間が埋まった割合|{gap_before:.2f} → {gap_after:.2f}%|投影上の元の隙間に対する面積比。ゼロにはなっていない|',
        f'|修正候補の正面投影面積|原本比 {front:+.4f}%|1%以内|','',
        '全身と拡大画像は観測点の密度が異なるので、最大値が同じになるとは限らない。同じ観測点同士で変更前後を比較した。隙間周辺の消失面積はほぼ残り、埋まりの改善だけで部位保持や3Dの通気経路を認定しない。','',
        '## まず分かったこと','',
        '- 診断再実行では、差集合直後とMesh64取り込み後に交差がなくても、全身簡略化と丸めで交差が生じた。新しい切り戻しは、その後処理を外してfloat64で保存した。',
        '- 原本を切らない切削体を連続面で検査しても、原本全表面との2mm条件に自動的に合格するわけではない。',
        '- 内側に見える原本部品も現行の距離判定に含む。断面図の黒い印はその反例であり、外側輪郭全体がその距離だけ動いたという意味ではない。',
        '- CGALと以前のOpenFOAM検査の不一致は残っている。新しい候補のOpenFOAM検査は未実施。部位・隙間・境界対応の人間レビューも未承認。','',
        '## 試行ごとの結果','',
        '|試行|生成・適用|原本全表面の反例下限 mm|CGAL交差対|閉じた多様体|時間 分|理由|',
        '|---|---|---:|---:|---|---:|---|']
    for c in candidates:
        state=c['state'];screen=c['screening'];coll=c['inspection'];topo=c['topology']
        distance=f"{screen['maximum_lower_m']*1000:.3f}" if screen else '未計測'
        lines.append(f"|{c['name']}|{state.get('generation')}|{distance}|{coll['intersection_pairs'] if coll else '未計測'}|{topo['closed_manifold'] if topo else '未計測'}|{c['seconds']/60:.2f}|{state.get('reason','')}|")
    lines+=['','反例は原本の頂点と面中心の検査。全身の最大値を測り切ったという意味ではなく、2mm不合格を示す下限である。PRECONDITION_FAILEDは接続・表裏などの前提が満たせなかった記録で、形状を生成し終えた記録ではない。','',
        '## 精度工程の切り分け','',
        '|状態|CGAL交差対|','|---|---:|']
    for r in summary['precision']['stages']:lines.append(f"|{r['surface']}|{r['inspection']['intersection_pairs']}|")
    lines+=['','これは保存済みBoolean出力からの診断再実行。過去に保存していなかったメモリ内状態まで一致したとは主張しない。以前の完成形状と今回の再取り込み結果が一致しないことも記録している。',
        f"同じ三角形を保ったfloat64→float32変換の頂点移動上限は {summary['precision']['maximum_corresponding_vertex_rounding_m']*1e6:.6f}µm。移動が微小でも、接近した面の交差状態は変わり得る。",'',
        '## 詳細計測','',
        '|検査|完了・値|','|---|---|']
    for key,value in summary['measurements'].items():
        if value is None:lines.append(f'|{key}|未完了|');continue
        r=value.get('result',value)
        if r and r.get('complete'):
            text=(f"{r['global_max_lower_m']*1000:.3f}–{r['global_max_upper_m']*1000:.3f} mm" if 'global_max_lower_m' in r else
                f"面積差 {r['relative_change']*100:+.4f}%" if 'relative_change' in r else '完了（詳細はJSON）')
            if 'near_degenerate_triangles' in r:text=f"極小三角形 {r['near_degenerate_triangles']} 枚、面積品質判定 {r['existing_area_quality_gate']}"
        elif value.get('stage_complete'):text='工程完了（個別の計測JSONを参照）'
        else:text='未完了'
        lines.append(f'|{key}|{text}|')
    lines+=['','距離は全身1mm・問題領域0.1mmの被覆半径と2µmの数値余裕。面積ゼロの面は統計上の重みがゼロだが、その点・線は距離の最大値・上下限から除外していない。投影格子1nmは計算規約であり原本の物理精度ではない。','',
        f"原本の固定頂点による別の反例下限は {selected_result['screening']['maximum_lower_m']*1000:.3f}mm。全身細分の下限とは観測点が違うため、この反例の方が強い。いずれも内側の面を含み、見える外形の差と混同しない。",
        f"原本の深度図は9視点すべてを再生成して配列SHAの一致を確認した。作業領域に全く重ならない三角形 {summary['outside_region']['original']['wholly_outside_faces']:,} 枚と領域外の使用頂点は、保存済み0.9mmと完全一致した。作業領域の境界をまたぐ三角形の外側断片は連続面として未検証なので、領域外保持の総合判定は未確認のままとする。",'',
        '## 比較画像','',
        '![全身6方向](whole-body.png)','', '![顔・髪・隙間](details.png)','',
        '![原本の固定反例と断面](counterexample-sections.png)','',
        '## 人間レビューと残件','',
        '元snapshotには部位名の一覧があるが、各三角形の意味付き部位名はない。連結部品・面番号・断面・視線の記録を基に、復元すべき原本面と境界の組合せを確認する必要がある。自由なスカルプトや推測形状は追加していない。',
        '全身の欠陥台帳のうち未処理の領域は残っている。上限24設定に達したため、6系統の全組合せ・全箇所をやり尽くしたという結論ではない。法線の向きを明示してそろえる張り替え、接続部の再三角形化、極小面の局所整理など、自動処理として未検証の選択肢も残る。',
        '0.05mm観測格子、位置補正の5回反復、薄い部品の0.1mm厚、1mmでの追加試行は未実行。薄い部品は0.4mmと0.2mmで交差解消が見られなかった。これらを検証済み・一般に不可能とは記載しない。',
        '部位の意味や対応する境界を一意に定められない箇所、原本の内側に見える面をどの研究対象として扱うかは、人間レビューに残す。',
        '人間レビューは `human-review.json`、再実行できる面・境界の選択は `manual-selection.template.json` に保存する。テンプレートの原本面番号は整理済み入力を参照する。選択の承認欄は未入力であり、候補採用や科学的承認を意味しない。',
        '`scripts/replay_local_surface_selection.py` に選択を渡すと、ハッシュ・面番号・境界・表裏を検証してから接続する。実データの人間選択は未実施。今回の24設定は使い切ったため、この方式の実試行は次回の承認済み試験で行う。','',
        '## 実行費用と保存','',
        f"報告開始までの実処理 {summary['elapsed_s']/60:.2f} 分。最大RSS {summary['peak_rss_bytes']/1024**3:.2f}GiB、最大プライベートコミット {summary['peak_private_commit_bytes']/1024**3:.2f}GiB。実装・ビルド・合成テストは別。最終値はexecution.jsonを参照。",
        '処理時間は各工程で記録した値の累積。初期工程の一部の起動前ハッシュ確認、ツール導入、最終台帳作成・コピーは別計上で、作業全体の経過時間ではない。保存容量は最終artifact-sha256.json、台帳工程の時間はfinalization.json、コピー結果はE-copy-verification.jsonを参照する。',
        '実際の入力・出力・実行ファイル・コードのハッシュは、各runの記録と最終artifact-sha256.jsonで追跡する。実行日時とローカル絶対パスは設定IDから分離する。',
        '本試験はDの非公開領域に一時保存。Eへの書き込みは自動承認レビューが時間切れとなったため、ハッシュ照合したコピーが完了するまでE保存済みとはしない。',
        '科学的状態はUNAPPROVED、ranking_eligible=false、Drag/Cd/CdA=null。欠落Gallop.CharaTransformProcessDataの役割と公式形状との完全一致も未確認。']
    (out/'REVIEW.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    write(out/'summary.json',summary)
    requests=[dict(candidate=c['name'],reason=c['state'].get('reason'),details=c['state'].get('details'),
        original_face_selection=None,boundary_correspondence=None,decision=None) for c in candidates if c['state'].get('generation')=='PRECONDITION_FAILED']
    write(out/'human-review.json',dict(scientific_approval=None,selected_candidate=None,required_parts=None,gaps=None,
        source_internal_surface_definition_change=None,ai_may_set_human_decision=False,requests=requests))
    inputs=read(root/'request.json')['input_surfaces']
    write(out/'manual-selection.template.json',dict(kind='runflow_local_face_selection_v1',approval_scope='FACE_AND_BOUNDARY_SELECTION_ONLY',
        decision=None,reviewer=None,source_cache_sha256=inputs['cleaned']['cache_sha256'],base_cache_sha256=inputs['base900']['cache_sha256'],
        source_face_ids=None,base_face_ids=None,source_boundary=None,base_boundary=None,reverse_source_winding=None,low_m=None,high_m=None))
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>RunFlow 局所修正レビュー</title><style>body{max-width:1150px;margin:3rem auto;padding:0 2rem;font:17px/1.8 system-ui;color:#223047;background:#f7fafc}img{width:100%;background:white;border:1px solid #dce4eb}a{color:#126582}h1{font-size:28px}p{max-width:850px}</style><h1>0.9mm全身：局所修正の比較</h1><p>現行の許容範囲には未到達。候補採用・科学的承認は未実施。</p><p><a href="REVIEW.md">日本語の詳しい報告</a> · <a href="summary.json">数値と検証状態</a> · <a href="human-review.json">人間レビュー項目</a></p>'+''.join('<h2>'+title+'</h2><img src="'+name+'">' for title,name in [('全身：原本・0.9mm・修正候補','whole-body.png'),('顔・髪・隙間','details.png'),('外形差と区別すべき原本部品の反例','counterexample-sections.png')]),encoding='utf-8')
    print('LOCAL_REPAIR_REVIEW_READY',str(out),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--selected',required=True);a=p.parse_args();report(a.root,a.selected)
