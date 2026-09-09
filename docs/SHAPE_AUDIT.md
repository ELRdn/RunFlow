# 保存済み形状の全体監査

CFD用形状を採用する前に、原形状と候補の差を調べる。再メッシュやCFDは実行しない。CFD試験の失敗結果・時間枠・2mm/1%の条件は変更しない。

## 調べる項目

| 検査 | 分かること | 限界 |
|---|---|---|
| 双方向の全表面距離 | 原形状で失われた面、候補で追加された面、面積重み付きの分布、最大距離の範囲 | 重複面・内部面も含む。外から空気が触れる面の面積とは異なる |
| 3方向の投影面積 | 正面・側面・上面の面積、減少部分、追加部分 | 正味の面積差だけでは、減少と追加が相殺される |
| 投影上の隙間 | 元からあった囲まれた背景領域の面積と、候補で埋まった面積 | 全3D通路の検証ではない。外側に開いた隙間は穴の数に含まれない |
| 6方向の最前面 | 外から直接見える面の位置、輪郭の減少、局所的な欠落候補 | 2mm間隔の視線でサンプリング。斜め方向・隠れた面の全数検証ではない |
| 選定断面 | 脚・衣装、頭・髪などの局所的な境界の変化 | 元データが開いた面を含むため、自動的に内外や空気の通過を認定しない |
| 部位レビュー | 大きな部位の存在、細部の減少箇所 | 現snapshotには面ごとの意味ラベルがなく、自動的な必須部位PASSは発行できない |

## 距離の集計方法

三角形を分割し、各小三角形の中心から各頂点までの距離が1mm以内になるまで細分化する。各中心の最近接距離を測り、小三角形の面積で重み付けする。細長い面や大きな面を、単純な頂点数の平均で過小評価しない。

最大距離の下限は測定最大値から2µmの数値余裕を引いた値、上限は各測定距離＋被覆半径＋2µmの最大値。閾値を超える面積の割合も、中心値による推定と、小三角形全体を考慮した上下限を分ける。これは監査用の分布であり、CFD取り込みの2mm条件を合格に変更するものではない。

6方向の最前面では、視線上の奥行き差と、原表面点から候補への最短距離を別に保存する。輪郭が少し欠けると、最前面が遠くの別部位へ切り替わり、奥行き差だけが大きくなる場合があるため。

被覆による上下限には2µmの工学的な数値余裕を加えるが、浮動小数点演算全体の厳密な区間証明ではない。面積がゼロの面は距離分布に含めない。6方向の点の割合は方向ごとの投影画素重みで、全表面の面積割合とは異なる。

## 投影の数値処理

三角形を少量ずつ2Dポリゴンへ投影して和集合を取り、最後に階層的に結合する。画素数から面積を推定せず、GEOSの浮動小数点幾何演算を使う。表裏の面は両方含み、和集合によって重複面積を除く。

ほぼ重なった辺でGEOSが数値例外を出す場合は、明示指定した2D精度格子を使用できる。今回の側面・上面では1nmを指定する。3D原形状・候補は変更せず、CFDの形状許容差も変更しない。精度格子、例外が出た実行、修正後の実行を別に記録する。丸めのない幾何計算と同じ表現で報告しない。

隙間の面積は、輪郭の内側に囲まれた領域から、そこに存在する別の部品の投影を差し引く。内側の部品を「隙間が埋まった」と二重計上しない。穴の総数は数値的に微小な領域の影響を受けるため、面積と1mm²以上の領域を併記する。

「元の隙間の何%が埋まったか」は元の背景領域に新たに重なった面積の割合である。同じ箇所の別の辺が削れて隙間が広がることもあるため、隙間の正味面積の減少率とは区別する。囲まれた穴が外側とつながると、穴の集計から外れる場合もある。

## 再実行

新規監査ディレクトリで始める。各段階は独立して上限・プロセス終了・RSS・出力容量を記録する。上限は距離が各方向20分、投影が各実行20分、6方向表示20分、選定断面5分。メモリ12GiB、出力10GiB。これはユーザーが追加指定した読み取り専用の監査で、CFD試験の予算を再開する処理ではない。

```powershell
.venv/Scripts/python.exe scripts/audit_saved_shape.py --trial private/phase1/smoke-002 --output private/phase1-validation/audit-new --stage cache
.venv/Scripts/python.exe scripts/audit_saved_shape.py --trial private/phase1/smoke-002 --output private/phase1-validation/audit-new --stage distance
.venv/Scripts/python.exe scripts/audit_saved_shape.py --trial private/phase1/smoke-002 --output private/phase1-validation/audit-new --stage projection
.venv/Scripts/python.exe scripts/audit_saved_shape.py --trial private/phase1/smoke-002 --output private/phase1-validation/audit-new --stage views
.venv/Scripts/python.exe scripts/audit_saved_shape.py --trial private/phase1/smoke-002 --output private/phase1-validation/audit-new --stage sections
.venv/Scripts/python.exe scripts/render_shape_audit.py --root private/phase1-validation/audit-new
```

可視点と最大差の区別も記録する場合は、`source-to-candidate.json`の`max_witness_m`を使い、監査ディレクトリの`witness-request.json`へ `[{"label":"source maximum","point_m":[x,y,z]}]` の形式で実座標を保存する。`views`の後に次を実行し、図を再生成する。座標は原形状と同じ解析座標・mで、推測値を入れない。

```powershell
.venv/Scripts/python.exe scripts/audit_saved_shape.py --trial private/phase1/smoke-002 --output private/phase1-validation/audit-new --stage witnesses
.venv/Scripts/python.exe scripts/render_shape_audit.py --root private/phase1-validation/audit-new
.venv/Scripts/python.exe scripts/summarize_shape_audit.py --root private/phase1-validation/audit-new
```

集計には全距離・3投影・可視点・断面とキャッシュ再構成の検証記録を要求する。今回の`cache-integrity-verification.json`は、元入力から新規ディレクトリへキャッシュを再生成してバイト単位で照合した記録である。人間の採用欄は自動で埋めない。

投影の例外を調査した後、未完了の方向だけを計算する例:

```powershell
.venv/Scripts/python.exe scripts/audit_saved_shape.py --trial private/phase1/smoke-002 --output private/phase1-validation/audit-new --stage projection --projection-view side --projection-grid-m 1e-9
```

失敗した同じ診断段階の修正後には、明示的な`--attempt <label>`で実行ログを分けられる。成功済みの段階は再試行できず、自動再試行はしない。全体の監査を繰り返す場合は新しいディレクトリを使う。元入力のSHA、キャッシュ、実行時のコード、ライブラリlock、実行ファイルのSHAを非公開で保持する。

## 全キャラ展開で必要な追加情報

今後の取り込みでは、レンダラー名に加え、頂点・三角形の開始位置と個数、材質、部位ラベル、重なりや内部面の扱いを保存したい。顔・衣装・髪は位置が重なるため、座標だけで意味ラベルを推測して確定しない。

評価基準は、全表面の差、外部表面の差、部位の保持、隙間の保持を分けて設計する。内部面の除去を扱う規約も、外から空気が触れる可能性を検査してから決める。数値が通るように、隠れた面を自動除外する運用にはしない。

初回の判定は今回の非公開レビューを材料に決め、次のキャラクターで規約を再確認する。監査の通過と、空気抵抗の科学的な妥当性は別である。

問題箇所で解像度を比較する追加実験は [局所ボクセル比較](LOCAL_VOXEL.md) を参照する。

切り出しを行わず全身から4解像度を生成する比較は [全身ボクセル比較](FULLBODY_VOXEL.md) を参照する。
