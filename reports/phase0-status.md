# Phase 0 実装・検証記録

検証日: 2026-09-06。**ユーザー採用条件でのPhase 0実行基盤は完成。指定走行の直接取り込み・実対象設定の再生成・円柱実行はPASS。実ゲームとの厳密な同等性は未認定。**

続行調査でレース候補の実在・指定衣装での再生・VMD取得を確認した。
PMX/VMDは52骨トラックすべて名前未対応のため停止。その後、固定版Unityの直接出力で16時刻の再現性・Blender形状転送比較を完了した。
詳細は [motion discovery](motion-discovery.md)、[直接出力検証記録](direct-capture.md)。
その後の [初回人間レビュー](intake-review.md) で、通常時の走行という暫定判断と側面4姿勢の部位OKを受領。
右接地を周期起点の統一規約とし、公式身長167cmの出典を確認した。
追加の正面・背面・左右画像も人間レビュー済み。衣装と脚の貫通を例外として他はOK、貫通の公式仕様認定は未確認。
中立立位と両足の256分割×2周期を二重測定し、形状・入力台帳一致を確認。[接地・実寸測定](contact-scale-measurement.md) に右足の接地候補と尺度の未確定事項を記録した。
その後、ユーザーが位相0.5894131075056082秒と元のUnity尺度を研究条件として採用。詳細身長測定は省略すると決定した。採用条件の反映・再取得・二重設定生成まで実行済み。[最終取り込み記録](adopted-capture.md)。

## 実測できたこと

| 項目 | 結果 | ローカル証拠 |
|---|---|---|
| Python CLI / JSON Schema | validate・sample・generate・baselineと比較・出力コマンドを実装 | src/runflow, schemas |
| 自動検証 | 92 tests PASS | pytest。入力・CFD・公開用出力・候補分類・DB・VMD骨名・静止系列拒否・二重capture入力SHA一致・接地候補・採用条件・時刻不整合の拒否を検証 |
| Windowsツール | Blender4.2.23 / MMD Tools4.5.14の起動・登録成功 | configs/toolchain.lock.json, private/oguri/pmx-import.log |
| UmaViewer | 2.1.8、commit d50b28379337b507751a7df705a10afeab2c37ceに対応する配布版 | configs/toolchain.lock.json |
| 対象衣装 | キャラ1006 / 衣装100602 = オグリキャップ / シンデレラグレイをmasterで確認 | private/intake.json |
| Steam JP | build25072715、ゲームデータは読み取りのみ | private/intake.json |
| PMX | 指定衣装を出力し、Blenderで16,329頂点を取り込み | private/oguri/pmx/oguri-1006-100602.pmx, pmx-inventory.json |
| 合成形状のBlender経路 | 16時刻のOBJ→snapshot比較PASS | private/synthetic/blender-input, blender-output |
| 同一設定再生成 | 自作の合成入力で2回一致 | private/synthetic/reproduction/reproduction.json |
| 実対象設定の再生成 | 採用位相・尺度による実manifestで2回一致 | private/oguri/adopted-002/configuration-final-002/accepted-verification.json |
| 採用条件のUnity/Blender検証 | 16時刻の全snapshot一致・形状転送PASS | private/oguri/adopted-002/comparison.json |
| Unity直接出力 | Editor2022.3.62f1で実モデル16時刻×2回。全snapshotハッシュ一致 | private/oguri/direct-final-002 |
| 実形状Blender転送 | 16,329頂点・29,999三角形。全16時刻の頂点・投影面積比較PASS | 同comparison.json。共有関節は独立検証ではない |
| 入力追跡 | 49 AssetBundleとmeta/masterを前後にSHA検査、2回の入力台帳一致 | 同inputs-0.json / inputs-1.json |
| OpenFOAM | WSL Ubuntu24.04、Foundation14 package20260724で実行 | private/baseline/run-003 |
| 円柱 | Re=1、checkMesh成功、正常終了、有限な力履歴5,001行 | private/baseline/run-003/checkMesh.log, foamRun.log, result.json |
| 公開用出力 | 許可リストからsummary.jsonのみ生成。原本・形状・自由記述・パスを含めない | artifacts/public-summary-run-003/summary.json |

