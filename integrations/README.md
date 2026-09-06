# Capture adapters

アセットは同梱しない。正式なsnapshotは `schemas/snapshot.schema.json`。
部位: head, torso, left_arm, right_arm, left_leg, right_leg, ears, hair, tail, costume。
必須関節: head, hip, left_hand, right_hand, left_knee, right_knee, left_foot, right_foot。
追加関節は両方のcaptureで名前集合を一致させる。

## 座標

前方+X、上方+Z、m。`source_to_rf` は倍率を含む4x4行列。
`meters_per_source_unit` / Unityの `rfScale` は検証用で、倍率を二重に掛けない。
メッシュと関節から各時刻のroot Xを引き、Y/Zを保持。
`root_position` には変換後の元の軌跡を保存する。
部位名だけでは存在の証拠にならない。人間の部位レビュー記録を別途要求する。

## Unity

UmaViewerソースを `d50b28379337b507751a7df705a10afeab2c37ce` に固定し、
`unity/RunFlowCapture.cs` を `Assets/RunFlow/` へ配置する。Unity 2022.3用。
固定版Editorで指定衣装の実モデルを16時刻×2回captureし、Blender形状転送比較までPASS。
条件・数値・未承認事項は [直接出力検証記録](../reports/direct-capture.md) を参照する。

### 固定版Editorでの自動診断

準備済み環境では、PowerShellで `& 'D:/VibeCoding/RunFlow/scripts/run_direct_capture.ps1'` を実行する。
各回で新規出力先を作り、Editorの実終了とcompleted記録を確認してからBlender比較へ進む。ライセンス不備・コンパイルエラー・静止した出力を成功と扱わない。

`RunFlowBatchDriver.cs` は固定版のVersion2シーンを開き、キャラ1006・モデル衣装suffix02を新規に2回ロードする。
通常巡航として未認定のrun02_baseを使い、clip長の1/64を刻み、5周期後から1周期を16分割する。
終点は重複させない。接地起点はまだ特定していないため、`contact_phase_verified=false` の診断である。
顔Animator・locatorをbody更新の後、spring更新の前に評価し、目線追従を無効化する。
springは階層パス順で固定。root・モデル・Animatorは実行ごとに作り直す。
読み込まれたAssetBundle、meta、master、captureソースのSHA-256を保存する。
ゲーム入力を前後で再ハッシュし、2回の入力台帳が異なれば比較を拒否する。データの追加ダウンロードは無効。

`diagnosticOnly=true` は未承認の部位ラベルでも診断を可能にするが、科学承認や研究入力としての採用を意味しない。
単位倍率1はUnity座標の公称mであり、公称身長への調整を行わない。実寸・前方軸・部位の確認は別途必要。

```powershell
.venv/Scripts/python.exe scripts/prepare_unity_project.py --project .tools/umaviewer-project/UmaViewer-d50b28379337b507751a7df705a10afeab2c37ce --viewer-config .tools/umaviewer/runtime/build/StandaloneWindows64/Config.json
& 'C:/Program Files/Unity 2022.3.62f1/Editor/Unity.exe' -batchmode -projectPath D:/VibeCoding/RunFlow/.tools/umaviewer-project/UmaViewer-d50b28379337b507751a7df705a10afeab2c37ce -executeMethod RunFlow.RunFlowBatchEntry.Execute -runFlowOutput D:/VibeCoding/RunFlow/private/oguri/direct-new -logFile D:/VibeCoding/RunFlow/.cache/unity-direct-new.log
.venv/Scripts/python.exe scripts/compare_direct_capture.py --capture-root private/oguri/direct-new --blender .tools/blender/blender-4.2.23-windows-x64/blender.exe
```

最初のprepareは未変更ソースに一度だけ実行する。秘密情報を含む可能性があるConfigは無視対象のプロジェクトにのみコピーし、ログ・provenanceへ内容を出さない。
GUI版Unityはシェルへ先に制御を返す場合がある。終了コードだけで成功判定せず、`completed.json` と各16snapshotを確認する。
比較はUnity間の完全ハッシュ一致、Blender往復後の頂点順・頂点差1e-5公称m以内・投影面積差1%以内を要求する。
OBJ経路の関節は共有メタデータなので、独立した関節差の検証とは報告しない。固定姿勢の平行移動だけの入力も拒否する。

