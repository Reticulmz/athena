# Implementation Plan

- [ ] 1. Foundation: schema, configuration, and test scaffolding
- [x] 1.1 Add beatmap mirror configuration and startup validation
  - Add configuration for official API enablement and credentials, mirror trust policy, direct `.osu` URL templates, community mirror URL templates, refresh timing, and bounded wait defaults.
  - Development and production reject source-dependent startup when required official source credentials are missing and official sources are enabled.
  - Tests can construct app config with fake source settings and no real external credentials.
  - Observable completion: configuration tests show invalid mirror URLs and missing required official source credentials fail before source-dependent operations are accepted.
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.4, 6.7, 6.9, 16.6_

- [x] 1.2 Add beatmap mirror database migration and ORM discovery
  - Create relational storage for beatmapsets, beatmaps, beatmap file attachments, and beatmap fetch states.
  - Add uniqueness and lookup constraints for beatmap id, checksum/md5, file attachment idempotency, and fetch targets.
  - Keep `.osu` bodies out of beatmap tables and reference shared blob records only from beatmap file attachment records.
  - Observable completion: Alembic upgrade creates all beatmap mirror tables and indexes, and ORM model imports are visible through metadata discovery.
  - _Requirements: 1.1, 1.2, 1.3, 1.5, 6.5, 7.4, 9.1, 9.3, 14.1, 14.2, 14.3, 14.4_

- [x] 1.3 Add typed beatmap factories and fake provider helpers
  - Add test factories for beatmapsets, beatmaps, fetch states, file attachments, metadata snapshots, and `.osu` file bodies.
  - Add fake metadata and file providers that can return success, pending, not found, rate limit, timeout, server failure, and checksum mismatch scenarios.
  - Observable completion: unit tests can create complete beatmap snapshots and file fetch responses without real network credentials.
  - _Requirements: 4.4, 7.1, 7.2, 7.5, 16.1, 16.2, 16.3_

- [x] 1.4 Validate blob-storage dependency contract for `.osu` bodies
  - Confirm the beatmap file fetch path can call the shared blob storage service for verified `.osu` bodies.
  - Add a typed fake blob storage service for beatmap mirror tests if the real blob-storage implementation is not available in unit scope.
  - Keep original filename, beatmap checksum, and attachment ownership outside the shared blob record.
  - Observable completion: beatmap mirror tests can store a verified `.osu` body through the fake or real blob service contract and observe a blob reference without embedding file bytes in beatmap metadata.
  - _Requirements: 6.3, 6.4, 6.5, 14.2_

- [ ] 2. Core domain and policy behavior
- [x] 2.1 Implement beatmap domain entities and status value rules
  - Model beatmapset metadata, beatmap identity, checksum/md5, source, verification, fetch timing, file state, and attachment metadata as typed domain values.
  - Represent official status, local override status, and effective status separately.
  - Preserve `Approved` as an official status while excluding it from assignable local override values.
  - Observable completion: domain tests distinguish official status, local override status, effective status, source, verification, and `.osu` attachment metadata without importing provider or ORM types.
  - _Requirements: 1.1, 1.2, 1.3, 1.5, 3.5, 6.5, 7.1, 7.2, 7.4, 8.4, 9.1, 9.2, 10.1, 10.4_
  - _Boundary: Beatmap, BeatmapSet_

- [x] 2.2 (P) Implement status resolution and eligibility projection
  - Derive effective status from local override when present and official status otherwise.
  - Reject `Approved` as a local override value.
  - Return score acceptance, leaderboard, ranked PP, loved PP, failed-score, `.osu` requirement, official verification, and denial reason fields.
  - Apply the default mirror trust policy so untrusted mirror status does not grant score, leaderboard, or PP eligibility.
  - Observable completion: tests cover Ranked, Approved, Loved, Qualified, Pending, WIP, Graveyard, NotSubmitted, Unknown, trusted mirror, untrusted mirror, and failed-score behavior.
  - _Depends: 2.1_
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 9.2, 9.4, 9.5, 10.2, 10.3, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 12.1, 12.2, 12.3, 12.4, 12.5, 13.1, 13.2, 13.3, 13.4_
  - _Boundary: BeatmapStatusResolver, BeatmapEligibilityService_

- [x] 2.3 (P) Implement freshness policy for beatmap status refresh
  - Treat Ranked, Approved, and Loved as stable unless explicit refresh or policy marks them stale.
  - Treat Qualified, Pending, and WIP as refreshable on a shorter cadence.
  - Treat Graveyard as refreshable on a longer cadence than Pending-like statuses.
  - Keep policy based on persisted timestamps and status without requiring a memory cache.
  - Observable completion: tests show next-refresh decisions differ by status and mirror-sourced records request official refresh on later access.
  - _Depends: 2.1_
  - _Requirements: 3.4, 8.1, 8.2, 8.3, 8.4, 8.5_
  - _Boundary: BeatmapFreshnessPolicy_

