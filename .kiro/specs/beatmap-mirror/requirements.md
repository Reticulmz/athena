# Requirements Document

## Introduction

Athena needs a shared beatmap metadata and `.osu` file resolution capability before score submission, leaderboard, rank management, WebUI, and future lazer workflows can rely on beatmap state safely. Score processing depends on beatmap identity, checksum verification, ranked status, leaderboard eligibility, and access to the `.osu` file for PP and star rating calculation.

This specification defines the behavior expected from the Beatmap Mirror Service: cache-first beatmap and beatmapset lookup, authoritative osu! API status handling, mirror fallback semantics, `.osu` file availability through blob storage, official-versus-local status separation, eligibility projection for downstream scoring, and clear boundaries around score processing and rank-management workflows.

## Boundary Context

- **In scope**:
  - Beatmap and beatmapset metadata resolution.
  - Lookup by beatmap id, beatmapset id, and checksum/md5.
  - Cache-first responses for known beatmaps.
  - osu! API as the authoritative source for official beatmap status.
  - Mirror fallback behavior when API sources are unavailable.
  - Official or legacy `.osu` file download before community mirror fallback.
  - Configurable community mirror URLs for last-resort `.osu` file fallback.
  - Configurable mirror trust behavior for operators.
  - `.osu` file attachment behavior using the shared blob storage capability.
  - Official status, local override status, and effective status semantics.
  - Eligibility results for score submission and leaderboard decisions.
  - Fetch state reporting for callers and operators.

- **Out of scope**:
  - Score submission payload parsing.
  - Score persistence, pending score retry, PP calculation, and leaderboard updates.
  - Bancho score result response formatting.
  - WebUI screens for requests or rank changes.
  - BanchoBot request and rank commands.
  - Rank request queues and approval workflow.
  - Replay, screenshot, or image upload behavior.
  - Final database schema and provider adapter design details.

- **Adjacent expectations**:
  - `blob-storage` stores `.osu` file bodies; this feature owns beatmap-specific file attachment behavior.
  - `score-submission` persists score payloads before asynchronous processing and consumes beatmap eligibility from this feature.
  - `beatmap-rank-management` owns permissioned local rank changes and must not bypass the status semantics defined here.
  - `web-ui` and BanchoBot features may expose request or rank controls later, but they consume this feature instead of duplicating beatmap status rules.

## Requirements

### Requirement 1: Beatmap Metadata Resolution

**Objective:** As a score or leaderboard feature, I want beatmaps to resolve by the identifiers clients provide, so that downstream workflows can validate plays against the correct beatmap.

#### Acceptance Criteria

1. When a caller resolves a beatmap by beatmap id, the Beatmap Mirror Service shall return the matching beatmap metadata when it is known.
2. When a caller resolves a beatmapset by beatmapset id, the Beatmap Mirror Service shall return the beatmapset metadata and its known beatmaps when they are known.
3. When a caller resolves a beatmap by checksum/md5, the Beatmap Mirror Service shall return the matching beatmap metadata when the checksum is known.
4. If the requested beatmap or beatmapset is unknown, then the Beatmap Mirror Service shall report that fetching is pending or failed rather than returning unrelated beatmap data.
5. The Beatmap Mirror Service shall expose enough beatmap identity data for downstream callers to distinguish beatmap id, beatmapset id, checksum/md5, game mode, and difficulty identity.

### Requirement 2: Cache-First Behavior

**Objective:** As a caller, I want known beatmaps to resolve without unnecessary external dependency, so that score and leaderboard workflows remain responsive.

#### Acceptance Criteria

1. When a caller requests a known and usable beatmap record, the Beatmap Mirror Service shall return the cached result synchronously.
2. When a cached record is missing required metadata, the Beatmap Mirror Service shall report the missing state and request a refresh.
3. When a cached record is stale according to its status freshness rules, the Beatmap Mirror Service shall return the best available cached data and request a refresh.
4. When a caller requests bounded waiting for a missing or stale record, the Beatmap Mirror Service shall wait no longer than the caller's requested limit.
5. If bounded waiting expires before the requested data becomes usable, then the Beatmap Mirror Service shall return a pending fetch result.

