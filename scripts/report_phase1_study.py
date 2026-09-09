"""Private, versioned sensitivity report; missing and failed trials stay visible."""
import argparse
from pathlib import Path
import sys
REPO=Path(__file__).resolve().parents[1];sys.path.insert(0,str(REPO/'src'))
from runflow.core import read,write,file_hash
from runflow.sensitivity import read_case,compare,richardson_equal_ratio
from runflow.cfd_paths import is_private


def report(root,output):
    root=root.resolve();output=output.resolve()
    if not is_private(root) or not output.is_relative_to(root):raise ValueError('Private campaign output required')
    output.mkdir(exist_ok=False)
    request=read(root/'request.json');ledger=read(root/'campaign.json')
    cases={'baseline':read_case(request['source_root'])};paths={'baseline':Path(request['source_root'])}
    for trial in ledger['attempts']:
        folder=root/trial['label']
        if trial['result_sha256']!=file_hash(folder/'result.json'):raise ValueError('Campaign result hash changed')
        cases[trial['case_id']]=read_case(folder);paths[trial['case_id']]=folder
    comparisons={}
    for purpose,names,target in [('advection',['baseline','advection-linear','advection-limited'],.03),
                                ('mesh',['mesh-fine','baseline','mesh-coarse'],.03),
                                ('domain',['baseline','domain-medium','domain-large'],.01)]:
        available=[cases[n] for n in names if n in cases]
        value=compare(available,purpose,target) if len(available)>1 else dict(status='INCOMPLETE',numerical_target_met=False)
        value['not_run']=[n for n in names if n not in cases]
        if value['not_run']:value.update(status='INCOMPLETE',numerical_target_met=False)
        if purpose=='mesh':
            value['GCI']=(richardson_equal_ratio([cases[n]['CdA_m2'] for n in names],1.25)
                if all(n in cases and cases[n]['status']=='PASS' for n in names) else dict(status='INCOMPLETE',fine_GCI_rel=None))
        comparisons[purpose]=value
    # Hash all resulting processor meshes to test actual same-grid evidence,
    # rather than claiming a deterministic mesher from equal dictionaries alone.
    base=paths['baseline']/'case';grid_comparisons={}
    for name in ('advection-linear','advection-limited'):
        if name not in paths:continue
        items={}
        for rank in range(4):
            for filename in ('points','faces','owner','neighbour','boundary'):
                rel=Path(f'processor{rank}/constant/polyMesh')/filename
                a,b=base/rel,paths[name]/'case'/rel
                items[rel.as_posix()]=dict(baseline=file_hash(a),candidate=file_hash(b)) if a.is_file() and b.is_file() else None
        grid_comparisons[name]=dict(files=items,identical=len(items)==20 and all(x and x['baseline']==x['candidate'] for x in items.values()))
    summary=dict(schema_version='phase1-sensitivity-report-1',comparisons=comparisons,
        actual_advection_mesh_comparisons=grid_comparisons,campaign_ledger_sha256=file_hash(root/'campaign.json'),
        solver_campaign_compute_s=ledger['consumed_compute_s'],phase1_complete=False,
        cycle_CdA_m2=None,scientific_approval=None,ranking_eligible=False,
        note='Full-cycle CFD and shape fidelity acceptance remain unresolved; converged provisional single pose is not final accuracy.')
    write(output/'summary.json',summary)
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,1,figsize=(11,8),sharex=True)
    lines=['# Phase 1 数値感度：中間記録','','正式な係数は収束条件を通過した試行だけに保存する。未収束の力は下図の診断用履歴としてのみ表示する。',
           '', '| 条件 | 実行判定 | セル数 | 正式CdA (m²) |','|---|---|---:|---:|']
    for name,case in cases.items():
        path=paths[name];force=path/'force-history.json';res=path/'residual-history.json'
        if force.exists():
            values=read(force);axes[0].plot([v['iteration'] for v in values],[v['drag_N'] for v in values],label=name+' / '+case['status'],lw=1)
        if res.exists():
            values=read(res)
            if isinstance(values,dict):
                pairs=[(float(k),v['p']) for k,v in values.items() if 'p' in v]
                if pairs:axes[1].semilogy(*zip(*pairs),label=name,lw=1)
        mesh=case['mesh'] or {};cda='null' if case['CdA_m2'] is None else f'{case["CdA_m2"]:.9f}'
        lines.append(f'| {name} | {case["status"]} | {mesh.get("cells","未完了")} | {cda} |')
    axes[0].set_ylabel('Diagnostic Drag (N)');axes[0].legend(fontsize=8);axes[0].grid(alpha=.25)
    axes[1].axhline(1e-4,color='black',ls='--',label='pressure gate');axes[1].set_ylabel('Initial pressure residual')
    axes[1].set_xlabel('Solver iteration (not animation time)');axes[1].legend(fontsize=8);axes[1].grid(alpha=.25)
    fig.suptitle('Phase 1 sensitivity — unconverged curves are diagnostics only');fig.tight_layout();fig.savefig(output/'histories.png',dpi=150);plt.close(fig)
    lines+=['','![力と残差の履歴](histories.png)','','## 判定',
            '',*['- '+k+': '+v['status']+'。未実行: '+(', '.join(v['not_run']) or 'なし') for k,v in comparisons.items()],
            '',f'このキャンペーンのCFD実行時間: {ledger["consumed_compute_s"]/60:.1f}分。Unity/Blender等の補助処理は別記録で、24時間枠内に1時間分を予約する。',
            '', '全周期CFD・メッシュ/領域/方式感度・形状忠実度の承認が揃うまでPhase 1全体は未完了。科学的承認はnull、ランキング対象外。',
            '', '原本・既存の収束済み結果・2mm/1%の形状基準を変更していない。欠落Gallop.CharaTransformProcessDataと公式との完全一致は未確認。']
    (output/'REVIEW.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    write(output/'artifact-hashes.json',{p.name:file_hash(p) for p in output.iterdir() if p.is_file()})
    print('SENSITIVITY_REPORT_SAVED',output,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();report(a.root,a.output)
