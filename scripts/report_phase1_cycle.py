"""Build the private Japanese report for a completed or bounded cycle run."""

import argparse
import math
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from runflow.core import file_hash, read, write
from runflow.cfd_paths import is_private
from runflow.gait_cycle import sampling_comparison


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _result_row(frame, attempt, root):
    if attempt is None:
        return dict(phase_index=frame, execution_status="NOT_RUN", drag_N=None, CdA_m2=None,
                    source_area_m2=None, comparison_family_sha256=None, result_sha256=None)
    folder = root / attempt["label"]
    result_path = folder / "result.json"
    if attempt.get("result_sha256") != file_hash(result_path):
        raise ValueError("Cycle result hash changed at frame " + str(frame))
    result = read(result_path)
    if result.get("execution_status") != attempt.get("status"):
        raise ValueError("Cycle ledger/result status mismatch at frame " + str(frame))
    return dict(phase_index=frame, execution_status=result.get("execution_status"),
                drag_N=result.get("drag_N"), CdA_m2=result.get("CdA_m2"),
                source_area_m2=result.get("source_area_m2"),
                comparison_family_sha256=result.get("comparison_family_sha256"),
                result_sha256=attempt.get("result_sha256"), phase_time_s=result.get("phase_time_s"),
                clip_phase_s=result.get("clip_phase_s"), output_bytes=attempt.get("output_bytes"),
                elapsed_s=attempt.get("execution", {}).get("elapsed_s"))


