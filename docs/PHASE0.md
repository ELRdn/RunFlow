# Phase 0 runbook

対象: 日本版Steam、オグリキャップ1006、シンデレラグレイ衣装100602、通常レース直線走行。
カード100603と衣装100602を混同しない。
現在の実行証拠と残件は `reports/phase0-status.md`。

## 環境

Python 3.12とuv.lock、Blender4.2.23、MMD Tools4.5.14、UmaViewerのcommit
`d50b28379337b507751a7df705a10afeab2c37ce` を固定する。
OpenFOAM Foundation14はUbuntu24.04の `openfoam14=20260724`。
取得URL・ハッシュは `configs/toolchain.lock.json`。
Windowsツールは `.tools/` に配置し、ユーザーのBlender設定・bashrcは変更しない。

新規環境では `python scripts/setup_tools.py --download` で固定アーカイブを取得・SHA-256検査する。
既存の展開先は上書きしないため、既存ランタイムの版は別途実行確認する。
WSL導入はUbuntu24.04内で `sudo bash /mnt/d/VibeCoding/RunFlow/scripts/setup_openfoam.sh`。
APTへの専用ソース追加とパッケージ導入を行う。Unity 2022.3 Editorのセットアップ・ライセンス確認は別途必要。
このPCではUnity **2022.3.62f1 / 4af31df58517** の導入と実行を確認済み。
準備済み固定プロジェクトは次の1コマンドで新規capture・Blender比較を実行する。

```powershell
& 'D:/VibeCoding/RunFlow/scripts/run_direct_capture.ps1'
```

同じプロジェクトを別のUnityで開いたまま実行しない。新規環境の準備は [adapter手順](../integrations/README.md)。
出力は `private/oguri/direct-<日時>/`。`completed.json`、`inputs-0/1.json`、`comparison.json` とログを残す。
候補clipの診断なので、接地や実寸が未承認のまま正式manifestを埋めない。

```powershell
uv sync --frozen --python 3.12 --cache-dir .cache/uv
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/runflow.exe schemas --output schemas
.venv/Scripts/python.exe scripts/reproduce_synthetic.py --output private/synthetic/repro-new
```

最後は自作データによる再現性試験。ゲーム取り込みの証明には使わない。

## 取り込み

走行候補の実測・VMD不一致は [motion discovery](../reports/motion-discovery.md) に記録。
台帳は `scripts/dump_motion_catalog.py`、対象絞り込みは `scripts/analyze_motion_catalog.py`。
どちらも `--game-data` と非公開の新規 `--output` を指定する。dumpには専用UmaViewerの `--viewer`、分析には `--catalog` が必要。
暗号化metaも同梱ライブラリを読み取り専用で使い、鍵・復号DBは出力しない。

```powershell
.venv/Scripts/python.exe scripts/dump_motion_catalog.py --game-data "<ゲームデータフォルダ>" --viewer .tools/umaviewer/runtime/build/StandaloneWindows64 --output private/motion-catalog/new-scan
.venv/Scripts/python.exe scripts/analyze_motion_catalog.py --catalog private/motion-catalog/new-scan/catalog.json --game-data "<ゲームデータフォルダ>" --output private/motion-catalog/new-analysis
.venv/Scripts/python.exe scripts/prepare_spring_patch.py --source "<固定版DynamicBone.cs>" --output private/unity-patch/new-patch
```

1. ゲーム内で必要なデータを取得し、meta・master/master.mdb・datを確認する。
2. 専用UmaViewerでJapan/Default、データパス、VmdKeyReductionLevel=1を設定する。
3. Characters → 1006 オグリキャップ → シンデレラグレイ → Model → Export Model。
4. PMXと関連ファイルは `private/oguri/pmx/` へ保存する。
5. 通常レース直線走行を選び、clip IDを記録。目・耳だけのclipや特殊演出を代用しない。
6. VMD先頭と元clip時刻を対応付ける。録画開始のクリックを接地イベントとみなさない。
7. `configs/manifest.pilot.template.json` を非公開領域にコピーし、ID・入力SHA-256・実寸根拠・変換・接地時刻を埋める。
8. `integrations/README.md` のアダプターでUnity2回・Blender1回の16時刻を取得し、数値と目視で照合する。

