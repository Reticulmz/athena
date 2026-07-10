# Requirements Document

## Introduction

`replay-download-accounting` は Issue #37 の spec である。目的は、Stable client が `GET /web/osu-getreplay.php` から replay download に成功した後、Issue #36 / PR #40 が固定した response bytes、status、headers を変えずに、Replay View Count と viewer user の latest activity を確定 policy に従って更新することである。

この spec は replay download の成功 response を「実視聴開始」ではなく、現時点で確認済みの server-observable consumption signal として扱う。Replay View Count は score-scoped projection とし、self-view、duplicate download、failure branch、accounting failure の扱いを明確にする。

## Boundary Context

- **In scope**: 成功した認証済み `/web/osu-getreplay.php` replay download 後の accounting、score-scoped Replay View Count、self-view no-count policy、viewer/score 単位の duplicate view cooldown、viewer latest activity touch、activity write throttle、failure branch no-update policy、response contract regression verification。
- **Out of scope**: `/web/osu-getreplay.php` の request parsing / auth / replay lookup / storage lookup / response bytes / status / headers の変更、`/web/replays/<id>` alias、download 済み replay の実 playback detection、durable per-download event history、user total replay views の source of truth、anti-cheat、replay frame validation、score submission replay persistence repair。
- **Adjacent expectations**: `replay-download-response` は success response と accounting metadata を提供する。将来 user total replay views が必要になった場合は score-scoped Replay View Count から集計する。将来 Target Stable Client traffic で playback signal が確認された場合は、Replay View Count policy を再検討する。

## Requirements

### Requirement 1: Accounting Trigger and Response Preservation

**Objective:** Stable client 利用者として、replay download の成功 response が accounting side effect によって壊れないことで、#36 の互換 contract のまま replay を取得したい。

#### Acceptance Criteria

1. When an authenticated replay download has a successful replay download response body, the Athena Replay Download Accounting Feature shall evaluate replay accounting after success is known.
2. If replay download authentication fails, the Athena Replay Download Accounting Feature shall not update Replay View Count or latest activity.
3. If replay download returns missing replay, hidden score, storage-missing replay, malformed request, or unavailable replay branch, then the Athena Replay Download Accounting Feature shall not update Replay View Count or latest activity.
4. When replay accounting is evaluated, the Athena Server shall preserve the replay download response status, headers, and body defined by Issue #36.
5. If replay accounting fails partially or completely, then the Athena Server shall still return the original successful replay download response and make the accounting failure operator-observable.
6. The Athena Server shall not expose replay accounting metadata, raw query values, credential values, or failure details in the client-visible replay download response.

### Requirement 2: Score-Scoped Replay View Count

**Objective:** Stable compatibility 保守者として、replay の view count が score 単位で一貫して増えることで、client/operator-visible な replay popularity を user aggregate とは分けて扱いたい。

#### Acceptance Criteria

1. When a counted replay download is accepted, the Athena Replay Download Accounting Feature shall increase the Replay View Count for the target score by one.
2. The Athena Server shall expose Replay View Count as a score-scoped value rather than a user-scoped source of truth.
3. When an existing score has no counted replay download, the Athena Server shall expose Replay View Count as `0`.
4. When a new score is created, the Athena Server shall make Replay View Count available as `0` until counted replay downloads occur.
5. The Athena Server shall not expose Replay View Count as unavailable or null.
6. The Athena Replay Download Accounting Feature shall not require durable per-download event history to compute the initial Replay View Count.
7. Where future user total replay views are needed, the Athena Server shall derive them from score-scoped Replay View Count rather than making this feature own a user-scoped replay view source of truth.

### Requirement 3: Self-View and Duplicate View Policy

**Objective:** 運営者として、owner self-check や repeated download で view count が膨らまないことで、Replay View Count を noisy な raw download count にしないようにしたい。

#### Acceptance Criteria

1. When the score owner successfully downloads their own replay, the Athena Replay Download Accounting Feature shall not increase Replay View Count.
2. When a non-owner viewer successfully downloads a score replay and no duplicate view cooldown applies, the Athena Replay Download Accounting Feature shall count the download as one Replay View Count increment.
3. When the same viewer successfully downloads the same score replay again within the duplicate view cooldown window, the Athena Replay Download Accounting Feature shall not increase Replay View Count.
4. When the same viewer successfully downloads a different score replay, the Athena Replay Download Accounting Feature shall evaluate duplicate view cooldown independently for that score.
5. When a different viewer successfully downloads the same score replay, the Athena Replay Download Accounting Feature shall evaluate duplicate view cooldown independently for that viewer.
6. The Athena Replay Download Accounting Feature shall use a 24-hour duplicate view cooldown window for the same viewer and score pair.
7. If temporary duplicate view cooldown state is lost or unavailable, then the Athena Replay Download Accounting Feature shall prefer preserving replay download success over guaranteeing exact cooldown continuity.
8. The Athena Replay Download Accounting Feature shall not use IP address, session token, or raw replay download query values as the source of truth for duplicate view identity.

