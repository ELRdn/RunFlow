# 接地候補と実寸の測定

2026-09-06。固定版Unityで中立立位と両足の細かい時系列を実測した。
**測定・入力の二重実行はPASS。右足接地の幾何学的候補は約0.5894秒。物理的な床面と身体頭頂の対応は未確定。**
元の形状・倍率は変更していない。

測定図を提示した後、ユーザーが**右足候補0.5894131075056082秒を研究上の位相基準として確定**した。
尺度も**詳細な身体頭頂測定を省略し、元のUnity倍率を信頼して採用**する判断を受領した。
1 Unity world単位を1mとして使用し、追加のリスケールは行わない。参照身長は1.67m。
これは研究条件の採用であり、実レースの床面や独立した実寸較正を検証済みに変えるものではない。
証拠は `private/oguri/measurements-002/adoption-decision.json`。測定時点のanalysisや画像は変更しない。

## 実行条件と再現性

対象はJP Steamのキャラ1006・衣装100602、候補 `anm_rac_type01_run02_base`。
Unity2022.3.62f1、UmaViewer d50b28379337b507751a7df705a10afeab2c37ce、既存DynamicBone固定更新パッチを使用。

- 中立姿勢: `IsTPose=true` により待機clipと笑顔を抑止。マージ済みprefabのbind poseをAnimator.Update前に取得。画像では立位・水平に開いた腕を確認した。
- 走行: モデルを新規ロードし、body→face→springを明示更新。1周期256step、dt約0.00234375秒、5周期ウォームアップ後に2周期を取得。
- 2周期の端点を含め513点。これは接地探索用であり、16時刻のCFD用サンプリングではない。
- 足は `M_Body` のAnkleとその子骨へのスキンウェイト合計0.8以上で選択。左793頂点、右790頂点。中立姿勢と走行で同じ頂点IDを使う。
- モデルを作り直して2回実行。中立形状、足の時系列、入力台帳の正規化JSONハッシュは各々完全一致。
- meta/master・ロード済みアセット・計測ソース・DynamicBoneのSHAを保存。測定前後に入力変更がないことを検査した。
- Python自動テスト83件PASS。C#静的コンパイルと実Editor実行を確認。

最終証拠: `private/oguri/measurements-002/`。
初回 `measurements-001` は形状・足の時系列が一致したが、最初の中立ロードだけ入力bundle一覧が少なかった。
002では計測前に対象bundleをロードしてから各モデルを新規生成し、入力一覧の一致も確認した。001も保持する。

## 接地候補

床面の暫定値は、立位での左右の靴の最下頂点を平均した `Z≈0`。
ゲームのレース地面を取得した値ではない。
足先がこの面から0.03単位以上離れた状態を0.1秒以上経た後、最初に下降して面を横切る時刻を線形補間する。
これは探索用の判定規約。短い踵・爪先の再交差を別の歩として数えない。

| 項目 | 右足 | 左足 |
|---|---:|---:|
| 最初の接触候補（5周期後を0秒） | 0.5894131 s | 0.2888969 s |
| 同一側の次の候補まで | 0.5999999 s | 0.6000002 s |
| 立位支持面より下の最大深さ | 0.0447718単位 | 0.0449048単位 |

右足候補はdense frame251～252（0.5882813～0.5906250秒）の間。親エージェントが接触前後の靴の形状を画像で確認し、踵が線に達してから爪先側へ移る動きを確認した。
立位支持面を基準にすると、その後に爪先が下へ入る。地形、靴、モーション合成、接地補正との関係は未照合。
採用した1単位=1mの尺度では深さは約4.5cmに相当する。実際のレース地面への貫通量とは断定しない。

| 仮定する床面の変化 | 右足の最初の候補 |
|---|---:|
| +0.005単位 | 0.5857195 s |
| 変更なし | 0.5894131 s |
| -0.005単位 | 0.6044259 s |

約18.7msの幅は、この3つの床面を試した感度であって、統計的な信頼区間ではない。
下げた床面では最初の浅い踵接触を越え、爪先側の交差を拾う。
したがって小数点以下の桁を増やして物理的な接地時刻が確定したようには扱わない。
`analysis.json` にこの候補を起点とした16時刻案を保存した。後続の人間判断で位相基準として採用されたが、**採用位相での16時刻再captureはまだ行っていない**。

## 身長・単位

[公式プロフィール](https://umamusume.jp/character/oguricap/) の身長167cmは前のレビューで確認済み。
今回DBの `scale=167` と、固定版ソースの `BodyScale=167/160.7529`、実行時倍率 `1.03886151` を照合した。
`height` カラムのカテゴリ値を身長として使っていない。

| 立位で測った範囲 | 上端Z（公称Unity単位、足裏面はほぼ0） |
|---|---:|
| 全mesh・耳と髪を含む | 1.73621488 |
| 耳のスキンウェイトが0の髪頂点のみ | 1.72856900 |
| M_Faceの上端 | 1.59112024 |

耳だけ除いても髪の立ち上がりが残る。M_Faceの上端も身体の頭頂とは認定できない。
中立姿勢で寸法を測る処理はできたが、**裸足から身体頭頂までの167cmに対応する測定点は未同定**。
この詳細測定は後続のユーザー判断により省略する。測定できなかった事実は残すが、追加の承認待ちにはしない。
`scale`値と公式身長の一致は倍率設定の追跡根拠であり、単独で1単位=1mの較正を証明しない。
全高を167cmに合わせて縮小する処理は行わない。

コードの確認箇所:

- 固定版 `UmaContainerCharacter.SetHeight`（291～305行）: scale/160.7529をPositionのlocalScaleへ設定。
- `UmaViewerBuilder.LoadNormalUma`（331～341行）: スケール設定後にInitialize、IsTPoseならidleをロードしない。
- `LoadUma` の第3引数は `mini`。`false`をloadMotion=falseと解釈しない。
- `Initialize` は頭頂や足裏を定義しない。`EyeHeight`も視線追従用で、頭頂マーカーではない。
- ログの `Gallop.CharaTransformProcessData` missing script警告は残る。今回の測定実行は終了したが、ゲームと同じ処理が全て動いた証明ではない。

## 測定図・再実行

非公開図:

- `figures-verified/neutral-scale.png`: 中立立位と全高・仮の1.67単位線。身体頭頂の測定線ではない。
- `figures-verified/right-contact.png`: 接地候補前後の8時刻。前後方向の並進のみ表示用にそろえ、高さ・形状を保持。

既存測定の図だけ再生成する場合は `render_measurement_evidence.py` に `--output` で新しい非公開ディレクトリを指定する。既存図は上書きしない。

```powershell
& scripts/run_direct_capture.ps1 -Measurements -RunName measurements-new
.venv/Scripts/python.exe scripts/analyze_measurements.py --measurement-root private/oguri/measurements-new
.tools/blender/blender-4.2.23-windows-x64/blender.exe --background --factory-startup --python-exit-code 2 --python scripts/render_measurement_evidence.py -- --measurement-root private/oguri/measurements-new
```

採用済みの位相・尺度をcaptureと正式manifestへ反映し、16時刻の二重出力・形状比較・設定SHA二重生成までPASS。[実行記録](adopted-capture.md)。
実ゲームとの合成条件・地面補正の一致、missing scriptのゲーム側機能は未確認の制約として残る。[欠落型調査](missing-transform-script.md)。
部位・位相・尺度の初回判断は受領済み。キャラクターCFDの科学的承認とランキング適格性は別途未承認。
