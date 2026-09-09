# 現状形状による暫定CFD

2026-09-08: `provisional-016` が固定した収束条件を通過し、暫定の1姿勢計測が成立した。独立監査と入力辞書の二重再生成もPASS。科学的承認・ランキング適格性は変更していない。実行設定と引き渡しは末尾を参照。

ユーザーは2026-09-07、形状の追加精度探索を停止し、現状の候補で空気抵抗を測ってから追加改善の要否を判断する方針を指定した。

対象は採用済み `adopted-002` frame 0、保存済み0.9mmへの局所切り戻しの候補。元の姿勢・尺度を維持し、全身再メッシュや新しい形状補修方式の比較は行わない。入力を特定するハッシュと実際のユーザー指示を非公開receiptへ記録する。

## 従来の判定との関係

既存の2mm・1%の形状監査と失敗履歴は保持する。暫定計測のために形状差の判定を保留する承認であり、形状の忠実度や必須部位を新しく人間承認した意味ではない。

数値計算の前提として、極小三角形に関係する頂点だけを既存の1µm以内の直接統合で1回整理する。残存する極小面、開いた境界・非多様体・自己交差があれば停止する。処理の前後と元の形状差を別々に保存する。

座標はfloat64を保ち、OpenFOAMへは17桁のOBJとして渡す。CFD専用の入出力が必要なため、この最終受け渡しではASCII OBJを使用する。Float32 STLへの変換や全身簡略化は挟まない。

元の投影面積はハッシュ照合して再利用する。整理後の候補面積は、変更に関係する三角形の投影面積から保守的な上下限を併記する。候補の公称値を再計測した厳密値とは扱わない。Cdは引き続き補修前の原本面積を分母にする。

## 実行

`configs/cfd.phase1-provisional.json` は形状入力と科学的状態だけを区別し、風速20m/s・地面なし・Foundation14 package20260724・定常RANS/k–ω SSTを保持する。4 MPIプロセス、100万セル、12GiB、出力10GiB、合計60分、段階上限、収束条件も既存試験と同じ。CLIの1回の呼び出しは新しい保存先への1試行。継続再試行の承認と運用は下記の「成功まで分析・再試行する方針」に従う。

```powershell
& .venv/Scripts/python.exe scripts/run_provisional_cfd.py --receipt <非公開の承認済み入力receipt.json> --output private/phase1/<新規名>
```

個別CLIは `runflow cfd prepare-provisional --receipt ... --protocol configs/cfd.phase1-provisional.json --output ...` と既存の `cfd run` / `cfd report`。実行の時間計測はprepare開始からで、コマンド間の待ち時間も含む。

結果の識別子は `phase1-provisional-1`、科学的状態は `UNVALIDATED_PROVISIONAL_GEOMETRY`、ランキング適格性はfalse。実行がPASSでも、現状形状・1条件の数値計算が収束したことだけを示す。未収束・失敗時の正式なDrag/Cd/CdAはnullのまま、途中値を診断履歴として保存する。

生成・メッシュ・計算・可視化を結び付け、力の履歴、残差、流量収支、y+、境界層の診断、使用時間・メモリ・セル数を非公開保存する。元の局所修正試験とPhase 0の採用記録は上書きしない。計測後に形状改善と感度検証の優先順位を再判断する。

## 初回の停止と入出力修正

初回 `private/phase1/provisional-001` は最小限の数値的な整理とCGALの検査を完了したが、OpenFOAMの診断出力中に形状工程の時間上限へ達した。メッシュ生成・ソルバーは未着手。TIMEOUTと未計測のDrag/Cd/CdAを保持する。

Foundation14の `surfaceCheck.C` は、独立した部品が複数ある場合にASCIIのゾーン図と各部品のOBJを出力してから自己交差を調べる。ゾーン図は入力ファイルの隣、部品OBJは作業ディレクトリに書くため、両方を専用のLinux一時領域へ移した。検査コマンド・入力座標・ツールは同一。診断はLinux内でtarへまとめ、非公開出力へ一括コピーしてSHAを検証する。

コピー・ハッシュ・検査・診断保存・一時領域の整理は同じ監視プロセス内で行う。Windowsの保存先とLinux一時領域を合算して出力上限を判定する。中断時は子孫プロセスの終了を検証し、未完了の診断を完成扱いせず、残った専用一時領域を `surface-scratch.json` に記録する。時間上限を超えてアーカイブを続けない。

