# Requirements Document

## Introduction

score-pp-calculation は、score-ingestion で保存された score に ranked PP と star rating を付与し、stable client の submit response と将来の leaderboard / stats が参照できる performance value を提供する feature です。

対象 user は stable client player と operator です。Player には送信直後または retry 時に PP を含む stable 互換 response を返し、operator には計算失敗、未計算、stale、formula migration を観測し再計算を発火できる運用手段を提供します。

## Boundary Context

- **In scope**:
  - Ranked / Approved の passed score に対する ranked PP と star rating 計算
  - `.osu` file availability を待つ bounded wait と stable retry response
  - Performance Calculation の state、current / historical record、provenance
  - calculator version と playstyle 別 Formula Profile に基づく stale / mismatch 検出
  - operator CLI からの PP Recalculation 発火
  - durable な Performance Recalculation Batch と work item による大規模再計算
  - 重複 submit retry と重複 calculation request の冪等処理

- **Out of scope**:
  - Loved / Qualified / failed score の PP 計算
  - beatmap leaderboard projection への反映
  - user stats / rank projection への反映
  - replay file を解析する PP 計算または anti-cheat verification
  - WebUI / admin operation surface による再計算操作
  - Relax / Autopilot score の実計算

- **Adjacent expectations**:
  - score-ingestion は Score、Score Submission、Replay attachment、beatmap status at submission を保存する
  - beatmap-mirror は PP 計算に必要な beatmap metadata と `.osu` file attachment availability を提供する
  - blob-storage は replay file と `.osu` file body の保存を提供する
  - later leaderboard / stats features may copy current PP for read optimization, but canonical performance value remains Performance Calculation

## Requirements

### Requirement 1: PP Eligibility

**Objective:** As a stable client player, I want eligible scores to receive ranked PP, so that the submitted result has a meaningful performance value.

#### Acceptance Criteria

1. When a passed score is submitted for a Ranked beatmap, the Score PP Calculation Feature shall treat the score as eligible for ranked PP calculation.
2. When a passed score is submitted for an Approved beatmap, the Score PP Calculation Feature shall treat the score as eligible for ranked PP calculation.
3. When a score is submitted for a Loved or Qualified beatmap, the Score PP Calculation Feature shall keep the score outside Performance Calculation scope.
4. When a failed score is submitted, the Score PP Calculation Feature shall keep the score outside Performance Calculation scope.
5. The Score PP Calculation Feature shall not reject an accepted Score solely because Performance Calculation is pending, unavailable, or out of scope.

### Requirement 2: Calculation Inputs

**Objective:** As an operator, I want PP calculated from server-validated score data and the correct beatmap file, so that performance values are reproducible.

#### Acceptance Criteria

1. When calculating PP for an eligible score, the Score PP Calculation Feature shall use the server-validated Score data as the score state input.
2. When calculating PP for an eligible score, the Score PP Calculation Feature shall use a `.osu` file attachment that belongs to the score's beatmap.
3. When replay data exists for a score, the Score PP Calculation Feature shall not require replay parsing for PP calculation.
4. When replay data is missing for a score, the Score PP Calculation Feature shall still allow PP calculation if the score is otherwise eligible.
5. If the required `.osu` file is temporarily unavailable, then the Score PP Calculation Feature shall keep the Performance Calculation pending rather than marking the score rejected.
6. If the required `.osu` file cannot be made usable for the score, then the Score PP Calculation Feature shall mark the Performance Calculation as unavailable with an operator-visible reason.

### Requirement 3: Stable Submit Response

**Objective:** As a stable client player, I want submit responses to include PP when available and clearly retry when calculation is still pending, so that client retry behavior remains compatible.

#### Acceptance Criteria

1. When a newly submitted eligible score is accepted, the Score PP Calculation Feature shall request Performance Calculation for that score.
2. While the bounded wait window is active, the Score PP Calculation Feature shall wait for the score's current Performance Calculation to become completed or unavailable.
3. When the current Performance Calculation completes within the bounded wait window, the Score PP Calculation Feature shall return a stable completed response that includes PP.
4. If the bounded wait window expires while the current Performance Calculation is still pending, then the Score PP Calculation Feature shall return a retryable error response to the stable client.
5. When the same submission is retried after Performance Calculation completed, the Score PP Calculation Feature shall return a stable completed response that includes PP.
6. When the same submission is retried while Performance Calculation is still pending, the Score PP Calculation Feature shall continue returning a retryable error response.
7. When the same submission is retried after Performance Calculation is unavailable, the Score PP Calculation Feature shall return a score accepted completed response with `pp` left as `0`.

### Requirement 4: Performance Calculation State

**Objective:** As an operator, I want each calculation to expose a clear state, so that pending, successful, failed, and historical records are distinguishable.

#### Acceptance Criteria

