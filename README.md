# RunFlow

> **From Fiction to Physics.**  
> **空想を、科学へ。**

RunFlow は、ウマ娘に描かれる走行を 3D シミュレーションによって物理的に検証し、公式走法と理論上最適化された走法を比較することで、人型高速走行の限界と現実世界への応用可能性を探究する研究プロジェクトです。

## Core Questions

1. 公式の走り方は、空力的にどれだけ優れているのか？
2. アニメ・ゲーム・漫画で描かれる超前傾姿勢は、物理的にどこまで合理的なのか？
3. 公式モデル・公式走行モーションを維持したとき、全キャラクターの空力性能はどう順位付けされるか？
4. 同じ身体形状のまま走法だけを最適化した場合、理論上どこまで高速化できるか？
5. 人間・競走馬・高速ヒューマノイドロボットと比較すると、人型高速走行の限界はどこにあるか？
6. 空力的な最適解は、生体力学・ロボティクス上でも成立するか？

## Research Tracks

- **Canonical Aerodynamics** — 公式モデルと公式モーションをそのまま解析
- **All-Character Benchmark** — 全キャラクターの公式空力ランキング
- **Pose / Gait Optimization** — 理論上最速のフォーム探索
- **Cross-Species Comparison** — 人間・馬との比較
- **Robotics Translation** — 高速二足ロボットとの比較・応用
- **Biomechanical Feasibility** — 筋力・関節・地面反力などの追加研究
- **AI-assisted Research** — Astra を研究助手として活用

## Official Terminology

- **Canonical Run**: 公式作品内で描かれる走法
- **Canonical Speed**: 作中で観測・推定される速度
- **Physics-estimated Speed**: 同一フォームから物理モデルで推定した速度
- **Canonical Aero Ranking**: 公式モデル＋公式走行を改変せず比較する空力ランキング
- **Optimized Run**: 身体形状を維持し、走法を最適化した走行
- **Theoretical Speed Ranking**: 空力・生体力学を統合した将来の理論速度ランキング

## Repository Structure

```text
RunFlow/
├─ README.md
├─ PROJECT_SPEC.md
├─ RESEARCH_PLAN.md
├─ EXPERIMENT_PROTOCOL.md
├─ ROADMAP.md
├─ ASTRA_WORKFLOW.md
├─ DATA_POLICY.md
├─ configs/             # pilot・未確定CFD・固定ツール版
├─ schemas/             # 入出力契約
├─ src/runflow/         # Python CLI
├─ integrations/        # Unity/Blender取り込み
├─ tests/
├─ docs/
├─ reports/             # 検証結果と残件
├─ scripts/
├─ private/             # 原本・派生形状・実行結果（Git管理外）
├─ .tools/              # 専用ツール（Git管理外）
└─ artifacts/           # ローカル公開用出力（Git管理外）
```

## Scientific Principle

RunFlow は「面白い結果」を作ることではなく、**同一条件・再現性・妥当性確認を優先して結果を受け入れる**ことを原則とします。  
「超前傾が最速ではない」「公式フォームが空力的に不利」「生体力学的には成立しない」といった結果も有効な研究成果として扱います。

## Status

**Current stage:** Phase 1.0 — the provisional single-pose CFD trial has converged. Raw-log verification and repeated input generation passed. Geometry fidelity and aerodynamic accuracy remain unvalidated; full-gait Phase 1 is incomplete. Phase 0 intake/reproduction remains verified.

1姿勢試験の導入・上限・判定: [Phase 1 runbook](docs/PHASE1.md)。
実装の検証範囲と引き渡し: [Phase 1 status](reports/phase1-status.md)。初回CFD試験の数値・形状・比較画像・結果は`private/phase1/`に保存する。
全キャラ展開へ向けた形状差・部位・隙間の検査方法: [Shape audit](docs/SHAPE_AUDIT.md)。監査資料は`private/phase1-validation/`に保存する。
全身入力の解像度比較と資源監視: [Full-body voxel comparison](docs/FULLBODY_VOXEL.md)。実形状・数値・比較資料は非公開の`E:\RunFlowPrivate\phase1-validation\fullbody-voxel-001\`と、中間幅0.9・0.8・0.7・0.6mmの`fullbody-voxel-002\`に保存し、公開出力へ含めない。

形状修正では保存済み1mm・0.9mmの全身候補へ微小補正と細部復元を試した。0.8mm以下は再生成しない。[Full-body surface repair](docs/FULLBODY_REPAIR.md)。元の形状許容差は維持する。

0.9mmを主軸に交差の発生工程と局所修正を試行枠内で検証し、二重生成・全身の精密比較を完了した。凹部・隙間は改善したが、形状の全条件合格は未達。[局所修正の計画](docs/LOCAL_REPAIR_PLAN.md) と [実装・結果・残件](docs/LOCAL_REPAIR_EXECUTION.md)。

ユーザー指示により追加の形状精度探索を停止し、形状差を明記した [暫定CFD計測](docs/PROVISIONAL_CFD.md) を実施した。裾付近の空気側の格子を追加細分化した試行で、既定の残差・抵抗・流量収支の条件をすべて通過した。一次風上方式による数値精度と形状忠実度は未承認。結果・図・独立監査は非公開の `private/phase1/provisional-016/review/REVIEW.md` に保存した。次は結果をレビューし、感度検証と追加形状改善の優先順位を判断する。

実装・再実行手順: [Phase 0 runbook](docs/PHASE0.md)。
検証済み事項と残件: [Phase 0 status](reports/phase0-status.md)。
走行候補の実測とPMX/VMD骨名不一致: [Motion discovery](reports/motion-discovery.md)。
固定版Unityの二重出力とBlender形状比較: [Direct capture](reports/direct-capture.md)。
採用済み接地位相・元尺度での実対象設定再生成: [Adopted capture](reports/adopted-capture.md)。
JSON Schemaは `schemas/`、CLIは `src/runflow/`、Unity/Blenderアダプターは `integrations/`。
アセットと派生形状は `private/`、専用ツールは `.tools/`（Git管理外）。
