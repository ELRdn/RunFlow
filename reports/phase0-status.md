# Phase 0 実装・検証記録

検証日: 2026-09-06。**基盤の実装・円柱実行は完了。指定走行の取り込みは未完了のため、Phase 0全体は未完了。**

続行調査でレース候補の実在・指定衣装での再生・VMD取得を確認した。
PMX/VMDは52骨トラックすべて名前未対応のため停止。その後、固定版Unityの直接出力で16時刻の再現性・Blender形状転送比較を完了した。
詳細は [motion discovery](motion-discovery.md)、[直接出力検証記録](direct-capture.md)。

## 実測できたこと

| 項目 | 結果 | ローカル証拠 |
|---|---|---|
| Python CLI / JSON Schema | validate・sample・generate・baselineと比較・出力コマンドを実装 | src/runflow, schemas |
| 自動検証 | 79 tests PASS | pytest。入力・CFD・公開用出力・候補分類・DB・VMD骨名・静止系列拒否・二重capture入力SHA一致を検証 |
| Windowsツール | Blender4.2.23 / MMD Tools4.5.14の起動・登録成功 | configs/toolchain.lock.json, private/oguri/pmx-import.log |
| UmaViewer | 2.1.8、commit d50b28379337b507751a7df705a10afeab2c37ceに対応する配布版 | configs/toolchain.lock.json |
| 対象衣装 | キャラ1006 / 衣装100602 = オグリキャップ / シンデレラグレイをmasterで確認 | private/intake.json |
| Steam JP | build25072715、ゲームデータは読み取りのみ | private/intake.json |
| PMX | 指定衣装を出力し、Blenderで16,329頂点を取り込み | private/oguri/pmx/oguri-1006-100602.pmx, pmx-inventory.json |
| 合成形状のBlender経路 | 16時刻のOBJ→snapshot比較PASS | private/synthetic/blender-input, blender-output |
| 同一設定再生成 | 自作の合成入力で2回一致 | private/synthetic/reproduction/reproduction.json |
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

## Phase 0を完了させる残件

1. **通常巡航・合成条件を同定する。** racemainの422候補、オグリのrace_running_type=1、run02_baseの再生は確認済み。Canonicalなmotion_idは未設定。代替衣装や未確認の合成条件で埋めない。
2. **元clip時刻と接地イベントを記録する。** KeyReductionLevel=1で候補VMDを取得済みだが、開始位相は不明、骨名対応はFAIL。クリック時刻を周期の起点にしない。
3. **実寸・座標・骨対応・部位をレビューする。** 身長の出典と測定位置、行列、ルート移動、髪・耳・尻尾・衣装を確認する。初回の人間レビュー記録が必要。
4. **承認した周期・尺度で正式取り込み判定を残す。** 候補の16時刻二重出力とBlender転送比較はPASS。共有Unity関節の一致を独立した関節位置差0.5%の検証とは扱わない。接地基準の周期で再取得し、直接メッシュ経路の採用根拠と部位レビューを残す。
5. **実対象manifestでgenerateを2回実行する。** pilot templateはnullを残し、入力検証で停止する状態を維持した。承認済み実アセットによる実験設定ハッシュの一致は未実施。今回のsnapshot一致とは別の完了条件。

## 既知の制約と境界

- OBJ経路の関節はUnity snapshotに由来し、Blender独立計測の関節ではない。PMX/VMD経路はBlenderの骨位置を計測する。
- 投影面積はYZ面に投影した三角形の和集合。透明テクスチャは扱わない。
- Unity captureは実験専用シーンで使う同期処理。body→face→springの固定更新とモデル再生成で二重captureを確認済み。通常の実ゲーム更新・合成条件との一致は未確認。
- 最初のbaseline run-001はWindowsパス変換でFAIL。その後修正し、run-002と最終runnerのrun-003で正常終了。失敗記録も非公開に残した。
- WSLは通常サンドボックスではアクセス拒否。許可されたローカル実行で動作を確認した。環境の照会だけを計算成功としていない。
- private / .tools / artifacts等はGit除外。公開用出力はローカル作成のみで、外部送信・push・commitは実施していない。
- Astra新規連携・全キャラ処理・クラウド・キャラクターCFD・感度解析・科学的承認は実施していない。

再実行手順は [runbook](../docs/PHASE0.md)、取り込み設定は [adapter説明](../integrations/README.md)。
上流の候補分類・録画処理は [固定版UmaViewerUI](https://github.com/katboi01/UmaViewer/blob/d50b28379337b507751a7df705a10afeab2c37ce/Assets/Scripts/UmaViewerUI.cs) を参照した。
