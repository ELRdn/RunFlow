# RunFlow — ROADMAP

## Phase 0 — Research Foundation

**Goal:** 研究条件を固定し、再現可能な基盤を作る。

Tasks:
- [x] Project specification
- [x] coordinate / unit convention
- [ ] model import pipeline
- [ ] motion extraction
- [x] fixed Unity diagnostic capture / 16 samples twice / Blender geometry transport
- [x] experiment database schema（JSON Schema / file records）
- [x] solver selection（OpenFOAM Foundation 14 / package 20260724）
- [x] baseline test object（Re=1 cylinder actual execution PASS）
- [x] IP / asset handling policy
- [x] roster snapshot policy

**Completion Gate:** 同じ入力から同じ experiment config を再生成できる。

2026-09-06: CLI・合成入力の再生成・円柱CFDは検証済み。
指定勝負服の候補run02_baseを固定版Unityで16時刻×2回直接出力し、全snapshotハッシュ一致とBlender形状転送比較PASS。
通常巡航の認定、接地位相、実寸・部位の初回レビュー、承認済み実対象manifestでの設定再生成は残る。
したがってPhase 0全体は未完了。[検証記録](reports/phase0-status.md)参照。

---

## Phase 1 — Full-Gait CFD Validation

**Goal:** 1キャラクターの走行周期全体について妥当な空力値を取得する。

Tasks:
- [ ] gait frame sampling
- [ ] mesh sensitivity
- [ ] convergence validation
- [ ] gait sampling sensitivity
- [ ] Drag / Cd / CdA extraction
- [ ] visualization
- [ ] known/reference sanity check

**Completion Gate:** 数値的妥当性まで確認された gait-level CFD pipeline が完成。

---

## Phase 2 — Canonical Gait / Media Study

**Goal:** 公式作品内の代表的な走法を比較する。

Candidates:
- game running gait
- anime running gait
- manga/anime extreme forward lean
- selected character-specific gaits

Outputs:
- Canonical vs Physics-estimated comparison
- media/gait comparison figures
- extreme-forward-lean analysis

**Completion Gate:** 複数公式走法を同一 protocol で比較可能。

---

## Phase 3 — All-Character Canonical Benchmark

**Goal:** 全対象キャラクターの公式空力ランキングを作成。

Rules:
- Original body proportions
- Original hair / ears / tail / costume
- Original running animation
- Identical CFD benchmark conditions

Outputs:
- RunFlow Canonical Aero Ranking
- Top / Bottom / Outlier analysis
- roster-wide dataset
- ranking visualizations

**Completion Gate:** roster snapshot 内の ranking-eligible 全キャラクター解析完了。

---

## Phase 4 — Maximum-Speed Gait Optimization

**Goal:** 身体形状を維持したまま、理論上より高速な走法を探索。

Stages:
1. aerodynamic-only
2. stability constrained
3. biomechanics constrained

Outputs:
- canonical vs optimized
- optimal posture/gait candidates
- theoretical aerodynamic improvement

**Completion Gate:** 最適化結果が再現可能で、Canonical baseline を定量比較できる。

---

## Phase 5 — Human / Horse / Robotics Benchmark

**Goal:** RunFlow の結果を現実世界の高速移動主体と比較する。

Targets:
- elite human sprinter
- racehorse
- leading high-speed humanoid robots

Comparison:
- same speed
- maximum speed
- normalized metrics

**Completion Gate:** 比較条件と限界を明示した cross-domain benchmark 完成。

---

## Phase 6 — Biomechanical Feasibility

**Goal:** 空力最適解が人型身体で成立する条件を検証。

Later research:
- ground reaction force
- joint torque
- joint power
- muscle equivalent force
- tendon loading
- skeletal loading
- energy cost

**Completion Gate:** 「空力的最適」と「身体的成立可能性」を分離して評価可能。

---

## Phase 7 — Translation to Engineering

**Goal:** 得られた知見の現実応用可能性を検討。

Possible domains:
- sprint biomechanics
- prosthetics
- exoskeletons
- humanoid robotics
- gait optimization
- high-speed biped control

Outputs:
- engineering implications
- limitations
- candidate follow-up experiments

---

## Continuous Track — Astra Research Assistant

全Phaseで Astra を研究助手として利用。

Track:
- automation coverage
- failed operations
- human interventions
- reproducibility
- generated artifacts
- validation failures

Astra 自体を主研究対象にはしない。
