# Implementation Plan

- [ ] 1. Durable accounting storage foundation
- [x] 1.1 Add score-scoped Replay View Count storage
  - Make Replay View Count a score-owned durable projection that starts at `0` for existing and new scores.
  - Enforce that the count is never unavailable, null, or negative.
  - Keep user total replay views out of this feature so future totals can aggregate from score counts.
  - Done when score creation and score read paths expose `0` for untouched scores and the database migration enforces non-null non-negative storage.
  - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 5.6_
  - _Boundary: Score Replay View Persistence_

- [x] 1.2 Add viewer latest activity durable storage
  - Add durable latest activity metadata for users without using row update metadata as a substitute.
  - Backfill existing users with a non-null activity timestamp and ensure new users receive one.
  - Keep latest activity as metadata rather than a per-download audit trail.
  - Done when user creation and user read paths expose non-null latest activity and the migration makes the field mandatory.
  - _Requirements: 4.1, 4.7_
  - _Boundary: User Latest Activity Persistence_

- [x] 1.3 Add durable mutation operations for replay count and activity
  - Add command-side score count increment behavior that reports whether the score existed.
  - Add command-side latest activity touch behavior that reports whether the viewer user existed.
  - Keep both operations available through the existing command persistence boundary.
  - Done when in-memory and SQL-backed repository contract checks can increment replay count and touch latest activity independently.
  - _Requirements: 2.1, 4.1, 6.1_
  - _Boundary: Score Replay View Persistence, User Latest Activity Persistence_

- [ ] 2. Core accounting metadata and temporary gates
- [x] 2.1 Extend replay download success metadata
  - Include score identity and score owner identity in successful replay download query results.
  - Ensure non-success replay download branches cannot carry accounting metadata.
  - Keep metadata internal so it is not serialized into the stable replay download response.
  - Done when success results can build accounting input without an extra transport-side lookup and non-success results have no metadata.
  - _Requirements: 1.1, 1.6, 3.8, 5.4_
  - _Boundary: Replay Download Metadata Extension_

- [x] 2.2 (P) Build temporary replay accounting gates
  - Add a 24-hour first-claim cooldown per viewer and score.
  - Add a 5-minute first-claim latest activity throttle per viewer.
  - Provide Valkey-backed and in-memory behavior with the same claim semantics.
  - Keep duplicate identity based only on authenticated viewer user id and score id.
  - Done when gate checks prove same viewer/same score is suppressed, different viewers or scores are independent, and activity throttle is viewer-scoped.
  - _Requirements: 3.3, 3.4, 3.5, 3.6, 3.8, 4.4, 4.5_
  - _Boundary: ReplayDownloadAccountingGate_

- [ ] 3. Replay download accounting command policy
- [x] 3.1 Apply Replay View Count policy
  - Count successful non-owner replay downloads when the duplicate cooldown gate is open.
  - Skip owner self-view without treating it as a counted view.
  - Suppress repeated same-viewer same-score downloads within the cooldown window.
  - Treat successful replay download as a server-observable consumption signal without naming it playback.
  - Done when command-level checks show non-owner increments once, self-view does not increment, and duplicate cooldown suppresses the second count.
  - _Depends: 1.3, 2.2_
  - _Requirements: 2.1, 3.1, 3.2, 3.3, 3.6, 3.7, 5.1, 5.2, 5.5, 6.1, 6.2, 6.3_
  - _Boundary: ReplayDownloadAccountingUseCase_

- [x] 3.2 Apply latest activity touch policy
  - Make every successful authenticated replay download eligible for latest activity update.
  - Keep self-view and duplicate cooldown hits eligible for latest activity.
  - Suppress durable activity writes while the viewer is inside the throttle window.
  - Prefer preserving replay download success when temporary throttle state is unavailable.
  - Done when command-level checks show success, self-view, and duplicate hit can touch activity, while throttle hit avoids another durable write.
  - _Depends: 1.3, 2.2_
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 6.4, 6.5_
  - _Boundary: ReplayDownloadAccountingUseCase_