### Requirement 4: Latest Activity Touch

**Objective:** Stable client 利用者として、成功した replay download が activity として反映されることで、server-observable stable workflow の利用時刻が不自然に古いままにならないようにしたい。

#### Acceptance Criteria

1. When an authenticated replay download succeeds, the Athena Replay Download Accounting Feature shall make the viewer user eligible for latest activity update.
2. When a successful replay download is a self-view, the Athena Replay Download Accounting Feature shall still make the viewer user eligible for latest activity update.
3. When a successful replay download is suppressed by duplicate view cooldown, the Athena Replay Download Accounting Feature shall still make the viewer user eligible for latest activity update.
4. While the viewer user is within the latest activity throttle window, the Athena Replay Download Accounting Feature shall not require another durable latest activity write for each successful replay download.
5. The Athena Replay Download Accounting Feature shall use a 5-minute latest activity throttle window per viewer user.
6. If temporary latest activity throttle state is lost or unavailable, then the Athena Replay Download Accounting Feature shall prefer preserving replay download success over guaranteeing exact latest activity write spacing.
7. The Athena Replay Download Accounting Feature shall treat latest activity as throttled activity metadata rather than a durable per-download audit log.

### Requirement 5: Accounting Scope Boundaries

**Objective:** 実装担当者と reviewer として、#37 の accounting policy が adjacent replay download / stats / playback work と混ざらないことで、後続 feature が別々に進められる状態にしたい。

#### Acceptance Criteria

1. The Athena Replay Download Accounting Feature shall treat successful replay download as server-observable replay consumption signal without claiming that the Stable client started replay playback.
2. The Athena Replay Download Accounting Feature shall not implement a durable per-download accounting event history.
3. The Athena Replay Download Accounting Feature shall not implement `/web/replays/<id>` alias behavior.
4. The Athena Replay Download Accounting Feature shall not change replay download request parsing, authentication rules, replay lookup, storage lookup, response status, response headers, or response body strategy.
5. Where future Target Stable Client evidence confirms a replay playback signal, the Athena Replay Download Accounting Feature shall mark Replay View Count policy as requiring revalidation before changing count semantics.
6. Where future user-stats work needs total replay views per user, the Athena Server shall allow that work to aggregate from score-scoped Replay View Count without changing #37 response behavior.

### Requirement 6: Verification and Operator Observability

**Objective:** Reviewer と運営者として、Replay View Count と latest activity の更新が説明可能であることで、count regression や response contract regression を検出したい。

#### Acceptance Criteria

1. When implementation is reviewed, the Athena Replay Download Accounting Feature shall provide verification for successful non-owner replay download incrementing Replay View Count once.
2. When implementation is reviewed, the Athena Replay Download Accounting Feature shall provide verification that self-view does not increment Replay View Count.
3. When implementation is reviewed, the Athena Replay Download Accounting Feature shall provide verification that duplicate view cooldown suppresses repeated same-viewer same-score increments within 24 hours.
4. When implementation is reviewed, the Athena Replay Download Accounting Feature shall provide verification that latest activity is eligible for update on successful replay download, self-view, and duplicate cooldown hit.
5. When implementation is reviewed, the Athena Replay Download Accounting Feature shall provide verification that latest activity throttle avoids requiring durable writes for every successful replay download within 5 minutes.
6. When implementation is reviewed, the Athena Replay Download Accounting Feature shall provide verification that auth failure, missing replay, hidden score, storage-missing replay, and malformed/unavailable branches do not update Replay View Count or latest activity.
7. When implementation is reviewed, the Athena Replay Download Accounting Feature shall provide regression verification that accounting success or failure does not change Issue #36 response bytes, status, or headers.
8. If Replay View Count update fails or latest activity update fails, then the Athena Replay Download Accounting Feature shall make the failed side effect distinguishable to operators without exposing raw replay payloads, raw query values, credential values, or local artifact paths.
