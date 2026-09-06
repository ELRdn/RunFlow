# RunFlow — RESEARCH_PLAN

## 1. Research Strategy

RunFlow は「1つの巨大シミュレーション」ではなく、**段階的に妥当性を積み上げる研究**として実施します。

---

## 2. Core Experimental Variables

### Independent Variables
- Character
- Running gait / animation
- Media/source
- Forward lean angle
- Gait phase
- Air velocity
- Later: biomechanical constraints

### Controlled Variables
- Fluid density
- Fluid viscosity
- Domain size
- Boundary conditions
- Solver family
- Meshing policy
- Sampling policy
- Coordinate system

### Dependent Variables
- Drag force
- Drag coefficient (Cd)
- Frontal area (A)
- CdA
- Pressure distribution
- Velocity field
- Wake structure
- Drag variability over gait cycle

---

## 3. Gait-Level Evaluation

RunFlow は「1枚の姿勢」ではなく、**走行周期全体**を評価します。

### Initial approximation
1ストライドを複数の代表フレームへ分割し、quasi-static CFD として評価します。

例:

```text
0%, 5%, 10%, ... 95%
```

実際のサンプリング数は Phase 1 の sensitivity test で決定します。

Phase 0の実装試験は16点・終点非重複・等時間重みとする。
接地イベントの元clip時刻を固定し、VMD録画開始時刻とは別に保存する。
Unity物理更新とBlenderの再現差はCFD実行前に検証する。詳細は `docs/PHASE0.md`。

### Gait average

各フレームの時間重みを考慮し、

- mean Drag
- mean Cd
- mean CdA
- peak Drag
- minimum Drag
- standard deviation / variation

を保存します。

---

## 4. Canonical vs Physics-estimated Data

作品内の速度・タイムは、シミュレーション値と分離します。

### Canonical / Observed
- 作中タイム
- 作中距離
- 映像から推定した速度
- ゲーム内部データ等から取得した速度

### Physics-estimated
- CFD から求めた空力抵抗
- 力学モデルから推定した必要出力
- 将来の最高速度モデル

双方は同一テーブルへ保存しますが、**混同しません**。

---

## 5. Phase 3 — All-Character Benchmark Design

### Purpose
全対象キャラクターの公式 3D 形状と公式走行モーションをそのまま使用し、同一条件で空力比較する。

### Benchmark Tier

#### Tier 1 — Full Roster
- 全キャラクター
- 統一された実用精度メッシュ
- 統一された gait sampling
- 同一基準速度
- 自動処理

#### Tier 2 — Deep Validation
対象:
- Top 10
- Bottom 10
- Outliers
- 特殊な走法
- 特殊な体格

追加:
- fine mesh
- stricter convergence
- more gait samples
- sensitivity analysis

---

## 6. Ranking Metrics

### Primary
**Mean CdA**

理由:
- Cd だけでは体格差が反映されない
- Drag だけでは速度条件の影響を受ける
- CdA は実際の空力抵抗の大きさを比較しやすい

### Secondary
- Mean Drag at standardized speed
- Cd
- frontal area
- maximum drag
- drag variance
- wake metrics

---

## 7. Optimization Study

Phase 4 では身体形状を保持し、走法のみを変更します。

### Candidate parameters
- torso lean
- head position
- arm position
- elbow angle
- hip angle
- knee angle
- stride length
- cadence
- vertical oscillation
- body center-of-mass trajectory

### Stage 1
Aerodynamic optimization only

### Stage 2
Aerodynamics + simple stability constraints

### Stage 3
Aerodynamics + biomechanics

### Output
- canonical gait
- optimized gait
- performance difference
- feasibility assessment

---

## 8. Cross-Species / Robotics Comparison

比較対象:
- elite human sprinter
- racehorse
- high-speed humanoid robot
- RunFlow canonical subjects
- RunFlow optimized subject

比較方法は複数使用します。

### Comparison A
Same speed

### Comparison B
Real-world maximum speed

### Comparison C
Normalized metrics
- speed / body length
- power / mass
- CdA
- dimensionless gait metrics where appropriate

---

## 9. Interpretation Policy

RunFlow は以下を区別します。

- **Aerodynamically optimal**
- **Mechanically feasible**
- **Biologically feasible**
- **Robotics-feasible**
- **Narratively canonical**

空力的に優れていても、生体力学的に成立しない場合があります。

その場合も、

> 「空力では有利だが、生体力学では不利」

という結果を採用します。
