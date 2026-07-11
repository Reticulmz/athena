# Requirements Document

## Introduction

stable client player と将来の Web leaderboard viewer は、Beatmap ごとの競技結果、順位、Viewer 自身の Personal Best を category ごとに確認できる必要がある。beatmap-leaderboards は、保存済み Score と current Performance Calculation から Beatmap Leaderboard と score-priority Personal Best を導き、stable getscores と Web 表示で Global / Country / Selected Mods / Friends category を一貫して扱えるようにする。

初期 scope は vanilla playstyle の Beatmap Leaderboard に限定し、Beatmap Leaderboard の Personal Best は score を優先する。User Profile、Top Plays、User Stats、User Ranking に使う PP-priority Performance Best は別機能として扱う。

## Boundary Context

- **In scope**: stable getscores と将来の Web 表示における Beatmap Leaderboard rows、score-priority Personal Best、Global / Country / Selected Mods / Friends category、stable score submit の Global / all-mods Personal Best delta、Beatmap status / checksum / user visibility 変更時の公開表示整合性。
- **Out of scope**: non-vanilla playstyle、lazer API、PP-priority Performance Best の実装、User Stats / User Ranking の集計、operator が非公開 Score を調査する内部表示、explicit Mirror mod filter。
- **Adjacent expectations**: score-ingestion は Score、pass/fail、server submission acceptance time、Beatmap checksum、actual mods、同一 submission retry 用の保存済み結果を提供し、leaderboard 非対象の Score も score record として保持できる。score-pp-calculation は PP 表示に使える current Performance Calculation を提供する。friend-relationships は viewer の current friend targets を提供する。Beatmap metadata は current Beatmap status と current checksum を提供する。user-stats は PP-priority Performance Best と stats/ranking 表示を所有する。

## Requirements

### Requirement 1: Leaderboard Availability And Categories
**Objective:** As a stable client player or Web leaderboard viewer, I want Beatmap Leaderboard availability and categories to behave consistently, so that I can inspect competitive results without category-specific surprises.

#### Acceptance Criteria
1. When a viewer requests a Beatmap Leaderboard for a Ranked, Approved, Loved, or Qualified Beatmap in vanilla playstyle, the Athena Server shall return leaderboard availability and rows for the requested supported Leaderboard Category.
2. When a viewer requests the Global Leaderboard Category, the Athena Server shall consider eligible scores from all Leaderboard Visible Users without filtering by mods, country, or friend relationship.
3. When a stable client requests the Local leaderboard type, the Athena Server shall use the same candidate set as the Global Leaderboard Category.
4. If a viewer requests an unsupported Leaderboard Category, the Athena Server shall return a compatible Beatmap header with no leaderboard rows and no Personal Best instead of falling back to Global rows.
5. If a viewer requests a non-vanilla playstyle in the initial scope, the Athena Server shall return a compatible empty leaderboard response for that playstyle.
6. When a stable client sends a song select or editor leaderboard request, the Athena Server shall return Beatmap availability information without score rows and without a Personal Best row.

### Requirement 2: Row Selection, Ordering, And Count
**Objective:** As a leaderboard viewer, I want rows to be ordered and counted predictably, so that rank display remains deterministic across clients and retries.

#### Acceptance Criteria
1. When a Leaderboard Scope contains multiple eligible scores for the same user, the Athena Server shall select that user's highest-ranked score-priority representative for that scope.
2. When the Athena Server ranks Beatmap Leaderboard candidates, the Athena Server shall order them by score descending, server submission acceptance time ascending, and Score ID ascending.
3. When the Athena Server returns Beatmap Leaderboard rows, the Athena Server shall return at most 50 rows for the request.
4. When the Athena Server returns Beatmap Leaderboard rows, the Athena Server shall assign row ranks from 1 through the number of returned rows in display order.
5. When the Athena Server returns a stable getscores response, the Athena Server shall report score count as the number of returned Beatmap Leaderboard rows and shall not include the Personal Best row in that count.
6. If two candidate scores have the same score and server submission acceptance time, the Athena Server shall rank the lower Score ID above the higher Score ID.

