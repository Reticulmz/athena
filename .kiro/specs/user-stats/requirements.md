# Requirements Document

## Introduction

user-stats は stable client のゲーム内表示に必要な current user stats を返す feature です。対象はログイン直後のメニュー右上、オンラインユーザー一覧、`STATS_REQUEST` 応答で使われる現在値であり、Score と current Performance Calculation から PP、Accuracy、Lv 表示に必要な total score、Global Rank、Play Count、Ranked Score、Total Score、Play Time を取得できる状態にします。

Score submit 時の `ft` (fail time milliseconds) と play time は後から正確に復元しづらいため、UserStats の集計より先に submit 時点の timing 情報を失わないことを prerequisite とします。

## Boundary Context

- **In scope**: score submit から得られる timing 情報の保存、current user stats の取得、stable `USER_STATS` への current stats 出力、login と stats request のゲーム内統合。
- **Out of scope**: 89日間の日別 rank graph、Web API / Web UI、country rank history、PP 計算実行、Replay parsing、Relax / Autopilot stats。
- **Adjacent expectations**: score-ingestion は accepted Score と submit-time timing を提供し、score-pp-calculation は current Performance Calculation を提供します。user-stats はそれらを読み、performance state を変更しません。

## Requirements

### Requirement 1: Submit Timing Preservation

**Objective:** As an operator, I want submit-time timing data to be preserved before stats aggregation, so that play time and failed-play stats do not depend on later reconstruction.

#### Acceptance Criteria

1. When a stable score submission includes `ft`, the Athena Server shall preserve the submitted fail time value with the accepted score.
2. When a stable score submission includes an exit or quit classification, the Athena Server shall preserve that classification with the accepted score.
3. When a stable score submission contains enough timing information to derive play time, the Athena Server shall make nullable `play_time_seconds` available for current stats aggregation.
4. If timing information is absent, malformed, or not enough to derive play time, then the Athena Server shall keep `play_time_seconds` unavailable without rejecting an otherwise valid score.
5. The Athena Server shall not infer precise play time during a later stats read when submit-time timing was not preserved.

### Requirement 2: Current Stats Values

**Objective:** As a stable player, I want my current profile stats to be available in-game, so that the menu and user list show meaningful progress values.

#### Acceptance Criteria

1. When current stats are requested for a known user, the Athena Server shall return PP, accuracy, global rank, play count, ranked score, total score, and nullable play time.
2. When a known user has no accepted score history, the Athena Server shall return zero PP, zero accuracy, zero global rank, zero play count, zero ranked score, zero total score, and unavailable play time.
3. When a stats source is temporarily incomplete, the Athena Server shall return stable-safe default values for unavailable fields without failing the login or stats request flow.
4. The Athena Server shall expose total score consistently enough for the stable client to derive the user's Lv display.
5. The Athena Server shall exclude Relax and Autopilot plays from initial current stats.

### Requirement 3: PP Policy

**Objective:** As a player, I want PP to reflect my best ranked performances, so that in-game stats match the expected osu!-style profile progression.

#### Acceptance Criteria

1. When a user has eligible current Performance Calculations, the Athena Server shall rank the user's best performance values by PP descending before total PP aggregation.
2. The Athena Server shall aggregate at most the top 200 eligible best performance values for current PP.
3. The Athena Server shall apply official-like weighting where the best performance contributes 100 percent and each following performance uses a `0.95 ** index` multiplier.
4. The Athena Server shall use an explicit bonus PP policy rather than hiding bonus behavior inside the weighted PP calculation.
5. If bonus PP compatibility has not been verified, then the Athena Server shall report weighted PP without an unverified bonus component.
6. The Athena Server shall treat current Performance Calculation as the PP source and shall not execute PP calculation while serving UserStats.

### Requirement 4: Accuracy and Score Aggregation Policy

**Objective:** As a player, I want accuracy and score totals to be derived consistently, so that displayed stats are stable across login and request flows.

#### Acceptance Criteria

1. When a user has eligible best performances, the Athena Server shall calculate current accuracy from the same best-performance policy used for PP ordering.
2. If a user has no eligible best performance, then the Athena Server shall return zero accuracy.
3. When total score is aggregated, the Athena Server shall include accepted stable scores according to the score persistence policy.
4. When ranked score is aggregated, the Athena Server shall include only scores that are eligible for ranked score contribution.
5. The Athena Server shall keep failed plays available for play count and play time policy without making them eligible for PP.

### Requirement 5: Global Rank

**Objective:** As a player, I want a current global rank, so that in-game stats show my position relative to other ranked players.

#### Acceptance Criteria

1. When global rank is requested for a user with positive current PP, the Athena Server shall rank the user against other leaderboard-visible users by current PP.
2. If a user has no positive current PP, then the Athena Server shall return global rank as unavailable for stable display.
3. When two users have the same current PP, the Athena Server shall apply a deterministic tie-break policy.
4. The Athena Server shall not create daily rank snapshots as part of current global rank retrieval.

### Requirement 6: Stable Login Stats

**Objective:** As a stable player, I want stats to appear immediately after login, so that the menu and initial roster do not show placeholder values.

#### Acceptance Criteria

1. When a stable login succeeds, the Athena Server shall include current stats for the logged-in user in the login packet stream.
2. When a stable login includes online roster users, the Athena Server shall make current stats available for roster display where stable compatibility requires `USER_STATS`.
3. If current stats cannot be read during login, then the Athena Server shall complete login with stable-safe default stats.
4. The Athena Server shall preserve the existing stable `USER_STATS` wire field meanings when replacing placeholder stats with current values.

### Requirement 7: Stable Stats Request

**Objective:** As a stable player, I want requested online users' stats to update, so that user list and presence details stay current.

#### Acceptance Criteria

1. When the stable client sends a stats request for one or more user ids, the Athena Server shall return current stats packets for users whose stats are available and visible to the requester.
2. If a requested user id is unknown, hidden, or unavailable, then the Athena Server shall avoid returning misleading non-zero stats for that user.
3. When multiple requested user ids are repeated, the Athena Server shall return at most one current stats response per user id.
4. If the stats request payload is malformed, then the Athena Server shall ignore the malformed request without disconnecting the requester.

### Requirement 8: Scope Boundaries and Compatibility

**Objective:** As an operator, I want the UserStats slice to remain focused on in-game current values, so that later Web and historical ranking work can evolve separately.

#### Acceptance Criteria

1. The Athena Server shall not expose Web API or Web UI user stats surfaces as part of this feature.
2. The Athena Server shall not generate rank history graphs or daily snapshots as part of this feature.
3. The Athena Server shall not mutate Performance Calculation state while serving current UserStats.
4. Where stable packet behavior is unclear, the Athena Server shall rely on protocol evidence or focused compatibility tests before changing client-observable packet shapes.
5. When future ranking history or Web profile features need current stats, the Athena Server shall provide current values without making those features own score or performance source data.