前回の完成表面は `surface-reuse-proof.json` に列挙したハッシュを検証して別の試行へコピーできる。補修・再メッシュ・座標変換は再実行しない。前回のTIMEOUTと開始・終了時刻は保持する。再利用は新規試行の実行予算の承認とは別であり、自動再試行はしない。

追加試行が明示的に承認された後の実行例：

```powershell
& .venv/Scripts/python.exe scripts/run_provisional_cfd.py `
  --receipt private/phase1-inputs/provisional-001.json `
  --reuse-proof private/phase1-inputs/surface-reuse-001.json `
  --output private/phase1/provisional-002
```

実行日時・絶対パス・診断ログのハッシュは設定IDから分離して `runtime-evidence-hashes.json` で照合する。入力receiptの設定ハッシュには保存場所を含めず、入力のSHAと承認内容を含める。

修正後の合成物体による実OpenFOAM検査、診断アーカイブのSHA、入力の未改変、一時領域の整理を確認した。Linuxの時間切れ・一時領域容量超過・子孫プロセス停止の実機試験も通過。これらは入出力と停止機構の検証であり、実キャラクターのCFD完了ではない。

## 承認された追加試行の結果

ユーザーは追加1回・最大60分を明示的に承認し、`private/phase1/provisional-002` を実行した。完成表面のコピーとハッシュ照合は成功し、Linux内の診断出力によりOpenFOAMの検査も正常終了まで到達した。しかしCGALとOpenFOAMの自己交差判定が一致せず、形状工程でFAILとして終了した。時間・メモリ・容量超過ではない。メッシュとソルバーは起動していない。

前回のTIMEOUTと今回のFAILを保持し、正式なDrag/Cd/CdAはnull。子孫プロセスの終了、診断アーカイブのSHA、一時領域の整理、旧試行の未改変を確認した。日本語の終了資料、検出位置の図、数値・ハッシュ台帳は非公開 `private/phase1/provisional-002/review/REVIEW.md` に保存した。

ソース上、CGALの厳密な三角形の組の判定とOpenFOAMの浮動小数点による辺・三角形の判定は異なる。入力はbinary64の同一OBJだが、これだけで不一致の原因が丸め誤差だとは断定できない。現在の診断位置には辺・面のIDがないため、次は読み込み後の座標と検出した組を記録し、同じ組を両方式で照合する必要がある。検査を無視してCFDへ進めたり、新たな形状修正や自動再試行を行ったりはしていない。

## 成功まで分析・再試行する方針

その後ユーザーが、失敗を分析して成功まで再試行を続けるよう明示的に指示した。上記の1回という回数制限を解除する。各試行は新規保存先とし、段階時間・メモリ・出力上限、収束条件、元の失敗記録を保持する。同じ失敗を原因分析なしに反復せず、修正と検証を経て次の試行へ進む。

### 独立した交差検査の照合

`integrations/openfoam/surfaceProbe.C` は、導入済みFoundation14の `findSelfIntersectOp` と同じ経路を使う診断用の別実行ファイルである。OpenFOAM本体を変更せず、読み込んだ全座標・面と、検出した辺・面IDを記録する。読み込み後のbinary64メッシュはCGALが検査した入力とSHAが一致し、検出位置も元のstock検査と全件一致した。

保存されたすべての検出組について、binary64の値を正確な有理数に変換して線分と三角形の交差を再計算した。全組が非交差であり、全身を対象にしたCGALの厳密述語による交差0組と一致した。この二つの結果から、今回のstock検査の陽性は実表面の自己交差ではないと判定した。検出位置の図だけによる判断ではない。

`scripts/qualify_cfd_surface.py` で入力・ツール・診断のハッシュを結び付けた検証記録を固定できる。再利用時も、全身の厳密検査、読み込み座標の一致、全検出組の有理数による再計算、stock検出位置の全件再現、現在のstock実行ファイルの一致を必須にする。実交差が一つでもある場合、入力や検出件数が違う場合、検査が未完了の場合は停止する。

この経路は `--surface-qualification private/phase1/surface-qualification-001` として指定する。`surface-worker.json` には検証記録の再利用であることと `stock_raw_pass: false` を記録し、生のstock検査を成功へ書き換えない。別の `surface-qualification.json` に厳密検証の合格を保存する。形状・科学的状態・収束条件は変更しない。

### メッシュ品質と定常反復の診断

`provisional-003` は表面の厳密検証を通過したが、生成したメッシュをstock `checkMesh` が歪みで拒否した。参照辞書の境界面の歪み上限が最終検査より緩かったため、生成段階の `maxBoundarySkewness` を4に厳しくした。形状、領域、細分化、最終検査の基準は変更しない。`provisional-004` ではメッシュ品質と指定した細分化の検査を通過した。

`provisional-004` の定常計算では力と流量収支が安定した一方、初期残差の振動が継続した。診断理由を `diagnosed-stop-request.json` に保存し、正常終了と流場保存を経てNOT_CONVERGEDとした。途中の力は診断用で、正式な係数はnullのまま。

反復方法を比較する入口は `--numerics standard-simple`。参照のSIMPLEC・速度緩和0.9に対し、標準SIMPLE・圧力緩和0.3・速度緩和0.7を使う。乱流変数の緩和、空間離散化、物理条件、最大反復数、収束判定は同じ。公式の [定常収束](https://doc.cfd.direct/notes/cfd-general-principles/steady-state-convergence) と [fvSolution](https://doc.cfd.direct/openfoam/user-guide-v14/fvsolution) を根拠にした設定である。小さな緩和値により更新をほぼ停止させ、見かけの収束を作る運用はしない。

実際に生成した辞書と反復プロファイルの記録を設定ハッシュへ含める。各失敗の結果・正常終了・判断理由を確認してから、新規試行を開始する。過去の実行ファイルとソースは各試行内に保存してあり、後の修正で過去の設定を置き換えない。

標準SIMPLEのみの比較でも残差が振動したため、次の離散化比較を追加した。すべて風速・物性・乱流モデル・形状・領域・メッシュ設定・収束基準は同じ。

| `--numerics` | 圧力・速度の更新 | 速度の移流項 |
|---|---|---|
| `motorbike-simplec` | 参照SIMPLEC、U=0.9 | linearUpwindV |
| `motorbike-simplec-upwind` | 参照SIMPLEC、U=0.9 | upwind（一次精度） |
| `standard-simple` | SIMPLE、p=0.3 / U=0.7 | linearUpwindV |
| `standard-simple-limited` | 同上 | limitedLinearV 1 |
| `standard-simple-upwind` | 同上 | upwind（一次精度） |

移流項はいずれも `bounded Gauss`。上表では乱流変数の緩和0.5と移流項、非直交補正、線形ソルバーの設定を維持する。局所的な制限の試行でも残差の長い振動が残ったことを記録し、一次風上の比較へ進んだ。

一次風上は数値拡散が大きく、[公式資料](https://doc.cfd.direct/openfoam/user-guide-v14/fvschemes) も速度場への精度上の制約を示している。もし収束しても、結果はこの離散化を含む暫定的な計算試験の値とする。高精度な空力係数や離散化への感度検証を完了したとは扱わず、形状改善の優先度を決める前に数値誤差を確認する。

追加の数値診断は、`standard-simple-upwind` へ次の接尾辞を順に追加したプロファイルで実施する。

| 接尾辞 | 直前の設定からの変更 |
|---|---|
| `-damped` | 速度緩和を0.7から0.5へ変更。圧力0.3は保持 |
| `-nonorth` | 非直交補正を0回から1回へ変更 |
| `-tight` | p/U/k/omegaの線形ソルバーを許容残差1e-10、relTol 0へ変更 |
| `-limiteddiffusion` | 拡散項と面法線勾配の非直交補正を `limited corrected 0.5` に変更 |

`-tight` からの別の比較として、`-turbdamped` はk/omegaの更新係数だけを0.3へ変更し、`-pressurelsq` は圧力勾配だけをleastSquaresへ変更する。この二つと `-limiteddiffusion` は同時に適用していない。速度勾配と力の集計方式は保持する。

非直交補正や内側の線形ソルバーを変更しても、外側の収束判定は全反復の最初の残差を確認する。同じ反復で複数回圧力を解いた場合は最大値を保持し、後の小さい残差だけを採用しない。補正の制限は空間近似の変更として記録し、精度向上が実証されたとは扱わない。

### 検証済み流場からの初期化

`--restart-from private/phase1/provisional-XXX` により、正常終了したNOT_CONVERGED試行の最終流場を次の初期値にできる。旧試行の完了・子プロセス停止・メッシュ・物性・形状・設定IDを検証し、全メッシュと4分割のU/p/k/omega/nut/phiをSHA照合してコピーする。未完了の試行、物理条件の変更、欠落・改変がある入力は拒否する。

新試行は反復0から始め、旧時刻管理ファイルをコピーしない。`restart.json` に元実験ID・元反復番号・累計反復数・相対ファイル名とSHAを保存する。`restart-runtime.json` はローカル保存場所と継承ログの出典を記録する。新試行の開始時の力も旧最終値と照合する。メッシュ生成済みであることを明記し、新試行でも `checkMesh` を実行する。

初期値の再利用で実行予算や未収束履歴を消さない。各試行の最大反復数・時間上限・全収束条件は保持し、通算反復数と試行ごとの費用を区別する。保存した流場同士の局所差も診断に用い、全身の抵抗が安定していることだけで局所の定常性を認定しない。

### 壁近くの式の接続を比較する

`--wall-treatment omega-blended` は、導入済みの `omegaWallFunction` が備える `blended true` を物体壁のomegaだけに追加する。既定値は `reference-switching`。k–omega SST、`nutkWallFunction`、静止壁、風速・物性・形状・収束条件は保持するが、**壁近くのモデル設定の変更**としてケース設定とハッシュへ記録する。

導入済みソースでは、既定方式は粘性域と対数域をy+によって切り替え、blended方式は両者を連続的につなぐ。ヘッダーには高Re壁関数の10<y+<30では既定方式の方が正確という説明があるため、連続化を精度改善と決めつけない。C/Hソースも上流資料として保存・ハッシュ照合する。

この変更には旧壁条件の流場を無条件で引き継がない。異なる壁条件の `--restart-from` は入力照合で拒否する。比較は新規一様流場から開始し、同じ初期化を行った参照試行と照合する。収束しても近壁処理と離散化の感度は未検証とする。

### 局所的な流体格子の診断

通常の反復設定と壁近くの接続方法で変動が残る場合、非公開プロトコルの `diagnostic_refinement` に、診断対象・採用snapshotのSHA・局所領域・追加細分化levelを明示する。元の0.9mm表面は変更せず、指定した空気側の領域だけを追加細分化する。背景格子・標準の表面と後流の細分化・領域・セル上限・収束条件は維持する。

メッシャーが指定領域とlevelを認識したこと、要求した内部細分化が完了したこと、最終の品質検査を通過したことを必須にする。セル数と各levelの個数も保存する。格子が異なる旧流場はそのまま再利用せず、一様流場から計算する。これは収束困難の原因を調べる限定した比較であり、3段階のメッシュ感度を完了した扱いにはしない。

## 収束した試行の再生成と引き渡し

`provisional-016` は、裾先付近の空気側を追加細分化した条件で全収束基準を通過した。形状は同じ完成表面、初期値は新規一様流場、壁関数は参照の `reference-switching`。一次風上の `standard-simple-upwind-damped-nonorth` を使用した。局所格子と反復設定を含む一つの試験条件の成功であり、格子・離散化・形状に対する精度保証ではない。

同じ入力を生成する実行入口は次のとおり。私有入力と固定版ツールが必要で、保存先は毎回新規にする。このコマンドは新しい実計算を開始する。今回の成功後には実行していない。

```powershell
& .venv/Scripts/python.exe scripts/run_provisional_cfd.py `
  --receipt private/phase1-inputs/provisional-001.json `
  --reuse-proof private/phase1-inputs/surface-reuse-001.json `
  --surface-qualification private/phase1/surface-qualification-001 `
  --protocol private/phase1-inputs/coat-tip-l6-protocol.json `
  --numerics standard-simple-upwind-damped-nonorth `
  --wall-treatment reference-switching `
  --output private/phase1/provisional-reproduction-NEW
```

計算時のソースは試行内へ保存済み。現在のソースをさらに変更した場合は新しい設定IDになるため、元のコード・ツール・辞書のハッシュを参照する。今回、保存済みコードから入力辞書を2回作り、全15ファイルが実際の入力とSHA一致した。現在のコードからも同じ辞書を生成できた。この照合は入力の再生成であり、CFDを二重実行した意味ではない。

非公開の `private/phase1/provisional-016/review/REVIEW.md` に結果、断面図、力・残差履歴、実行費用、試行台帳、独立監査、入力再生成と成果物ハッシュを保存した。補助監査コードもレビュー領域に保存している。自動検証は323 tests PASS。過去の失敗を保持し、成功後の追加試行は止めた。形状の追加修正を再開するかは、この暫定結果と今後の数値感度の検証を踏まえて判断する。
