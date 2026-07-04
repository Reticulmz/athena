# 実装計画

- [ ] 1. Foundation: body strategy gate と Stable compatibility vocabulary を固める
- [x] 1.1 Replay download success body strategy を安全に確定できる gate を作る
  - Local-only raw blob validation の入力と出力が repository-managed files に残らないようにする
  - `blocked`、`direct_blob_bytes`、`assemble_download_body` のいずれかを実装が参照できる sanitized decision state として扱う
  - `blocked` の場合は success 200 を返せないことがテストで観測できる
  - Raw replay bytes、complete `.osr`、password、password hash、raw query values が成果物に含まれないことが確認できる
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 5.1, 5.2, 5.3, 6.1, 6.3_

- [x] 1.2 Stable replay download の branch と body strategy 語彙を定義する
  - Success、auth failure、hidden score、storage missing、missing replay provisional、malformed request provisional、body strategy blocked を区別できる
  - Replay Download Response Body と stored Replay blob object を別概念として表現する
  - Compatibility vocabulary が transport、SQLAlchemy、storage backend を import しないことが確認できる
  - Enum/value object の値が existing contract fixture labels と対応することを unit tests で確認できる
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 4.4, 6.1, 6.3_

- [ ] 2. Core: replay lookup と storage read の read-only boundaries を作る
- [x] 2.1 Replay download candidate の query repository contract を定義する
  - Score not found、hidden score、missing replay、available replay を repository result として区別する
  - Available replay は blob id、checksum、byte size だけを返し、raw bytes や storage key を返さない
  - Contract tests が typed fake data で各 candidate branch を検証できる
  - _Requirements: 3.1, 4.2, 4.3, 4.4, 4.5, 6.2, 6.3_

- [x] 2.2 (P) SQLAlchemy replay download candidate projection を実装する
  - Existing score、replay attachment、user visibility inputs から replay download candidate を read-only に投影する
  - Hidden score と missing replay が同じ 404 response に写像される前段で、内部 branch としては区別される
  - SQLAlchemy query は raw blob bytes を読まず、short query session だけで完了することが tests から確認できる
  - _Depends: 2.1_
  - _Requirements: 3.1, 4.2, 4.3, 4.4, 4.5, 6.2_
  - _Boundary: SQLAlchemy Replay Download Query Repository_

- [x] 2.3 (P) In-memory replay download candidate projection を実装する
  - In-memory repository state から SQLAlchemy adapter と同じ candidate branches を返す
  - Query service tests が DB なしで missing、hidden、missing replay、available replay を作れる
  - Contract tests が SQLAlchemy adapter と同じ observable branch set を確認できる
  - _Depends: 2.1_
  - _Requirements: 3.1, 4.2, 4.3, 4.4, 4.5, 6.2_
  - _Boundary: In-memory Replay Download Query Repository_

- [x] 2.4 (P) Blob byte reader の read-only protocol と unavailable error handling を作る
  - Query workflow は blob id から bytes を読む protocol だけに依存する
  - Storage backend key、filesystem path、blob implementation detail が query result や response に出ない
  - Missing blob metadata または backend content unavailable が storage-missing branch に変換できる typed error として観測できる
  - _Requirements: 2.2, 2.3, 4.3, 4.5, 5.4_
  - _Boundary: Blob Byte Reader_

- [ ] 2.5 (P) Confirmed query keys の parser と malformed fallback を実装する
  - `c` と `m` が typed request に parse され、`u` と `h` は auth mapping だけに渡される
  - Missing/malformed `c` / `m` と unknown field は target-confirmed behavior ではなく provisional fallback として分類される
  - Parser result と test failure output に raw `u`、raw `h`、raw query values が残らない
  - _Requirements: 1.2, 1.4, 5.1, 5.3, 5.4, 6.2, 6.3_
  - _Boundary: Replay Download Query Parser_

- [ ] 3. Core: replay download query workflow と body production を作る
- [ ] 3.1 Replay download body assembler を実装する
  - `blocked` strategy では bytes を生成せず、success branch を不可にする
  - `direct_blob_bytes` strategy では validation 済み stored bytes だけを response body として返す
  - `assemble_download_body` strategy では local validation で確定した変換だけを使い、未確定なら blocked として扱う
  - Synthetic bytes を使う tests で direct、assemble、blocked の observable result を確認できる
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.3, 5.1, 5.2, 5.3, 6.1, 6.3_

- [ ] 3.2 Replay download query use-case の branch classification を実装する
  - Authenticated user id、score id、ruleset から replay candidate を読み、response branch を決定する
  - Available replay だけが blob reader と body assembler に進む
  - Blob read unavailable は storage-missing branch になり、storage internals は result に含まれない
  - Replay view count や latest activity の mutation が呼ばれないことを tests で確認できる
  - _Depends: 2.1, 2.4, 3.1_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.3, 3.4, 4.2, 4.3, 4.4, 4.5, 6.1, 6.2, 6.3, 6.4_

