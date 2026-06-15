# Requirements Document

## Introduction

stable-beatmap-file-warmup は、stable client が beatmap を参照する自然な flow の中で `.osu` file attachment を事前準備し、後続の score submission と Performance Calculation が file availability 待ちになりにくくする feature です。

対象 user は stable client player と operator です。Player には既存の stable 互換 response semantics を維持しつつ、getscores、STATUS_CHANGE、score submit fallback の 3 段階で Beatmap File Warmup を発火します。Operator には warmup が発火したか、既に利用可能だったか、発火できなかったかを観測できる状態を提供します。

## Boundary Context

- **In scope**:
  - stable `GET /web/osu-osz2-getscores.php` からの Beatmap File Warmup 発火
  - stable `STATUS_CHANGE` packet からの Beatmap File Warmup 発火
  - stable `POST /web/osu-submit-modular-selector.php` からの fallback Beatmap File Warmup 発火
  - warmup request の idempotency、認証済み入口限定、stable response semantics の維持
  - warmup が発火、skip、既存 file 利用、発火不能になった理由の operator-visible diagnostics

- **Out of scope**:
  - PP 計算、star rating 計算、Performance Calculation state の更新
  - beatmap metadata provider、`.osu` file provider、blob storage backend の取得ロジック変更
  - leaderboard rows、personal best、user stats、rank projection の更新
  - stable response body への warmup 状態追加
  - lazer / WebUI / admin API からの warmup 操作

- **Adjacent expectations**:
  - beatmap-mirror は Beatmap File の取得、検証、attachment availability を提供する
  - score-ingestion は accepted Score と retry / reject semantics を所有する
  - score-pp-calculation は準備済み Beatmap File を Performance Calculation 入力として利用する
  - web-legacy-leaderboard-endpoint は getscores response format を所有し、この feature は response format ではなく warmup side effect を追加する

## Requirements

### Requirement 1: Warmup Scope and Semantics

**Objective:** As a stable client player, I want Athena to prepare beatmap files before score submission, so that later score processing and PP calculation are less likely to wait for file availability.

#### Acceptance Criteria

1. When a stable client references a beatmap through a supported warmup entrance, the Stable Beatmap File Warmup Feature shall request Beatmap File Warmup for the referenced beatmap.
2. When Beatmap File Warmup is requested for a beatmap whose Beatmap File is already available, the Stable Beatmap File Warmup Feature shall treat the request as successful without changing stable client response semantics.
3. When Beatmap File Warmup is requested more than once for the same beatmap, the Stable Beatmap File Warmup Feature shall converge on one effective file preparation outcome.
4. If Beatmap File Warmup cannot identify a beatmap from the stable client input, then the Stable Beatmap File Warmup Feature shall skip file warmup without rejecting the client action solely for that reason.
5. The Stable Beatmap File Warmup Feature shall not calculate PP, update score state, update leaderboard projections, or expose warmup state in stable client response bodies.

### Requirement 2: Getscores Warmup

**Objective:** As a stable client player, I want song select getscores requests to warm up the beatmap file, so that a later play submission has a higher chance of immediate PP calculation readiness.

#### Acceptance Criteria

1. When an authenticated stable client sends a parseable request to `/web/osu-osz2-getscores.php` with a usable beatmap identity, the Stable Beatmap File Warmup Feature shall request Beatmap File Warmup for that beatmap.
2. When a getscores request fails authentication, the Stable Beatmap File Warmup Feature shall not request Beatmap File Warmup.
3. When a getscores request cannot be parsed into a usable beatmap identity, the Stable Beatmap File Warmup Feature shall not request Beatmap File Warmup.
4. When a getscores request produces a known-header response, the Stable Beatmap File Warmup Feature shall keep the stable getscores header response format unchanged.
5. When a getscores request produces unavailable or update-available response, the Stable Beatmap File Warmup Feature shall keep the stable short response format unchanged.
6. If Beatmap File Warmup request fails after a valid getscores request is otherwise handled, then the Stable Beatmap File Warmup Feature shall preserve the getscores response outcome and make the warmup failure operator-visible.

### Requirement 3: STATUS_CHANGE Warmup

**Objective:** As a stable client player, I want changing my play status to a beatmap to warm up that beatmap file, so that the server starts preparation before I submit a score.

#### Acceptance Criteria

1. When an authenticated stable client sends a `STATUS_CHANGE` packet containing a usable beatmap id, the Stable Beatmap File Warmup Feature shall request Beatmap File Warmup for that beatmap.
2. When an authenticated stable client sends a `STATUS_CHANGE` packet containing a usable beatmap checksum but no usable beatmap id, the Stable Beatmap File Warmup Feature shall request Beatmap File Warmup for the beatmap identified by that checksum when it can be resolved.
3. When a `STATUS_CHANGE` packet does not reference a beatmap, the Stable Beatmap File Warmup Feature shall not request Beatmap File Warmup.
4. When a `STATUS_CHANGE` packet references the same beatmap repeatedly, the Stable Beatmap File Warmup Feature shall avoid creating conflicting warmup outcomes.
5. If Beatmap File Warmup cannot be requested from a `STATUS_CHANGE` packet, then the Stable Beatmap File Warmup Feature shall continue processing the client status update without disconnecting the client solely for warmup failure.

