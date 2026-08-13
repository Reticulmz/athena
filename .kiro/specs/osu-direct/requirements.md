# Requirements Document

## Introduction

Athena needs osu!direct-compatible stable search and beatmapset pickup behavior so stable clients can browse known beatmapsets, inspect single beatmapsets from now-playing or direct links, and get consistent empty results when metadata is unavailable. The current Beatmap Mirror Service already owns beatmap metadata resolution and file warmup; this feature adds the searchable catalog, stable direct response behavior, coverage tracking, and index maintenance needed to expose that metadata through stable osu!direct endpoints.

This specification defines user-visible and operator-visible behavior for osu!direct search, hybrid upstream search supplementation, search catalog coverage, point lookup, search backend selection, rebuild/recovery, and deferred download/rating concerns. It does not implement `.osz` package download caching or a rating system.

## Boundary Context

- **In scope**:
  - Stable `/web/osu-search.php` search responses for known beatmapsets.
  - Stable `/web/osu-search-set.php` point lookup responses by beatmapset id, beatmap id, and checksum.
  - Shared point lookup behavior for future now-playing and beatmap link entrances.
  - Search catalog coverage tracking for feed windows and explicit beatmapset id ranges.
  - Configurable search access policy with authenticated access as the default.
  - Configurable search backend selection across ParadeDB, Meilisearch, and PostgreSQL `tsvector`, plus optional external index synchronization.
  - Materialized search input, backend index field declarations, rebuild behavior, and operator diagnostics.
  - Worker priority behavior for point lookup, catalog feed sync, and id range crawl.

- **Out of scope**:
  - `.osz` package download implementation and download cache.
  - Rating collection, rating-based ranking, and playcount-based ranking.
  - Stable score submission, getscores, leaderboard, PP, or file warmup response changes.
  - WebUI, admin UI, and public API surfaces for osu!direct management.
  - Supporter entitlement billing or perk implementation.
  - Client-side song select filters such as AR, OD, CS, HP, BPM, or length.

- **Adjacent expectations**:
  - Beatmap Mirror remains the source of truth for beatmapset and beatmap metadata.
  - Beatmap file warmup and `.osu` attachment behavior remain owned by Beatmap Mirror and related worker jobs.
  - Future now-playing and beatmap link handling should reuse the same point lookup behavior but may expose different chat or API responses.
  - Future rating and playcount systems may replace the temporary handling of `Top Rated` and `Most Played`.

## Requirements

### Requirement 1: Stable osu!direct Access

**Objective:** As an operator, I want osu!direct access to be policy-controlled, so that deployments can choose whether stable clients may use direct search.

#### Acceptance Criteria

1. The osu!direct feature shall default to allowing authenticated stable users to use osu!direct search and point lookup.
2. Where osu!direct access is disabled, the osu!direct feature shall reject search and point lookup requests without exposing catalog data.
3. Where a future supporter-entitlement policy is configured, the osu!direct feature shall be able to deny access for users that do not satisfy that policy.
4. When an unauthenticated stable request reaches osu!direct endpoints, the osu!direct feature shall return the stable-compatible authentication failure behavior for that endpoint.
5. The osu!direct feature shall keep access policy decisions separate from search result ranking and catalog coverage state.
6. When authenticated access is enabled, the stable login response shall expose the client-visible Supporter bit required to display stable supporter features without granting server-side Supporter privileges.

### Requirement 2: Search Catalog and Coverage

**Objective:** As an operator, I want Athena to know which beatmapset metadata ranges have been collected, so that search results can be understood as cached catalog results rather than live upstream search.

#### Acceptance Criteria

1. When beatmapset metadata is saved, the osu!direct feature shall make the beatmapset eligible for search catalog indexing only when it has at least one usable child beatmap.
2. When a catalog feed window is synchronized, the osu!direct feature shall record the source, status scope, sort or window identifier, observed beatmapset id range, cursor or page marker when available, and completion time.
3. When an explicit beatmapset id range crawl completes, the osu!direct feature shall record the completed id chunk, status scope, from id, to id, and completion time.
4. If a feed window synchronization fails before completion, the osu!direct feature shall not mark that window as covered.
5. If an id range crawl chunk fails before completion, the osu!direct feature shall not mark that id range chunk as covered.
6. The osu!direct feature shall distinguish feed-observed ranges from explicit id-range coverage so operators can tell whether a range was guaranteed by crawl or merely observed from a feed.

### Requirement 3: Catalog Synchronization Policy

**Objective:** As an operator, I want catalog synchronization to be configurable and rate-aware, so that osu!direct remains useful without exhausting upstream limits.

#### Acceptance Criteria

