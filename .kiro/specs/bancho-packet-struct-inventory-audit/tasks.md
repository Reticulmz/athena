# 実装計画

`1.` から `4.` のような小数なしの major numbered row は grouping header である。
実行対象の implementation task は小数付き row と task `5` から `7` である。
親 checkbox の `[ ]` は section header を示すための表記であり、小数付き子 task の完了状態とは独立して扱う。

- [ ] 1. 監査表記と scope 境界の土台を整える
- [x] 1.1 #33 の audit-only 境界を matrix に明示する
  - #33 の対象を C2S packet、S2C packet、Bancho struct の監査に限定し、#16 の sibling inventory と #17 の fixture extraction をこの spec の実装対象から分離する
  - parser、builder、handler、runtime behavior、fixture file、real-client traffic capture をこの作業で完了扱いにしない boundary note を追加する
  - 完了時には matrix の該当箇所から、#33 の必須監査対象と範囲外 row の扱いをレビューできる
  - _Requirements: 1.4, 7.1, 7.2_
  - _Boundary: Scope Boundary Checklist_

- [x] 1.2 audit classification と evidence note の読み方を定義する
  - 既存 implementation status と audit classification が別概念であることを legend で説明する
  - `required`、`deferred`、`out of scope`、`needs reference evidence` の分類語彙と、延期理由、除外理由、evidence gap の書き方を定義する
  - exact source name、verification status、fixture blocker を row note から読めるようにする
  - 完了時には各 row の実装成熟度と互換性上の監査判断を混同せずに読める
  - _Requirements: 2.1, 2.2, 2.4, 2.5, 6.4, 7.3_
  - _Boundary: Audit Classification Legend, Reference Evidence Contract_

- [ ] 2. C2S packet inventory を監査する
- [x] 2.1 C2S packet row の実装状況と evidence note を埋める
  - Issue #33 の source docs に含まれる C2S packet row が matrix 上で漏れなく残っていることを確認する
  - 各 C2S row に current implementation status、audit classification、evidence note、reference source を追加または補強する
  - `required` row には判断根拠を示し、source が不足する row は `needs reference evidence` として残す
  - 完了時には C2S Packet Coverage のすべての対象 row に監査分類と evidence note がある
  - _Requirements: 1.1, 2.2, 2.3, 3.1, 8.1_
  - _Boundary: C2S Packet Audit Table_

- [x] 2.2 C2S payload 判断、曖昧 behavior、fixture blocker を明示する
  - 各 C2S row について payload / no-payload の確認状態を evidence note から読めるようにする
  - 曖昧な behavior には doc audit、reference implementation audit、real-client traffic capture のどれが次に必要かを示す
  - #17 fixture extraction をブロックする C2S row には blocker 関係と source gap を記録する
  - 完了時には C2S row から parser/handler 着手可否と #17 への影響を判断できる
  - _Requirements: 3.2, 3.3, 3.4, 8.1_
  - _Boundary: C2S Packet Audit Table, Fixture Handoff Contract_

- [ ] 3. S2C packet inventory を監査する
- [x] 3.1 S2C builder status と runtime emission status を分けて記録する
  - Issue #33 の source docs に含まれる S2C packet row が matrix 上で漏れなく残っていることを確認する
  - 各 S2C row に builder status、runtime emission status、または documented non-emission reason を記録する
  - builder が存在しても runtime emission が未完成の row は、完了済み builder と未完成 runtime を別状態として示す
  - Athena が送信しない方針の packet は互換性上の non-emission reason を示す
  - 完了時には S2C Packet Coverage で「作れる packet」と「実際に送る packet」を区別できる
  - _Requirements: 1.2, 2.2, 2.3, 4.1, 4.2, 4.3, 8.2_
  - _Boundary: S2C Packet Audit Table_

- [x] 3.2 S2C の曖昧 behavior と fixture blocker を明示する
  - S2C behavior が曖昧な row には doc audit、reference implementation audit、real-client traffic capture のどれが次に必要かを示す
  - builder evidence、runtime evidence、payload reference が食い違う row は evidence gap として残す
  - #17 fixture extraction をブロックする S2C row には blocker 関係と exact source または source gap を記録する
  - 完了時には S2C row から fixture extraction 前に必要な追加監査を判断できる
  - _Requirements: 4.4, 6.3, 8.2_
  - _Boundary: S2C Packet Audit Table, Reference Evidence Contract_

