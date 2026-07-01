# Implementation Plan

- [ ] 1. Foundation: submit timing and protocol prerequisites
- [x] 1.1 Persist submit timing on accepted scores
  - Add nullable fail time, play time, and play time source to the accepted score model and durable schema.
  - Extend score submission so parsed `ft` and exit or quit classification survive the accepted score persistence boundary.
  - Derive nullable play time from fail time or available beatmap length, and keep it unavailable when source data is missing or malformed.
  - Done: repository contract tests and score submission integration tests can retrieve the stored timing values from accepted passed and failed scores.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 4.5_
  - _Boundary: Score Timing Fields_

- [x] 1.2 (P) Confirm and implement stats request payload parsing
  - Add focused compatibility fixtures for the stable stats request payload before relying on the parser behavior.
  - Parse canonical user id list payloads and reject trailing, malformed, or oversized payloads without disconnecting the requester.
  - Done: parser tests prove accepted and malformed stats request payload behavior.
  - _Requirements: 7.4, 8.4_
  - _Boundary: StatsRequestProtocol_

- [ ] 2. Performance best projection
- [x] 2.1 Create the PP-priority best performance projection
  - Add the projection contract and persistence that stores one best performance per user, beatmap, ruleset, and playstyle.
  - Enforce deterministic replacement ordering by PP, submission time, and score identity.
  - Keep projection rows derived from Score and current Performance Calculation only.
  - Done: memory and SQL-backed repository tests show unique scope replacement and deterministic tie breaks.
  - _Requirements: 3.1, 3.2, 3.6, 4.1, 4.5, 8.3_
  - _Boundary: PerformanceBestProjection_

- [x] 2.2 Refresh and rebuild performance bests
  - Add a refresh workflow for one affected score and a rebuild workflow for a user or beatmap scope.
  - Ensure refresh skips ineligible scores, missing current PP, unavailable performance, and non-vanilla plays without mutating Performance Calculation.
  - Done: refresh and rebuild tests converge projection rows after new scores and recalculation outcomes.
  - _Requirements: 3.1, 3.2, 3.6, 4.5, 8.3, 8.5_
  - _Boundary: PerformanceBestProjection_

- [ ] 3. Current stats policy and read model
- [x] 3.1 Implement current stats calculation policy
  - Calculate weighted PP from at most 200 best performances with the `0.95 ** index` weighting sequence.
  - Keep bonus PP as an explicit zero policy until compatibility evidence supports a different formula.
  - Calculate weighted accuracy from the same best-performance set and return stable defaults for empty users.
  - Done: policy tests cover top-200 truncation, weights, zero bonus PP, zero accuracy, and non-negative outputs.
  - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2_
  - _Boundary: UserStatsPolicy_

- [x] 3.2 Implement batch current stats reads
  - Read play count, ranked score, total score, nullable play time, best performance rows, and rank inputs for deduplicated user ids.
  - Apply leaderboard-visible filtering and deterministic PP tie breaks for global rank.
  - Keep Relax and Autopilot plays outside the initial stats result.
  - Done: repository contract tests return correct stats for empty users, multiple users, tied PP, missing play time, and hidden users.
  - _Requirements: 2.1, 2.2, 2.3, 2.5, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4_
  - _Boundary: UserStatsQueryRepository_

- [x] 3.3 Expose a transport-neutral current stats query
  - Add a read-only query use-case that accepts one or more user ids and returns current stats without opening command persistence.
  - Preserve deduped request ordering and stable-safe defaults for unavailable fields.
  - Done: service tests prove the query delegates to read repositories, applies stats policy, and never mutates source state.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.6, 5.2, 8.3, 8.5_
  - _Boundary: CurrentUserStatsQuery_

- [ ] 4. Stable bancho integration
- [x] 4.1 Send current stats during stable login
  - Map current stats into the existing `USER_STATS` packet builder without changing wire field meanings.
  - Replace logged-in user placeholder stats with current values and keep default fallback behavior when stats reads fail.
  - Include roster stats where stable compatibility requires stats packets for online roster display.
  - Done: login packet stream tests contain current stats values and still preserve existing channel and friend packet ordering.
  - _Requirements: 2.3, 6.1, 6.2, 6.3, 6.4, 8.4_
  - _Boundary: StableUserStatsMapper, StableLoginStatsIntegration_

- [x] 4.2 Respond to stable stats requests
  - Add the stats request handler and register it with the stable packet dispatcher.
  - Deduplicate requested ids, filter unavailable or hidden users, and enqueue at most one `USER_STATS` packet per visible requested user.
  - Ignore malformed payloads after logging and keep the requester session active.
  - Done: handler tests prove visible responses, unknown user suppression, deduplication, malformed payload handling, and packet queue output.
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 8.4_
  - _Boundary: StatsRequestHandler_
  - _Depends: 1.2, 3.3_

- [ ] 5. Validation and compatibility coverage
- [x] 5.1 Verify current stats across score, performance, and stable flows
  - Add integration coverage from score submission timing through current stats reads.
  - Add performance best refresh coverage for completed current PP and recalculation replacement outcomes.
  - Add stable login and polling-flow coverage for non-zero PP, accuracy, play count, ranked score, total score, rank, and default fallbacks.
  - Done: integration tests demonstrate the in-game current stats path from persisted source data to `USER_STATS` packets.
  - _Requirements: 1.1, 1.3, 2.1, 2.2, 2.3, 3.6, 4.1, 4.4, 5.1, 6.1, 7.1, 8.3_
  - _Boundary: CrossBoundaryValidation_

- [x] 5.2 Run implementation gates and boundary review
  - Run focused unit, repository, integration, and stable protocol tests for this feature.
  - Run the project quality gate and inspect architecture boundaries for transport, query, repository, and domain dependency direction.
  - Done: relevant tests and quality checks pass, and no UserStats code mutates Performance Calculation state or adds Web/history scope.
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_
  - _Boundary: Validation_
