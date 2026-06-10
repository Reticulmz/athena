# Requirements Document

## Introduction

Athena には osu! stable client から送信される gameplay score を受け付ける stable-compatible score submission pipeline が必要である。現在は login、beatmap metadata resolution、`.osu` file fetch、`/web/osu-osz2-getscores.php` の header response までは存在するが、play 後の score submission、replay 保存、PP 計算、beatmap leaderboard rows、user stats 反映、client retry への idempotent response は未実装である。

この仕様は `score-submission` として、`POST /web/osu-submit-modular-selector.php` を中心に stable score submission を受け付け、認証済み gameplay result を保存し、score / replay / PP / leaderboard / user stats / getscores score rows に反映する。対象は vanilla play の `osu`、`taiko`、`catch`、`mania` であり、Relax と Autopilot は将来拡張できる軸を予約するが、実際の RX/AP scoring と detection は含めない。

## Boundary Context

- **In scope**:
  - osu web domain 上の stable client 向け `POST /web/osu-submit-modular-selector.php`。
  - observed modular multipart request shape の受け付け、検証、credential redaction。
  - password-md5 credential、active bancho session、decrypted payload identity を組み合わせた score submit authorization。
  - valid gameplay result、failed play、replay body、client retry dedupe、submission result snapshot の保存。
  - all four vanilla rulesets の score validation、accuracy、grade、rank category、PP、best score、leaderboard、user stats 更新。
  - `GET /web/osu-osz2-getscores.php` に score rows と personal/user-visible score state を表示するための score data 提供。
  - getscores、STATUS_CHANGE、score submit fallback による `.osu` file availability 改善。
  - stable-compatible completed、accepted-pending、retryable failure、terminal reject responses。

- **Out of scope**:
  - Relax / Autopilot の実際の scoring、detection、leaderboard 表示。
  - anti-cheat 判定、replay frame validation、cheat investigation workflow。
  - replay download / playback endpoints。
  - Friends leaderboard filtering と social graph。
  - legacy non-modular score submit endpoints。
  - score submission 完了後の proactive S2C notification。
  - Web-only Loved PP/rank の実装。
  - formula migration UI、管理 CLI、manual recalculation command。

- **Adjacent expectations**:
  - `beatmap-mirror` は beatmap metadata、effective status、`.osu` file attachment availability を提供する。
  - `web-legacy-leaderboard-endpoint` は getscores request parsing と header response を提供し、この feature は score rows と score-aware behavior を追加する。
  - `presence-status` は将来 STATUS_CHANGE の完全な状態配信と RX/AP detection を所有するが、この feature は `.osu` prefetch に必要な最小限の signal consumption だけを扱う。
  - `blob-storage` は replay body と `.osu` file body の binary storage を提供する。
  - `roadmap.md` はこの feature から外した後続機能を追跡する。

## Requirements

### Requirement 1: Stable Submit Endpoint Scope

**Objective:** As a stable client user, I want completed plays to be submitted through the expected legacy endpoint, so that Athena records gameplay instead of silently losing play results.

#### Acceptance Criteria

1. When a stable client sends a score submission to `/web/osu-submit-modular-selector.php` on the osu web domain, the Score Submission Feature shall process the request as a stable modular score submission.
2. If a score submission is sent to a non-osu web domain, then the Score Submission Feature shall not require a fallback route for this feature.
3. The Score Submission Feature shall support submitted gameplay results for `osu`, `taiko`, `catch`, and `mania`.
4. The Score Submission Feature shall reserve score identity dimensions for future Relax and Autopilot playstyles without exposing RX/AP behavior as supported gameplay.
5. The Score Submission Feature shall not implement legacy non-modular score submission endpoints in this feature.

### Requirement 2: Multipart Request Compatibility

**Objective:** As a stable compatibility maintainer, I want Athena to accept observed stable modular submit shapes, so that real stable clients can submit scores without request-shape mismatches.

#### Acceptance Criteria

1. When a score submission contains the observed fields `x`, `ft`, duplicate `score`, `fs`, `bmk`, `sbk`, `c1`, `st`, `pass`, `osuver`, `s`, `i`, `iv`, or `token`, the Score Submission Feature shall preserve each field's compatibility meaning for parsing, validation, redaction, or future audit according to the finalized compatibility evidence.
2. When duplicate `score` fields are present, the Score Submission Feature shall distinguish the encrypted score payload field from the replay/binary payload field according to stable-compatible decoding rules.
3. If required identity, credential, score payload, or replay payload fields are missing, then the Score Submission Feature shall return a terminal rejection that does not create a leaderboard-visible score.
4. If optional opaque fields are present but not needed for initial scoring, then the Score Submission Feature shall retain, hash, redact, or ignore them according to the documented storage policy rather than logging raw credential-like data.
5. If request text fields, binary fields, multipart part count, or total upload size exceed configured safety limits, then the Score Submission Feature shall reject the submission without storing a leaderboard-visible score.
6. The Score Submission Feature shall make malformed multipart, oversized payload, and unknown-field conditions observable to operators without exposing credential material.

