# RunFlow — DATA_POLICY

## 1. Purpose

RunFlow は研究用ワークフローと結果の再現性を重視しますが、第三者ゲーム・アニメ等の知的財産を尊重します。

---

## 2. Game Assets

ゲーム由来の以下のデータは、原則として公開リポジトリへ含めません。

- 3D meshes
- textures
- rig files
- extracted animations
- proprietary game files

ローカル研究環境のみで扱い、利用条件を確認します。

---

## 3. Public Repository

公開可能なものを中心とします。

- scripts
- CFD configs
- experiment metadata
- numerical results
- charts
- original diagrams
- methodology
- paper/report
- asset hashes / IDs where appropriate
- reproducibility instructions that do not redistribute protected assets

---

## 4. Character References

キャラクター名・作品名を研究対象の識別のために記載する場合でも、公式関係者による研究と誤認されないよう明確にします。

推奨表記:

> RunFlow is an independent fan research project and is not affiliated with or endorsed by the rights holders.

---

## 5. Roster Snapshot

全キャラクターベンチマークは、必ず対象時点を固定します。

```text
Roster snapshot: YYYY-MM-DD
Source version: ...
Benchmark version: ...
```

新規キャラクター追加後は新しいランキングバージョンとして扱います。

---

## 6. Reproducibility without Asset Redistribution

実装では `private/` に原本・PMX/VMD・texture・snapshot/OBJ等の派生形状を保管する。
`.tools/`、private、assets、models、motions、resultsをGitから除外する。
`runflow publish` はローカル数値要約の許可列だけを出力し、自由記述・パス・形状をコピーしない。
これは外部公開コマンドではない。公開前にGitの追跡対象を別途点検する。
pilot rosterはcharacter+costumeで識別し、master hashとSteam buildで対象時点を記録する。

第三者アセット自体を配布できない場合でも、以下を保存します。

- source/version identifier
- model/animation hash
- extraction notes
- scale metadata
- frame sampling timestamps
- transformation matrix
- CFD-ready preprocessing log

これにより、同一アセットへ正当にアクセスできる研究者が再現できる設計を目指します。