### Requirement 3: Authoritative Source Priority

**Objective:** As an operator, I want official osu! API data to be authoritative, so that ranked status and eligibility are not silently determined by fallback sources.

#### Acceptance Criteria

1. When official osu! API data is available, the Beatmap Mirror Service shall treat that data as authoritative for official beatmap status.
2. If the primary official source is unavailable and another official source is available, then the Beatmap Mirror Service shall use the available official source before using a mirror source.
3. If all official sources are unavailable and a mirror source can provide beatmap data, then the Beatmap Mirror Service shall mark the result as mirror-sourced and unverified.
4. When a mirror-sourced record is accessed later and official sources are available, the Beatmap Mirror Service shall request an official refresh.
5. The Beatmap Mirror Service shall expose the source and verification state of returned metadata to callers.

### Requirement 4: Provider Configuration Expectations

**Objective:** As an operator, I want external beatmap sources to be explicitly configured, so that development and production do not accidentally run with incomplete source credentials.

#### Acceptance Criteria

1. When official beatmap sources are enabled in development or production, the Beatmap Mirror Service shall require the configuration needed to access those sources.
2. If required official source configuration is missing while official sources are enabled, then the Beatmap Mirror Service shall report a configuration error before accepting source-dependent operations.
3. Where fallback sources are enabled, the Beatmap Mirror Service shall make their availability observable to operators.
4. Where tests use fake beatmap sources, the Beatmap Mirror Service shall allow source-dependent behavior to be exercised without real external credentials.
5. Where a community mirror is configured for last-resort `.osu` file fallback, the Beatmap Mirror Service shall accept an operator-provided mirror URL configuration.
6. If a configured community mirror URL is invalid or incomplete, then the Beatmap Mirror Service shall report a configuration error before using it for file fallback.

### Requirement 5: Mirror Trust Policy

**Objective:** As an operator, I want mirror-derived status trust to be configurable, so that deployments can choose between safety and availability during upstream outages.

#### Acceptance Criteria

1. While mirror status trust is disabled, the Beatmap Mirror Service shall not use mirror-derived status to grant leaderboard or PP eligibility.
2. Where mirror status trust is explicitly enabled, the Beatmap Mirror Service shall allow mirror-derived status to contribute to effective eligibility.
3. When a returned result depends on mirror-derived status, the Beatmap Mirror Service shall expose that the result is mirror-derived.
4. The Beatmap Mirror Service shall default to treating mirror-derived status as unverified for eligibility.

### Requirement 6: `.osu` File Availability

**Objective:** As a score processing feature, I want `.osu` files to be attached and verified, so that PP and star rating calculations can use the correct beatmap body.

#### Acceptance Criteria

1. When a caller requests a beatmap that requires a `.osu` file and the file is already available, the Beatmap Mirror Service shall report the file as available.
2. When a caller requests a beatmap that requires a `.osu` file and the file is missing, the Beatmap Mirror Service shall request file fetching and report the file as pending.
3. When a `.osu` file body is fetched, the Beatmap Mirror Service shall verify it against the expected beatmap checksum before making it available.
4. If a fetched `.osu` file does not match the expected checksum, then the Beatmap Mirror Service shall reject that file attachment and report a file failure.
5. The Beatmap Mirror Service shall store `.osu` file bodies through the shared blob storage capability rather than embedding file bodies in beatmap metadata.
6. When a `.osu` file must be fetched, the Beatmap Mirror Service shall prefer official or legacy osu! file sources before community mirror sources.
7. If official or legacy `.osu` file sources are unavailable and a community mirror file source is configured, then the Beatmap Mirror Service shall allow the `.osu` file fetch to fall back to the configured community mirror.
8. When a `.osu` file is fetched from a community mirror, the Beatmap Mirror Service shall expose the file source as mirror-derived.
9. If official or legacy `.osu` file sources are temporarily unavailable due to rate limiting, timeout, or server failure, then the Beatmap Mirror Service shall treat the direct file source as unavailable for fallback purposes.
10. If `.osu` file retrieval from direct file sources is unavailable and an archive-based fallback is supported in a future scope, then the Beatmap Mirror Service shall verify the extracted `.osu` file against the expected checksum before making it available.

