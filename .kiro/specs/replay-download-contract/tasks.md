# 実装計画

- [ ] 1. Replay download evidence の基盤を用意する
- [x] 1.1 Replay download を stable verification surface として扱えるようにする
  - Replay download surface、sanitized fixture、response branch、body decision、blob diagnostic result を同じ verification 語彙で表現する
  - Password、password hash、session token、raw credential、raw replay、complete `.osr` bytes を reportable model から除外する
  - 完了時には unit tests で replay download evidence model が secret-like values を repr / report に出さないことを確認できる
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 1.2 Sanitized fixture schema と validator を追加する
  - Target client family、build / `osuver` observation status、method、path、query key set、auth field category、response status、header key set、body kind、safe hash、byte size を fixture で表現する
  - Raw query values、credential-like values、raw replay bytes、complete `.osr` bytes、HAR archive が fixture に含まれる場合は validation failure にする
  - 完了時には fixture validator tests が valid fixture を pass、secret-containing fixture を fail として確認できる
  - _Requirements: 1.1, 5.1, 5.2, 5.3, 5.4, 5.5_

- [ ] 2. Target traffic と reference evidence を収集する
- [x] 2.1 Target Stable Client の replay download traffic を sanitized fixture 化する
  - Target client family、build / `osuver` observation status、capture time、workflow entrance を記録する
  - Replay download request の method、path、query key set、auth field presence を raw values なしで記録する
  - `/web/osu-getreplay.php` と `/web/replays/<id>` のどちらが target client から観測されたかを fixture と docs から読めるようにする
  - 完了時には target route / auth presence の fixture が validator を通り、build / `osuver` が request に出ない capture は `not_observed` として採用される
  - _Requirements: 1.1, 1.2, 1.3, 7.1, 7.2, 7.3, 7.4_

- [x] 2.2 `bancho.py`、`deck`、`lets` の replay download reference audit を行う
  - `bancho.py` は stable baseline comparison として route、auth、success/missing branch を確認する
  - `deck` は missing、hidden、storage-missing branch の status / body summary を確認する
  - `lets` は `/web/replays/<id>` alias の route / response variant を確認する
  - Reference が一致しない branch は unresolved として記録し、target traffic または明示 rationale なしに contract として採用しない
  - 完了時には reference response fixture と audit summary から source、branch、status、header keys、body kind、unresolved reason が読める
  - _Requirements: 1.4, 1.5, 2.2, 2.3, 2.4, 4.1, 4.2, 4.3, 4.4, 4.5, 7.2, 7.3, 7.4_

- [x] 2.3 Replay download response contract を branch ごとに固定する
  - Success、auth failure、missing replay、hidden score、storage-missing、missing score id、malformed score id、missing mode、malformed mode、unknown field を branch として整理する
  - Confirmed branch は target traffic または reference source を示し、unresolved branch は `未確認` と blocker reason を示す
  - 完了時には #36 が扱える branch と blocked のまま残す branch が response contract table から判断できる
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 8.3, 8.4_

- [ ] 3. Replay blob integrity と body assembly decision を確定する
- [x] 3.1 Replay Blob Diagnostic Procedure を実装または手順化する
  - Score id から replay attachment、blob metadata、storage object existence、metadata size/hash、observed size/hash を照合できるようにする
  - Diagnostic output は raw replay bytes や credential-like values を含まない
  - 完了時には diagnostic tests または documented dry-run result で integrity pass、missing replay、missing blob metadata、missing storage object、hash/size mismatch を区別できる
  - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [x] 3.2 Target-client-compatible body 判定と body assembly decision を記録する
  - Stored Replay blob bytes が target client または approved parser で replay download response body として消費できるかを local-only artifact で確認する
  - Blob integrity が pass しても target body compatibility が fail する場合は download body format mismatch として扱う
  - 完了時には body decision fixture から `direct_blob_bytes`、`assemble_download_body`、または `blocked` の選択と根拠が読める
  - _Requirements: 2.5, 3.1, 3.2, 3.3, 3.4, 6.3, 6.5_

- [ ] 4. Docs と #36 handoff を更新する
- [x] 4.1 Stable compatibility guide と matrix の replay download evidence を更新する
  - Replay Download evidence note に route/auth/request/response/body decision の confirmed / unresolved 状態を反映する
  - Matrix の replay download rows に current classification、evidence source、remaining gaps、alias policy を反映する
  - 完了時には guide と matrix が同じ primary route、auth blocker、response blocker、body assembly decision を示している
  - _Requirements: 8.1, 8.2, 8.3, 8.4_

- [ ] 4.2 #36 と #37 の境界を handoff として明示する
  - #36 が implementation-ready か blocked かを exact blocker と sanitized fixture path で示す
  - #36 が実装すべき route、auth、request fields、response branches、download body strategy を confirmed contract としてまとめる
  - #37 の replay view count と latest activity は #36 readiness から外し、download response behavior に影響する場合だけ再確認対象にする
  - 完了時には後続エージェントが docs / issue handoff だけで #36 の着手可否を判断できる
  - _Requirements: 8.3, 8.4, 8.5_

- [ ] 5. Validation と品質確認を行う
- [ ] 5.1 Fixture / diagnostic / docs の regression tests を通す
  - Fixture validator tests、redaction tests、reference branch tests、body decision tests、diagnostic output tests を実行する
  - Existing stable verification catalog が replay download surface を known gap / evidence surface として扱うことを確認する
  - 完了時には replay download fixture と diagnostic が raw secret / raw replay を出さないことを test output で確認できる
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 6.2, 6.3, 6.4, 6.5, 7.1, 7.2, 7.3, 7.4, 8.1, 8.2, 8.3, 8.4, 8.5_

- [ ] 5.2 Focused quality checks と diff review を行う
  - Relevant pytest、ruff、basedpyright、import-linter checks を実行する
  - Markdown tables と fixture JSON が parse できることを確認する
  - `git diff` で raw capture、raw replay bytes、complete `.osr` bytes、credential-like values が含まれていないことを確認する
  - 完了時には実行した command、pass/fail、未検証項目を実装報告に含められる
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 8.1, 8.2, 8.3, 8.4, 8.5_
