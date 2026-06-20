# 実装計画

- [x] 1. 監査対象と分類土台を確定する
- [x] 1.1 Legacy web-family の監査対象 inventory を確定する
  - Stable HTTP Endpoint Coverage と Reference Route Inventory を照合し、Issue #32 の対象になる grouped row と exact path row を洗い出す
  - `/web/*.php` と `/rating/ingame-rate*.php` を in-scope とし、release / static / media / download overlap は adjacent context として分離する
  - 完了時には、対象 endpoint family と exact path の一覧が matrix / guide 更新作業の入力として読める
  - _要件: 1.1, 1.2, 1.3, 1.4, 8.4_
  - _境界: Audit Scope Index_

- [x] 1.2 Final audit classification の適用ルールを matrix 更新前に固定する
  - `required`、`compatibility no-op`、`deferred`、`out of scope`、`needs reference evidence` の使い分けを監査メモで確認する
  - `candidate` が監査後の最終分類に残らないよう、pre-audit status と final audit classification を分ける
  - 完了時には、response shape 未確認 endpoint や reference-only endpoint が推測で `required` / `compatibility no-op` にならない判断基準が matrix 更新に使える
  - _要件: 2.1, 2.2, 2.3, 2.4, 2.5, 4.3, 4.4_
  - _境界: Classification Contract_

- [x] 2. Endpoint family evidence を監査する
- [x] 2.1 Endpoint family evidence note の共通形式を guide に反映する
  - Auth method、required request params、success response、auth failure response、domain/data-not-found response、malformed request response の6項目を確認済み / 未確認 / scope 外で表せる形にする
  - Success-only evidence だけで implementation-ready に見えないよう、failure sentinel と malformed request の欄を明示する
  - 完了時には、後続 endpoint family 監査が同じ evidence note 形式で記録できる
  - _要件: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_
  - _境界: Evidence Note Template_

- [x] 2.2 現行実装済みまたは P0 play に近い endpoint family を監査する
  - `/web/bancho_connect.php`、`/web/osu-osz2-getscores.php`、`/web/osu-submit-modular-selector.php`、registration fallback の current implementation status と evidence source を確認する
  - Replay download、`/web/osu-session.php` など P0 play への影響がある candidate / missing family は missing implementation と missing evidence を分けて記録する
  - 完了時には、現行実装済み family と P0 play 近傍 family の required / partial / evidence gap が matrix と guide から読める
  - _要件: 2.3, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.1, 8.1, 9.1, 9.3, 10.4, 10.5_
  - _境界: Matrix Classification Surface, Guide Evidence Surface_

- [x] 2.3 古い getscores / submit aliases を best effort support 候補として監査する
  - `/web/osu-getscores.php` から `/web/osu-getscores6.php` までの response variant が未特定なら `needs reference evidence` として残す
  - `/web/osu-submit-modular.php`、`/web/osu-submit.php`、`/web/osu-submit-new.php` の request / response variant が未特定なら `needs reference evidence` として残す
  - 完了時には、現行 osu!stable client の P0 required route と古い stable client alias の best effort support 候補が混ざらず読める
  - _要件: 4.2, 5.1, 5.2, 5.3, 5.4, 8.2, 8.3, 10.5_
  - _境界: Legacy Alias Tracker_

- [x] 2.4 Beatmap / osu!direct / file-helper family を監査する
  - `/web/osu-search.php`、`/web/osu-search-set.php`、`/web/osu-getbeatmapinfo.php`、`/web/osu-getstatus.php`、osz2 helper routes の classification と evidence gaps を整理する
  - `/web/maps/*` や download/static overlap は adjacent context とし、この spec の本体分類に吸収しない
  - 完了時には、beatmap lookup と direct/file-helper family の required / deferred / needs reference evidence と follow-up evidence が guide から読める
  - _要件: 1.4, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.1, 8.1, 8.3, 9.3, 10.4, 10.5_
  - _境界: Audit Scope Index, Guide Evidence Surface_

