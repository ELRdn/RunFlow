# 保存済み全身候補の微修正

対象は採用済み `adopted-002` frame 0 の、保存済み1mm・0.9mm全身候補。元の姿勢・尺度・RF座標・原本を維持する。0.8mm以下も含め、新しいボクセル再生成は行わない。CFD実行・候補の採用・許容差変更・科学的承認は含めない。

本書は実施済みの比較を記録する。残る方法と、0.9mmを主軸にする次の試験案は [局所修正の残件調査・計画](LOCAL_REPAIR_PLAN.md) を参照。生成済み8候補の計測完了と、局所修正方式を尽くした状態は異なる。追加試験はまだ開始していない。

入口は `scripts/run_fullbody_surface_repair.py`。専用Python環境とBlender 4.2.23 LTSを使用する。既存のPhase 0/CFD CLI契約は変更しない。

```powershell
& .venv/Scripts/python.exe scripts/run_fullbody_surface_repair.py --output E:/RunFlowPrivate/phase1-validation/fullbody-repair-NEW --action probe
& .venv/Scripts/python.exe scripts/run_fullbody_surface_repair.py --output E:/RunFlowPrivate/phase1-validation/fullbody-repair-NEW --action compare
```

`probe` は新規出力先だけを受け付ける。原本・manifest・共通整理済み入力・保存済み2候補・参照図をハッシュ検証し、既知の不合格点と復元対象の面を確認する。参照元は `fullbody-voxel-001/v1000` と `fullbody-voxel-002/v900` に固定している。入力設定は新しい保存先の `request.json` に記録する。`compare` はその確認済み保存先で一度だけ実行できる。終了した試験・開始済み比較の自動再試行や上書きは拒否する。

## 修正の比較

最初に3方法を試し、実際の停止・距離の原因を踏まえて2方法を追加した。各基準へ独立に適用する5方法・計10枠を記録し、生成できた候補と未起動・資源停止を区別する。

|方法|処理|主な限界|
|---|---|---|
|nearest25|各頂点を元の最寄り面へ25%戻す。最大移動0.5mm|欠落した面そのものは増えない。近接する別の面へ引かれる可能性がある|
|normal50|最寄り面との差を候補の頂点法線へ投影し、50%戻す。最大移動0.5mm|横方向の移動を抑えるが、面の交差や裏返りを自動的には防げない|
|detail_union|可視の欠落候補を元の面から薄い立体として復元し、全身候補とExact Booleanで結合|薄さは近似。開いた元の面や交差から生じる誤り、固体の内部に埋もれる面の除去を別検査する必要がある|
|manifold|同じ閉じた立体をManifold 3.5.2で結合|入力が閉じていることを要求する。和集合は固体内部の面を外へ戻さず、後処理後の接続検査も必要|
|raycarve2|原本へ向けた光線で確認した空間を、固定した顔・髪の領域で全身候補から差し引く|有限の奥行き格子と余裕により未修正部分が残る。原本の連続した外形や自己交差のなさを保証しない|

復元対象は、元の三角形の頂点・中心のいずれかが候補から1mm超離れ、原本を6方向から見た際の最初の面として確認できるもの。共通整理済み原本の面番号で保存し、頂点を共有する隣接1周を加える。部位名の自動認定ではない。Booleanには全身候補を渡し、切り出した全身からの再生成はしない。

薄い立体はComplex Solidify / Constraints、中央配置、厚み0.4mmを使用する。0.4mmは面の厚みであり、ボクセル解像度ではない。数値で指定した厚さをそのまま精度とみなさず、出力後に測る。最初の移動・結合候補では生成直後と、既存の退化面周辺の1µm整理後を区別して保存する。

空間の切り戻しでは、元の全身を見た0.1mmの奥行き格子、0.2mmの手前余裕、3×3近傍の浅い側への制限から閉じた切削形状を作る。この0.1mmは観測格子であり、全身のボクセル再生成ではない。全身候補からの差集合後、Manifoldの1µm簡略化とbinary32再取り込みを使用する。ライブラリの簡略化許容差を独立した精度証明とみなさず、完成形状へ従来の距離・面積・接続・自己交差検査を適用する。平滑化・体格変更・部位省略は追加しない。

追加入口は `run_manifold_repair_trial.py --action generate`、同 `--action measure`、`run_ray_carve_trial.py --revision 1`。いずれも `--root` で元の比較先を指定する。`--revision 2` は今回の読み取り専用float64バッファのネイティブ取り込み失敗から、保存済み切削形状を再利用する限定的な継続経路である。成功した生成を再試行する機能ではない。

Manifoldは公式3.5.2のCPython 3.12 Windows wheelを `.tools/manifold3d-3.5.2` に分離して読み込み、wheelと展開ファイルをSHA固定する。通常の依存lockやBlender版を変更しない。必要な `install.json` と固定ファイルがない環境では停止する。

新しい環境では `.venv/Scripts/python.exe scripts/install_repair_manifold.py` で固定wheelだけを取得する。既存の導入先は上書きしない。実験時に使用した処理コードは各非公開出力の `tool-sources` に保管し、終了後の実装修正と実測に使った版を区別する。

## 判定と計測

既存の2mm・正面投影面積1%を維持する。元の全三角形を対象とした双方向距離、全身1mm／問題部位0.1mmの被覆、1nmの投影精度格子、同じ6方向の表示を再使用する。面積差に加えて減少・追加・対称差、元の隙間が埋まった部分・広がった部分・外につながった部分を保存する。

1点でも2mm超の下限が確認できれば不合格の反例になる。一方、部分的な計測や可視点だけの小さな差では、全身合格を認定しない。全原本の面を含む距離と、外から最初に見える面の差は別の指標である。6方向で見えないだけで密閉された内部とは判断しない。

