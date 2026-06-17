# Implementation Plan

- [x] 1. Friend Relationship の永続化基盤を作る

- [x] 1.1 Friend Relationship 用の DB schema と migration を追加する
  - 片方向 relationship を owner と target の複合キーで保存できるようにする。
  - self relationship を保存できない制約と、user 削除時に relationship が残らない参照整合性を入れる。
  - migration と model-level 検証で、重複追加、逆方向 relationship、self relationship の扱いが観測できる。
  - _Requirements: 1.1, 1.3, 1.4, 2.6, 9.1_

- [x] 1.2 Friend Relationship の repository contract と Unit of Work 境界を追加する
  - add、remove、target existence、owner-scoped read、relationship existence read の contract を command/query に分ける。
  - command repository は Unit of Work 配下でだけ mutation でき、query repository は read-only として扱える。
  - 型チェック上、command/query use-case から concrete repository や DB session を直接参照しない状態になる。
  - _Requirements: 1.1, 1.2, 1.5, 2.1, 2.2, 2.3, 3.1, 8.1, 9.2_

- [x] 1.3 In-memory Friend Relationship repository を実装する
  - memory Unit of Work の transaction snapshot に relationship state を含める。
  - duplicate add と missing remove が idempotent に振る舞う。
  - contract tests で owner-filtered read、reverse-edge independence、rollback/commit behavior が確認できる。
  - _Requirements: 1.3, 1.4, 2.6, 2.7, 3.3, 8.5_

- [x] 1.4 SQLAlchemy Friend Relationship repository を実装する
  - SQLAlchemy command repository は UoW-owned session を使い、commit/rollback しない。
  - query repository は owner-scoped friend IDs と relationship existence を read-only に返す。
  - SQLAlchemy repository tests で offline target を含む add/read/remove と idempotency が確認できる。
  - _Requirements: 1.2, 2.1, 2.2, 2.3, 2.6, 2.7, 3.1, 3.4, 8.1, 8.2_

- [x] 2. Friend-Only DM の active session state を更新できるようにする

- [x] 2.1 SessionStore に `pm_private` 専用 update contract を追加する
  - active session の `pm_private` だけを更新し、他の session field を変えない。
  - missing session では `False` 相当の結果を返し、新しい session や account-level state を作らない。
  - memory implementation の unit tests で true/false 更新、missing session、他 field preservation が確認できる。
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 2.2 Valkey SessionStore の `pm_private` 更新を atomic に実装する
  - Valkey-backed session JSON を部分更新し、既存 TTL と user-session mapping を維持する。
  - missing session と expired session は state を作らず false outcome になる。
  - Valkey integration tests で TTL preservation と field preservation が確認できる。
  - _Requirements: 5.3, 5.4, 5.5_

- [x] 3. Identity domain と command/query use-case を実装する

- [x] 3.1 Friend Relationship domain policy を追加する
  - one-way relationship、self-target rejection、friendable target、friendable system user の語彙を domain に定義する。
  - BanchoBot は friendable system user として明示追加可能で、自動追加の概念を持たない。
  - domain tests で one-way invariant、mutual-as-two-edges、self rejection、BanchoBot friendability が確認できる。
  - _Requirements: 1.1, 1.3, 1.4, 1.5, 4.1, 4.4, 4.5, 9.1, 9.4_

- [x] 3.2 Friend add/remove command use-case を実装する
  - existing friendable target は add/remove でき、offline target でも add できる。
  - unknown target、self-add、duplicate add、missing remove、nonfriendable system target は durable state を変えない no-op outcome になる。
  - command tests で stable が無視できる typed outcome と durable state の変化が確認できる。
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 4.1, 4.4, 4.5, 9.3, 9.4_

- [x] 3.3 (P) Friend read query use-case を実装する
  - owner-scoped friends list、relationship existence、Friends leaderboard eligible user IDs を同じ source of truth から返す。
  - reverse relationship は owner の friends list や leaderboard eligible set に含めない。
  - query tests で empty set、offline target inclusion、BanchoBot explicit-only、score row 非生成が確認できる。
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 4.2, 4.3, 6.2, 6.3, 8.1, 8.2, 8.3, 8.4, 8.5, 9.2_
  - _Boundary: Friend relationship queries_
  - _Depends: 1.3, 1.4, 3.1_

- [x] 3.4 (P) Friend-Only DM session command use-case を実装する
  - stable packet から得た enabled state を active session の `pm_private` に反映する。
  - missing session では state を作らず、transport が安全に無視できる outcome を返す。
  - command tests で login-derived state と later update state の両方が確認できる。
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_
  - _Boundary: Friend-only session update_
  - _Depends: 2.1, 2.2_

- [x] 4. Stable protocol packet surface を補完する

- [x] 4.1 `USER_DM_BLOCKED` の stable packet builder を追加する
  - blocked outcome は stable `Message` payload として、empty sender/content、target name、sender ID `0` を持つ。
  - protocol tests で packet ID、payload length、target encoding が固定される。
  - PM integration tests がこの builder の bytes を利用できる状態になる。
  - _Requirements: 6.4_
  - _Boundary: Stable protocol builders_

