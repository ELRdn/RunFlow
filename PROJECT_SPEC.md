# RunFlow — PROJECT_SPEC

**Tagline:** From Fiction to Physics.  
**Japanese:** 空想を、科学へ。  
**Project Type:** Independent Computational Research / CFD / Biomechanics / Robotics  
**Status:** Phase 0 implementation v0.1 — gait validation pending

---

## 1. Mission

RunFlow の使命は、フィクションに描かれる高速走行を「それっぽい」で終わらせず、3D 形状・走行モーション・流体力学・生体力学を用いて定量的に検証することです。

初期の主対象はウマ娘の公式 3D モデルおよび公式走行モーションです。

---

## 2. Primary Goal

> **公式走法の物理的特徴を再現・計測し、そこから理論上最も高速な人型走行フォームを探索する。**

---

## 3. Research Questions

### RQ1 — Canonical Aerodynamics
公式の走り方は、走行周期全体でどの程度の空気抵抗を受けるか？

### RQ2 — Media / Gait Comparison
ゲーム・アニメ・漫画など媒体ごとの走法は、空力的にどのような差を持つか？

### RQ3 — Extreme Forward Lean
極端な前傾姿勢は、空力・安定性・走行可能性の観点からどこまで合理的か？

### RQ4 — All-Character Ranking
公式モデル・公式モーション・公式体格を維持した場合、全キャラクターの空力性能はどう順位付けされるか？

### RQ5 — Maximum-Speed Optimization
身体形状を変更せず、走法のみを最適化したとき、どのようなフォームが最高速度に近づくか？

### RQ6 — Real-World Comparison
人間、競走馬、高速ヒューマノイドロボットと比較したとき、人型高速走行の性能限界はどこに位置するか？

### RQ7 — Biomechanical Feasibility
空力的に優れた走法を成立させるために、どの程度の地面反力・関節トルク・筋力・腱・骨格特性が必要か？

### RQ8 — Engineering Translation
RunFlow で得た走法最適化の知見は、人間のスポーツ科学・義足・外骨格・高速二足ロボティクスへ応用可能か？

---

## 4. Scope

### In Scope
- 公式 3D モデルの形状
- 公式走行アニメーション
- 走行周期全体の空力評価
- Cd / CdA / Drag / frontal area / wake / pressure field
- 作品・媒体間比較
- 全キャラクター Canonical Aero Ranking
- 走法最適化
- 人間・馬・ロボットとの比較
- 後期フェーズでの生体力学評価
- Astra による研究支援

### Out of Scope — Initial Phases
- 筋肉量の直接推定
- 完全な流体構造連成
- 毛髪・衣服の高精度 FSI
- 作品内設定を「現実の真値」とみなすこと
- CFD 値のみから最高速度を断定すること
- ゲームアセットの再配布

---

## 5. Research Objects

### Canonical Character
1キャラクターを以下のセットとして定義します。

```text
CharacterRecord
├─ character_id
├─ source_title
├─ source_version
├─ model
├─ skeleton
├─ body_proportions
├─ costume
├─ hair
├─ tail
├─ ears
├─ running_animation
├─ canonical_height
└─ observed/canonical speed data
```

### Rule
Canonical Benchmark では、体格・髪・耳・尻尾・衣装を含め、**そのキャラクター固有のデザインを保持**します。

---

## 6. Ranking Policy

Phase 3 のランキングは **「最速ランキング」ではありません**。

正式名称：

> **RunFlow Canonical Aero Ranking**

主要順位:
1. Mean CdA
2. Mean Drag at standardized speed
3. Mean Cd
4. Mean frontal area
5. Drag variability across gait cycle

将来、空力＋生体力学が統合された後にのみ、

> **RunFlow Theoretical Speed Ranking**

を使用します。

---

## 7. Scientific Quality Gates

研究結果を採用するには、最低限以下を満たします。

- Solver convergence
- Mesh independence / mesh sensitivity
- Geometry preprocessing log
- Reproducible solver settings
- Identical comparison conditions
- Gait sampling sensitivity
- Unit consistency
- Sanity check against known/reference geometry
- Human review of AI-generated setup

---

## 8. AI Role

Astra は **Research Assistant** として使用します。

Astra が担当可能:
- Blender 操作
- モーション抽出
- geometry cleanup
- batch preprocessing
- meshing
- solver configuration
- simulation execution
- visualization
- data extraction
- reporting support

最終的な scientific validation と採否判断は人間が行います。

---

## 9. Deliverables

Phase 0実装はPython CLI・JSON Schema・Unity/Blenderアダプター・OpenFOAM円柱ランナー。
初回対象はSteam日本版、オグリキャップ1006、シンデレラグレイ衣装100602。
実装の成功と研究対象の科学的承認は別であり、[実行状況](reports/phase0-status.md)を参照する。

- GitHub repository
- Reproducible experiment configs
- Character benchmark dataset（配布可能なメタデータのみ）
- Canonical Aero Ranking
- CFD figures / flow visualizations
- Technical report
- Paper-style PDF
- Astra execution logs
