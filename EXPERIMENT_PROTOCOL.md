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

### Phase 1.0 限定プロトコル

`RF-CFD-P1-SMOKE-001`（`configs/cfd.phase1-smoke.json`）は、採用済みframe 0・元尺度・地面なし・流入(-20,0,0)m/sだけを扱う実行試験。全周期の科学的承認には用いない。
Foundation14 package20260724、定常RANS/SIMPLE、k–ω SST、密度1.2kg/m³・動粘性1.5e-5m²/sを固定する。20m/sは公式速度ではない。
補修は頂点統合1µm、必要時だけ1mmボクセルを1回。表面距離の双方向上限2mm・投影面積差1%・閉鎖性・非多様体・自己交差の検査を通過した形状だけ実行する。
再メッシュ後の退化三角形に触れる頂点だけを1µm以内で1回統合し、辺・面を持たない残留頂点だけを除く。四角形の面積だけでは判定せず、出力三角形と辺・頂点の接続を検査し、補修履歴と処理コードのSHAを保存する。
形状600秒、メッシュ1200秒、計算1500秒、集計300秒、合計3600秒。MPI4プロセス、12GiB、出力10GiB、100万セルを上限とする。
Drag=-Fx（圧力＋粘性）、CdA=Drag/(0.5ρU²)、Cd=CdA/補修前投影面積。力の密度換算はOpenFOAM内の1回のみ。
300反復以降の残差・Drag変動・質量収支の複合判定は [Phase 1 runbook](docs/PHASE1.md) と固定JSON契約を正とする。未収束・失敗・上限到達の正式なDrag/Cd/CdAはnull、常に科学的未承認・ランキング不適格。

ユーザー承認の暫定経路では、既知の形状忠実度不足を明記した別契約で現状形状を計測する。[暫定CFD](docs/PROVISIONAL_CFD.md) の局所的な流体格子と反復設定を用いた1姿勢試行は収束済み。形状の2mm基準、数値感度、科学的承認は別の未完了項目であり、この成功で置き換えない。

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
Phase 1専用契約は `src/runflow/cfd_contracts.py` と `schemas/cfd-*.schema.json` に分離する。Phase 0の禁止フラグ・結果契約を昇格させない。
従来のYAML例は概念説明であり、CLIの入力にはJSON契約を使う。
設定はcanonical UTF-8 JSONをSHA-256化し、実行日時・ファイル絶対パスを設定IDから除外する。
入力asset IDs/hashes、ソースとツールの版、変換、前処理、時刻、時間重みはIDに含める。
execution_statusとscientific_statusを分離し、Phase 0 CLIはscientific approvalを発行しない。
暫定取り込み判定は関節差<=身長0.5%、YZ投影三角形の和集合面積差<=1%。
16点は取り込みテスト用で、CFD感度が確認されたサンプル数ではない。

位相の統一規約は右足の初期接地から次の右足の初期接地までとする。
これは利き足の認定ではない。左右の姿勢差を保持し、反転や片脚の複製で対称化しない。
実際の接地時刻は映像・足裏・地面の関係で別途同定し、未同定のclip先頭を接地として登録しない。
初回レビューの判断と未確定事項は `reports/intake-review.md` に記録する。
pilotでは人間判断により、立位の靴支持面への右足の初回下降交差（clip位相0.5894131075056082秒）を研究基準として採用する。
詳細な身長較正を省略し、元のUnity world尺度を1単位=1mとして採用する。追加リスケールは行わない。
これらはpilotの採用仮定であり、実レースの地面との一致や独立した実寸測定を検証済みとは記さない。

ランキングには必ずバージョンを付けます。

例:

```text
RunFlow Canonical Aero Ranking v0.1
Roster snapshot: YYYY-MM-DD
Benchmark protocol: RF-CFD-B01
```

新キャラクター追加時に過去ランキングを書き換えず、新しい roster snapshot を作成します。