1. The osu!direct feature shall allow status-specific synchronization intervals for catalog feed and id range work.
2. The default synchronization interval shall be the same for all beatmap statuses.
3. When point lookup, feed synchronization, and id range crawl compete for upstream work, the osu!direct feature shall prioritize point lookup over catalog crawl work.
4. The osu!direct feature shall apply a shared upstream request budget across point lookup, feed synchronization, and id range crawl work.
5. If the shared request budget is exhausted, the osu!direct feature shall delay lower-priority catalog work rather than blocking stable request handling.
6. The osu!direct feature shall make catalog sync delay, failure, and retry state visible to operators.

### Requirement 4: Search Query Behavior

**Objective:** As a stable player, I want osu!direct search to return stable-compatible results from Athena's known catalog, so that the client can browse beatmapsets predictably.

#### Acceptance Criteria

1. When a stable client searches with text, status, mode, and page parameters, the osu!direct feature shall search the known catalog using those stable inputs.
2. When a stable client searches with an empty text query, the osu!direct feature shall return a normal catalog listing for the requested status, mode, and page.
3. When a stable client searches for `Newest`, the osu!direct feature shall treat it as a special listing request rather than a literal text query.
4. When a stable client searches for `Top Rated` or `Most Played`, the osu!direct feature shall treat it as a special listing request and use the documented fallback ordering until rating and playcount ranking are implemented.
5. When the catalog has more results beyond the current stable page, the osu!direct feature shall return a stable-compatible count sentinel indicating more results.
6. The osu!direct feature shall not implement client-side song select filters such as AR, OD, CS, HP, BPM, or length in the stable osu!direct search query.
7. When local search results are incomplete, the osu!direct feature shall use configured upstream search providers within a bounded wait and merge usable upstream beatmapsets into the stable response.
8. When completed id-range coverage is missing or local candidates fall outside completed coverage, the osu!direct feature shall use configured upstream search providers even if the local page is full.
9. When page 0 is requested again after the configured refresh interval, the osu!direct feature shall refresh from configured upstream search providers to improve first-page freshness.

### Requirement 5: Stable Response Shape

**Objective:** As a stable player, I want direct search rows to be formatted in the stable client format, so that the osu!direct panel can parse them.

#### Acceptance Criteria

1. When search returns beatmapsets, the osu!direct feature shall format each row as a stable direct beatmapset row with child difficulty summaries.
2. When point lookup returns a beatmapset, the osu!direct feature shall format the response as a single stable direct beatmapset row.
3. The osu!direct feature shall sanitize stable row delimiter characters from upstream text fields before returning a response.
4. The osu!direct feature shall exclude beatmapsets with no usable child beatmaps from search and point lookup responses.
5. The osu!direct feature shall hide stale, partial, coverage, source, and index diagnostics from stable response bodies.
6. If a response cannot be safely represented in the stable direct row format, the osu!direct feature shall omit that beatmapset from the stable response.

### Requirement 6: Search Backend Selection

**Objective:** As an operator, I want a configurable search backend, so that Athena can use the deployment's preferred search infrastructure while keeping stable responses consistent.

#### Acceptance Criteria

1. The osu!direct feature shall support configurable search backend values `auto`, `paradedb`, `meilisearch`, and `tsvector`.
2. The osu!direct feature shall support an optional external index synchronization backend.
3. The osu!direct feature shall require the configured search backend to expose beatmapset candidate ids and ranking scores rather than stable response bodies.
4. When a search backend returns candidate ids, the osu!direct feature shall hydrate final stable responses from the beatmap metadata source of truth.
5. If the explicitly configured search backend is unavailable, the osu!direct feature shall fail startup or configuration validation before accepting search traffic.
6. If the optional external index synchronization backend is unavailable and search is not explicitly configured to use Meilisearch, the osu!direct feature shall continue to serve search through an available PostgreSQL backend.
7. Where the search backend is configured as automatic, the osu!direct feature shall prefer ParadeDB `pg_search`, then configured Meilisearch, and fall back to PostgreSQL `tsvector` before accepting search traffic.
8. Where the search backend is explicitly configured as ParadeDB, the osu!direct feature shall fail startup if `pg_search` is not installed, not created, or missing required index fields.
9. Where the search backend is explicitly configured as `tsvector`, the osu!direct feature shall not require the `pg_search` extension.
10. Where the search backend is explicitly configured as `meilisearch`, the osu!direct feature shall require Meilisearch external index configuration and fail startup if Meilisearch is unavailable.

### Requirement 7: Search Index Field Declaration

**Objective:** As an operator, I want search fields to be declared consistently, so that SQL and external search indexes do not drift from each other.

#### Acceptance Criteria

