# RunFlow — EXPERIMENT_PROTOCOL

## 1. Purpose

この文書は RunFlow の比較実験を再現可能にするための共通プロトコルです。

---

## 2. Coordinate Convention

全モデルを共通座標系へ変換します。

- Forward: +X
- Up: +Z
- Lateral: +Y

実装時に別座標を使用する場合でも、変換行列を記録します。

実装規約v1: m/s/kg。source_to_rf行列に倍率を含め、meters_per_source_unitは検証用の宣言値とする。
変換は等方スケールのみ許容し、反転の有無を記録。mesh/jointsからroot Xを引き、Y/Zを保持する。
root_positionは変換後の元軌跡。身長は出典と測定部位を記録し、髪・耳を含む外接高さへ一律に合わせない。

---

## 3. Geometry Preprocessing

各フレームについて以下を記録します。

- source asset ID
- source version
- animation ID
- frame/time
- world scale
- transforms
- mesh repair operations
- removed geometry
- generated collision/CFD shell
- watertight status
- triangle count

Canonical Benchmark では見た目・体格に影響する形状変更を禁止します。

許容:
- CFD計算のための軽微な topology repair
- 法線修正
- 非表示内部メッシュの除外（条件を全対象で統一）

---

## 4. Gait Sampling

Phase 1 で以下を比較して必要サンプル数を決定します。

例:
- 8 frames / cycle
- 16 frames / cycle
- 24 frames / cycle
- 32 frames / cycle

平均 CdA の変化が十分小さくなる点を採用します。

---

## 5. CFD Comparison Rule

全キャラクター比較では以下を固定します。

- air properties
- inlet speed
- turbulence model
- domain ratios
- wall conditions
- mesh policy
- convergence thresholds
- force integration method

詳細な数値は Phase 1 で確定後、versioned config として保存します。

---

## 6. Validation

### Mandatory
- residual/convergence check
- force history check
- mesh sensitivity
- gait sampling sensitivity
- geometry inspection
- dimension/unit validation

### Recommended
- independent solver or simplified analytical comparison
- selected high-resolution reruns
- comparison against published/reference human aerodynamic data

---

## 7. Result Record

各ケースは以下の形式で保存します。

```yaml
experiment_id:
character_id:
source:
source_version:
motion_id:
gait_phase:
canonical_height:
reference_speed:
mesh_level:
solver:
air_density:
viscosity:
drag_N:
Cd:
frontal_area_m2:
CdA_m2:
converged:
validation_status:
notes:
```

---

## 8. Character Aggregate Record

```yaml
character_id:
gait_id:
sample_count:
mean_drag_N:
peak_drag_N:
mean_Cd:
mean_frontal_area_m2:
mean_CdA_m2:
CdA_std:
ranking_eligible:
validation_level:
```

---

## 9. Ranking Eligibility

ランキング掲載には以下を満たす必要があります。

- 全必須フレーム計算完了
- validation_status = PASS
- geometry error なし
- same benchmark version
- same standardized speed
- same solver protocol

失敗ケースは順位へ無理に含めず、`NOT_RANKED` とします。

---

## 10. Versioning

実装上の正規データ契約は `schemas/`、生成元は `src/runflow/contracts.py`。
従来のYAML例は概念説明であり、CLIの入力にはJSON契約を使う。
設定はcanonical UTF-8 JSONをSHA-256化し、実行日時・ファイル絶対パスを設定IDから除外する。
入力asset IDs/hashes、ソースとツールの版、変換、前処理、時刻、時間重みはIDに含める。
execution_statusとscientific_statusを分離し、Phase 0 CLIはscientific approvalを発行しない。
暫定取り込み判定は関節差<=身長0.5%、YZ投影三角形の和集合面積差<=1%。
16点は取り込みテスト用で、CFD感度が確認されたサンプル数ではない。

ランキングには必ずバージョンを付けます。

例:

```text
RunFlow Canonical Aero Ranking v0.1
Roster snapshot: YYYY-MM-DD
Benchmark protocol: RF-CFD-B01
```

新キャラクター追加時に過去ランキングを書き換えず、新しい roster snapshot を作成します。
