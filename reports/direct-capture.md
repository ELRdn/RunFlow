# 固定版Unityの直接出力・16時刻検証

2026-09-06。**指定衣装の候補走行について、直接出力・二重実行の再現性・Blender形状転送比較を完了。全16時刻PASS。**
Phase 0全体の完了、通常巡航のCanonical認定、科学的承認は意味しない。

## 実行条件

| 項目 | 固定値・実測 |
|---|---|
| Unity Editor | 2022.3.62f1 / 4af31df58517 |
| UmaViewer | d50b28379337b507751a7df705a10afeab2c37ce |
| 対象 | オグリキャップ1006 / シンデレラグレイ100602 / model suffix02 |
| 候補clip | 3d/motion/racemain/body/type01/anm_rac_type01_run02_base |
| 周期・サンプル | clip長約0.6秒、16点、終点重複なし |
| 固定更新 | clip長/64（約0.009375秒）、4stepごとに出力 |
| ウォームアップ | 5周期、320step |
| 出力時刻 | 約3.0000～3.5625秒、約0.0375秒間隔。実際の浮動小数値はsnapshotに保存 |
| 初期化 | モデル全体を破棄・再ロードして2回取得 |
| 更新順 | spring前処理 → body Animator → face Animator/有効時locator → spring |
| spring | 31個、階層パス順、カメラ距離culling無効 |
| 形状 | 16,329頂点、29,999三角形、SkinnedMeshRenderer台帳14件 |
| 軸・尺度 | Unity (x,y,z) → RunFlow (z,x,y)、倍率1。実寸と前方の科学的レビューは未承認 |
| 元軌跡 | Positionを別に保存、変換後の前進Xのみ形状から分離。このclipのroot移動は0 |
| Blender | 4.2.23、OBJ取り込み、形状に物理を再適用しない |

## 数値結果

| 検査 | 結果 |
|---|---|
| Unity 2回のsnapshot内容SHA-256 | 16/16完全一致 |
| 別Editor起動の先行captureとの照合 | 16/16完全一致。先行captureは入力ハッシュ記録追加前の診断 |
| Unity→Blender最大頂点位置差 | 6.381440168341322e-8 公称m（閾値1e-5） |
| 正面投影面積の最大相対差 | 1.2935624884638616e-8（約0.000001294%、閾値1%） |
| 頂点数・共有関節メタデータ | 全16時刻一致 |
| 入力台帳 | 49 AssetBundle、meta/master、captureソース。2回一致 |
| 入力変更検知 | 各capture前後の再ハッシュで変更なし |
| 自動テスト | 79 passed |

snapshot内容ハッシュはキー順を正規化したJSONから算出する。ファイルのバイト列SHAとは区別する。
投影面積はYZ面の三角形の和集合であり、透明テクスチャの透過は含まない。
プレビューは0/4/8/12番目の4姿勢。親エージェントが手足姿勢の変化と側面形状を確認したが、人間の全部位レビューの代用ではない。

## 証拠と再生成

非公開の実行先: `private/oguri/direct-final-002/`。

- `completed.json`: Unityのcapture完了、版と診断状態。
- `inputs-0.json` / `inputs-1.json`: 入力DB・読み込み済みアセット・captureソースのSHA-256。
- `inventory-0.json` / `inventory-1.json`: モデル、clip、spring順、mesh、骨の参照先。
- `unity-a/` / `unity-b/`: 各16組のOBJ、snapshot、変換・更新条件provenance。
- `diagnostic-adapter.json` / `blender/` / `blender.log`: 入力SHA付きBlender取り込みと実形状。
- `comparison.json`: 各時刻の全比較値。
- `preview.png`: 非公開の形状プレビュー。

Unityログ: `.cache/unity-direct-final-002.log`。
数値と証拠ハッシュのみの監査要約: [direct-capture.audit.json](direct-capture.audit.json)。
最終capture後に追加した入力台帳一致の自動停止ゲートは、保存済み実入力へ適用してPASSを確認した。

```powershell
& 'D:/VibeCoding/RunFlow/scripts/run_direct_capture.ps1'
```

固定Editor版を検査し、新規出力を使い、Unityの終了と完了記録を確認してからBlender比較する。
ゲームの追加ダウンロードは無効。Config内の鍵等はprovenanceやログへ転記しない。
準備方法は [integrations](../integrations/README.md)。

## 修正した実行上の問題

- 初回の起動失敗はlicenseログで確認。インストール完了後のHubライセンス更新を経て、固定Editorの実行に成功した。
- Head/Hipの同名Transformは単純な全階層検索では曖昧。HeadはUmaViewerのHeadBone参照、他はPosition以下の骨を明示して解消した。
- master.mdbのSHA取得はSQLiteが開いているため共有エラーになった。読み取り専用のFileStreamで共有を許可し、変更検出は前後SHAで維持した。
- 失敗したcaptureや起動ログは保持し、成功した結果に混ぜていない。

## 残る研究上の判定

通常巡航のclipとpitch/stride等の合成条件、接地起点、実寸・前方・部位の初回レビューは未確定。
OBJ経路の関節はUnity由来の共有データであり、独立したBlender骨計測との比較ではない。
PMX/VMDの52骨トラック不一致は未修正。今回検証した経路はUnityで変形済みの形状を直接転送する経路。
部位ラベルは期待する項目の一覧で、存在を人間が承認した記録ではない。
これらを埋めた正式manifestによる設定SHAの二重生成は残件。`scientific_status=PENDING_HUMAN_REVIEW`、`ranking_eligible=false`を維持する。
