# Implementation Plan

- [x] 1. 監査分類の土台と matrix 更新形式を整える
- [x] 1.1 stable release/update 監査で使う glossary を確定する
  - Stable Compatibility Route Classification、Stable Operational Dependency、Stable Fixture Requirement を互いに混同しない用語として定義する
  - 用語は route 固有の response shape や fixture identifier を含めず、後続の stable compatibility audit でも再利用できる形にする
  - 完了時には glossary から、互換分類、運用依存、fixture 要否が別軸であることを確認できる
  - _Requirements: 4.1, 4.6_
  - _Boundary: Route Classification Glossary_

- [x] 1.2 release/update matrix row の監査軸を決める
  - Matrix row から route classification、response shape、evidence source、operational dependency、fixture requirement を読める表現を決める
  - 既存 implementation status を互換分類で上書きせず、runtime 実装状況と audit policy を分けて読めるようにする
  - 完了時には後続 route row が同じ監査軸で更新でき、proxying や hosting が実装既定値として読まれない
  - _Requirements: 4.1, 4.6_
  - _Boundary: Release Update Matrix Rows, Operational Dependency Matrix_

- [x] 2. no-update route の matrix row を監査する
- [x] 2.1 `/web/check-updates.php` の no-update policy を matrix に反映する
  - `/web/check-updates.php` を `required-no-update` として分類し、chosen response shape を `[]` として記録する
  - `deck` の `[]`、`bancho.py` の empty body 比較、ユーザー確認済みの current osu!stable `--devserver` behavior を evidence source として残す
  - 初期 no-update row の operational dependency は `none` とし、ppy proxying は将来の `proxy-decision-required` 判断であって初期実装既定値ではないことを matrix row から読めるようにする
  - 完了時には `/web/check-updates.php` row から `check_updates_no_update_json_array` fixture handoff まで追跡できる
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_
  - _Boundary: Release Update Matrix Rows, Operational Dependency Matrix, Evidence Consistency Notes_

- [x] 2.2 release manifest routes と root aliases の no-update policy を matrix に反映する
  - `/release/update` と `/update` を empty body の `required-no-update` として分類する
  - `/release/update.php` と `/update.php` を `0` response の `required-no-update` として分類する
  - `/release/update2.php` と `/update2.php` を empty body の `required-no-update` として分類する
  - `/release/patches.php` と `/patches.php` を empty body の `required-no-update` として分類する
  - これらの manifest row は operational dependency `none` とし、hosted update metadata や artifact distribution は初期 no-update policy の外であることを示す
  - 完了時には release manifest と root alias の各 row が同じ no-update contract に従って読める
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_
  - _Boundary: Release Update Matrix Rows, Operational Dependency Matrix_

- [x] 3. file-like release route の deferred policy を明示する
  - `/release/<filename>` を `deferred` とし、operational dependency を `hosted-artifact-decision-required` として記録する
  - `/release/filter.txt` を `deferred` とし、operational dependency を `proxy-decision-required` として記録する
  - `/release/Localisation/<filename>` を `deferred` とし、operational dependency を `proxy-decision-required` として記録する
  - `/release/<language>/<filename>` を `deferred` とし、operational dependency を `hosted-artifact-decision-required` として記録する
  - File bytes serving や external proxy route は `required-no-update` として扱わず、初期実装既定値ではないことを row note から確認できる
  - _Requirements: 2.6, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_
  - _Boundary: Deferred Route Decision Notes, Operational Dependency Matrix_

- [x] 4. #17 向け fixture handoff catalog を作る
  - `/web/check-updates.php` row に `check_updates_no_update_json_array` を fixture identifier として紐づける
  - Empty-body release manifest/root alias row に `release_no_update_empty` を紐づける
  - `/release/update.php` と `/update.php` row に `release_update_php_zero` を紐づける
  - Deferred file/proxy routes は fixture requirement `deferred` とし、placeholder fixture identifier を作らない
  - 完了時には #17 が response bytes ごとの fixture identifier を matrix から取得できる
  - _Requirements: 1.5, 4.2, 4.3, 4.4, 4.5_
  - _Boundary: Fixture Handoff Catalog_

- [x] 5. evidence consistency と needs-reference behavior を確認する
  - Matrix row と `docs/stable-compatibility-guide.md` の Update And Release Endpoints section を照合し、response shape と evidence source が矛盾していないか確認する
  - 確認済み evidence で解決できる場合だけ `docs/stable-compatibility-guide.md` を補正し、未確認の場合は matrix 側に evidence gap として残す
  - Evidence が不足する route は `needs-reference` とし、推測で response contract を作らない
  - 完了時には selected response、deferred decision、needs-reference row のいずれも evidence source または evidence gap を持つ
  - _Requirements: 1.3, 4.1, 4.6_
  - _Boundary: Evidence Consistency Notes_

- [x] 6. 最終 validation と scope review を行う
  - Release/update matrix row が route classification、operational dependency、evidence source、fixture requirement を持つことを確認する
  - `CONTEXT.md` が glossary-only であり、route 固有の response shape や fixture identifier を含んでいないことを確認する
  - `src/`、`tests/fixtures/`、migration、dependency、runtime configuration が変更されていないことを確認する
  - `git diff --check` と targeted `rg` checks で fixture identifiers、operational dependency values、deferred / needs-reference vocabulary を確認する
  - 完了時には実行した validation command、pass/fail 結果、未解決 evidence gap を実装報告に含められる
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_
  - _Boundary: Documentation Validation_