### Requirement 3: Personal Best Rows
**Objective:** As a viewer, I want my Personal Best to be shown separately from the top rows, so that I can see my own standing even when I am outside the returned top 50.

#### Acceptance Criteria
1. When an authenticated viewer has an eligible score-priority Personal Best in the requested Leaderboard Scope, the Athena Server shall return that Personal Best separately from the Beatmap Leaderboard rows.
2. When the viewer's Personal Best is outside the returned top 50 rows, the Athena Server shall return the Personal Best row with its actual rank in the requested Leaderboard Scope.
3. When the viewer's Personal Best is also included in the returned top 50 rows, the Athena Server shall return the same Score in both the Personal Best row and the Beatmap Leaderboard rows.
4. When a viewer requests the Global, Country, or Friends Leaderboard Category, the Athena Server shall resolve the Personal Best without applying a mods filter.
5. When a viewer requests the Selected Mods Leaderboard Category, the Athena Server shall resolve the Personal Best inside the selected Leaderboard Mod Filter.
6. If the viewer is unknown or unauthenticated, the Athena Server shall not return a Personal Best row.
7. If the viewer is not a Leaderboard Visible User, the Athena Server shall not return that viewer's Personal Best row while still allowing public leaderboard rows to be returned.

### Requirement 4: Country And Friends Scopes
**Objective:** As a stable client player, I want Country and Friends leaderboards to reflect my current viewer context, so that those categories match the people I expect to compare against.

#### Acceptance Criteria
1. When a viewer requests the Country Leaderboard Category, the Athena Server shall include only eligible scores whose score owner currently has the same country as the viewer.
2. If the viewer has no current country or has country `XX`, the Athena Server shall return no Country rows and no Country Personal Best.
3. When a viewer requests the Friends Leaderboard Category, the Athena Server shall include eligible scores from the viewer's current friend targets and from the viewer.
4. If another user has a reverse-only friend relationship toward the viewer, the Athena Server shall not include that user in the viewer's Friends leaderboard unless the user is also one of the viewer's current friend targets.
5. When a viewer requests the Country or Friends Leaderboard Category, the Athena Server shall not restrict candidates by Selected Mods filtering.
6. When a viewer's friend relationship changes, the Athena Server shall reflect the current friend targets on subsequent Friends leaderboard reads.
7. When a score owner's current country changes, the Athena Server shall reflect the current country on subsequent Country leaderboard reads.
8. If the viewer is unknown or unauthenticated, the Athena Server shall return no Country rows, no Friends rows, and no Personal Best row for viewer-dependent categories.

### Requirement 5: Selected Mods Filtering
**Objective:** As a player comparing a mod-specific leaderboard, I want mod filters to match osu! leaderboard semantics while preserving the mods actually used on each score.

#### Acceptance Criteria
1. When a viewer requests the Selected Mods Leaderboard Category, the Athena Server shall filter Beatmap Leaderboard rows and Personal Best by the selected Leaderboard Mod Filter.
2. When a score contains Nightcore, the Athena Server shall match it with Double Time and Nightcore selected-mod filters while preserving Nightcore in the displayed score mods.
3. When a score contains Perfect, the Athena Server shall match it with Sudden Death and Perfect selected-mod filters while preserving Perfect in the displayed score mods.
4. When the NoMod filter is selected, the Athena Server shall include scores that have no gameplay-affecting mods even if they include Sudden Death, Perfect, or Mirror.
5. When the NoMod filter is selected, the Athena Server shall exclude scores that include Nightcore.
6. When multiple gameplay-affecting mods are selected, the Athena Server shall require all selected gameplay-affecting mods and shall exclude scores with unselected gameplay-affecting mods.
7. When a score matches multiple Leaderboard Scopes, the Athena Server shall allow that score to appear in each matching scope without rewriting its displayed mods.
8. If a viewer explicitly requests the Mirror selected-mod filter in the initial scope, the Athena Server shall return no Selected Mods rows and no Selected Mods Personal Best for that filter.