カードID100603と衣装ID100602は別物。`chara_data.height=2` は身長の実測値として使用しない。
PMXを読み込めたことは、走行中の形状が忠実であることの証明ではない。
合成データはゲーム由来ではなく、対象キャラの再現性PASSへ流用しない。

再生成した合成設定SHA-256:
`f0a8f82286224c855e84f7d2f7a02354468d4720d54a3514bd56dda3f3fd1b3c`

円柱実験ID:
`rf-baseline-e30032980516dcf90e4f245706dad0e93124bdcb70aa8deec20d2135f68c0dea`

円柱は直径0.001m・流速0.015m/s・動粘性1.5e-5m²/s。導入された上流ケースをコピーし、入力ファイルのSHA-256、ソルバー版、runnerのSHA-256、力の生履歴とログを保存した。
未解釈のDrag/Cd/CdAはnull。実行成功と科学的承認を分離し、ランキング適格性はfalse。

## 採用条件の反映と引き渡し

1. **通常走行pilotを選定済み。** run02_baseをユーザー採用の研究入力とする。実ゲームでのpitch/stride等の完全な合成条件は未認定で、Canonical検証フラグはfalse。
2. **位相・尺度を反映済み。** 右足の幾何学的接地0.5894131075056082秒、元のUnity world単位を1m、追加倍率1。詳細身長測定はユーザー判断で省略。
3. **欠落型を調査済み。** 固定ソースに実装・明示参照なし、取得は正常終了、生成階層の欠落MonoBehaviourは0。ゲーム側の役割は不明。[詳細](missing-transform-script.md)。
4. **16時刻の再取得・比較PASS。** 共有Unity関節は独立したBlender関節計測と区別する。衣装の貫通は原形状のまま保持。
5. **実対象設定SHA一致。** `349e3a3906442710b813e03f92cdf5366c43521681cf1775fde2abbfcd92038e`。pilot templateのnullは残し、正式manifestは非公開に保存。

Phase 1ではCFD用表面の自己交差・閉鎖性、流れ・地面条件、メッシュ・時刻数の感度、収束を検証する。公式同等性と科学的承認は別途未確定。

## 既知の制約と境界

- OBJ経路の関節はUnity snapshotに由来し、Blender独立計測の関節ではない。PMX/VMD経路はBlenderの骨位置を計測する。
- 投影面積はYZ面に投影した三角形の和集合。透明テクスチャは扱わない。
- Unity captureは実験専用シーンで使う同期処理。body→face→springの固定更新とモデル再生成で二重captureを確認済み。通常の実ゲーム更新・合成条件との一致は未確認。
- 最初のbaseline run-001はWindowsパス変換でFAIL。その後修正し、run-002と最終runnerのrun-003で正常終了。失敗記録も非公開に残した。
- WSLは通常サンドボックスではアクセス拒否。許可されたローカル実行で動作を確認した。環境の照会だけを計算成功としていない。
- private / .tools / artifacts等はGit除外。ソース・設定・文書はコミット2a92b9aとしてGitHubへpush済み。原本・派生形状、private / artifacts配下のファイルは含めていない。
- Astra新規連携・全キャラ処理・クラウド・キャラクターCFD・感度解析・科学的承認は実施していない。

再実行手順は [runbook](../docs/PHASE0.md)、取り込み設定は [adapter説明](../integrations/README.md)。
上流の候補分類・録画処理は [固定版UmaViewerUI](https://github.com/katboi01/UmaViewer/blob/d50b28379337b507751a7df705a10afeab2c37ce/Assets/Scripts/UmaViewerUI.cs) を参照した。