- [ ] 3. Core persistence behavior
- [x] 3.1 Implement in-memory beatmap repository
  - Store beatmapsets, beatmaps, checksum lookup, file attachments, and fetch states in typed in-memory structures.
  - Support idempotent pending fetch markers and duplicate attachment handling.
  - Preserve local override values when metadata snapshots refresh official status.
  - Observable completion: repository contract tests pass for lookup by beatmap id, beatmapset id, checksum, fetch state transitions, local override preservation, and duplicate file attachment behavior.
  - _Depends: 2.1_
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 6.1, 6.2, 6.5, 7.1, 7.2, 7.3, 7.4, 7.5, 9.1, 9.3, 9.4, 14.1, 14.2, 14.3, 14.4_
  - _Boundary: BeatmapRepository_

- [x] 3.2 Implement SQLAlchemy beatmap repository
  - Persist beatmapset snapshots, beatmaps, checksum lookup, file attachments, and fetch states using short repository-owned transactions.
  - Enforce database constraints for beatmap identity, checksum lookup, fetch targets, and duplicate file attachments.
  - Ensure official metadata refresh updates official fields without clearing local override.
  - Observable completion: integration tests pass against the configured test database for snapshot persistence, lookup paths, idempotent fetch state, duplicate attachment behavior, and local override preservation.
  - _Depends: 1.2, 3.1_
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 6.1, 6.2, 6.5, 7.1, 7.2, 7.3, 7.4, 7.5, 9.1, 9.3, 9.4, 14.1, 14.2, 14.3, 14.4_
  - _Boundary: BeatmapRepository_

- [ ] 4. Source provider behavior
- [x] 4.1 Implement metadata provider contracts and status mapping
  - Normalize official API and mirror metadata into provider-neutral beatmapset snapshots.
  - Map external status values into Athena rank status values, including Approved and Loved.
  - Mark official metadata as verified and mirror metadata as unverified.
  - Normalize provider errors into source failure categories for service and job handling.
  - Observable completion: provider tests show official source priority, mirror fallback metadata marking, status mapping, and source failure normalization without leaking provider-specific objects.
  - _Depends: 2.1_
  - _Requirements: 3.1, 3.2, 3.3, 3.5, 4.1, 4.2, 4.3, 4.4, 16.1, 16.2, 16.4_
  - _Boundary: BeatmapMetadataProvider_

- [ ] 4.2 Implement direct and mirror `.osu` file source provider
  - Fetch `.osu` files from current direct source first, legacy direct source second, and configured community mirror URL third.
  - Use GET for mirror fallback so catboy-style endpoints work even when HEAD does not.
  - Treat rate limit, timeout, connection error, and upstream server failure as fallback-triggering temporary failures.
  - Do not automatically treat not found as a mirror fallback success path.
  - Observable completion: provider tests show source order, configured URL template usage, 429/timeout/5xx fallback, 404 exclusion, original filename capture when available, and mirror source reporting.
  - _Depends: 1.1_
  - _Requirements: 4.5, 4.6, 6.6, 6.7, 6.8, 6.9, 6.10, 16.3, 16.4, 16.6_
  - _Boundary: BeatmapFileProvider_

- [ ] 5. Beatmap mirror service behavior
- [ ] 5.1 Implement cache-first resolve operations and structured result states
  - Resolve by beatmap id, beatmapset id, and checksum/md5.
  - Return cached usable data synchronously.
  - Return structured metadata status, file status, source, verification, last fetch, next refresh, eligibility, and reason fields.
  - Return pending or failed state instead of unrelated beatmap data when records are unknown.
  - Observable completion: service tests show known records resolve without provider calls and unknown records return pending or failed states with distinguishable metadata and file status.
  - _Depends: 2.2, 2.3, 3.1_
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 7.1, 7.2, 7.3, 7.4, 7.5, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 15.4_
  - _Boundary: BeatmapMirrorService_

- [ ] 5.2 Implement refresh enqueue and bounded wait behavior
  - Enqueue metadata fetch for missing, stale, mirror-sourced, and explicitly refreshed records.
  - Enqueue file fetch when `.osu` is required and missing.
  - Wait only up to the caller's requested bound and recheck persisted state without holding database transactions or connections across the wait.
  - Observable completion: service tests show stale and missing records enqueue fetches, bounded wait returns fresh data when completed in time, and returns pending fetch when the wait expires.
  - _Depends: 5.1_
  - _Requirements: 2.2, 2.3, 2.4, 2.5, 3.4, 6.1, 6.2, 8.1, 8.2, 8.3, 8.5, 14.3, 15.1, 15.2, 15.3_
  - _Boundary: BeatmapMirrorService_

