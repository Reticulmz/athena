# Implementation Plan

- [x] 1. Foundation: configuration, schema, and shared search contract
- [x] 1.1 Add osu!direct runtime policy and backend configuration
  - Add access policy settings for authenticated default, disabled mode, and reserved supporter-entitlement mode.
  - Add search backend settings for `auto`, ParadeDB, Meilisearch, and `tsvector`, plus optional external index synchronization.
  - Add point lookup bounded wait, status sync intervals, shared upstream budget, and catalog priority settings.
  - Startup validation fails when the configured search backend cannot be used.
  - The completed configuration lets tests construct app, worker, and fake provider graphs without external credentials.
  - _Requirements: 1.1, 1.2, 1.3, 1.5, 3.1, 3.2, 3.4, 6.1, 6.2, 6.5, 6.6, 10.7_
  - _Boundary: Config_

- [x] 1.2 Add durable search input, coverage, and index state storage
  - Add schema for beatmapset-owned materialized search input, catalog coverage records, and external index state.
  - Add the preferred optional ParadeDB search index over declared materialized input.
  - Enforce non-null semantic identity for coverage and index state scopes.
  - The completed migration can be applied and rolled back on a PostgreSQL test database.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 7.1, 7.2, 7.3, 7.4, 8.4, 9.3, 9.5_
  - _Boundary: Persistence_

- [x] 1.3 Define the shared direct search field declaration
  - Define one code-owned declaration for searchable, filterable, sortable, and displayed fields.
  - Include artist, title, creator, source, tags, difficulty names, unicode artist, and unicode title as searchable fields.
  - Include status, mode, and beatmapset id as filterable fields.
  - Include last update and beatmapset id as sortable fields.
  - The completed declaration is consumed by both SQL search validation and optional external index settings.
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_
  - _Boundary: SearchIndexDefinition_

- [x] 2. Core search input and backend behavior
- [x] 2.1 Maintain materialized search input during beatmap metadata saves
  - Build one materialized search input per complete usable beatmapset.
  - Make incomplete, inactive, deleted, not submitted, or childless beatmapsets ineligible from source metadata.
  - Update search input state in the same durable consistency boundary as beatmap metadata saves.
  - Metadata saves are not reported as complete catalog updates when search input update fails.
  - The completed search input stays consistent with saved metadata in command repository tests.
  - _Requirements: 2.1, 8.1, 8.2, 8.3, 8.4, 8.5, 11.1, 11.2, 11.4, 11.5_
  - _Boundary: SearchProjection_

- [x] 2.2 (P) Implement the ParadeDB search backend
  - Search active beatmapsets by stable text, status, mode, and page inputs.
  - Return candidate beatmapset ids with ranking scores only.
  - Support fallback ordering for empty query and special listing requests.
  - Validate ParadeDB search capabilities before serving search traffic.
  - The completed backend can return ranked candidates without hydrating stable response bodies itself.
  - _Depends: 1.2, 1.3_
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 6.1, 6.3, 6.4, 6.5, 7.5, 12.3, 12.4, 12.5_
  - _Boundary: ParadeDBSearchBackend_

- [x] 2.3 (P) Implement optional external index synchronization
  - Apply the shared field declaration to the external index settings.
  - Index external documents only after metadata and search input changes are committed.
  - Record failed index updates for retry or rebuild.
  - Continue serving through a PostgreSQL backend when optional external index synchronization is unavailable.
  - Use `meilisearch-python-sdk` for Meilisearch settings, indexing, and search backend access.
  - The completed adapter never uses external document fields as stable response source data.
  - _Depends: 1.2, 1.3_
  - _Requirements: 6.2, 6.3, 6.4, 6.6, 7.1, 7.5, 7.6, 9.1, 9.2, 9.3, 9.4_
  - _Boundary: ExternalIndexBackend_

- [x] 2.4 Add search input and external index rebuild commands
  - Rebuild materialized search input from stored beatmap metadata.
  - Rebuild optional external index state from current metadata-derived documents.
  - Make rebuilds idempotent and operator-triggered, not app startup work.
  - The completed rebuild path can recover stale materialized search input or a stale external index.
  - _Depends: 2.1, 2.3_
  - _Requirements: 7.5, 8.1, 9.2, 9.3, 9.5_
  - _Boundary: DirectIndexingCommands_

