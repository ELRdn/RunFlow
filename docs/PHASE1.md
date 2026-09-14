# Phase 1.0：1姿勢の実行試験

ユーザー指示により形状の精度探索を停止して実施した [現状形状での暫定CFD](PROVISIONAL_CFD.md) は、1姿勢で収束済み（2026-09-08）。独立監査と入力再生成も通過し、次は結果レビューと数値感度・追加形状改善の優先順位を判断する。以下は元の形状ゲート付き試験の仕様として保持する。暫定計測の結果を、この仕様の形状合格へ読み替えない。

## 32姿勢キャンペーンは8姿勢パイロットまで進行（2026-09-14）

Phase A の実行基盤を commit したうえで、止まっていた frame 4〜31 の形状修復を
自動化した。Foundation の証拠点から最近傍頂点を取り、面の重ならないファン中心だけを
coplanar-fan 再三角形化へ渡すループで、7フレームを無人で Foundation 検査へ通した。
座標は動かさず、穴埋めも部位削除もしない。2mm／1% の形状基準は不変である。

8姿勢パイロットは 4レーン × 1ワーカー × MPI 4ランクで実行し、現行家族
`phase1-cycle-family-2` の下で12フレーム（0,3,4,8,9,12,14,17,18,20,24,28）が PASS した。
frame 13 は修復と形状監査を通ったが、CFD が収束しなかった。np4 の同時実行ではソルバ段が
段上限に達して TIMEOUT、単独 np8 では正常終了したものの抗力・残差・流量の全収束ゲートが
不合格だった。正式な Drag/CdA は null とし、集約にも入れない。閾値は変更していない。
`gait_cycle.aggregate()` は 8姿勢スケジュールの frame 16 を欠くため `INCOMPLETE` を
返し、平均値は返さない。欠落を補間せず、8本完走を必要十分なサンプル数とも主張しない。

frame 16 は native Blender 表面が非閉鎖（境界辺120本・非多様体辺120本）で、
修復候補自体は Foundation 検査を通過したが、双方向表面距離の 2mm ゲート
（source→candidate の上限 39.04mm）で CFD 入場を拒否された。閾値は緩めていない。
同じ原因が frame 5（42.46mm）と frame 6（57.21mm）でも実測され、いずれも
面積 1e-16〜1e-15 m² の**退化三角形**が native 側に1枚あるだけで、形状差ではない。
監査の source を統合済み表面に固定するか面積下限を導入するかは、版上げと A/B 実測を
伴う契約判断として残す。

詳細は [Phase B レポート](../reports/phase-b/phase-b-report.md)、
[修復自動化](../reports/phase-b/repair-automation.md)、
[8姿勢パイロット](../reports/phase-b/pilot-8pose.md)、
[非閉鎖クラスの診断](../reports/phase-b/frame16-diagnosis.md) にある。

## 旧停止記録（frame 3の形状監査後、2026-09-13）

2026-09-13時点で、32姿勢のうちframe 0〜2は修復・形状監査・CFDを完了した。frame 3は、座標を移動しない局所再三角形化によってFoundationの自己交差を113件から0件まで減らし、既存の外形差2mm・投影面積差1%の形状基準も通過した。ただし、分割再実行した上面投影が`projections-merged.json`に保存され、現行契約が要求する正規の`projections.json`は未完了のままである。このため、frame 3のCFDはまだ実行していない。

旧キャンペーン`cycle-phase1-full-001`ではframe 0〜2のCFDがPASS、frame 3が修復パイプラインのFAILとして記録されている。終了済みPIDを指す`active.json`も監査証跡として残っている。これらの記録は書き換えない。再開時は、投影を視点単位で再開して正規結果へ統合する処理を実装し、frame 0〜3の検証済み候補を参照する新しいmappingと新しいキャンペーン領域を作る。

旧24時間枠の台帳上の消費は18,743.624秒（約5.21時間）、残りは64,056.376秒（約17.79時間）。ユーザー指示により長時間処理はここで停止し、次の実計算を始める前に新しい時間上限を決める。科学的状態は`UNVALIDATED_PHASE1_CYCLE`、ランキング適格性はfalseのままとする。