1. The Score PP Calculation Feature shall represent Performance Calculation state as one of `queued`, `fetching_file`, `calculating`, `completed`, `unavailable`, or `superseded`.
2. While a Performance Calculation is `queued`, `fetching_file`, or `calculating`, the Score PP Calculation Feature shall treat its client response state as pending.
3. When a Performance Calculation is `completed`, the Score PP Calculation Feature shall expose PP and star rating as available.
4. When a Performance Calculation is `unavailable`, the Score PP Calculation Feature shall expose that PP cannot currently be provided and include an operator-visible reason.
5. When a Performance Calculation is `superseded`, the Score PP Calculation Feature shall keep it as historical evidence and exclude it from stable submit response selection.

### Requirement 5: Current Performance Value and Provenance

**Objective:** As an operator, I want current PP values to be traceable to a calculator and profile, so that formula changes and recalculation outcomes are explainable.

#### Acceptance Criteria

1. The Score PP Calculation Feature shall keep at most one current Performance Calculation per score.
2. When a Performance Calculation completes, the Score PP Calculation Feature shall preserve PP, star rating, calculator version, Formula Profile, beatmap file attachment identity, calculation state, and calculated timestamp.
3. When a score has historical Performance Calculations, the Score PP Calculation Feature shall distinguish them from the current Performance Calculation.
4. When stable submit response needs PP, the Score PP Calculation Feature shall use only the current Performance Calculation.
5. The Score PP Calculation Feature shall keep Score gameplay data as the source of truth for gameplay result and Performance Calculation as the source of truth for PP.

### Requirement 6: Completion Waiting

**Objective:** As a stable client player, I want submit waiting to scale without changing response semantics, so that high traffic does not create unnecessary retries.

#### Acceptance Criteria

1. When an eligible score requests bounded wait, the Score PP Calculation Feature shall wait for a Performance Completion Signal for that score.
2. When a Performance Completion Signal is received, the Score PP Calculation Feature shall re-read the current Performance Calculation before building the client response.
3. If a Performance Completion Signal is missing, delayed, or lost, then the Score PP Calculation Feature shall perform a final current-state check before returning a timeout response.
4. If the final current-state check still shows a pending state, then the Score PP Calculation Feature shall return a retryable error response.
5. The Score PP Calculation Feature shall treat completion signals as wait optimization rather than the source of truth for PP values.

### Requirement 7: Submission Retry and Duplicate Score Handling

**Objective:** As a stable client player, I want repeated submit requests to converge on the same accepted score, so that network retries do not create duplicate performance records.

#### Acceptance Criteria

1. When the same submission fingerprint is retried, the Score PP Calculation Feature shall bind the retry to the existing accepted Score.
2. When a retried submission is bound to an existing Score, the Score PP Calculation Feature shall build the response from the existing Score and its current Performance Calculation.
3. When a retried submission is bound to an existing Score, the Score PP Calculation Feature shall not copy PP into the submission result snapshot as a canonical value.
4. When a different submission identifier reuses an existing online checksum, the Score PP Calculation Feature shall preserve the existing terminal reject behavior.
5. When a different submission identifier reuses an existing replay checksum, the Score PP Calculation Feature shall preserve the existing terminal reject behavior.

### Requirement 8: Duplicate Calculation Requests

**Objective:** As an operator, I want duplicate calculation requests to be safe, so that retries and repeated wake-up events do not corrupt current PP.

#### Acceptance Criteria

1. When duplicate Performance Calculation requests target the same score and current provenance, the Score PP Calculation Feature shall converge to one current result.
2. When the current Performance Calculation is completed and its provenance matches the active calculator version, Formula Profile, and beatmap file attachment, the Score PP Calculation Feature shall treat duplicate calculation requests as successful no-ops.
3. While a matching current Performance Calculation is pending, the Score PP Calculation Feature shall prevent duplicate processors from producing conflicting current results.
4. If duplicate processing observes a temporary claim conflict, then the Score PP Calculation Feature shall allow retry without marking the score unavailable.
5. When a duplicate request targets stale or mismatched provenance, the Score PP Calculation Feature shall route it through PP Recalculation behavior rather than overwriting current PP directly.

### Requirement 9: PP Recalculation Selection

**Objective:** As an operator, I want to identify scores that need recalculation, so that calculator and profile changes can be applied consistently.

#### Acceptance Criteria

1. When an eligible score has no Performance Calculation, the Score PP Calculation Feature shall include it in uncalculated recalculation candidates.
2. When an eligible score's current Performance Calculation is stale, the Score PP Calculation Feature shall include it in stale recalculation candidates.
3. When an eligible score's current calculator version differs from the active calculator version, the Score PP Calculation Feature shall include it in provenance-mismatch recalculation candidates.
4. When an eligible score's current Formula Profile differs from the active Formula Profile for its playstyle, the Score PP Calculation Feature shall include it in provenance-mismatch recalculation candidates.
5. When an operator explicitly includes unavailable records, the Score PP Calculation Feature shall include unavailable current Performance Calculations in recalculation candidates.
6. When a score is outside PP eligibility, the Score PP Calculation Feature shall not include it in PP Recalculation candidates.

### Requirement 10: Recalculation CLI Entry Point