- [x] 2.5 Add PostgreSQL tsvector SQL search fallback
  - Support `auto`, `paradedb`, `meilisearch`, and `tsvector` search backend configuration.
  - Prefer ParadeDB in automatic mode, then configured Meilisearch, and fix the process to tsvector only when higher-quality backends are unavailable.
  - Keep explicit ParadeDB startup validation strict when `pg_search` is missing, uncreated, or index fields are stale.
  - Validate tsvector fallback against the same materialized search input field declaration without adding a new migration.
  - The completed fallback keeps search available on PostgreSQL deployments without `pg_search`.
  - _Depends: 2.2_
  - _Requirements: 6.1, 6.3, 6.4, 6.5, 6.7, 6.8, 6.9, 7.1, 7.2, 7.3, 7.4_
  - _Boundary: DirectSearchBackend_

- [x] 3. Catalog synchronization and upstream priority
- [x] 3.1 Implement shared upstream budget and priority scheduling
  - Apply one request budget across point lookup, feed sync, and id range crawl work.
  - Give point lookup higher priority than background catalog crawl.
  - Delay low-priority catalog work when the budget is exhausted instead of blocking stable request handling.
  - Emit operator-visible diagnostics for sync delay, failure, and retry state.
  - The completed scheduler can be tested with concurrent point lookup and crawl requests.
  - _Requirements: 3.3, 3.4, 3.5, 3.6, 10.5, 10.6_
  - _Boundary: DirectCatalogScheduler_

- [x] 3.2 (P) Implement feed window catalog synchronization
  - Fetch configured status and sort feed windows through Beatmap Mirror metadata fetch paths.
  - Record source, status scope, sort or window identifier, observed id range, cursor or page marker, and completion time only after success.
  - Record failed feed windows without marking them covered.
  - The completed feed sync makes newly observed beatmapsets searchable after metadata saves complete.
  - _Depends: 3.1_
  - _Requirements: 2.2, 2.4, 2.6, 3.1, 3.2, 3.4, 3.6_
  - _Boundary: DirectFeedSync_

- [x] 3.3 (P) Implement explicit beatmapset id range crawl coverage
  - Process configured id chunks under the shared budget.
  - Record completed id range chunks with status scope, from id, to id, and completion time.
  - Record failed chunks without marking the range covered.
  - The completed id range crawl distinguishes guaranteed crawled chunks from feed-observed ranges.
  - _Depends: 3.1_
  - _Requirements: 2.3, 2.5, 2.6, 3.1, 3.2, 3.4, 3.6_
  - _Boundary: DirectRangeCrawl_

- [x] 4. Stable search and point lookup use-cases
- [x] 4.1 Implement direct search access policy and request parsing
  - Authenticate stable users before search or point lookup work begins.
  - Apply authenticated default, disabled, and reserved supporter-entitlement policy decisions.
  - Expose the stable Supporter bit at login when authenticated direct access is enabled.
  - Keep friend, country, and selected-mods leaderboard categories usable when the client exposes supporter features.
  - Parse stable search parameters for text query, status, mode, and page.
  - Reject unauthenticated or denied requests without exposing catalog data.
  - The completed parser produces typed direct search requests for valid stable query strings.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 4.1, 4.2_
  - _Boundary: DirectAccessAndParsing_

- [x] 4.2 Implement direct search query and metadata hydration
  - Recognize `Newest`, `Top Rated`, and `Most Played` as special listing requests rather than literal text.
  - Search through the configured backend and hydrate final beatmapsets from Beatmap Mirror metadata.
  - Exclude incomplete, childless, inactive, deleted, or not submitted beatmapsets.
  - Use bounded upstream search to supplement local misses, incomplete pages, coverage gaps, and page 0 refreshes.
  - The completed query returns stable-ready result models with count sentinel information.
  - _Depends: 2.2, 4.1_
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.1, 5.4, 5.5, 5.6, 6.3, 6.4, 11.2, 12.3, 12.4, 12.5_
  - _Boundary: DirectSearchQuery_

- [x] 4.3 Implement point lookup with bounded wait
  - Resolve point lookup by beatmapset id, beatmap id, checksum, and normalized beatmap link target.
  - Request metadata fetch when lookup metadata is missing.
  - Wait up to the configured limit, defaulting to five seconds.
  - Return stable-compatible empty response for unresolved, inactive, deleted, not submitted, or incomplete beatmapsets.
  - The completed lookup leaves background fetch work eligible after timeout.
  - _Depends: 3.1, 4.1_
  - _Requirements: 5.2, 5.4, 5.5, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 11.1, 11.3, 11.4, 12.2_
  - _Boundary: DirectPointLookup_