Phase 0で採用したオグリ1006・衣装100602のframe 0を、地面なし・20m/sで静止させて計算する。20m/sと空気物性は研究用の仮条件であり、公式速度の認定ではない。

## 実行

```powershell
uv sync --locked
& scripts/run_phase1_smoke.ps1 -RunName smoke-new
```

新しい名前が必須。`prepare`が形状条件を満たさなければ`run`を呼ばず、理由と比較資料を保存する。上限を広げた再試行は自動実行しない。

個別CLI:

```powershell
.venv/Scripts/runflow.exe cfd prepare private/oguri/adopted-002/configuration-final-002/manifest.json --asset-root private/oguri/adopted-002 --protocol configs/cfd.phase1-smoke.json --frame 0 --output private/phase1/smoke-new
.venv/Scripts/runflow.exe cfd run --output private/phase1/smoke-new
.venv/Scripts/runflow.exe cfd report --output private/phase1/smoke-new
```

32フレームの継続計算は、非公開Eドライブの台帳を使う。再起動などで`active.json`が残った場合は、関連PIDが終了していることを確認したうえで、途中ディレクトリを削除せず退避して再開する。以下は旧`cycle-phase1-full-001`の再現用コマンドであり、現在の再開入口としては使用しない。

```powershell
& .venv/Scripts/python.exe scripts/run_phase1_full_cycle.py `
  --request private/phase1-inputs/cycle-002/request.json `
  --native-root E:/RunFlowPrivate/phase1/cycle-native-discovery-001 `
  --output-root E:/RunFlowPrivate/phase1/cycle-phase1-full-001 `
  --mapping private/phase1-inputs/cycle-002/repaired-mapping-001.json `
  --recover-interrupted
