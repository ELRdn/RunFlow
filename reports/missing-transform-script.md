# 固定版UmaViewerの欠落スクリプト調査

2026-09-06。対象ソース: `d50b28379337b507751a7df705a10afeab2c37ce`、Unity 2022.3.62f1。

`Gallop.CharaTransformProcessData` の警告は残る。固定版Viewerでの取得・再現性検証は実行できるが、ゲーム内の変形処理がすべて再現されたとは認定できない。

## 確認した根拠

- 固定ソースの `Assets/**/*.cs` を全文検索したところ、`CharaTransformProcessData` / `transform_process` の型定義・明示的な参照は0件。
- `Assets/Scripts/UmaDatabase/UmaDatabaseEntry.cs:82–85` の `Get<T>` は依存込みでAssetBundleを読み、`LoadAllAssets()` 後に型を選別する。型選別前にアセットの読み込みが起こる。
- `Assets/Scripts/UmaContainerCharacter.cs:563–575` の `LoadBody` は `InstantiateEntry` で取得したBodyからAnimatorと `upbody_ctrl` を取得する。この箇所で欠落型のデータは処理していない。
- 実行ログ `.cache/unity-adopted-002.log` では該当警告1件の後、`unity-a` と `unity-b` の16時刻出力がそれぞれ成功した。
- 同実行の `inventory-0.json` / `inventory-1.json` に生成されたモデル階層の全MonoBehaviour型と欠落数を保存した。両回とも `missing_behaviour_count=0`。これは生成階層の検査であり、読み込み元に未知のデータ型がない証明ではない。
- 入力台帳には `3d/chara/body/bdy1006_02/extensions/ast_bdy1006_02_transform_process_data` が含まれる。SHA-256は `22c60f92ccd4bc303ad14311429aa57153680b85cd56d3fe00f889d068ed8a8e`。該当入力も他の依存ファイルとともに非公開保存した。

## 分かっていないこと

ゲーム側の該当型の実装は取得していない。名称だけからIK・衣装補正・骨の変形などの役割を断定しない。警告が出たデータの実際の補正量や、衣装と脚の貫通との因果関係も未確認。

Viewer内で使われていないことと、ゲーム内でも不要であることは別の判断になる。欠落型を空クラスで置き換えて警告を消す措置は実施していない。

## 引き渡し

今回採用した入力は「固定版UmaViewerで再現した、ユーザー選定の通常走行pilot」とする。位相・尺度・衣装の貫通に関するユーザー判断は適用済み。公式同等性の認定には、ゲームの同時刻形状または補正仕様との照合が別途必要。

キャラクターCFDの科学的承認・ランキング適格性は付与しない。