### Requirement 3: Score Submission Authorization

**Objective:** As an operator, I want score submissions tied to authenticated active sessions, so that forged web requests cannot submit scores for other users.

#### Acceptance Criteria

1. When a score submission contains valid password-md5 credential material for a user with an active bancho session, the Score Submission Feature shall authorize the request only if the decrypted payload identity matches that same user.
2. If the password credential is missing, invalid, or belongs to a different user than the decrypted score payload, then the Score Submission Feature shall reject the submission.
3. If the user has no active bancho session, then the Score Submission Feature shall reject the submission.
4. If a `token` field or token-like value is present, then the Score Submission Feature shall not treat it as sufficient authorization by itself.
5. While authorization fails, the Score Submission Feature shall not disclose beatmap status, leaderboard placement, PP, or other score-processing diagnostics in the client response.
6. The Score Submission Feature shall not persist or log raw password credential material.

### Requirement 4: Gameplay Result Persistence

**Objective:** As a player, I want submitted plays to be stored reliably, so that successful submissions survive retries, processing delays, and later leaderboard rebuilds.

#### Acceptance Criteria

1. When an authenticated score submission contains a valid decrypted gameplay result, the Score Submission Feature shall store the gameplay result as a score record.
2. When an authenticated score submission contains a replay body, the Score Submission Feature shall store the replay body as score replay data unless the submission is terminally rejected before replay persistence.
3. When a score is stored, the Score Submission Feature shall preserve the submitted beatmap identity, user identity, ruleset, mods, score value, max combo, hit counts, pass/fail state, grade, client version signal, and submitted-at time when available.
4. When a score is stored, the Score Submission Feature shall record the beatmap's effective status and score category at submission time.
5. If a valid gameplay result is a failed play, then the Score Submission Feature shall store it as a gameplay result while excluding it from PP, best score, and leaderboard eligibility.
6. If a gameplay result cannot be decrypted or validated enough to identify user, beatmap, ruleset, score, and pass/fail state, then the Score Submission Feature shall not store it as a valid score record.

### Requirement 5: Idempotent Retry Handling

**Objective:** As a stable client user, I want retries after network or processing delays to produce consistent results, so that duplicate client submissions do not create duplicate scores.

#### Acceptance Criteria

1. When the same canonical score submission is received more than once, the Score Submission Feature shall identify it as the same submission.
2. When a duplicate submission is received after processing completed, the Score Submission Feature shall return the same completed submission result as the original submission.
3. When a duplicate submission is received while processing is still pending, the Score Submission Feature shall return a stable-compatible pending or retryable response without creating another score.
4. If two distinct submissions have different gameplay identity or score content, then the Score Submission Feature shall not collapse them solely because their raw multipart bodies are similar.
5. The Score Submission Feature shall retain enough structured submission result data to rebuild stable-compatible retry responses after the initial request has ended.

### Requirement 6: Bounded Processing Response

**Objective:** As a stable client user, I want score submission responses to complete predictably, so that the client can handle success, retry, or failure states correctly.

#### Acceptance Criteria

1. When score processing completes within the configured bounded wait, the Score Submission Feature shall return a stable-compatible completed response.
2. When score processing remains incomplete after the configured bounded wait, the Score Submission Feature shall return a stable-compatible accepted-pending response.
3. If score processing fails due to a temporary dependency condition, then the Score Submission Feature shall return a retryable failure response when stable compatibility requires the client to retry.
4. If score processing fails due to invalid credentials, malformed payload, unsupported ruleset, or terminal validation failure, then the Score Submission Feature shall return a terminal reject response.
5. The Score Submission Feature shall distinguish completed, accepted-pending, retryable failure, and terminal reject outcomes in operator-visible diagnostics.

### Requirement 7: Beatmap Eligibility and Status Rules

**Objective:** As an operator, I want score effects to follow beatmap status rules, so that rankings and statistics reflect only eligible beatmaps.

#### Acceptance Criteria

1. When a passed score is submitted on a Ranked or Approved beatmap, the Score Submission Feature shall make it eligible for ranked PP, ranked user stats, global rank, country rank, best score, and beatmap leaderboard.
2. When a passed score is submitted on a Loved beatmap, the Score Submission Feature shall make it eligible for beatmap leaderboard only and shall exclude it from game-visible PP, global rank, country rank, and ranked user stats.
3. When a score is submitted on a Qualified beatmap, the Score Submission Feature shall apply the finalized compatibility rule for leaderboard and PP eligibility documented before design approval.
4. When a score is submitted on Pending, WIP, Graveyard, NotSubmitted, or Unknown beatmap status, the Score Submission Feature shall apply the finalized compatibility rule for storage and visibility documented before design approval.
5. When a beatmap status changes after submission, the Score Submission Feature shall preserve the original score record and shall make current leaderboard and user-stat projections reflect the beatmap's current effective eligibility.
6. If a beatmap is no longer ranked-eligible, then the Score Submission Feature shall exclude its scores from current ranked PP and ranking projections.