- [x] 2.5 Social / status / UI / private-server family を監査する
  - Rating、comment、favourite、stats、friends、mark-as-read、tweets、lastfm、login preflight、seasonal、title/menu、coins、benchmark の classification と evidence gaps を整理する
  - `/web/osu-getseasonal.php` は現行 client 呼び出し確認済みとして扱うが、exact empty-array body と cache contract が fixture-backed になるまでは `needs reference evidence` に残し、dynamic seasonal background 管理は後続 scope とする
  - Beatmap submission endpoints は P0 core login/play 後の `deferred` とし、coins / benchmark は通常プレイ evidence がなければ `out of scope` として理由を記録する
  - 完了時には、social / status / UI / private-server family の no-op、deferred、out-of-scope、needs-evidence の理由が matrix と guide から読める
  - _要件: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.1, 6.1, 6.2, 6.3, 6.4, 7.1, 7.2, 7.3, 7.4, 8.1, 9.3_
  - _境界: Compatibility No-op Tracker, Deferred Scope Tracker, Out-of-scope Tracker_

- [x] 3. Matrix と guide の traceability を統合する
- [x] 3.1 Reference Route Inventory の exact path traceability を更新する
  - Grouped family row と exact path row の対応を読み取れるようにする
  - Exact path ごとに response variant や evidence status が違う場合、family-level summary だけで差分を隠さない
  - 完了時には、Reference Route Inventory から各 exact path の classification または evidence note 参照が辿れる
  - _要件: 8.2, 8.3, 8.4, 9.2_
  - _境界: Exact Path Traceability Surface_

- [x] 3.2 Stable HTTP Endpoint Coverage と guide evidence gaps を整合させる
  - Stable HTTP Endpoint Coverage の grouped row に final audit classification と concise reason を反映する
  - Guide の endpoint family evidence gaps と matrix の row classification が同じ family 名 / path を参照するようにする
  - Matrix と guide の記述が矛盾する箇所は unresolved evidence gap として残す
  - 完了時には、matrix が進捗 source of truth、guide が詳細 evidence source として同じ endpoint family を指している
  - _要件: 8.1, 9.1, 9.3, 9.4_
  - _境界: Matrix Classification Surface, Guide Evidence Surface, Evidence Source Register_

- [x] 4. フォローアップと audit-only 境界を確定する
- [x] 4.1 Missing work を follow-up checklist として分離する
  - Missing implementation、missing fixture、missing traffic evidence を別々の follow-up item として記録する
  - フォローアップ項目がある endpoint を implementation complete や fixture extraction complete と誤読できないようにする
  - 完了時には、後続 issue が必要な endpoint family と evidence type が checklist から読める
  - _要件: 4.2, 6.4, 10.4, 10.5_
  - _境界: フォローアップチェックリスト_

- [x] 4.2 Runtime / fixture / traffic capture がこの spec に混入していないことを確認する
  - Diff に `src/`、`tests/`、fixture artifact が含まれていないことを確認する
  - Compatibility no-op candidate や seasonal candidate も route stub 実装ではなく follow-up implementation work として残す
  - 完了時には、この spec の成果が docs/spec 更新だけであることを diff と docs から確認できる
  - _要件: 10.1, 10.2, 10.3_
  - _境界: Audit-only Boundary Guard_

- [x] 5. 監査結果を検証する
- [x] 5.1 Requirement coverage と classification completeness を確認する
  - すべての requirement ID が task と docs 更新結果に対応していることを確認する
  - In-scope row に final classification または `needs reference evidence` が残っていることを確認し、final `candidate` が残っていないことを確認する
  - 完了時には、requirements 1.1 から 10.5 までの監査結果が matrix / guide / checklist のいずれかで検証できる
  - _要件: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3, 5.4, 6.1, 6.2, 6.3, 6.4, 7.1, 7.2, 7.3, 7.4, 8.1, 8.2, 8.3, 8.4, 9.1, 9.2, 9.3, 9.4, 10.1, 10.2, 10.3, 10.4, 10.5_
  - _境界: Audit-only Boundary Guard, Matrix Classification Surface, Guide Evidence Surface_

- [x] 5.2 Markdown review と diff review を実行する
  - Matrix と guide の tables / headings が Markdown として読める形を保っていることを確認する
  - `git diff --name-only` で変更範囲が docs/spec/glossary に限定されていることを確認する
  - 完了時には、review 結果として docs-only audit の完了条件と未解決 follow-up が報告できる
  - _要件: 9.1, 9.2, 9.3, 9.4, 10.1, 10.2, 10.3, 10.4, 10.5_
  - _境界: Audit-only Boundary Guard_