- [ ] 3.3 Add operation outcomes and sanitized failure observability
  - Distinguish replay count failure from latest activity failure in command results and logs.
  - Allow count and activity operations to fail independently without rolling back the other operation.
  - Exclude raw replay payloads, raw query values, credential values, and local artifact paths from all accounting diagnostics.
  - Done when failure-path checks can identify which side effect failed and confirm no sensitive fields appear in emitted diagnostics.
  - _Depends: 3.1, 3.2_
  - _Requirements: 1.5, 1.6, 3.7, 4.6, 6.8_
  - _Boundary: ReplayDownloadAccountingUseCase_

- [ ] 4. Stable replay download integration
- [ ] 4.1 Attach accounting to successful replay download responses
  - Invoke accounting only after a successful replay download body and metadata are available.
  - Do not invoke accounting for auth failure, malformed request, hidden score, missing replay, storage-missing replay, or unavailable branches.
  - Preserve the existing stable response status, headers, and body whether accounting succeeds or fails.
  - Do not add `/web/replays/<id>` behavior or change parsing, auth, lookup, storage, or response strategy.
  - Done when handler checks prove command calls happen only on success and every failure branch remains mutation-free.
  - _Depends: 2.1, 3.3_
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 5.3, 5.4, 6.6, 6.7_
  - _Boundary: Stable Replay Handler Hook_

- [ ] 4.2 Wire runtime and test composition
  - Provide the accounting command through the score service graph.
  - Provide the production temporary gate through the Valkey-backed infrastructure graph.
  - Replace the gate with an in-memory adapter in test composition.
  - Ensure stable web legacy handler construction receives the accounting dependency without changing route registration.
  - Done when app/test dependency resolution can construct the replay download handler with accounting enabled.
  - _Depends: 2.2, 3.3, 4.1_
  - _Requirements: 1.1, 3.7, 4.6, 6.6_
  - _Boundary: Stable Replay Handler Hook, ReplayDownloadAccountingGate, ReplayDownloadAccountingUseCase_

- [ ] 5. Verification and regression coverage
- [ ] 5.1 Verify replay download response preservation end to end
  - Cover accounting success and accounting failure on a successful replay download.
  - Cover auth failure, malformed request, hidden score, missing replay, and storage-missing replay as no-update branches.
  - Assert response status, headers, and body remain the Issue #36 contract in accounting success and failure paths.
  - Done when endpoint-level checks prove response bytes are unchanged and failure branches do not update count or activity.
  - _Depends: 4.2_
  - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6, 5.3, 5.4, 6.6, 6.7, 6.8_
  - _Boundary: Stable Replay Handler Hook_

- [ ] 5.2 (P) Verify durable persistence and migration integrity
  - Verify existing scores and new scores expose Replay View Count as `0` until counted downloads occur.
  - Verify Replay View Count increments by exactly one for an accepted counted download.
  - Verify users have non-null latest activity and touch updates only the viewer user.
  - Done when repository and migration checks pass for non-null defaults, constraints, count increment, and latest activity touch.
  - _Depends: 1.3_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 4.1, 4.7, 6.1_
  - _Boundary: Score Replay View Persistence, User Latest Activity Persistence_

- [ ] 5.3 (P) Verify cooldown, throttle, and partial failure behavior
  - Verify duplicate cooldown suppresses repeated same-viewer same-score increments within 24 hours.
  - Verify cooldown identity is independent per score and per viewer.
  - Verify latest activity throttle avoids repeated durable writes within 5 minutes.
  - Verify temporary gate loss or unavailability preserves replay download success semantics.
  - Done when unit checks cover duplicate suppression, independent cooldown keys, throttle suppression, gate unavailable behavior, and sanitized partial failure logs.
  - _Depends: 3.3_
  - _Requirements: 3.3, 3.4, 3.5, 3.6, 3.7, 4.3, 4.4, 4.5, 4.6, 6.3, 6.4, 6.5, 6.8_
  - _Boundary: ReplayDownloadAccountingGate, ReplayDownloadAccountingUseCase_

- [ ] 5.4 Run focused implementation validation
  - Run the replay download accounting unit and integration test set.
  - Run the relevant formatting, lint, type, and import-boundary checks for touched modules.
  - Fix any drift between generated tasks, requirements, design, and implementation before claiming completion.
  - Done when the focused test and quality commands pass, or any remaining failure is isolated and documented with the blocking cause.
  - _Depends: 5.1, 5.2, 5.3_
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8_
  - _Boundary: Verification_