- [x] 4.2 stable friend packet payload の parser/handler expectations を固定する
  - add/remove は stable int32 target ID、friend-only DM update は stable boolean payload として扱う。
  - malformed payload は mutation されず、既存 handler と同じ drop behavior になる。
  - handler-level tests が use-case を typed fake で呼び出せる状態になる。
  - _Requirements: 2.1, 2.2, 2.8, 5.3_
  - _Boundary: Stable friend handlers_
  - _Depends: 3.2, 3.4_

- [x] 5. Login friends list と stable friend handlers を runtime に接続する

- [x] 5.1 Login response の friends list を query-backed にする
  - successful login response の `FRIENDS_LIST` が logged-in user の current friend target IDs を返す。
  - no friends は empty list、reverse-only relation は含まれない、offline target は含まれる。
  - LoginResponseBuilder tests で BanchoBot が explicit relationship なしには friends list に出ないことが確認できる。
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 4.2, 4.3, 9.2_
  - _Depends: 3.3_

- [x] 5.2 stable friend handlers を実装する
  - `ADD_FRIEND` と `REMOVE_FRIEND` が command use-case を呼び、直接 response packet を enqueue しない。
  - `CHANGE_FRIENDONLY_DMS` が active session privacy state を更新する。
  - handler tests で typed fake use-case への packet adaptation と no-response behavior が確認できる。
  - _Requirements: 2.1, 2.2, 2.8, 5.3_
  - _Depends: 4.2_

- [x] 6. Private Message delivery に Friend-Only DM policy を接続する

- [x] 6.1 PM command に target-side Friend-Only DM policy を追加する
  - target の active session が `pm_private=False` の場合は friend status だけでは block しない。
  - target が `pm_private=True` の場合、target が sender を friend に追加済みなら deliverable、未追加なら blocked outcome になる。
  - PM command tests で blocked PM が target delivery と accepted-history persistence を行わないことが確認できる。
  - _Requirements: 6.1, 6.2, 6.3, 6.5, 9.5_
  - _Depends: 3.3_

- [x] 6.2 system response delivery と BanchoBot command path を friend-only block から分離する
  - BanchoBot command response と Athena system response は player-originated PM gate を通らず、invoking user に返る。
  - player が BanchoBot に PM した場合、BanchoBot を friend に追加していなくても command handling が実行される。
  - chat command tests で BanchoBot response bypass と player-originated blocking の違いが確認できる。
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 9.5_
  - _Depends: 6.1_

- [x] 6.3 stable PM handler で blocked outcome を sender-visible packet に変換する
  - PM command が blocked outcome を返したとき、sender に `USER_DM_BLOCKED` が enqueue される。
  - target には original PM packet が enqueue されない。
  - handler tests で delivered、offline、target-not-found、blocked の observable packet behavior が区別できる。
  - _Requirements: 6.4, 6.5, 7.4_
  - _Depends: 4.1, 6.1_

- [x] 7. Runtime wiring と test provider を完成させる

- [x] 7.1 Repository と use-case provider wiring を追加する
  - production graph が SQLAlchemy friend repositories と friend use-cases を解決できる。
  - test graph が in-memory repositories と SessionStore fake を使って同じ contracts を満たす。
  - provider/dispatcher tests で login builder、friend handlers、PM command の依存が全て解決され、packet dispatch できることが確認できる。
  - _Requirements: 2.1, 3.1, 5.3, 6.1, 8.1, 9.3_
  - _Depends: 1.2, 3.2, 3.3, 3.4, 5.1, 5.2, 6.1_

- [x] 7.2 import boundary と package exports を整理する
  - command/query/domain/repository/stable transport の import direction が architecture rules に合う。
  - new repository contracts と use-cases が existing package exports から利用できる。
  - import-linter と basedpyright の対象になる形で orphan module が残らない。
  - _Requirements: 1.1, 8.4, 9.1, 9.2_
  - _Depends: 7.1_

- [x] 8. End-to-end behavior と regression を検証する

- [x] 8.1 stable friend pipeline の integration tests を追加する
  - add friend 後の relogin で target ID が friends list に入り、remove 後の relogin で消える。
  - offline target と explicit BanchoBot add が login friends list に反映される。
  - reverse-only relationship が logged-in user の friends list に出ないことが確認できる。
  - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 9.2_
  - _Depends: 7.1_

- [x] 8.2 friend-only PM pipeline の integration tests を追加する
  - `CHANGE_FRIENDONLY_DMS` 後、non-friend sender の PM は target に届かず sender に blocked packet が返る。
  - target が sender を friend に追加済みの場合、friend-only DM 中でも PM が届く。
  - BanchoBot command response は friend-only DM によって block されないことが確認できる。
  - _Requirements: 5.3, 6.1, 6.2, 6.3, 6.4, 6.5, 7.1, 7.3, 7.4, 9.5_
  - _Depends: 6.3, 7.1_

- [x] 8.3 targeted tests と quality checks を通す
  - friend relationship repository、session store、identity command/query、stable bancho handler、chat PM tests が全て成功する。
  - `ruff`、`basedpyright`、import-linter の関連チェックで新規違反がない。
  - broad gate を実行する場合でも unrelated dirty worktree を巻き戻さず、失敗時は原因と修正対象が特定できる。
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 6.2, 6.3, 6.4, 6.5, 7.1, 7.2, 7.3, 7.4, 8.1, 8.2, 8.3, 8.4, 8.5, 9.1, 9.2, 9.3, 9.4, 9.5_
  - _Depends: 8.1, 8.2_
