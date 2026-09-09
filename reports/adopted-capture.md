# 採用条件での取り込み・再生成

2026-09-06。**右接地・元尺度を適用した16時刻の二重取得、Blender形状転送、実対象の設定二重生成はPASS。**

非公開証拠: `private/oguri/adopted-002/`。最終判定は `configuration-final-002/accepted-verification.json`、入力manifestは `configuration-final-002/manifest.json`。

## 採用条件

- オグリキャップ1006 / 勝負服100602、Steam JP build25072715。
- ユーザーが研究用の通常走行として選定した `3d/motion/racemain/body/type01/anm_rac_type01_run02_base`。実ゲームでの全合成条件を認定した意味ではない。
- 右足の中立靴底平面への下降交差 `0.5894131075056082 s` を周期起点とする。利き足を仮定せず、左右の非対称性は残す。
- 1 Unity world単位を1mとして採用。既存BodyScale 1.03886151を保持し、追加倍率は1。167cmは参考身長で、頭頂・裸足の実測値ではない。詳細測定はユーザー判断で省略した。
- 既存の正面・背面・左右レビューを適用。衣装と脚の貫通は原形状のまま注記する。全16時刻を新たに人間が目視確認したとは記録しない。

## 実行結果

| 検査 | 結果 |
|---|---|
| 固定Unity | 2022.3.62f1 / 4af31df58517、固定UmaViewer d50b283 |
| 更新 | 採用位相で初期化、5周期=1280ステップのウォームアップ、1周期256分割、16ステップごとに採取 |
| 取得 | 16時刻×2回、全snapshotのSHA-256一致 |
| 形状 | 各16,329頂点、29,999三角形 |
| Blender転送 | 全16時刻PASS。最大頂点差6.582818664452268e-8 m |
| 正面投影面積 | 最大相対差1.3705079052228834e-8（約0.000001371%） |
| 位相のfloat変換 | 指定0.5894131075056082 s → 適用0.5894130940998821 s、差約13.4 ns |
| 時刻追跡 | 記録したAnimator内部時刻と採取時刻の差は全16時刻で0 s。実ゲームの時刻精度を保証する数値ではない |
| 入力 | 49 AssetBundle、meta/masterとcaptureスクリプトのSHAを追跡。二重取得の入力台帳一致 |
| 設定再生成 | 実manifestからCLI generateを2回実行し、設定全体が一致 |
| 停止条件 | 単位不明・モデル欠落・SHA不一致・CFD設定不足がすべてCLI exit 2、出力生成なし |
| 公開用出力 | summary.jsonだけ。原本・形状・自由記述・ローカルパスなし |

設定SHA-256:

`349e3a3906442710b813e03f92cdf5366c43521681cf1775fde2abbfcd92038e`

manifest SHA-256:

`05734479e8d3fcc499e76022eb099c4d710d1e1c5d10449375838ce30dd5feec`

実アセットと処理ソースはそれぞれ非公開の `source-assets/`・`configuration-final-002/processing-sources/` に保存。実行日時を含むprovenanceは設定IDへの入力にせず、決定記録・入力台帳・snapshot・処理ソースを内容のハッシュで関連付けた。

## 失敗記録も保持

- `adopted-001`: 二重形状とBlender比較はPASSだが、更新へ渡すfloat刻みと、記録時に計算し直した刻みに約50nsの時刻不整合を検出。設定生成を停止した。
- 刻みの実際のbinary32値を保存するよう修正し、`adopted-002` を新規取得。不整合は解消した。
- `adopted-002` の最初の設定生成はCLIのモジュール指定誤りで停止した。`runflow.cli` へ修正し、新規 `configuration/` で二重生成が成功。ルート直下の `manifest.json` は失敗時の中間物であり、正式入力は `configuration-final-002/manifest.json`。
- その後、ゲームDB固定値の検査とDynamicBone・ツールlockの保存を加えた。`configuration-final/` は相対パスと絶対パスの混在を検出して停止。入力ルートを正規化し、新規 `configuration-final-002/` の二重生成が最終PASSとなった。途中の出力は上書きせず保持している。

最終manifestに対する停止条件と公開用出力の検査は `acceptance-final/verification.json`、公開用要約は `artifacts/public-summary-adopted-final-002/summary.json`。ゲームmeta/masterが固定snapshotと異なる場合は旧ビルド名での再生成を拒否する。pytestは92件PASS。

## 妥当性の境界

共有Unity関節は転送メタデータであり、独立したBlender関節計測ではない。PMX/VMD経路の骨対応不一致は解消済みとは扱わず、直接出力経路を研究入力として採用する。

欠落 `Gallop.CharaTransformProcessData` 型のゲーム側の役割は未確認。[調査記録](missing-transform-script.md) の通り、Viewerでの取得は成立するが、公式と同一の変形・合成を保証しない。

ユーザーが採用した研究条件での取り込み・再現性基盤は完成した。今後のキャラクターCFDでは、衣装の自己交差・閉じた表面の作成、境界条件、メッシュと時刻数の感度、収束、科学的承認を扱う。Drag/Cd/CdAはnull、ランキング適格性はfalseを維持する。

再実行は [Phase 0 runbook](../docs/PHASE0.md)。新しい位相のプレビューは非公開 `preview/parts-review.png`。
