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

**Current stage:** Phase 0 — foundation, cylinder smoke and 16-frame direct capture/transport verified; canonical gait and intake review pending.

実装・再実行手順: [Phase 0 runbook](docs/PHASE0.md)。
検証済み事項と残件: [Phase 0 status](reports/phase0-status.md)。
走行候補の実測とPMX/VMD骨名不一致: [Motion discovery](reports/motion-discovery.md)。
固定版Unityの二重出力とBlender形状比較: [Direct capture](reports/direct-capture.md)。
JSON Schemaは `schemas/`、CLIは `src/runflow/`、Unity/Blenderアダプターは `integrations/`。
アセットと派生形状は `private/`、専用ツールは `.tools/`（Git管理外）。
