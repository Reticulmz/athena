# Implementation Plan

- [ ] 1. Foundation: fixture and persistence lookup prerequisites
- [ ] 1.1 Add stable beatmap-info fixtures and parser/formatter baseline tests
  - Store the observed stable import request separately from the official/reference response body, excluding HTTP chunk framing bytes.
  - Add failing tests that verify request body shape, response row fields, non-request response order, and fixture provenance.
  - The completed state is visible when tests can load both fixtures and assert the expected filename batch and pipe-delimited row content.
  - _Requirements: 3.6, 8.3, 8.4, 13.1, 13.2, 13.3, 13.4_

- [ ] 1.2 Add exact filename fallback support to beatmap persistence
  - Add a repository read capability for exact original `.osu` filename lookup without making filename an authoritative identity.
  - Update in-memory persistence so unit and integration tests can resolve known filename-only entries.
  - Add SQLAlchemy persistence support and a migration only if current persisted metadata has no existing original filename field to query.
  - The completed state is visible when checksum and id lookups still work unchanged, while a stored original filename can resolve a beatmap through the repository contract.
  - _Requirements: 4.3, 5.1, 6.2, 12.1_

- [ ] 2. Core transport helpers
- [ ] 2.1 (P) Implement stable request parsing and lookup candidate normalization
  - Accept observed JSON bodies containing `Filenames` and `Ids`, preserving the response index for each entry.
  - Enforce the 100-entry batch limit and return typed parse outcomes for empty, malformed, and oversized batches.
  - Prefer recognizable checksum/md5 data, then explicit id entries, then exact filename fallback; do not infer ids from ambiguous filename text.
  - The completed state is visible when parser tests cover real fixtures, invalid shapes, over-limit batches, zero entries, priority ordering, and unparsable filename omission.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.1, 4.2, 4.3, 4.4, 4.5, 13.1_
  - _Boundary: BeatmapInfoRequestParser_

- [ ] 2.2 (P) Implement stable response status, grade, and row formatting
  - Map effective beatmap statuses to stable-compatible numeric values or omit rows when the status should not be visible to stable clients.
  - Format resolved rows as `index|beatmap_id|beatmapset_id|md5|status|grade_osu|grade_taiko|grade_catch|grade_mania`.
  - Return neutral grades for all modes until personal grade persistence exists, and keep score mutation out of formatting.
  - The completed state is visible when formatter tests assert fixture-compatible rows, omitted unresolved/unmappable rows, neutral grade fallback, and absence of provenance fields.
  - _Requirements: 7.1, 7.2, 7.3, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 9.1, 9.2, 9.3, 9.4, 9.5, 10.1, 10.2, 10.3, 10.4, 12.1, 12.2, 12.3_
  - _Boundary: BeatmapInfoFormatter, StableStatusMapper, BeatmapInfoGradeProvider_

- [ ] 2.3 (P) Implement legacy web authentication for stable web credentials
  - Verify `u` and `h` through the existing user, password, and session abstractions.
  - Require an active bancho session before authorizing user-specific beatmap info.
  - Redact password md5 and raw credential values from operator diagnostics.
  - The completed state is visible when auth tests distinguish valid credentials with session, invalid credentials, missing credentials, and no active session.
  - _Requirements: 2.1, 2.2, 2.3, 2.4_
  - _Boundary: LegacyWebAuthService_

- [ ] 3. Core metadata resolution
- [ ] 3.1 Resolve beatmap-info batches through cache-first metadata lookup
  - Resolve entries by checksum first, explicit beatmap id second, and repository filename fallback third.
  - Request metadata resolution for unknown checksum/id targets using bounded wait and metadata-only options.
  - Treat pending work as existing work, avoid duplicate conflicting results for repeated targets, and keep filename fallback as persisted metadata only.
  - The completed state is visible when resolver tests show known cache hits return immediately, unknown targets request metadata, pending results are omitted, and duplicate targets do not expose conflicting rows.
  - _Depends: 1.2, 2.1_
  - _Requirements: 4.1, 4.2, 4.3, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 7.1, 7.2, 7.4, 11.1, 11.2, 11.3_

- [ ] 3.2 Reuse beatmapset snapshots within a batch before formatting
  - Recheck persisted metadata after bounded wait so multiple difficulties from the same beatmapset can resolve consistently.
  - Keep response association through stable index values instead of relying on response line order.
  - The completed state is visible when tests show one resolved beatmapset snapshot can satisfy later same-set entries and all resolved rows carry consistent beatmapset ids and statuses.
  - _Depends: 3.1_
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 8.4_

- [ ] 4. Endpoint integration and routing
- [ ] 4.1 Wire the beatmap-info handler into the web legacy app
  - Add the handler and endpoint adapter through the existing DI, lifespan state, and Starlette composition pattern.
  - Register `POST /web/osu-getbeatmapinfo.php` only under `osu.$DOMAIN`, without adding a path-based fallback for other hosts.
  - Return `401` without beatmap data for authentication failures and `200` empty body for parse errors, zero entries, oversized batches, or fully unresolved batches.
  - The completed state is visible when integration tests can post to the osu host route and cannot reach the feature through non-osu host fallback routes.
  - _Depends: 2.1, 2.2, 2.3, 3.2_
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.4, 3.3, 3.4, 3.5, 5.5, 7.2, 8.5, 12.4_

- [ ] 4.2 Add operator-observable diagnostics without leaking sensitive data
  - Log parse failures, oversized batches, unparsable entries, unresolved repeated patterns, and auth failures with credentials redacted.
  - Keep internal source, verification, local policy, and override provenance out of stable response bodies.
  - The completed state is visible when tests or structured-log assertions show the expected diagnostic events and response bodies contain no credentials or provenance fields.
  - _Depends: 4.1_
  - _Requirements: 2.4, 3.4, 3.5, 4.4, 8.6, 11.4, 12.3_

- [ ] 5. Compatibility and load validation
- [ ] 5.1 Validate the stable fixture happy path end to end
  - Exercise the real stable request fixture through the endpoint with a known filename-only repository entry.
  - Assert response rows include beatmap id, beatmapset id, md5, stable status, and four grade fields with correct index association.
  - The completed state is visible when the integration test passes against the fixture and does not depend on response line order.
  - _Depends: 4.2_
  - _Requirements: 3.6, 4.3, 6.4, 8.1, 8.3, 8.4, 10.2, 13.1, 13.4_

- [ ] 5.2 Validate auth, unresolved, status, and load boundaries
  - Cover unauthorized requests, no-session requests, unknown metadata, not-submitted results, hidden statuses, and a valid 100-entry batch.
  - Assert metadata-only resolution does not request `.osu` file bodies and does not create, update, or recalculate scores.
  - The completed state is visible when boundary tests pass for empty-body behavior, omitted rows, bounded waits, duplicate targets, and 100-entry batches.
  - _Depends: 5.1_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 5.2, 5.3, 5.5, 5.6, 7.1, 7.2, 7.3, 9.5, 10.3, 10.4, 11.1, 11.2, 11.3, 11.4_

- [ ] 6. Final quality verification
- [ ] 6.1 Run focused and project quality checks for the endpoint
  - Run formatter, linter, type checker, and relevant unit/integration tests for the changed transport, service, repository, and migration areas.
  - Fix any failures by addressing root causes instead of suppressing type or lint errors.
  - The completed state is visible when the relevant pytest suite, ruff, basedpyright, and migration checks pass or any unavailable external prerequisite is explicitly reported.
  - _Depends: 5.2_
  - _Requirements: 1.1, 1.3, 3.6, 13.1_