### Requirement 6: Score Eligibility And User Visibility
**Objective:** As a leaderboard viewer, I want only competitive and publicly visible scores to appear, so that leaderboard rows represent valid public competition.

#### Acceptance Criteria
1. When a score is failed, the Athena Server shall exclude it from Beatmap Leaderboard rows, Personal Best rows, and score-priority representative selection.
2. Where a failed or otherwise leaderboard-ineligible score is stored as a score record, the Athena Server shall keep that score excluded from Beatmap Leaderboard rows, Personal Best rows, and score-priority representative selection.
3. When a score owner is a Leaderboard Visible User, the Athena Server shall allow that owner's eligible scores to appear in public Beatmap Leaderboard rows and Personal Best rows.
4. If a score owner is not a Leaderboard Visible User, the Athena Server shall exclude that owner's scores from public Beatmap Leaderboard rows and Personal Best rows.
5. When a score owner's visibility changes, the Athena Server shall apply the current visibility state on subsequent leaderboard reads.
6. When a score owner becomes visible again, the Athena Server shall allow that owner's previously eligible scores to appear again if all current leaderboard conditions are satisfied.
7. When a viewer who is not a Leaderboard Visible User requests a public leaderboard, the Athena Server shall continue to return public rows owned by other Leaderboard Visible Users.

### Requirement 7: Beatmap Status And Checksum Freshness
**Objective:** As a player, I want leaderboards to reflect the current playable Beatmap file and rank state, so that outdated or pre-eligible scores do not pollute current competition.

#### Acceptance Criteria
1. When a Beatmap is not currently Ranked, Approved, Loved, or Qualified, the Athena Server shall return no Beatmap Leaderboard rows and no Personal Best for that Beatmap.
2. If a score was submitted before the Beatmap became leaderboard-visible, the Athena Server shall not adopt that score into Beatmap Leaderboard rows or Personal Best after the Beatmap is promoted.
3. When a Beatmap leaves a leaderboard-visible status, the Athena Server shall hide existing Beatmap Leaderboard rows and Personal Best rows for that Beatmap on subsequent reads.
4. When a Beatmap checksum changes, the Athena Server shall exclude scores submitted against older checksums from current Beatmap Leaderboard rows and Personal Best rows.
5. When a stable client requests scores with an outdated Beatmap checksum, the Athena Server shall return the compatible update-available response without score rows and without a Personal Best row.
6. While leaderboard reconciliation is pending after Beatmap status or checksum changes, the Athena Server shall still apply current status and checksum rules before returning public leaderboard rows.

### Requirement 8: Score Submit Personal Best Delta
**Objective:** As a stable client player submitting a score, I want the submit response to compare the relevant Personal Best consistently, so that retry and category behavior are predictable.

#### Acceptance Criteria
1. When the Athena Server accepts a new eligible passed score, the Athena Server shall compare it against the user's previous Global all-mods score-priority Personal Best for the same Beatmap, ruleset, and playstyle.
2. When a stable score submit response includes a Personal Best delta, the Athena Server shall base that delta only on the Global all-mods score-priority Personal Best.
3. When a score is ineligible for Beatmap Leaderboard competition, the Athena Server shall not use that score to improve the submit response Personal Best delta.
4. When the same submission is retried and a saved submit result exists, the Athena Server shall return the saved submit result and shall not recalculate the Personal Best delta.
5. When a viewer later opens Country, Friends, or Selected Mods leaderboards, the Athena Server shall resolve those category-specific Personal Best rows from the requested Leaderboard Scope rather than from the score submit response.

### Requirement 9: Performance Display And Stats Boundary
**Objective:** As a player and as an operator, I want Beatmap Leaderboard scoring and PP-based profile ranking to remain separate, so that score leaderboards do not distort PP-driven stats.