### Requirement 7: Fetch State Reporting

**Objective:** As a downstream caller, I want beatmap results to include fetch state, so that each workflow can decide whether to proceed, wait, retry, or show pending state.

#### Acceptance Criteria

1. When the Beatmap Mirror Service returns beatmap metadata, it shall include whether metadata is fresh, stale, pending fetch, or failed.
2. When the Beatmap Mirror Service returns beatmap file state, it shall include whether the `.osu` file is available, pending fetch, missing, or failed.
3. When a fetch attempt fails, the Beatmap Mirror Service shall expose the failure state without replacing known valid data with unrelated data.
4. The Beatmap Mirror Service shall expose last fetch and next refresh timing when that information is known.
5. The Beatmap Mirror Service shall make pending and failed states distinguishable to callers.

### Requirement 8: Status Freshness Rules

**Objective:** As an operator, I want beatmap status refresh behavior to reflect how likely each status is to change, so that stable statuses do not create unnecessary external load and mutable statuses can update.

#### Acceptance Criteria

1. While a beatmap is effectively Ranked, Approved, or Loved, the Beatmap Mirror Service shall treat its status as stable unless an explicit refresh is requested or policy marks it stale.
2. While a beatmap is effectively Qualified, Pending, or WIP, the Beatmap Mirror Service shall consider it eligible for periodic refresh because it may become Ranked.
3. While a beatmap is effectively Graveyard, the Beatmap Mirror Service shall refresh it less frequently than Pending-like statuses.
4. When a beatmap status changes after refresh, the Beatmap Mirror Service shall expose the updated effective status to downstream callers.
5. The Beatmap Mirror Service shall not require a memory cache for correct freshness behavior.

### Requirement 9: Official Status and Local Override

**Objective:** As a rank management workflow, I want official status and local override status to remain separate, so that local operations are not overwritten by upstream refreshes.

#### Acceptance Criteria

1. The Beatmap Mirror Service shall distinguish official status from local override status.
2. The Beatmap Mirror Service shall expose an effective status derived from official status and local override status.
3. When official metadata is refreshed, the Beatmap Mirror Service shall update official status without removing an existing local override.
4. When local override status is absent, the Beatmap Mirror Service shall derive effective status from official status.
5. When local override status is present, the Beatmap Mirror Service shall derive effective status according to the local override rules.

### Requirement 10: Approved Status Handling

**Objective:** As an operator, I want legacy Approved maps to remain representable without allowing new manual Approved assignments, so that compatibility and moderation policy stay aligned.

#### Acceptance Criteria

1. When official source data identifies a beatmap as Approved, the Beatmap Mirror Service shall preserve Approved as an official status.
2. When eligibility is evaluated for an Approved beatmap, the Beatmap Mirror Service shall treat Approved the same as Ranked for leaderboard and ranked PP eligibility.
3. If a local rank change attempts to assign Approved, then the Beatmap Mirror Service shall reject that local override value.
4. The Beatmap Mirror Service shall keep Approved distinguishable from Ranked in returned status data.

### Requirement 11: Score Eligibility Projection

**Objective:** As a score submission feature, I want a beatmap eligibility projection, so that scoring logic can avoid duplicating beatmap status rules.

#### Acceptance Criteria

1. When eligibility is requested for a beatmap, the Beatmap Mirror Service shall return whether the beatmap accepts scores.
2. When eligibility is requested for a beatmap, the Beatmap Mirror Service shall return whether the beatmap has an online leaderboard.
3. When eligibility is requested for a beatmap, the Beatmap Mirror Service shall return whether the beatmap awards ranked PP.
4. When eligibility is requested for a beatmap, the Beatmap Mirror Service shall return whether the beatmap awards loved PP.
5. When eligibility is requested for a beatmap, the Beatmap Mirror Service shall return whether the beatmap requires a `.osu` file for PP-related processing.
6. When eligibility is requested for a beatmap, the Beatmap Mirror Service shall return whether the eligibility is officially verified.

### Requirement 12: Initial Eligibility Rules