- [x] 4.4 Implement stable direct response formatting
  - Format search responses as count line plus stable beatmapset rows with child difficulty summaries.
  - Format point lookup responses as one stable beatmapset row or empty body.
  - Sanitize delimiters and newlines from upstream text fields.
  - Hide stale, partial, source, coverage, and index diagnostics from stable response bodies.
  - The completed formatter preserves stable row shape for search and point lookup contract tests.
  - _Depends: 4.2, 4.3_
  - _Requirements: 4.5, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 10.6, 11.3, 12.1, 12.2_
  - _Boundary: StableDirectFormatter_

- [x] 5. Runtime integration
- [x] 5.1 Wire stable web legacy routes and providers
  - Register `/web/osu-search.php` and `/web/osu-search-set.php` on the stable web legacy host route.
  - Add endpoint adapters, lifespan state, and provider graph wiring for direct handlers.
  - Preserve existing bancho, getscores, replay, score submit, registration, and health routes.
  - The completed app routes authenticated stable direct requests to DI-resolved handlers.
  - _Depends: 4.4_
  - _Requirements: 1.1, 1.4, 4.1, 5.1, 5.2, 10.1, 10.2, 10.3_
  - _Boundary: StableWebLegacyIntegration_

- [x] 5.2 Wire catalog, index, and rebuild worker jobs
  - Register task payload adapters for feed sync, id range crawl, external index update, and rebuild.
  - Validate primitive job payloads before invoking command use-cases.
  - Report missing worker runtime dependencies as observable job failures.
  - The completed worker can execute direct catalog and index jobs without importing SQLAlchemy models inside job adapters.
  - _Depends: 2.4, 3.2, 3.3_
  - _Requirements: 3.3, 3.4, 3.5, 3.6, 9.1, 9.3, 9.5_
  - _Boundary: OsuDirectJobs_

- [x] 6. Validation and compatibility coverage
- [x] 6.1 Add unit coverage for domain, search input, query, and formatter behavior
  - Verify access policy, special query parsing, field declarations, delimiter sanitation, count sentinel, and fallback ordering.
  - Verify search input activation and disabling for usable, childless, inactive, deleted, and not submitted beatmapsets.
  - Verify point lookup target normalization and timeout-to-empty behavior.
  - The completed unit tests fail if stable direct search starts exposing partial diagnostics or childless sets.
  - _Requirements: 1.1, 1.2, 1.3, 1.5, 4.3, 4.4, 4.5, 5.3, 5.4, 5.5, 7.1, 7.2, 7.3, 7.4, 8.2, 8.3, 10.4, 10.6, 10.7, 11.1, 11.2, 11.3, 12.3, 12.4, 12.5_
  - _Boundary: OsuDirectUnitTests_

- [x] 6.2 Add repository and backend integration coverage
  - Verify metadata save and search input update share one durable consistency boundary.
  - Verify search backends return candidate ids and scores and final hydration reads metadata.
  - Verify coverage records distinguish completed, failed, feed-observed, and id-range crawled records.
  - Verify optional external index failure records retry state while SQL search remains usable.
  - The completed integration tests fail when search input drift or backend-source-of-truth drift is introduced.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.4, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 8.1, 8.4, 8.5, 9.1, 9.2, 9.3, 9.4, 9.5_
  - _Boundary: OsuDirectIntegrationTests_

- [x] 6.3 Add stable endpoint contract coverage
  - Verify `/web/osu-search.php` returns count plus stable rows for authenticated users.
  - Verify `/web/osu-search-set.php` resolves by `s`, `b`, and `c`.
  - Verify unauthenticated or denied requests do not expose catalog data.
  - Verify point lookup miss returns `200` empty body after bounded wait.
  - The completed contract tests preserve existing stable web routes while adding direct routes.
  - _Requirements: 1.1, 1.2, 1.4, 4.1, 4.2, 5.1, 5.2, 5.6, 10.1, 10.2, 10.3, 10.5, 10.6, 11.3, 12.1, 12.2_
  - _Boundary: StableDirectContractTests_

- [x] 6.4 Add recovery and scheduling validation
  - Verify point lookup work is prioritized over feed and range crawl under shared budget pressure.
  - Verify local misses and coverage gaps use bounded upstream search without making the stable response depend on persisted external documents.
  - Verify search input and external index rebuilds are idempotent and operator-triggered.
  - Verify app startup validates the configured search backend and does not rebuild indexes automatically.
  - The completed validation covers the production recovery paths described by the design.
  - _Requirements: 3.3, 3.4, 3.5, 3.6, 4.6, 6.5, 9.2, 9.3, 9.5, 10.5, 10.6_
  - _Boundary: OsuDirectRecoveryTests_