def report(root, output):
    root = Path(root).resolve()
    output = Path(output).resolve()
    if not is_private(root) or not output.is_relative_to(root):
        raise ValueError("Private cycle output and nested report directory are required")
    if output.exists():
        raise ValueError("Fresh cycle report output required")
    request = read(root / "request.json")
    ledger = read(root / "campaign.json")
    attempts = {int(row["phase_index"]): row for row in ledger.get("attempts", [])}
    skipped = {int(row["phase_index"]): row for row in ledger.get("skipped", [])}
    if set(attempts) & set(skipped):
        raise ValueError("A cycle frame cannot be both attempted and skipped")
    rows = []
    for frame in range(int(request["frame_count"])):
        if frame in attempts:
            rows.append(_result_row(frame, attempts[frame], root))
        elif frame in skipped:
            item = skipped[frame]
            rows.append(dict(phase_index=frame, execution_status=item.get("status", "NOT_RUN"), drag_N=None,
                             CdA_m2=None, source_area_m2=None, comparison_family_sha256=None,
                             result_sha256=None, skip_reason=item.get("reason")))
        else:
            rows.append(_result_row(frame, None, root))
    for row in rows:
        if row["execution_status"] == "PASS":
            for key in ("drag_N", "CdA_m2", "source_area_m2"):
                if not _finite(row.get(key)) or float(row[key]) <= 0:
                    raise ValueError("PASS cycle row has invalid formal data at frame " + str(row["phase_index"]))
    sampling = sampling_comparison(rows)
    prior_root = Path(request["prior_campaign_root"]).resolve()
    prior_summary = prior_root / "report-final-001" / "summary.json"
    sensitivity = None
    if prior_summary.exists():
        sensitivity = read(prior_summary)
    sensitivity_complete = bool(sensitivity) and all(
        isinstance(value, dict) and value.get("numerical_target_met") is True
        for value in sensitivity.get("comparisons", {}).values())
    cycle_complete = sampling["aggregates"]["32"]["status"] == "COMPLETE_NUMERICAL_ONLY"
    shape_fidelity = "UNRESOLVED"
    phase1_complete = cycle_complete and sensitivity_complete and shape_fidelity == "PASS"
    output.mkdir(parents=True, exist_ok=False)
    summary = dict(
        schema_version="phase1-cycle-report-1",
        campaign_ledger_sha256=file_hash(root / "campaign.json"),
        request_sha256=file_hash(root / "request.json"),
        source_manifest_sha256=request["source_manifest_sha256"],
        prior_sensitivity_summary_sha256=file_hash(prior_summary) if prior_summary.exists() else None,
        frame_count=len(rows),
        pass_count=sum(row["execution_status"] == "PASS" for row in rows),
        failed_or_unconverged=[row["phase_index"] for row in rows if row["execution_status"] not in ("PASS",)],
        rows=rows,
        sampling=sampling,
        sensitivity=dict(status="COMPLETE" if sensitivity_complete else "INCOMPLETE",
                         summary_sha256=file_hash(prior_summary) if prior_summary.exists() else None),
        shape_fidelity_status=shape_fidelity,
        cycle_complete=cycle_complete,
        phase1_complete=phase1_complete,
        scientific_approval=None,
        ranking_eligible=False,
        note="Cycle coefficients are numerical smoke evidence under the fixed provisional geometry; they are not scientific approval or ranking data.",
    )
    write(output / "summary.json", summary)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    colors = {"PASS": "#2a7f62", "NOT_CONVERGED": "#d98c18", "FAIL": "#c23b3b",
              "TIMEOUT": "#7c4d9f", "BLOCKED": "#555555", "NOT_RUN": "#999999",
              "NOT_RUN_BUDGET": "#777777", "NOT_RUN_RESOURCE": "#777777"}
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True, layout="constrained")
    for row in rows:
        x = row["phase_index"]
        status = row["execution_status"]
        if _finite(row.get("CdA_m2")):
            axes[0].scatter([x], [row["CdA_m2"]], color=colors.get(status, "#555555"), s=28)
        axes[1].scatter([x], [1 if status == "PASS" else 0], color=colors.get(status, "#555555"), s=28)
    axes[0].set_ylabel("CdA [m²] (formal PASS only)")
    axes[0].set_title("RunFlow Phase 1 cycle — diagnostic pose results")
    axes[0].grid(alpha=.25)
    axes[1].set_ylabel("PASS")
    axes[1].set_yticks([0, 1], ["other", "PASS"])
    axes[1].set_xlabel("Animation phase index; solver iteration is stored separately")
    axes[1].grid(alpha=.25)
    fig.savefig(output / "cycle.png", dpi=160)
    plt.close(fig)
    lines = [
        "# RunFlow Phase 1 全周期CFDレビュー",
        "",
        "採用済みオグリキャップ（シンデレラグレイ）の通常走行候補を、32姿勢・0.9 mm全身表面・同一OpenFOAM条件で順番に処理した記録。",
        "",
        f"- 32姿勢の正式結果: {summary['pass_count']}/32",
        f"- 周期計算: {'完了' if cycle_complete else '未完了'}。欠落・失敗値から平均を補っていない。",
        f"- 8/16/32比較の数値判定: {'達成' if sampling['numerical_target_met'] else '未達／未完了'}",
        f"- 既存の数値感度試験: {'完了' if sensitivity_complete else '未完了'}",
        f"- 形状忠実度: {shape_fidelity}",
        f"- Phase 1全体: {'完了' if phase1_complete else '未完了'}。科学的承認はnull、ランキング対象外。",
        "",
        "![姿勢別CdA](cycle.png)",
        "",
        "## 姿勢別結果",
        "",
        "| 位相 | 実行判定 | Drag (N) | CdA (m²) | 処理時間 (s) |",
        "|---:|---|---:|---:|---:|",
    ]
    for row in rows:
        drag = f"{row['drag_N']:.6g}" if _finite(row.get("drag_N")) else "null"
        cda = f"{row['CdA_m2']:.9g}" if _finite(row.get("CdA_m2")) else "null"
        elapsed = f"{row['elapsed_s']:.1f}" if _finite(row.get("elapsed_s")) else "null"
        lines.append(f"| {row['phase_index']} | {row['execution_status']} | {drag} | {cda} | {elapsed} |")
    lines += [
        "",
        "## 周期集計",
        "",
        "```json",
        __import__("json").dumps(sampling, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 判断と制約",
        "",
        "- 0.9 mm表面はユーザー承認済みの暫定入力で、原本との双方向2 mm形状許容差は未達のまま保持している。髪・耳・尻尾・衣装・手足の削除や体格変更は行っていない。",
        "- 服と脚の交差は採用時レビューの記録どおり残している。公式挙動との完全一致、Gallop.CharaTransformProcessDataの役割、Steamクライアント全体のメタデータ一致は未確認。",
        "- 各姿勢のゲーム時刻・クリップ位相と、CFDの反復番号は別項目で保存している。欠測・未収束・タイムアウトのDrag/Cd/CdAはnull。",
        "- 前回の領域感度、移流方式、格子感度の不足は別の感度レポートに残し、全周期の完了だけでPhase 1全体完了とはしていない。",
        "- 圧力・速度のVTKと力・残差履歴は各フレームの非公開ディレクトリに保持する。",
    ]
    (output / "REVIEW.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    hashes = {path.relative_to(output).as_posix(): file_hash(path) for path in output.rglob("*")
              if path.is_file() and path.name != "artifact-hashes.json"}
    write(output / "artifact-hashes.json", hashes)
    print("PHASE1_CYCLE_REPORT_SAVED", output, flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report(args.root, args.output)


if __name__ == "__main__":
    main()