```powershell
.venv/Scripts/python.exe scripts/probe_assets.py --game-data "<ゲームデータフォルダ>" --steam-build "<build ID>" --output private/intake.json
.venv/Scripts/runflow.exe validate private/oguri/manifest.json --asset-root private/oguri
.venv/Scripts/runflow.exe sample private/oguri/manifest.json --asset-root private/oguri --output private/oguri/sampling.json
.venv/Scripts/runflow.exe generate private/oguri/manifest.json --asset-root private/oguri --output private/oguri/config-a
.venv/Scripts/runflow.exe generate private/oguri/manifest.json --asset-root private/oguri --output private/oguri/config-b
.venv/Scripts/runflow.exe verify-gait private/oguri/manifest.json --asset-root private/oguri --reference private/oguri/unity-a --candidate private/oguri/blender --repeat private/oguri/unity-b --output private/oguri/gait-verification.json
```

新規の出力先を使う。null、単位不明、入力欠落・ハッシュ不一致は意図どおり停止する。
`chara_data.height` は身体形状カテゴリであり身長ではない。耳・髪を含む外接高さへ公称身長を合わせない。
スケール・頭頂/足底の定義は人間が確認する。

## 検証とデータ契約

生成設定はUTF-8 JSONのキー順・区切りを固定してSHA-256化する。
ファイル絶対パス・実行日時をIDから除き、入力内容・ID・ツール版・変換・前処理・時刻・重みを含める。
CLIスキーマは `schemas/`。asset台帳・sampling・experiment・result・task-logを保存する。
16点は終点を重複させず等間隔。必要CFDサンプル数はPhase1で評価する。

比較は関節位置差が身長の0.5%以内、YZ面への三角形投影和集合の面積差が1%以内。
重なる三角形を二重計上しない。透明テクスチャは考慮しないため、毛髪カード等は別途確認する。
Unity二重実行はsnapshot全体のハッシュ一致を要求する。
数値合格だけで部位の存在や公式への忠実性を認定しない。

`Execution PASS`と`Scientific PASS`は別。CLIは科学的承認を発行しない。
未計算のDrag/Cd/CdAはnull、Phase0キャラクターはランキング対象外。

## CFD smoke

```powershell
.venv/Scripts/runflow.exe baseline --output private/baseline/new-run --distro Ubuntu --timeout 1200
```

WSL権限の制限がある場合は通常のローカル端末で実行する。
新規ケースで `blockMesh → mirrorMesh → checkMesh → foamRun` を実行し、ログ・入力ハッシュ・結果を関連付ける。
直径0.001m、流速0.015m/s、動粘性1.5e-5m²/sからRe=1を実ファイルで検証する。
Linux側timeoutも設け、古い計算結果を再利用しない。
成功条件はMesh OK、正常終了、有限な力の履歴。人体空力の妥当性の証明ではない。

`configs/cfd.phase1.template.json` は意図的に未設定。`generate --cfd` は不完全なら拒否する。
完全な設定でもPhase0 CLIにはキャラクターCFDの起動機能はない。

## ローカル公開用要約

```powershell
.venv/Scripts/runflow.exe publish private/baseline/new-run/result.json --output artifacts/public-summary-new
```

外部公開ではない。許可された数値・status・IDだけを書き、notes・パス・形状をコピーしない。
第三者アセット、派生メッシュ、PMX/VMD/blend、全ゲームDBは非公開。
rosterはcharacter+costumeとsource snapshotで識別し、追加時は別snapshotを作る。

一次資料: [UmaViewer](https://github.com/katboi01/UmaViewer)、[MMD Tools](https://github.com/MMD-Blender/blender_mmd_tools)、[OpenFOAM](https://openfoam.org/download/14-ubuntu/)。