- [ ] 6. Background fetch jobs
- [ ] 6.1 Implement idempotent metadata fetch job
  - Mark metadata fetch pending only when no equivalent fetch is already pending.
  - Fetch official metadata before mirror metadata.
  - Save official snapshots without clearing local overrides and save mirror snapshots as unverified.
  - Mark normalized failure state when all configured sources fail.
  - Observable completion: job tests show duplicate pending fetches do not create conflicting states, official refresh preserves local override, mirror snapshots remain unverified, and all-source failure records failed state.
  - _Depends: 3.1, 4.1_
  - _Requirements: 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 3.5, 7.1, 7.3, 7.4, 8.1, 8.2, 8.3, 8.4, 9.3, 14.1, 14.3, 14.4, 16.1, 16.2, 16.4_
  - _Boundary: FetchBeatmapMetadataJob_

- [ ] 6.2 Implement idempotent `.osu` file fetch job
  - Require expected md5 from beatmap metadata before attaching a file.
  - Fetch file bytes through the file provider and verify expected md5 before blob storage attachment.
  - Store verified file bodies through the blob storage service and attach the returned blob to the beatmap.
  - Record source, original filename when available, fetched time, verified time, and checksum mismatch failures.
  - Observable completion: job tests show verified files attach once, duplicate verified files return existing attachment behavior, checksum mismatch does not attach bytes, and source failures update file fetch state.
  - _Depends: 3.1, 4.2_
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 6.10, 7.2, 7.3, 14.2, 14.3, 14.4, 16.3, 16.4, 16.6_
  - _Boundary: FetchBeatmapFileJob_

- [ ] 7. Runtime integration and composition
- [ ] 7.1 Register beatmap mirror dependencies in the application runtime
  - Register repository implementations by environment, metadata providers, file providers, eligibility service, mirror service, and required configuration validation.
  - Test environment uses in-memory repository and fake providers without real external credentials.
  - Non-test environments use SQLAlchemy repository and configured provider adapters.
  - Observable completion: composition tests can resolve `BeatmapMirrorService` in test and non-test configurations with the expected repository/provider choices.
  - _Depends: 3.2, 5.2_
  - _Requirements: 4.1, 4.2, 4.4, 15.4_
  - _Boundary: service_registry, AppConfig_

- [ ] 7.2 Register beatmap fetch jobs in the worker runtime
  - Add worker-side beatmap mirror runtime construction for metadata and file jobs.
  - Register metadata and file fetch taskiq jobs through the existing job registry.
  - Ensure jobs report runtime unavailable diagnostics instead of raising unhandled errors when worker state is incomplete.
  - Observable completion: worker/job tests show both beatmap fetch task names are registered and can resolve their required runtime service from taskiq state.
  - _Depends: 6.1, 6.2, 7.1_
  - _Requirements: 2.2, 6.2, 14.1, 14.2, 14.3, 16.1, 16.2, 16.3_
  - _Boundary: worker_runtime, JobRegistry_

- [ ] 7.3 Add structured observability for source, fallback, checksum, and eligibility outcomes
  - Emit structured diagnostics for metadata fetch start/success/failure, file fetch start/success/failure, source rate limits, mirror fallback usage, checksum mismatch, and eligibility denial.
  - Redact API credentials and authorization values from provider diagnostics.
  - Observable completion: logging tests capture expected event names and fields for success, all-source failure, mirror fallback, rate limit, checksum mismatch, and unverified eligibility denial.
  - _Depends: 6.1, 6.2_
  - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6_
  - _Boundary: BeatmapMirrorService, Providers, Jobs_

- [ ] 8. End-to-end and regression validation
- [ ] 8.1 Add resolve-metadata end-to-end flow with fake providers
  - Exercise missing beatmap resolution, pending metadata state, metadata job completion, and later fresh cache resolution.
  - Include lookup by beatmap id, beatmapset id, and checksum/md5 in the same validation path or tightly related tests.
  - Observable completion: E2E-style tests show a missing beatmap transitions from pending fetch to fresh resolved metadata without real network credentials.
  - _Depends: 7.2_
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.5, 7.1, 7.3, 7.5, 14.1, 14.3, 14.4_

- [ ] 8.2 Add `.osu` file availability end-to-end flow with fake blob storage
  - Exercise file-missing state, file fetch job completion, md5 verification, blob storage write, and attachment availability.
  - Include community mirror fallback after simulated direct source rate limit.
  - Observable completion: E2E-style tests show file status transitions to available only after md5 verification and records mirror source when fallback is used.
  - _Depends: 7.2_
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 7.2, 7.3, 14.2, 14.4, 16.3, 16.4, 16.6_

- [ ] 8.3 Add boundary regression tests for downstream separation
  - Verify beatmap mirror does not parse score payloads, calculate PP, write leaderboards, format Bancho score result responses, own request queues, or enqueue polling packets.
  - Verify downstream local rank changes can use local override semantics without changing official status.
  - Observable completion: regression tests and import boundaries show beatmap mirror remains independent from score-submission, leaderboard, WebUI, BanchoBot rank commands, and Bancho transports.
  - _Depends: 7.3_
  - _Requirements: 9.1, 9.3, 15.1, 15.2, 15.3, 15.4, 15.5_