### Requirement 8: Score Validation, Accuracy, and Grade

**Objective:** As a leaderboard viewer, I want submitted score values to be normalized by server-side rules, so that leaderboard and user stats are not based solely on client-reported summaries.

#### Acceptance Criteria

1. When a score payload includes hit counts, combo, mods, score value, pass/fail state, or client-reported accuracy/grade, the Score Submission Feature shall validate the submitted values against ruleset-specific expectations.
2. When a valid score is processed, the Score Submission Feature shall calculate accuracy from server-trusted hit counts, ruleset, mods, and pass/fail state.
3. When a valid score is processed, the Score Submission Feature shall calculate grade from server-trusted score data and ruleset-specific grade rules.
4. If client-reported accuracy or grade differs from server-calculated values, then the Score Submission Feature shall preserve the discrepancy for operator visibility without using the client value as authoritative.
5. If a score's hit counts or ruleset-specific values are internally inconsistent, then the Score Submission Feature shall reject the score or store it as non-leaderboard-visible according to the finalized compatibility rule.

### Requirement 9: Performance Calculation and Provenance

**Objective:** As a player, I want eligible scores to receive PP consistently, so that ranking and user stats are explainable and recalculable.

#### Acceptance Criteria

1. When a passed score is eligible for PP, the Score Submission Feature shall calculate PP and star rating from the score data and matching `.osu` file.
2. When PP or star rating is calculated, the Score Submission Feature shall record enough provenance to identify the formula profile, calculator source, beatmap file attachment, and calculation time.
3. If the required `.osu` file is unavailable during processing, then the Score Submission Feature shall request file availability and return a stable-compatible pending or retryable response according to the processing outcome.
4. If PP cannot be calculated for a score that is otherwise valid, then the Score Submission Feature shall store the score without awarding ranked PP until recalculation succeeds.
5. The Score Submission Feature shall exclude failed plays and non-PP-eligible beatmap categories from PP awards.

### Requirement 10: Beatmap Leaderboard Rows

**Objective:** As a player viewing song select, I want submitted scores to appear in beatmap leaderboards, so that the server displays competitive results after plays are submitted.

#### Acceptance Criteria

1. When getscores requests a beatmap with leaderboard-eligible scores, the Score Submission Feature shall provide score rows for that beatmap.
2. When beatmap leaderboard rows are produced, the Score Submission Feature shall order rows by score descending for the relevant ruleset, playstyle, category, and filtering controls.
3. When a user has a leaderboard-visible score on the requested beatmap, the Score Submission Feature shall expose the user's relevant personal score state where stable getscores compatibility expects it.
4. If PP display is supported by the stable response format used by Athena, then the Score Submission Feature shall include PP display metadata for score rows that have calculated PP.
5. If PP display is not supported by the finalized stable response format, then the Score Submission Feature shall keep PP stored internally without corrupting the stable response.
6. While Friends leaderboard filtering is unsupported, the Score Submission Feature shall not claim to provide Friends-filtered leaderboard results.
7. Where Country leaderboard filtering is supported by stable compatibility evidence, the Score Submission Feature shall filter leaderboard rows by the submitting user's country.

### Requirement 11: Best Score and Score Replacement

**Objective:** As a player, I want my best score state to update predictably, so that personal bests and leaderboard placement match stable expectations.

#### Acceptance Criteria

1. When a user submits a passed leaderboard-eligible score that beats their previous best for the same beatmap, ruleset, playstyle, and category, the Score Submission Feature shall update the user's best score projection.
2. When a user submits a passed leaderboard-eligible score that does not beat their previous best for the same beatmap, ruleset, playstyle, and category, the Score Submission Feature shall preserve the previous best score projection.
3. When a score is failed or non-leaderboard-eligible, the Score Submission Feature shall not replace the user's best score projection.
4. When score replacement affects leaderboard position, the Score Submission Feature shall make the updated position visible through subsequent leaderboard requests.
5. If a previous best becomes ineligible because beatmap status changes, then the Score Submission Feature shall recalculate best score projections from currently eligible scores.

### Requirement 12: User Statistics and Rankings

**Objective:** As a player, I want submitted scores to update my visible stats, so that login stats and rankings reflect gameplay progress.

#### Acceptance Criteria