- [ ] 3.3 Replay download query workflow の focused tests を揃える
  - Missing score、hidden score、missing replay provisional、storage missing、blocked strategy、direct bytes、assemble body を網羅する
  - Failure branches は client-visible cause を持たない result として検証される
  - Test fixtures と assertion output に raw replay payload、credential values、local artifact paths が含まれない
  - _Depends: 3.2_
  - _Requirements: 3.1, 3.3, 3.4, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4, 6.2, 6.3, 6.4_

- [ ] 4. Transport: Stable web legacy response mapping を実装する
- [ ] 4.1 Replay download handler の auth mapping と request orchestration を実装する
  - `u` と `h` が existing legacy session credential boundary に渡される
  - Auth failure は parser/query lookup に進まず、401 empty body を返す
  - Auth success 後だけ parser と replay download query use-case が呼ばれることを handler tests で確認できる
  - _Depends: 2.5, 3.2_
  - _Requirements: 1.1, 1.2, 3.3, 4.1, 5.4, 6.2_

- [ ] 4.2 Stable response formatter を全 branch に対して実装する
  - Success は non-blocked strategy のときだけ HTTP 200、target-compatible bytes、`Content-Type`、`Content-Disposition` を返す
  - Hidden score、storage missing、missing replay provisional、malformed request provisional、body strategy blocked は empty 404 response に写像される
  - Unavailable replay response は authorization、visibility、metadata、storage の内部原因を client-visible body に出さない
  - Handler tests が status、headers、body length、secret non-exposure を branch ごとに確認できる
  - _Depends: 4.1_
  - _Requirements: 1.4, 2.4, 3.1, 3.2, 3.3, 3.4, 4.2, 4.3, 4.4, 4.5, 5.4, 6.2, 6.3, 6.4_

- [ ] 5. Integration: route、DI、startup validation を接続する
- [ ] 5.1 Stable web legacy route と endpoint delegate を追加する
  - Primary route `GET /web/osu-getreplay.php` が stable web legacy app で handler に到達する
  - `/web/replays/<id>` はこの spec の route として登録されない
  - Route smoke test が primary route を観測でき、alias が required behavior ではないことを確認できる
  - _Depends: 4.2_
  - _Requirements: 1.1, 1.3, 6.2, 6.3_

- [ ] 5.2 Provider graph と startup eager resolution を接続する
  - Replay download handler、parser、query use-case、repository、blob reader が runtime provider graph から解決される
  - App startup が handler dependency error を first request 前に検出できる
  - In-memory runtime provider graph でも replay download route smoke test が実行できる
  - _Depends: 2.2, 2.3, 2.4, 4.2, 5.1_
  - _Requirements: 1.1, 3.1, 4.1, 6.2_

- [ ] 5.3 End-to-end branch smoke tests を追加する
  - Sanitized request values で auth failure 401 empty body が app route 経由で観測できる
  - Missing replay provisional または storage-missing 404 empty body が app route 経由で観測できる
  - Non-blocked body strategy fixture がある場合だけ success 200 smoke test を有効化し、blocked の場合は 200 が返らないことを確認する
  - _Depends: 5.2_
  - _Requirements: 1.1, 1.2, 2.1, 2.4, 3.1, 3.2, 3.3, 4.1, 4.3, 4.4, 4.5, 5.4, 6.2, 6.3_

- [ ] 6. Validation: focused checks と quality gate を通す
- [ ] 6.1 Replay download focused test suite を実行し、不足を修正する
  - Parser、handler、query use-case、repository、composition integration の tests が pass する
  - All in-scope response branches と body strategy gate が tests から追跡できる
  - Failing test がある場合は implementation 側を先に疑い、confirmed contract 変更が必要な場合だけ spec gap として止める
  - _Depends: 5.3_
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4, 6.1, 6.2, 6.3, 6.4_

- [ ] 6.2 Quality and boundary checks を通し、secret/raw artifact 混入を review する
  - Relevant lint、type、import boundary checks が pass する
  - Diff review で raw capture、raw replay bytes、complete `.osr`、password values、password hashes、raw query values、local artifact paths が含まれないことを確認できる
  - Runtime adapters が SQLAlchemy models、DB sessions、raw SQL、storage backend implementation を import していないことを確認できる
  - _Depends: 6.1_
  - _Requirements: 3.3, 4.5, 5.1, 5.2, 5.3, 5.4, 6.2, 6.3, 6.4_