専用シーンにroot、Animator、clip、関節Transformを指定する。
`animatorStateName` へ実際のcontroller stateを指定する。固定版UmaViewerは `motion_2` を使う。
state名とclipファイル名は別。再生中のclipが指定clipと一致することをコードで検査する。
固定刻みは `1/fps`、sample間隔は `simulationStepsPerSample/fps`。
16点の時刻は `(warmupSteps + i*simulationStepsPerSample)/fps` で、CLIのsamplingと一致させる。
終了点を重複させない。出力先には存在しない非公開ディレクトリを指定する。

`scripts/prepare_spring_patch.py` は固定版DynamicBoneのSHA-256を確認し、変更済みコピーを新規出力する。
通常のフレーム更新を抑止するmanual modeと、明示dtによる更新APIを追加する。
Default mode内も引数dtを使うよう変更し、通常再生時は従来どおり呼び出し元のTime.deltaTimeを受け取る。
上流checkoutは書き換えず、生成したDynamicBone.csを研究専用Unityプロジェクトへ組み込む。

`RunFlowSpringBridge.springs` に対象モデルのDynamicBoneを重複なし・固定順で設定する。
以下をInspectorでpersistent listenerとして結線する。

| RunFlowCapture event | RunFlowSpringBridge |
|---|---|
| onResetUmaViewerSprings | Begin |
| onBeforeAnimation | BeforeAnimation |
| onStepUmaViewerSprings(dt) | Step（dynamic float） |
| onFinish | End |

`onFinish` は例外時もfinallyから呼ばれる。カメラ距離によるspring無効化は明示的に解除した実験シーンが必要。
接続を検証するまで `hasVerifiedSpringIntegration` はfalse。
上流DynamicBoneのDefault modeは内部で `Time.deltaTime` を使うため、Animatorを固定刻みにするだけでは不十分。
初期化、更新順序、時間供給を固定して二重captureを比較する必要がある。
**固定版Editorで結線・body→face→springの明示更新・実モデル二重実行を確認済み。これは指定した更新条件の再現性であり、実ゲームの合成条件との一致を主張しない。**
キャプチャは同期処理。実験専用シーンで実行し、通常更新との二重実行を避ける。

出力はOBJ・snapshot JSON・provenance。元軌跡、変換、mesh順、joint source、warmupを記録する。

## Blender

```powershell
.tools/blender/blender-4.2.23-windows-x64/blender.exe --background --factory-startup --python-exit-code 2 --python integrations/blender/runflow_capture.py -- --manifest private/oguri/adapter.json --output private/oguri/blender-new
```

取り込み専用manifestはCLIの実験manifestとは別。
共通キーは `schema_version:"1"`, `route`, `source_to_rf`, `meters_per_source_unit`,
`parts_review_reference`, `samples`（昇順time_sを含む16要素）。

### obj_sequence

各sampleに `obj, obj_sha256, snapshot, snapshot_sha256` を指定する。パスはmanifest基準。
Unity側snapshotの関節・時刻・部位を使う。OBJ単体では関節情報が欠けるため拒否する。
既にRFのmなので行列は単位行列、倍率1。root Xを二度引かない。
実行可能な合成例: `python scripts/blender_smoke.py --output private/synthetic/new-input`。

### mmd_tools_pmx_vmd

追加キー:

| キー | 意味 |
|---|---|
| pmx, pmx_sha256, vmd, vmd_sha256 | 入力とハッシュ |
| mmd_tools_parent | addons親フォルダへのパス |
| mmd_wheel_dependencies | 同梱OpenCC wheelの展開先 |
| armature_name, root_bone | インポート後の明示的な名前 |
| joints | semantic名から元の骨名への対応 |
| part_objects | 各必須部位からmesh名配列への対応 |
| vmd_start_frame | VMD先頭を配置するBlender整数フレーム |
| vmd_fps | 録画フレームと秒の対応 |
| recording_start_clip_s | VMD先頭に対応する元clip時刻 |

PMX/VMD倍率は1、単位変換は行列へ集約する。
行列はBlenderのPMX軸変換後に対して測定する。Unity行列を無条件で流用しない。
自動cleanup、頂点結合、骨名変更、IK修正を無効化し、rigidbody worldを停止する。
アドオン登録はプロセス内のみ。preferencesや既存blendは保存しない。
VMDはMMD rootを選択して読み、骨とモーフの両方を取り込む。armatureだけの選択によるモーフ欠落を避ける。
全VMD骨トラックの名前対応を取り込み前に検査する。今回の原本PMXと候補VMDは52/52トラックが未対応のため停止する。
固定版RecorderはPosition→センター、Hip→グルーブ等の変換とA-pose補正も行う。
名前の置換だけで忠実性を認定せず、対応・基準姿勢・IK・springを検証するか直接メッシュ経路を使う。