1. The osu!direct feature shall declare searchable, filterable, sortable, and displayed fields for the beatmapset search document.
2. The osu!direct feature shall include artist, title, creator, source, tags, difficulty names, unicode artist, and unicode title in the initial searchable fields.
3. The osu!direct feature shall include status, mode, and beatmapset id in the initial filterable fields.
4. The osu!direct feature shall include last update and beatmapset id in the initial sortable fields.
5. When a search field declaration changes, the osu!direct feature shall require materialized search input and backend index revalidation.
6. The osu!direct feature shall not infer new searchable fields from arbitrary metadata without an explicit declaration.

### Requirement 8: Search Input Consistency

**Objective:** As an operator, I want the materialized search input to stay consistent with saved metadata, so that SQL search does not miss newly saved beatmapsets.

#### Acceptance Criteria

1. When beatmapset metadata is saved, the osu!direct feature shall update materialized search input in the same durable consistency boundary as the metadata save.
2. When a beatmapset becomes incomplete, inactive, deleted, or not submitted, the osu!direct feature shall make that beatmapset ineligible for search from source metadata and child beatmaps.
3. When a beatmapset has searchable metadata but no usable child beatmaps, the osu!direct feature shall keep it out of search results.
4. The osu!direct feature shall treat materialized search input as index input and not as the source of truth for stable response hydration.
5. If materialized search input update fails during metadata save, the osu!direct feature shall not expose the metadata save as a fully successful catalog update.

### Requirement 9: External Index Synchronization

**Objective:** As an operator, I want external index synchronization to be recoverable, so that external search failures do not corrupt the catalog.

#### Acceptance Criteria

1. When materialized search input changes are committed, the osu!direct feature shall request external index updates after the metadata and search input changes are durable.
2. If an external index update fails, the osu!direct feature shall keep SQL search available.
3. If an external index update fails, the osu!direct feature shall record the failed index state for retry or rebuild.
4. When the external index is stale, the osu!direct feature shall not use external index document fields as stable response source data.
5. The osu!direct feature shall provide an operator-triggered rebuild path from stored metadata to materialized search input and external index state.

### Requirement 10: Point Lookup

**Objective:** As a stable player, I want single beatmapset lookup to work for now-playing, links, and direct pickup, so that not-yet-listed beatmapsets can become available after lookup.

#### Acceptance Criteria

1. When point lookup is requested by beatmapset id, the osu!direct feature shall resolve the matching beatmapset metadata when it is known.
2. When point lookup is requested by beatmap id, the osu!direct feature shall resolve the owning beatmapset metadata when it is known.
3. When point lookup is requested by checksum, the osu!direct feature shall resolve the owning beatmapset metadata when it is known.
4. When point lookup receives a beatmap link in a future entrance, the osu!direct feature shall normalize the link to beatmapset id or beatmap id before resolving.
5. If point lookup metadata is missing, the osu!direct feature shall request a metadata fetch and wait up to the configured bounded wait limit.
6. If point lookup metadata is still unavailable after the bounded wait limit, the osu!direct feature shall return the stable-compatible empty response and leave the background fetch eligible to continue.
7. The default point lookup bounded wait limit shall be five seconds.

### Requirement 11: Inactive and Tombstone Handling

**Objective:** As a stable player, I want inactive or deleted beatmapsets to disappear from direct search, so that search results do not contain unusable entries.

#### Acceptance Criteria

1. When upstream metadata indicates a beatmapset is deleted, inactive, or not submitted, the osu!direct feature shall record that state for future lookup decisions.
2. While a beatmapset is deleted, inactive, or not submitted, the osu!direct feature shall exclude it from search responses.
3. While a beatmapset is deleted, inactive, or not submitted, the osu!direct feature shall return the stable-compatible empty point lookup response.
4. If a deleted, inactive, or not submitted beatmapset is requested repeatedly, the osu!direct feature shall avoid repeatedly treating it as an uncached unknown beatmapset.
5. When a later authoritative refresh changes an inactive beatmapset into a usable state, the osu!direct feature shall make it eligible for search again.

### Requirement 12: Deferred Download and Rating Scope

**Objective:** As an operator, I want temporary direct behavior to be explicit, so that future download and rating work can replace it cleanly.

#### Acceptance Criteria

1. The osu!direct feature shall not implement `.osz` package download or download caching.
2. When point lookup discovers metadata for a not-yet-crawled beatmapset, the osu!direct feature shall not require `.osz` package availability before returning the metadata response.
3. The osu!direct feature shall document that `Top Rated` ordering is a fallback until a rating system exists.
4. The osu!direct feature shall document that `Most Played` ordering is a fallback until playcount-based direct ranking is implemented.
5. When a future rating or playcount ranking system is implemented, the osu!direct feature shall allow those ranking sources to replace the documented fallback without changing stable wire format.