- [ ] 4. Bancho struct inventory を監査する
- [x] 4.1 Struct row の source、missing note、packet dependency を埋める
  - Issue #33 の source docs に含まれる Bancho struct row が matrix 上で漏れなく残っていることを確認する
  - 各 struct row に confirmed source、missing field/value audit note、または explicit deferral reason を示す
  - packet payload に使われる struct は blocking packet dependencies を明示する
  - stable layout や enum value が未確認の struct は追加で必要な reference evidence を示す
  - 完了時には Bancho Struct Coverage のすべての対象 row から source、未確認点、依存 packet を判断できる
  - _Requirements: 1.3, 2.2, 2.3, 5.1, 5.2, 5.3, 8.3_
  - _Boundary: Struct Audit Table_

- [x] 4.2 Struct fixture priority と exact source を明示する
  - #17 fixture extraction の優先入力となる struct row を分類し、exact reference source name を記録する
  - exact source が未確定の struct は `needs reference evidence` として残し、必要な audit type を示す
  - C2S/S2C packet row と struct row の blocker 表現が同じ分類語彙で読めるようにする
  - 完了時には #17 が struct fixture の抽出順序と source 不足を matrix から判断できる
  - _Requirements: 5.4, 6.2, 6.3, 8.3_
  - _Boundary: Struct Audit Table, Fixture Handoff Contract_

- [x] 5. #17 fixture extraction blocker rollup を作る
  - C2S、S2C、struct の監査結果から、#17 をブロックする row identifier、row type、classification、implementation status、exact reference source、blocker reason を一覧化する
  - confirmed required row と `needs reference evidence` row を分け、exact source がない blocker を fixture-ready として扱わない
  - `Match`、`MatchJoin`、`ReplayFrameBundle`、`ScoreFrame`、S2C enum correction cases など guide の fixture backlog 優先項目を rollup に反映する
  - [x] blocker row list を confirmed section と needs-evidence section に分ける
  - [x] 各 blocker row に row identifier、type、classification、status、exact source または source gap、blocker reason を持たせる
  - [x] exact source を持たない blocker を needs-evidence section に含める
  - [x] #17 が fixture extraction 着手可否を blocker list から判断できる情報を揃える
  - 完了時には #17 の fixture extraction 入力候補と未解決 evidence gap を同じ section から確認できる
  - _Requirements: 3.4, 5.4, 6.1, 6.2, 6.3, 6.4, 7.4_
  - _Boundary: Fixture Blocker Rollup_

- [x] 6. Matrix と guide の整合性を検証する
  - matrix の audit result と guide の Bancho Packet Payload Reference / Struct Field Reference を照合する
  - 矛盾が confirmed evidence で解決できる場合だけ guide を更新し、それ以外は matrix に unresolved evidence gap として残す
  - C2S、S2C、struct の曖昧 behavior が、必要な audit type と exact source gap を持っていることを確認する
  - [x] matrix と guide の不一致を C2S / S2C / struct row の evidence note または consistency table に記録する
  - [x] 各不一致を confirmed evidence で解決可能か unresolved evidence gap のままか判定する
  - [x] 解決できない不一致を matrix に unresolved evidence gap として残す
  - [x] confirmed evidence がある場合だけ guide update 対象にする
  - 完了時には matrix と guide の矛盾が silent drift にならず、未確認箇所としてレビューできる
  - _Requirements: 2.3, 2.5, 3.3, 4.4, 5.3, 6.3, 8.4_
  - _Boundary: Guide Consistency Check, Reference Evidence Contract_

- [x] 7. 最終 validation と scope review を行う
  - C2S、S2C、struct の row coverage を確認し、Requirement 1.1 から 8.4 までの受け入れ条件に対応する row note または rollup があることを確認する
  - `src/`、`tests/fixtures/`、migration、package manager、runtime configuration が変更されていないことを確認する
  - `git diff --check` と、classification vocabulary / blocker rollup / unresolved evidence gap の targeted `rg` checks を実行する
  - Markdown table rendering と diff をレビューし、implementation gap や fixture gap が完了扱いになっていないことを確認する
  - [x] validation command、pass/fail 結果、未解決 evidence gap を completion record に含める
  - 完了時には実行した validation command、pass/fail 結果、未解決 evidence gap を実装報告に含められる
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3, 5.4, 6.1, 6.2, 6.3, 6.4, 7.1, 7.2, 7.3, 7.4, 8.1, 8.2, 8.3, 8.4_
  - _Boundary: Documentation Validation_