#### Acceptance Criteria
1. When a Beatmap Leaderboard row has current Performance Calculation for a Ranked or Approved score, the Athena Server shall make that PP value available to leaderboard surfaces that can display PP.
2. If a Beatmap Leaderboard row has no current Performance Calculation, the Athena Server shall still allow the row to appear when all score eligibility conditions are satisfied.
3. If a Beatmap Leaderboard row belongs to a Loved or Qualified Beatmap, the Athena Server shall not require PP availability for that row to appear.
4. The Athena Server shall rank Beatmap Leaderboard rows and Personal Best rows by score-priority ordering, not by PP.
5. Where User Profile, Top Plays, User Stats, or User Ranking need a representative score, the Athena Server shall treat PP-priority Performance Best as separate from Beatmap Leaderboard Personal Best.

### Requirement 10: Operational Reconciliation
**Objective:** As an operator, I want leaderboard-derived views to recover from delayed rebuilds and state changes, so that public output remains correct while background work catches up.

#### Acceptance Criteria
1. When user visibility changes, the Athena Server shall allow leaderboard reconciliation to run asynchronously without blocking public leaderboard reads.
2. When Beatmap status changes, the Athena Server shall allow leaderboard reconciliation to run asynchronously without blocking public leaderboard reads.
3. When Beatmap checksum changes, the Athena Server shall allow leaderboard reconciliation to run asynchronously without blocking public leaderboard reads.
4. While reconciliation is pending, the Athena Server shall filter public responses using current Beatmap status, current Beatmap checksum, current score owner visibility, and score eligibility.
5. When reconciliation runs more than once for the same affected user or Beatmap set, the Athena Server shall converge to the same public leaderboard result.

### Requirement 11: 永続化型とmigrationの整合性
**Objective:** 運用者として、閉集合値とprojection identityをDBでも型安全に保ち、upgrade/downgradeを既存データを壊さず実行できるようにしたい。

#### Acceptance Criteria
1. Athena ServerはScore play time source、Beatmap fetch target/state、Score Submission state、Score Performance state/profile/reasonを含む閉集合値をdomain EnumとPostgreSQL Enumで表現しなければならない。
2. Athena Serverはpersistence columnを原則`NOT NULL`とし、`NULL`を本当にunknown、unavailable、またはnot-applicableな値だけに使用しなければならない。
3. `score_performance_calculations`では`queued`、`fetching_file`、`calculating`の処理中stateに限って`claim_owner`と`claim_expires_at`のpairを保持でき、未claim時および`completed`、`unavailable`、`superseded`では両方を`NULL`にしなければならない。`performance_recalculation_work_items`では`claimed`のときだけ両方を非`NULL`にし、`pending`およびterminal stateでは両方を`NULL`にしなければならない。
4. Athena ServerはBeatmap、ruleset、playstyle、userのnatural identityごとにGlobal all-mods rowを`beatmap_leaderboard_user_bests`へ1行だけ保存し、current Beatmap checksumを非`NULL`の置換可能なfreshness属性として保持しなければならない。`score_id` uniquenessにより1 source Scoreから重複projection rowが作られてはならない。
5. Athena ServerはSelected Mods互換性をsource Scoreのactual modsからread-time canonical predicateで導き、derived filter key columnや追加のSelected Mods projection rowを作成してはならない。
6. Historically unconstrainedなstring columnをPostgreSQL Enumへ変換する前に、migrationは既存の非`NULL`値がdestination Enumに含まれることを検証しなければならない。
7. Repository queryとAlembic data migrationはSQLAlchemy Core/ORM式を使用し、textual SQLはPostgreSQL `USING`のようにtextual DDL fragmentを要求するAPIへ限定し、その理由をcall siteへ記録しなければならない。
8. Upgrade時、migrationは有効なGlobal projection dataを保持し、重複するSelected Mods projection rowを削除し、stale-checksum Global rowをcurrent-checksum candidateへ置き換えなければならない。
9. Downgrade時、migrationはcurrent-checksum eligible source Scoresからlegacy Global/Selected Mods projection rowを再構築し、NoMod、NC/DT、PF/SD互換性を復元しなければならない。
10. PostgreSQL integration testsはread-time mod predicates、window ranking、stale-checksum replacement、Enum bind behavior、`upgrade -> downgrade -> upgrade` round tripを検証しなければならない。