**Objective:** As an operator, I want a CLI entry point for PP recalculation, so that I can trigger backfills and profile migrations without calculating inside the CLI process.

#### Acceptance Criteria

1. When an operator runs PP Recalculation in dry-run mode, the Score PP Calculation Feature shall report candidate counts and reason breakdown without creating recalculation work.
2. When an operator runs PP Recalculation with execution enabled, the Score PP Calculation Feature shall create durable recalculation work and start background processing.
3. The Score PP Calculation Feature shall support recalculation filters for score id, beatmap id, user id, ruleset, and candidate limit.
4. The Score PP Calculation Feature shall treat candidate limit as an optional cap for testing or partial operation rather than a required safety condition.
5. The Score PP Calculation Feature shall require an explicit full-scope flag for profile migration or other all-candidate recalculation runs.
6. Where unavailable records are included, the Score PP Calculation Feature shall require an explicit include-unavailable option.
7. The Score PP Calculation Feature shall not calculate PP inside the operator CLI process.

### Requirement 11: Durable Recalculation Batch

**Objective:** As an operator, I want large recalculation runs to survive background processing and wake-up signal failures, so that profile migrations eventually process all intended scores.

#### Acceptance Criteria

1. When execution creates recalculation work, the Score PP Calculation Feature shall group the work under a Performance Recalculation Batch.
2. When a Performance Recalculation Batch is created, the Score PP Calculation Feature shall preserve the selected filters, candidate reasons, Formula Profile, calculator version, and operator-visible progress.
3. While a Performance Recalculation Batch has pending work, the Score PP Calculation Feature shall allow background processing to handle work in bounded chunks.
4. If background processing stops before finishing claimed work, then the Score PP Calculation Feature shall make stale work eligible for later retry.
5. If a wake-up signal is lost, then the Score PP Calculation Feature shall allow pending or stale work to be discovered and resumed later.
6. The Score PP Calculation Feature shall treat durable batch work as the source of truth for unfinished recalculation work.

### Requirement 12: Formula Profile Consistency

**Objective:** As a ranked leaderboard maintainer, I want one Formula Profile per playstyle, so that PP values remain comparable across users.

#### Acceptance Criteria

1. The Score PP Calculation Feature shall maintain Formula Profile as a playstyle-scoped calculation policy.
2. When a Formula Profile changes for a playstyle, the Score PP Calculation Feature shall require eligible scores in that playstyle to converge to the new profile.
3. When a Formula Profile migration is in progress, the Score PP Calculation Feature shall keep existing current PP available until replacement calculation finalization.
4. When replacement calculation finalizes, the Score PP Calculation Feature shall supersede the old current Performance Calculation and make the replacement current.
5. The Score PP Calculation Feature shall not use user flags or user subsets to split ranked PP calculations within the same playstyle Formula Profile.

### Requirement 13: PP Representation and Stable Formatting

**Objective:** As a stable client player, I want PP displayed in a stable-compatible format, so that the submit response remains compatible with existing clients.

#### Acceptance Criteria

1. When Performance Calculation stores PP, the Score PP Calculation Feature shall preserve decimal precision suitable for later leaderboard and stats use.
2. When stable submit response includes PP, the Score PP Calculation Feature shall round PP to the nearest integer for the stable chart `pp` field.
3. When stable submit response has no PP because calculation is unavailable or out of scope, the Score PP Calculation Feature shall leave the stable chart `pp` field as `0`.
4. The Score PP Calculation Feature shall not expose calculator internals or operator diagnostics in stable client responses.

### Requirement 14: Calculator Adoption and Isolation

**Objective:** As an operator, I want a consistent calculator policy with recorded version data, so that PP values can be audited and recalculated after calculator changes.

#### Acceptance Criteria

1. The Score PP Calculation Feature shall use the approved PP calculator for performance and star rating calculation.
2. When calculator version changes, the Score PP Calculation Feature shall make affected eligible scores discoverable as recalculation candidates.
3. When calculation succeeds, the Score PP Calculation Feature shall record the calculator version used for that result.
4. When calculation fails due to calculator input or execution failure, the Score PP Calculation Feature shall mark the Performance Calculation unavailable with an operator-visible reason.
5. The Score PP Calculation Feature shall keep calculator-specific implementation details out of stable client responses and operator CLI output except for approved version/provenance fields.

### Requirement 15: Future Scope Boundaries

**Objective:** As a feature owner, I want Wave 2 scope to remain narrow, so that later leaderboard, stats, and verification work can build on clear PP records.

#### Acceptance Criteria

1. The Score PP Calculation Feature shall not update beatmap leaderboard projection as part of Wave 2.
2. The Score PP Calculation Feature shall not update user stats or user rank projection as part of Wave 2.
3. The Score PP Calculation Feature shall not use replay file parsing as a PP calculation input in Wave 2.
4. Where Loved PP is introduced in a future scope, the future feature shall extend PP eligibility before creating Performance Calculations for Loved scores.
5. Where Relax or Autopilot PP is introduced in a future scope, the future feature shall define playstyle-specific Formula Profiles before calculating those scores.