境界・辺と頂点の非多様体・法線の不整合・退化面を確認する。自己交差は独立した検査記録がない限り未確認とし、必須部位・隙間は人間レビューを残す。すべて `scientific_status=UNAPPROVED`、`ranking_eligible=false`、採用なし、Drag/Cd/CdAはnull。

## 時間・資源・保存

実処理の合計は最大12時間。各生成30分、各候補の計測75分、報告30分の段階上限と残り総予算を同時に適用する。合成テスト・実装時間は含めない。前処理・2つの実入力確認は消費済み予算に加算する。

CPUは24論理コアまで指定し、投影は8プロセス。前回と同じプライベートコミット80GiB、空きRAM8GiB、コミット余裕16GiB、出力300GiB、空き容量E50/C20/D15GiBを監視する。初回のExact結合では、監視間隔内の急な確保でコミット上限の超過を観測した。後続にはWindows Job Objectのメモリ割当て制限を追加し、合成試験で確認した。現在の主入口も同じ制限を使用する。子プロセスの終了を確認し、資源制限で失敗した生成は自動再実行しない。

候補の保存はNumPyのバイナリと分割処理を維持する。原本・候補・コード・実行ファイルのSHA-256を関連付け、設定IDからパスと日時を分離する。初回確認・本比較・追加方式それぞれのコードを保存する。既知点の座標は非公開設定から取得する。

独立した自己交差検査は `check_repair_intersections.py --root <比較先> --case <候補> --local-io --attempt 3 --timeout 600`。Foundation 14の `surfaceCheck -checkSelfIntersection` と座標が一致するbinary STLを使う。Windowsドライブへの大量のASCII診断出力で時間切れになったため、同一形状をWSL内の専用一時領域で検査し、診断ファイルをまとめてEへ保存する。形状や検査実行ファイルは変えない。WSL側の時間・RSS・容量・ハートビートも監視し、所有する検査プロセスの終了確認後、一時領域だけを片付ける。実行成功と交差検出の有無は別項目である。

実形状・数値・図はEの非公開領域に保存する。リポジトリには実装・手順・定性的な進捗を残し、公開用出力へ取り込まない。`finish_surface_repair_validation.py --root <比較先>` が選定断面を計測し、`finalize_surface_repair.py --root <比較先>` が追加方式を含めて集計する。日本語の最終入口は `final-REVIEW.md`、統合結果は `final-summary.json`。最初の `REVIEW.md` と `summary.json`、途中プレビュー、失敗ログを残し、完成済み資料への上書きは拒否する。

`--report-output <新しい非公開フォルダ>` を指定すると、Eの形状を読み取り専用で参照し、資料だけを別の非公開領域へ生成できる。今回の完成版はEの `fullbody-repair-003/final-review/final-REVIEW.md`。自動承認レビューの時間切れ後、ユーザーが `scripts/copy_surface_repair_review.ps1` を手動実行し、最終資料16ファイルのコピーとSHA照合を完了した。コピー先の実ファイルも照合記録に対して再検証済み。作成元の `private/phase1-validation/repair-final-review-002/` と既存の試験記録は保持する。既存の配布先への上書きは拒否する。図の凡例の修正と保存済み基準の局所投影参照は資料の修正であり、補修候補を再生成したものではない。

今回の試験では、生成可能だった候補の計測を終えたが、全条件を通る補修候補は得られなかった。微小移動だけでは欠落を戻しきれず、面の足し戻しは固体に埋まる面を復元できなかった。観測空間の切り戻しでは局所改善を確認した一方、距離超過と候補間の自己交差検査の違いが残った。必須部位の最終人間レビュー・候補採用は未実施。詳細な数値・図・費用・検査記録は非公開の `fullbody-repair-003` に保存する。

## 手法の調査

[Blender 4.2 Shrinkwrap](https://docs.blender.org/manual/en/4.2/modeling/modifiers/deform/shrinkwrap.html)、[Solidify](https://docs.blender.org/manual/en/4.2/modeling/modifiers/generate/solidify.html)、[Boolean](https://docs.blender.org/manual/en/4.2/modeling/modifiers/generate/booleans.html)を確認し、設定を[固定版の実装](https://github.com/blender/blender/blob/d0cbe84903e8550c66247e96f9703f60e4b7c3b7/source/blender/makesrna/intern/rna_modifier.cc)と対応付けた。新しいBlenderの機能を4.2にあるとみなさない。

[CGAL Alpha Wrapping](https://doc.cgal.org/latest/Alpha_wrap_3/index.html)は三角形群から閉じた包絡面を作れる別方式だが、内部の面を含む双方向2mmを保証せず、今回は実装しなかった。[Manifold作者の説明](https://github.com/elalish/manifold/discussions/471)に従い、閉じた基準とSolidify済みの入力を確認してから[固定版3.5.2](https://github.com/elalish/manifold/releases/tag/v3.5.2)を追加試行に使用した。

[Curless–Levoyの一次論文](https://graphics.stanford.edu/papers/volrange/)は、奥行き観測と空き空間を区別する考え方の参考とした。今回の2.5D切削試験は、この論文のボクセル統合処理を実装したものではない。[Foundation 14のsurfaceCheck](https://github.com/OpenFOAM/OpenFOAM-14/blob/master/applications/utilities/surface/surfaceCheck/surfaceCheck.C)では、自己交差検査より先に分割部品とASCIIの領域図を書き出す順序も確認した。

欠落 `Gallop.CharaTransformProcessData` の役割と、公式形状との完全一致は引き続き未確認。