**Objective:** As a leaderboard feature, I want consistent initial eligibility rules, so that beatmap status drives score acceptance and PP behavior predictably.

#### Acceptance Criteria

1. While a beatmap is effectively Ranked or Approved, the Beatmap Mirror Service shall mark it as accepting scores, having a leaderboard, and awarding ranked PP.
2. While a beatmap is effectively Loved, the Beatmap Mirror Service shall mark it as accepting scores, having a leaderboard, and awarding loved PP without awarding ranked PP.
3. While a beatmap is effectively Qualified, the Beatmap Mirror Service shall mark it as accepting scores and having a leaderboard without awarding ranked or loved PP.
4. While a beatmap is effectively Pending, WIP, Graveyard, NotSubmitted, or Unknown, the Beatmap Mirror Service shall not mark it as accepting scores, having a leaderboard, or awarding PP.
5. While a beatmap's effective eligibility depends only on untrusted mirror status, the Beatmap Mirror Service shall not grant score, leaderboard, or PP eligibility.

### Requirement 13: Failed Score Eligibility

**Objective:** As a score submission feature, I want failed-score eligibility to be explicit, so that total score behavior can be implemented without polluting leaderboard or PP results.

#### Acceptance Criteria

1. When a failed score is submitted for a beatmap that accepts scores, the Beatmap Mirror Service shall indicate that the beatmap is eligible for failed score storage.
2. When a failed score is submitted for a beatmap that does not accept scores, the Beatmap Mirror Service shall indicate that the beatmap is not eligible for failed score storage.
3. The Beatmap Mirror Service shall not mark failed scores as leaderboard eligible.
4. The Beatmap Mirror Service shall not mark failed scores as best-score, ranked PP, or loved PP eligible.

### Requirement 14: Fetch Job Idempotency

**Objective:** As an operator, I want repeated lookup and refresh requests to be safe, so that concurrent score and WebUI activity does not create conflicting beatmap states.

#### Acceptance Criteria

1. When multiple callers request the same missing beatmap, the Beatmap Mirror Service shall avoid exposing duplicate conflicting results.
2. When multiple callers request the same missing `.osu` file, the Beatmap Mirror Service shall avoid exposing duplicate conflicting file attachments.
3. If a fetch is already pending for a requested beatmap, then the Beatmap Mirror Service shall report the existing pending state to callers.
4. When a repeated fetch completes with the same verified data, the Beatmap Mirror Service shall keep the beatmap result consistent for callers.

### Requirement 15: Downstream Boundary

**Objective:** As a feature owner, I want beatmap resolution to be separated from score and rank workflows, so that downstream features can evolve without duplicating beatmap source rules.

#### Acceptance Criteria

1. The Beatmap Mirror Service shall not parse score submission payloads.
2. The Beatmap Mirror Service shall not calculate PP, update leaderboards, or format Bancho score result responses.
3. The Beatmap Mirror Service shall not own rank request queues, request approvals, BanchoBot rank commands, or WebUI rank screens.
4. When downstream features need beatmap status, file state, or eligibility, the Beatmap Mirror Service shall provide those results through its own beatmap resolution behavior.
5. When downstream features need to change local rank status, they shall use the local override semantics exposed by this feature rather than changing official status.

### Requirement 16: Observability and Operator Feedback

**Objective:** As an operator, I want source, refresh, and file failures to be visible, so that beatmap-dependent score issues can be diagnosed.

#### Acceptance Criteria

1. When a source lookup succeeds, the Beatmap Mirror Service shall make the selected source observable to diagnostics.
2. When all configured sources fail, the Beatmap Mirror Service shall report a source failure instead of returning a successful unknown result.
3. When checksum verification fails for a `.osu` file, the Beatmap Mirror Service shall make the integrity failure observable to diagnostics.
4. When a mirror fallback is used, the Beatmap Mirror Service shall make the fallback use observable to diagnostics.
5. When eligibility is denied due to unverified source data, the Beatmap Mirror Service shall expose that denial reason to callers.
6. When a direct `.osu` file source is rate limited, the Beatmap Mirror Service shall make the rate-limit condition observable to diagnostics.
