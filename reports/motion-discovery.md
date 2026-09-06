# レース走行のローカル調査と取り込み試験

2026-09-06。**走行アセットの実在とUnityでの再生を確認。通常巡航のCanonical認定とPhase 0完了は未達。**

## 確認結果

- ローカルmetaから `3d/motion/` の94,968件を読み取り専用で抽出。前後のmeta SHA-256は一致。
- `3d/motion/racemain/` は422件。アセット種別は `_3d_cutt`。
- `racemain/_default/anm_rac_typexx_run01_base` は台帳に存在するが、今回のローカルdatには未配置。Genericの `/type0` 等の条件にも一致しない。
- `racemain/body/type01/anm_rac_type01_run02_base` と同系列のpitch/strideはローカルに存在し、Genericから実名で検索できた。
- 指定衣装のオグリキャップで `anm_rac_type01_run02_base` を再生し、異なる手足姿勢を確認した。非公開スクリーンショット2枚を保存。
- masterの `chara_data.id=1006` は `race_running_type=1`。この値からtype01への対応を自動認定していない。
- 通常巡航・開始・スパート・汗拭い・合成ウェイトの意味は未確定。type番号やrun番号だけで分類を確定しない。

台帳にはtype01～04やtype99内の追加系列、base/pitch/strideなどがある。「strideは3種類」という添付調査のコミュニティ観察を、今回のゲーム版の確定仕様には採用しない。

## VMD試験で判明した不一致

対象: `3d/motion/racemain/body/type01/anm_rac_type01_run02_base`

- 指定衣装でUse RootMotionを有効化、Speed=1、KeyReductionLevel=1としてVMDを録画した。
- VMDは52骨トラック、フレーム0～782。録画は候補調査用で、元clip上の開始位相・接地イベントは未同定。
- 固定版Recorderの既定刻みは **0.03333秒**。厳密な1/30秒とは異なるため、そのまま記録した。
- Blender4.2.23 / MMD Tools4.5.14でPMX/VMDを読めたが、**52トラックすべての名前がPMXと不一致**。最終診断は `CANDIDATE_BINDING_FAIL`。
- PMXにはPosition/Hip/Spine等の原名が残り、VMDはセンター/グルーブ/上半身等を使っている。Recorderにはセンターの入れ替え、A-pose補正、足IK用変換もある。単純な名前置換だけでは忠実性の証明にならない。
- 本取り込みアダプターへ未対応VMDトラックを拒否する検査を追加した。読み込めただけの静止モデルを合格させない。

VMD SHA-256: `d89053749060e8aec97b53870846729444b1a34164913f07d2d0fc528751738e`

## 直接出力の実装・実行

固定版DynamicBoneへ、初期化・animation前処理・明示dt更新・解除を追加するパッチ生成器とUnity bridgeを作成した。
Default更新内のTime.deltaTime参照を引数dtへ切り替え、manual mode中は通常Update/FixedUpdate/LateUpdateを停止する。
Captureは実際のcontroller state名を受け取り、終了・例外時にspring manual modeを解除する。

生成パッチ・bridge・CaptureのC#コンパイルは成功。配布DLLにも旧DynamicBone型があるため、検査時はローカルの変更済み型を選ぶCS0436警告が出る。実プロジェクトでは同じソースを置換して組み込む必要があり、配布DLLを差し替えたわけではない。

必要Editorは上流ProjectVersionで **2022.3.62f1 / 4af31df58517** と確認し、この版を導入して実行した。既存6系は使用していない。
指定衣装、31 spring、body→face→spring更新で16時刻を2回直接出力し、全snapshotハッシュ一致。
Blender4.2.23へのOBJ転送後の頂点・投影面積比較もPASS。[条件と定量結果](direct-capture.md)。

## 非公開の実行証拠

| 場所 | 内容 |
|---|---|
| private/motion-catalog/scan-002/catalog.json, motions.txt | 全実パス、種別、locator、依存情報。復号DBや鍵は出力しない |
| private/motion-catalog/analysis-002/ | 最終分類器で再生成した569件のshortlist、MOTION_MAP.csv、master値。racemain422件を含む |
| private/oguri/motion-preview/ | 画面、候補VMD、取得provenance、最終取り込みログ |
| private/oguri/motion-import/run02-base-002/ | FAIL診断と調査用blend。研究入力として未承認 |
| private/unity-patch/001/ | SHA-256確認済みの変更済みDynamicBoneとprovenance |
| private/oguri/direct-final-002/ | 固定Editorの実形状16時刻×2回、入力SHA、Blender比較、非公開プレビュー |

残件: 通常巡航・合成条件の照合 → 接地イベントと周期起点の確定 → 承認した位相で再取得 → 実寸/部位の人間レビュー → 実対象で設定ハッシュ二重生成。
pilotの確定motion_idはnullを維持した。

## 提供された実ゲーム映像の確認

ブラウザーで以下の2ページを開き、映像を静止して確認した。動画全体の連続観察や6イベントのフレーム対応付けは未完了。

- [Vania / Arima Kinen](https://www.youtube.com/watch?v=0lAIZG_MwNA): タイトルと投稿者、説明のglobal表記を確認。ゲート直後、正面寄りの集団走行、側面寄りの集団走行を確認した。側面には `Accel. Up` 表示があり、キャラクターの重なりもあるため、この画面をスキル非発動の通常巡航周期として採用しない。
- [Valfor / URA Finals](https://www.youtube.com/watch?v=GVfJXh0cMac): タイトルと投稿者、No commentary gameplay表記、通常衣装のOguri Capプロフィールを確認。残り200m・Triumphant Pulse表示の固有演出は通常巡航の比較から除外。説明にはCinderella Grayも記載されているが、該当衣装の走行区間は今回まだ同定できていない。
- [Full Run](https://www.youtube.com/watch?v=VxD020QOC8g) と [あぽろの育成映像](https://www.youtube.com/watch?v=pQ9eAiBvMKw) はユーザー提供の追加候補。今回の実視聴・照合は未実施。

映像内の版・衣装と今回のJP Steam buildの一致は未確認。シーク直後の古い表示フレームを時刻証拠にしないため、ここでは秒単位の採用区間を登録していない。
右足前方最大→右接地→交差→左足前方最大→左接地→交差の対応時刻、最大脚開き、接地位置、遊脚回収、胴体、腕の5項目はすべて未判定。
見た目の類似だけではclip ID・pitch/stride合成ウェイト・速度倍率の一意な特定にならない。Canonical認定、関節差0.5%、面積差1%の判定を映像から代用しない。

最終検証数は [Phase 0記録](phase0-status.md) を参照。実Editor統合・実形状capture・Blender形状転送比較はPASS。Canonical認定と科学的承認は未実施。

一次資料:
[固定版DB reader](https://github.com/katboi01/UmaViewer/blob/d50b28379337b507751a7df705a10afeab2c37ce/Assets/Scripts/UmaDatabase/UmaDatabaseController.cs)、
[固定版一覧UI](https://github.com/katboi01/UmaViewer/blob/d50b28379337b507751a7df705a10afeab2c37ce/Assets/Scripts/UmaViewerUI.cs)、
[固定版VMD recorder](https://github.com/katboi01/UmaViewer/blob/d50b28379337b507751a7df705a10afeab2c37ce/Assets/Scripts/Exporters/VMDRecorder/UnityHumanoidVMDRecorder.cs)、
[固定版DynamicBone](https://github.com/katboi01/UmaViewer/blob/d50b28379337b507751a7df705a10afeab2c37ce/Assets/Scripts/DynamicBone/Scripts/DynamicBone.cs)。
