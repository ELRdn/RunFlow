# RunFlow — ROADMAP

## Phase 0 — Research Foundation

**Goal:** 研究条件を固定し、再現可能な基盤を作る。

Tasks:
- [x] Project specification
- [x] coordinate / unit convention
- [x] model import pipeline（ユーザー採用条件の直接出力。公式同等性は未認定）
- [x] motion extraction（選定済みrun02_base、右接地基準の1周期）
- [x] fixed Unity diagnostic capture / 16 samples twice / Blender geometry transport
- [x] experiment database schema（JSON Schema / file records）
- [x] solver selection（OpenFOAM Foundation 14 / package 20260724）
- [x] baseline test object（Re=1 cylinder actual execution PASS）
- [x] IP / asset handling policy
- [x] roster snapshot policy

**Completion Gate:** 同じ入力から同じ experiment config を再生成できる。

2026-09-06: CLI・合成入力の再生成・円柱CFDは検証済み。
指定勝負服の候補run02_baseを固定版Unityで16時刻×2回直接出力し、全snapshotハッシュ一致とBlender形状転送比較PASS。
その後ユーザーが右接地位相0.5894131075056082秒・元のUnity尺度を採用し、詳細身長測定の省略と衣装貫通の注記を決定した。
採用条件で再取得した16時刻の二重出力・Blender比較と、実対象manifestからの設定SHA二重生成はPASS。
ユーザー採用条件でのPhase 0実行基盤は完成。欠落スクリプト・実ゲームの合成条件に由来する公式同等性の未確認は制約として残す。[採用条件の検証記録](reports/adopted-capture.md)参照。

---

## Phase 1 — Full-Gait CFD Validation

**Goal:** 1キャラクターの走行周期全体について妥当な空力値を取得する。

### Phase 1.0 — Bounded single-pose smoke

- [x] 専用CLI・固定プロトコル・非公開の結果契約
- [x] 1姿勢、60分上限、資源監視、失敗時の停止と保存
- [x] 採用frame 0を1回試験し、形状品質ゲートによる停止を記録
- [x] 継続試験で退化面の局所補修を検証し、保存済み表面の距離超過を独立確認
- [x] 保存済み形状の全表面距離・投影面積・主要部位・隙間を監査し、再利用可能な手順を保存
- [x] 問題箇所の局所解像度比較を実施し、表面消失と全身への適用制限を記録（補修採用なし）
- [x] 全身入力の4解像度を上限付きで試験し、形状差・隙間・資源費用・未完了条件を記録（全4条件の比較完了には未到達）
- [x] 追加の全身中間幅4条件を生成・計測し、部位消失の変化と前回との比較を保存（補修採用・CFDは未実施）
- [x] 保存済み1mm・0.9mmへ移動・結合・空間の切り戻しを試し、生成済み候補の全身計測と局所改善・自己交差・資源停止を記録（全条件合格は未達）
- [x] 0.9mmの追加局所修正を承認された試行枠で検証し、交差発生工程・二重生成・選定候補の精密計測・未実行範囲を記録（全条件合格は未達）
- [x] ユーザー指示により形状の精度探索を停止し、現状形状の誤差を記録した暫定CFDの実行契約を追加
- [x] 暫定試行の表面検査の時間切れを記録し、Linux内の診断出力・検証済み表面の再利用・停止監視を修正して合成試験を完了
- [x] 明示承認された追加1回を実施し、同一表面でのOpenFOAM検査完了とCGALとの判定不一致による停止を記録
- [x] 形状を変更せず、OpenFOAMの読み込み後の全座標・面と検出組を特定し、全身CGAL検査と全検出組の有理数検査で誤検出を確認
- [x] メッシュ生成の歪み制限を最終検査に合わせて厳しくし、実対象のメッシュ品質・指定した細分化を確認
- [x] 実対象の定常計算と流場保存まで接続し、初回の未収束履歴を保存して反復設定の診断を追加
- [x] 現状の0.9mm修正候補で、暫定の1姿勢・収束済み空気抵抗を取得し、図・生ログの独立監査・入力再生成を完了する
- [ ] 暫定結果をレビューし、数値感度の検証と追加形状改善の優先順位を判断する
- [ ] 実対象のCFD用形状を全条件で合格させる
- [ ] 形状忠実度を含む全条件を満たした実対象のメッシュ・収束済み空気抵抗を取得する

実行手順は [Phase 1](docs/PHASE1.md)、初期の停止証拠は非公開の`private/phase1/smoke-001/REVIEW.md`と`private/phase1/smoke-002/REVIEW.md`。全体監査は`private/phase1-validation/global-shape-002/REVIEW.md`、再利用手順は [形状監査](docs/SHAPE_AUDIT.md)。その後、形状の精度探索を保留した暫定計測が収束した。最新の図・結果・検証証拠は`private/phase1/provisional-016/review/REVIEW.md`。形状忠実度と数値感度を含むPhase 1全体の完了ではない。

全身比較では細かい候補の部位消失を確認し、計測の時間切れ・生成時の資源停止も記録した。実装・手順は [全身ボクセル比較](docs/FULLBODY_VOXEL.md)、数値・形状・比較資料はEドライブの非公開領域に保存する。形状修正では1mm・0.9mmを対象とし、0.8mm以下を再生成しない。[微修正の比較](docs/FULLBODY_REPAIR.md)で局所改善は確認したが、全条件合格は未達。原本の凹部と露出・内部・重複面を区別した追加補修は、暫定結果を踏まえて再判断する。許容差や原本全表面の判定範囲は変更していない。

残る6系統を一次資料と照合した [局所修正計画](docs/LOCAL_REPAIR_PLAN.md) は承認後に実装・試行した。全身の欠陥台帳と精度工程の診断、多方向の切り戻し、張り替え・薄い部品・位置補正の比較を行い、選定候補の二重生成と精密計測まで完了。凹部・隙間の改善は確認したが、可視面を含む距離と品質の残件がある。試行上限で終了し、全方法の検証完了とはしない。未実行範囲と環境上の制限は [実行記録](docs/LOCAL_REPAIR_EXECUTION.md) に残す。

その後ユーザーが「いったん形状の精度探索を止めて空気抵抗を計測し、その後で形状をもっと正確にするか判断する」と指示した。この暫定計測は、原本との形状差を記録して保留し、既存の数値条件・資源上限・収束条件で進める。2mm基準の合格や全キャラ共通の精度保証へ読み替えない。手順は [暫定CFD](docs/PROVISIONAL_CFD.md)。

Tasks:
- [ ] gait frame sampling
- [ ] mesh sensitivity
- [ ] convergence validation
- [ ] gait sampling sensitivity
- [ ] Drag / Cd / CdA extraction
- [ ] visualization
- [ ] known/reference sanity check

**Completion Gate:** 数値的妥当性まで確認された gait-level CFD pipeline が完成。

次は3段階のメッシュ・領域感度、8/16/32時刻のサンプリング感度を確認する。手足の動きを含む非定常計算はPhase 1.5へ分離する。

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