1. When a valid gameplay result is stored, the Score Submission Feature shall update play count according to the finalized failed-play and status eligibility rules.
2. When a valid gameplay result has reliable play duration, the Score Submission Feature shall update play time according to the finalized duration source rule.
3. When a valid gameplay result is stored, the Score Submission Feature shall update total score according to the finalized stable-compatible rule.
4. When a passed score is ranked-eligible, the Score Submission Feature shall update ranked score, weighted PP, accuracy, global rank, and country rank for the relevant user, ruleset, playstyle, and category.
5. When a Loved score is processed, the Score Submission Feature shall not update game-visible ranked PP, global rank, country rank, or ranked user stats.
6. When a user's stats change, the Score Submission Feature shall make subsequent login/user-stats packets reflect the updated stats.
7. The Score Submission Feature shall maintain independent stats for each supported ruleset and reserved playstyle/category dimension.

### Requirement 13: Failed Play Behavior

**Objective:** As a player, I want failed plays to be recorded consistently, so that play history and basic activity stats are not lost while rankings remain fair.

#### Acceptance Criteria

1. When a failed gameplay result is authenticated and validly decoded, the Score Submission Feature shall store it as a failed score record.
2. When a failed gameplay result includes replay data, the Score Submission Feature shall store the replay data subject to the same safety limits as passed replays.
3. When a failed play is stored, the Score Submission Feature shall exclude it from PP, best score, beatmap leaderboard rows, global rank, and country rank.
4. When a failed or exited play is authenticated and validly decoded, the Score Submission Feature shall derive play time from `ft` by converting milliseconds to seconds, subject to configured sanity limits.
5. When failed play statistics are finalized from compatibility evidence, the Score Submission Feature shall apply those rules to play count, play time, and total score.
6. If failed play behavior differs across existing stable-compatible implementations, then the Score Submission Feature shall document Athena's selected behavior before design approval.

### Requirement 14: `.osu` File Availability

**Objective:** As an operator, I want score processing to have the matching `.osu` file available before PP calculation, so that score submissions do not fail solely because file fetch was late.

#### Acceptance Criteria

1. When getscores resolves a known beatmap, the Score Submission Feature shall request `.osu` file availability without delaying the stable header response beyond the configured getscores behavior.
2. When a STATUS_CHANGE packet identifies a beatmap by id or checksum, the Score Submission Feature shall request `.osu` file availability for that beatmap when enough identity is present.
3. When a score submission needs a `.osu` file that is missing, the Score Submission Feature shall request file availability and wait only within the configured submit response budget.
4. If `.osu` file fetching remains pending after the response budget, then the Score Submission Feature shall keep the submission pending or retryable rather than terminally rejecting an otherwise valid score.
5. If `.osu` file fetching fails definitively for a PP-eligible score, then the Score Submission Feature shall make the score's processing state observable to operators and preserve retry/recalculation ability where appropriate.

### Requirement 15: Security, Privacy, and Observability

**Objective:** As an operator, I want score submission to be diagnosable without leaking secrets, so that production issues can be investigated safely.

#### Acceptance Criteria

1. When score submission authentication fails, the Score Submission Feature shall log a non-secret failure reason and shall not log raw password-md5 material.
2. When request parsing, replay storage, beatmap resolution, PP calculation, leaderboard update, or user stats update fails, the Score Submission Feature shall make the failure category observable to operators.
3. If opaque request fields are retained for audit, then the Score Submission Feature shall store them according to a documented redaction, hash, or blob policy.
4. If a submitted replay or opaque field exceeds retention policy or safety limits, then the Score Submission Feature shall reject or quarantine it according to the finalized policy.
5. The Score Submission Feature shall not expose internal diagnostics, raw opaque fields, credential material, or storage identifiers in stable client responses.

### Requirement 16: Compatibility Research and Validation Evidence

**Objective:** As a maintainer, I want score submission behavior backed by stable-compatible evidence, so that Athena does not lock in guessed wire behavior.

#### Acceptance Criteria

1. The Score Submission Feature shall document compatibility findings for request decoding, duplicate `score` multipart handling, response formats, retry behavior, failed score behavior, Loved behavior, Qualified behavior, raw field storage policy, and score/user-stat schema expectations before design approval.
2. The Score Submission Feature shall compare at least Akatsuki/bancho.py, osuRipple/lets, and osuTitanic/deck where accessible for stable score submission behavior before design approval.
3. The Score Submission Feature shall document the selected behavior when reference implementations disagree or official stable behavior is unavailable before design approval.
4. The Score Submission Feature shall validate stable request parsing and response formatting with fixtures or captured-compatible examples before implementation completion.
5. If compatibility evidence proves a requirement's behavior incorrect, then the Score Submission Feature shall update the requirement or explicitly document the deviation before design or implementation proceeds.