### Requirement 4: Score Submit Fallback Warmup

**Objective:** As a stable client player, I want score submit to trigger final beatmap file preparation if earlier warmup did not happen, so that accepted score processing can still progress.

#### Acceptance Criteria

1. When a stable client submits a score for a beatmap that can be resolved and whose Beatmap File is not available, the Stable Beatmap File Warmup Feature shall request Beatmap File Warmup as a fallback.
2. When a stable client submits a score for a beatmap whose Beatmap File is already available, the Stable Beatmap File Warmup Feature shall not require another file fetch before preserving score submission behavior.
3. When score submission is terminally rejected for reasons unrelated to Beatmap File availability, the Stable Beatmap File Warmup Feature shall not convert that terminal reject into a retryable response.
4. When score submission is accepted but Beatmap File Warmup is still pending, the Stable Beatmap File Warmup Feature shall not reject the accepted score solely because the Beatmap File is pending.
5. If Beatmap File Warmup cannot be requested during score submit fallback, then the Stable Beatmap File Warmup Feature shall preserve the score submission outcome and make the warmup failure operator-visible.

### Requirement 5: Security and Abuse Resistance

**Objective:** As an operator, I want warmup to be limited to authenticated stable client activity, so that file fetch work cannot be triggered cheaply by unauthenticated traffic.

#### Acceptance Criteria

1. When a stable warmup entrance lacks valid authentication or active session context, the Stable Beatmap File Warmup Feature shall not request Beatmap File Warmup.
2. When stable client input contains malformed beatmap identity fields, the Stable Beatmap File Warmup Feature shall not request Beatmap File Warmup from those malformed fields.
3. When repeated stable client activity references the same beatmap in a short period, the Stable Beatmap File Warmup Feature shall keep warmup idempotent from the operator perspective.
4. If warmup work is unavailable due to runtime or downstream file preparation failure, then the Stable Beatmap File Warmup Feature shall report the failure without leaking credential values or raw binary payloads.
5. The Stable Beatmap File Warmup Feature shall not make unauthenticated getscores, status change, or submit traffic capable of triggering Beatmap File Warmup.

### Requirement 6: Operator Observability

**Objective:** As an operator, I want to understand whether warmup fired and why it did or did not, so that PP readiness and fetch issues can be diagnosed.

#### Acceptance Criteria

1. When Beatmap File Warmup is requested from getscores, the Stable Beatmap File Warmup Feature shall expose the warmup entrance and beatmap identity in operator-visible diagnostics.
2. When Beatmap File Warmup is requested from `STATUS_CHANGE`, the Stable Beatmap File Warmup Feature shall expose the warmup entrance and beatmap identity in operator-visible diagnostics.
3. When Beatmap File Warmup is requested from score submit fallback, the Stable Beatmap File Warmup Feature shall expose the warmup entrance and beatmap identity in operator-visible diagnostics.
4. When Beatmap File Warmup is skipped because the file is already available, the Stable Beatmap File Warmup Feature shall make the skip reason operator-visible.
5. When Beatmap File Warmup is skipped because no usable beatmap identity is available, the Stable Beatmap File Warmup Feature shall make the skip reason operator-visible without treating it as a client-visible failure.
6. When Beatmap File Warmup request fails, the Stable Beatmap File Warmup Feature shall make the failure reason operator-visible without changing the stable client response body.

### Requirement 7: Compatibility Boundaries

**Objective:** As a stable compatibility maintainer, I want file warmup to preserve existing stable protocol behavior, so that clients continue to interact with Athena as before.

#### Acceptance Criteria

1. When Beatmap File Warmup is added to getscores, the Stable Beatmap File Warmup Feature shall preserve existing getscores authentication, parse, status mapping, and response body behavior.
2. When Beatmap File Warmup is added to `STATUS_CHANGE`, the Stable Beatmap File Warmup Feature shall preserve existing packet parsing and dispatch behavior for other stable packets.
3. When Beatmap File Warmup is added to score submit fallback, the Stable Beatmap File Warmup Feature shall preserve existing score submission idempotency, duplicate online checksum rejection, and duplicate replay checksum rejection.
4. Where future Performance Calculation consumes Beatmap File availability, the Stable Beatmap File Warmup Feature shall provide only preparation behavior and shall not become the source of truth for PP readiness.
5. The Stable Beatmap File Warmup Feature shall keep stable client response bodies free of internal file fetch state, warmup diagnostics, and downstream storage details.