```

`--recover-interrupted`は明示指定時だけ有効で、実行中PIDを検出した場合は停止する。退避された`frame-XX-001.interrupted-*`と`active.interrupted-*`は監査用に保持する。各フレームの成功は実行ゲートの通過を意味し、科学的承認やランキング適格性は付与しない。

合計60分はprepare開始からの経過時間で管理する。個別コマンド間で待った時間も含む。geometry600秒、mesh1200秒、solver1500秒、report300秒を上限とし、MPI4プロセス、12GiB、出力10GiBを監視する。実装・合成テストは実オグリ試験の予算へ含めない。

## 形状と数値条件

固定条件は `configs/cfd.phase1-smoke.json`。契約は `src/runflow/cfd_contracts.py` に分離し、Phase 0の16時刻契約・CFD実行禁止フラグを書き換えない。

1µmの頂点統合、重複面・退化面除去、法線整合を行う。閉じなければ固定Blender4.2.23で1mmボクセル再メッシュを1回実施する。平滑化、体格変更、部位削除は行わない。

再メッシュ後は、出力される三角形で面積ゼロ相当（1e-16m²未満）の面を検出する。その面に触れる頂点だけを、既存の頂点へ1µm以内で1回統合する。元の頂点番号順で統合先を固定し、各頂点から統合先までの距離を制限するため、連鎖した統合で移動量が増えることはない。対象・統合先座標・移動量を非公開の補修履歴へ保存する。

この統合で辺・面を持たなくなった未使用頂点だけを除去し、その座標も履歴へ残す。面が接続する頂点や部位を、この処理で削除することはない。

品質検査は四角形の面積だけで判定せず、実際に書き出す三角形を数える。辺の接続に加え、頂点に複数の面群が点だけで接する問題と、法線の不整合も検査する。退化面が消えても接続不良が残れば停止する。

表面距離は双方向に三角形を細分する。各三角形の中心から相手表面までの距離に、中心から頂点までの最大距離と2µmの数値誤差余裕を加え、三角形全域の上限とする。上限2mm以内を証明できない領域・未完了検査は不合格。距離が通った場合に正面投影面積差1%以内と、Foundation 14 `surfaceCheck -checkSelfIntersection`を確認する。

部位保持は、人間レビュー済み原形状の表面全域が許容距離内で残ることを根拠にする。新しい人間レビューや独立した公式形状検証を発行するものではない。

CFDはFoundation14 package20260724、定常RANS/SIMPLE、k–ω SST。物体はnoSlip、流入(-20,0,0)、下流圧力0、他の外部境界はsymmetryPlane。密度1.2、動粘性1.5e-5、乱れ強度1%、乱れ長さ0.01H、H=1.67m。

領域・メッシュ・層・収束閾値は固定プロトコルの値から生成し、motorBikeSteadyと共通辞書の内容・ハッシュを記録する。予定した物体近傍細分化level 5、100万セル以内、checkMesh成功を必須とする。

`checkMesh -parallel`の標準検査を必須とし、表面に接するセルのlevelと、領域内で未完了の細分化セルが0であることを確認する。追加の`-allGeometry`検査は標準検査とは区別する。合成キューブでは追加検査で凹セルが指摘されたため、これを空力精度の承認へ使わない。

WSLのMPI起動では、hwlocのGL検出が使えない画面サーバーへの接続待ちになった。CPU計算のworkerと子プロセスにだけ`HWLOC_COMPONENTS=-gl`を設定する。WSLのグローバル設定は変更しない。別セッションのMPI子プロセスも追跡してRSSを合算し、終了を検証する。

## 判定と証拠

- PREPARED: 形状検査とケース生成まで。CFD未実行。
- PASS: 正常終了と全収束条件が成立した小規模実行試験。
- BLOCKED / FAIL / TIMEOUT / NOT_CONVERGED: 理由を保存し、正式なDrag/Cd/CdAはnull。

すべて `scientific_status=UNVALIDATED_SMOKE`、`ranking_eligible=false`。力は圧力＋粘性を一度だけ足し、Drag=-Fx。OpenFOAM forcesが密度換算するため、読み取り時に密度を再乗算しない。Cdの基準面積は補修前の正面投影面積。

収束には300〜2000反復の範囲で、直近100反復すべてのp初期残差≤1e-4、Ux/Uy/Uz/k/omega≤1e-5、平均Dragの前100反復との差≤1%、直近100反復の幅≤平均の2%、流入に対する流量収支誤差≤0.1%を要求する。欠損・非有限の履歴は通さない。

実験IDには原snapshot、補修後OBJ、元manifest、プロトコル、Blender実行ファイル、上流辞書、OpenFOAM/MPI実行ファイル、処理コード、依存lockのSHAを含める。形状で停止した場合も`attempt-identity.json`で使用入力を結び付ける。絶対パスと実行日時はIDから分離する。

各試行の`tool-sources/`には使用した処理コードと依存lockも保存する。補修コードを変更した継続試験は新しい出力先へ記録し、過去の失敗記録や設定を上書きしない。数値条件・許容差は固定プロトコルのまま、コードのSHAで処理の違いを識別する。

原形状、補修候補、比較画像、入力・設定ID、メッシュ・計算ログ、力・残差・流量、資源使用量を `private/phase1/<RunName>` に保存する。計算した場合はVTKとメッシュ断面・圧力・速度・履歴図を残す。形状段階で停止した場合、未生成のCFD図を作ったことにはしない。

VTKはFoundation14標準のバイナリ形式で、内部セルのp/Uを4並列で書き出す。`-noLinks -excludePatches '(".*")' -noFaceZones -noPointValues`で図に使わない出力を省く。物体パッチや計算結果は削除しない。WSLのWindowsドライブではASCIIの細かなwriteが大量のファイルI/O待ちを生むため、時間上限を伸ばす対処はしない。
読み取り側は既存ASCIIとbig-endian binaryに対応し、rankごとの実ファイルを1回ずつ読む。全体VTKフォルダのリンクや境界面ファイルを二重に集計しない。バイナリ変更は保存形式の変更であり、物性・境界条件・係数の定義は同じ。

## 次段階

時間上限を再設定した後は、次の順序で再開する。

1. 正面・側面・上面の投影を個別に再開し、入力SHA-256とツール版を検証して正規`projections.json`へ統合する。
2. 旧台帳を変更せず、frame 0〜3を参照する新mappingと`cycle-phase1-full-002`を作る。
3. frame 3を単独でCFDへ接続し、結果と資源使用量を確認する。
4. 座標不変のcoplanar-fan修復をFoundation不合格時だけ使う限定fallbackとして組み込む。
5. frame 4〜31を、修復、完全形状監査、CFDの順で1姿勢ずつ処理する。
6. 細格子の失敗原因を直して再試行し、3段階メッシュ、領域、8/16/32姿勢の感度を集計する。

各工程は、形状監査PASS、CFD実行PASS、科学的承認を別々に記録する。長時間処理の再開前に新しい実計算上限を設定する。

全身の解像度比較を受け、保存済み1mm・0.9mmを微修正の対象とする。0.8mm以下の再生成は終了し、新しいボクセル再生成を行わない比較入口を追加した。手順・方法・判定・資源上限は [全身候補の微修正](FULLBODY_REPAIR.md)。既存の2mm・1%と、原本全表面の範囲を維持する。

微小移動、薄い立体の結合、観測空間の切り戻しを試し、生成できた全身候補の距離・投影・断面・接続を計測した。局所的な改善は得られたが、全基準を満たす候補は未取得。切り戻し候補の独立した自己交差検査も保存し、この形状ゲート付き経路ではCFDを停止した。その後の暫定計測はユーザー承認による別契約であり、距離の不合格記録を保持する。

保存済み原形状と候補の全体比較には [形状監査](SHAPE_AUDIT.md) を使う。全表面の距離と、外から直接見える面の差、正味面積と減少・追加面積、投影上の隙間と3D通路を区別する。監査結果だけで既存のCFD合否条件を変更しない。

今回の実行費用と失敗理由を基に、3段階のメッシュ感度、領域感度、8/16/32時刻の感度へ進む。全周期CFDは今回の実行に含めない。手足の動きを含む非定常計算はPhase 1.5。

欠落`Gallop.CharaTransformProcessData`のゲーム側の役割は未確認。衣装の自己交差や公式の合成条件との一致を、CFD実行成功だけで認定しない。

## Phase A の高速化基盤（2026-09-13）

Phase A は科学的プロトコルと許容差を変えずに、監査コスト・直列実行・I/O を
削るための基盤を追加した。数値契約を変える場合は実測 A/B と版上げを必須とする。

- 投影監査の精度グリッドは既定で 10nm 以下を強制したまま。明示的な
  --benchmark 指定時のみ粗いグリッドを許し、出力に benchmark を記録する。
- source 投影の決定的キャッシュ（source のみ。候補は毎回再計算）。
  --no-projection-cache で無効化でき、キャッシュ有無で比較結果が一致する。
- --view による 3 面の同時実行。正規の projections.json は全面成功後にのみ
  決定的順序で統合する。1 面でも失敗すれば incomplete のままとする。
- 権威成果物は「3面すべてを含み complete の projections.json」。既存の分割
  成果物はハッシュ検証を通った場合のみ後方互換で受理する。
  scripts/promote_projection_audit.py が再計算なしで正規形へ昇格する。
- cycle_family() は科学値のみをハッシュする。limits（プロセス数・メモリ・
  出力・各時間上限）は execution-profile.json へ分離し、家族判定に含めない。
  家族の版は phase1-cycle-family-2。
- スクラッチは D: の NVMe に 2 スロット（Windows 側 NTFS と Linux 側 ext4）。
  E: は権威アーカイブとして維持し、正規成果物のみチェックサム付きで書き戻す。
- フレーム並列ランナーはワーカーごとに隔離ルートと単一ライター台帳を持ち、
  親は共有台帳を書かない。集約は家族不一致を拒否する。

計測手順と結果は [Phase A ベースライン](../reports/phase-a/phase-a-baseline.md)、
[投影 A/B](../reports/phase-a/projection-grid-ab.md)、
[frame-03 契約](../reports/phase-a/frame03-contract.md)、
[資源と家族](../reports/phase-a/resource-family.md)、
[並列ランナー](../reports/phase-a/parallel-runner.md)、
[スクラッチ](../reports/phase-a/scratch-io.md) を参照。
