# beatmap-mirror Gap Analysis

Generated at: 2026-06-04T19:43:28+09:00

Status note: requirements were auto-approved during `$kiro-spec-design beatmap-mirror -y`. This analysis informed the generated design.

## Scope Analyzed

The generated requirements define a shared Beatmap Mirror Service that resolves beatmap and beatmapset metadata, uses official osu! API sources as authoritative, supports mirror fallback, stores `.osu` file bodies through `blob-storage`, separates official status from local override status, and exposes eligibility for score submission and leaderboard features.

## Current State Investigation

### Existing Assets

- `src/osu_server/config.py`
  - `AppConfig` is the central typed configuration object using pydantic-settings.
  - Existing required runtime config is currently `database_url` and `valkey_url`.
  - New beatmap provider credentials, mirror trust policy, source toggles, and refresh timing settings fit here.

- `src/osu_server/composition/service_registry.py`
  - Registers repositories and services by environment.
  - Test environment uses in-memory repositories and state stores.
  - Production/development use SQLAlchemy repositories and Valkey-backed state stores.
  - Beatmap mirror should follow this pattern: interface repository, in-memory test repository, SQLAlchemy repository, service registration in composition.

- `src/osu_server/worker.py`, `src/osu_server/jobs/__init__.py`, `src/osu_server/jobs/chat_persistence.py`, `src/osu_server/infrastructure/jobs/registry.py`
  - taskiq is already the background job boundary.
  - Jobs are registered through a local `JobRegistry` and attached to a broker.
  - Worker runtime currently builds only chat persistence runtime.
  - Beatmap metadata fetch and `.osu` file fetch jobs can reuse this registration pattern, but worker runtime composition must be expanded.

- `src/osu_server/repositories/interfaces/*`, `repositories/memory/*`, `repositories/sqlalchemy/*`
  - Repository pattern is established.
  - SQLAlchemy repositories open short sessions per method and map ORM models to domain dataclasses.
  - In-memory repositories are used for tests rather than AsyncMock-heavy tests.

- `src/osu_server/repositories/sqlalchemy/models/*`
  - ORM models use SQLAlchemy 2.0 `Mapped` and `mapped_column`.
  - Domain models do not depend on ORM models.
  - Beatmap models should follow this pattern and be imported for Alembic discovery.

- `src/osu_server/infrastructure/state/interfaces/packet_queue.py` and Valkey/memory implementations
  - Per-user packet queue already exists for later score-result notifications.
  - Beatmap mirror itself should not enqueue Bancho packets, but score-submission can later use the packet queue after consuming beatmap results.

- `.kiro/specs/blob-storage/*`
  - `blob-storage` is specified as the upstream storage boundary.
  - It explicitly leaves domain-specific attachment tables to downstream features.
  - Beatmap mirror therefore owns beatmap file attachment records while delegating bytes to the Blob Storage Service.

### Existing Beatmap Capability

No existing Athena beatmap domain, repository, provider, metadata cache, checksum lookup, `.osu` attachment, or rank-status service was found. The only current beatmap references are protocol fields such as player status `beatmap_md5` and `beatmap_id`, plus roadmap/spec notes.

## Requirement-to-Asset Map

| Requirement Area | Existing Assets | Gap |
|---|---|---|
| 1. Metadata resolution | Repository/service patterns | Missing beatmap and beatmapset domain models, lookup repository, and resolver service |
| 2. Cache-first behavior | SQLAlchemy + in-memory repository patterns | Missing persisted beatmap cache, stale/pending/failed result model, bounded wait behavior |
| 3. Source priority | `httpx` dependency exists; config pattern exists | Missing official provider abstraction, v2/v1 adapters, mirror adapter, source failure normalization |
| 4. Provider configuration | `AppConfig` validation pattern | Missing osu! API credentials/config validation and fake-provider test path |
| 5. Mirror trust policy | Config pattern | Missing mirror trust config and eligibility behavior |
| 6. `.osu` file availability | `blob-storage` spec, repository pattern | Missing beatmap file attachment table/model/repository, `.osu` checksum verification behavior, official/legacy file source support, and optional last-resort community mirror file URL support |
| 7. Fetch state reporting | Domain dataclass pattern | Missing result objects for metadata/file status, source, verification, timings |
| 8. Status freshness rules | None specific | Missing status enum, freshness policy, refresh scheduling/request behavior |
| 9. Official/local override | Roadmap notes | Missing explicit status separation and effective-status calculation |
| 10. Approved handling | Requirements only | Missing legacy Approved representation and local override rejection |
| 11-13. Score eligibility | Requirements only | Missing eligibility projection service/value object |
| 14. Fetch idempotency | taskiq, DB constraints possible | Missing idempotency model for concurrent fetches and duplicate attachments |
| 15. Downstream boundary | Existing layer contracts | Needs design to keep score/rank/Bancho packet behavior out of beatmap mirror |
| 16. Observability | structlog exists | Missing beatmap-specific source/fetch/checksum/eligibility diagnostic events |

## External Dependency Research

### Official osu! API Surface

The official osu! API v2 documentation includes:

- `GET /beatmaps/lookup` with `checksum`, `filename`, and `id` query parameters.
- `GET /beatmaps` with repeated `ids[]`, up to 50 beatmaps at once.
- `GET /beatmaps/{beatmap}`.
- `GET /beatmapsets/{beatmapset}` and beatmapset lookup endpoints.

Source: https://osu.ppy.sh/docs/

Implication: requirements for beatmap id and checksum lookup are supported by official API v2. Design still needs to verify the exact wrapper method names and response fields for the selected Python client.

### Python osu! API Client Candidates

- `ossapi`
  - PyPI describes complete API v2 and v1 coverage, with sync and async v2 clients.
  - PyPI metadata lists GNU Affero General Public License v3.
  - Source: https://pypi.org/project/ossapi/

- `aiosu`
  - PyPI describes async v1 and v2 clients and Python `>=3.10,<4.0`.
  - PyPI metadata lists `GPL-3.0-or-later`.
  - Source: https://pypi.org/project/aiosu/

- `osu.py`
  - Documentation describes a Python wrapper for osu! API v2.
  - Source: https://osupy.readthedocs.io/

Implication: design should not commit to a runtime dependency before license compatibility is reviewed. The provider adapter boundary is important regardless of the final choice. A thin internal HTTP client may remain a fallback if suitable permissive-library coverage is not available.

### Existing Private Server Reference

`bancho.py` separates beatmap metadata fetching from `.osu` file fetching and verifies `.osu` md5 before using the file. It also has cache-first beatmap behavior. Athena should preserve the separation but adapt storage to `blob-storage`.

Reference source: https://github.com/osuAkatsuki/bancho.py/blob/master/app/objects/beatmap.py

Additional finding: `bancho.py` uses `old.ppy.sh/api/get_beatmaps` when an osu! API key is configured and `osu.direct/api/get_beatmaps` as a metadata fallback when no key is provided. For `.osu` bodies, it fetches `old.ppy.sh/osu/{beatmap_id}`, retries the fetch up to three attempts, returns unavailable on HTTP status errors, checks the expected md5, and writes the file to local disk. It does not appear to fall back to a community mirror for `.osu` bodies. Athena should follow the same source-separation idea: prefer official or legacy direct `.osu` file sources first, store bodies through `blob-storage`, and reserve configurable community mirror or archive-extraction fallback for later or last-resort use.

### Direct `.osu` File Endpoint Check

Manual HEAD checks on 2026-06-04 confirmed that both current and legacy direct file URLs return `.osu` attachment responses for beatmap id `75`:

- `https://osu.ppy.sh/osu/75`
  - HTTP 200.
  - `content-type: text/plain;charset=UTF-8`.
  - `content-disposition: attachment; filename="Kenji Ninuma - DISCOPRINCE (peppy) [Normal].osu"`.
- `https://old.ppy.sh/osu/75`
  - HTTP 200.
  - `content-type: text/plain;charset=UTF-8`.
  - Same `.osu` attachment filename.

Implication: design should prefer `https://osu.ppy.sh/osu/{beatmap_id}` as the first direct `.osu` file source, with `https://old.ppy.sh/osu/{beatmap_id}` as a legacy-compatible fallback if needed. The fetched body must still be verified against expected md5 before attachment.

Rate-limit implication: community mirror fallback should be considered primarily for temporary direct-source unavailability such as HTTP 429, timeout, or upstream 5xx. A 404/not found response should not automatically fall back as if the map were valid elsewhere unless design explicitly defines that behavior.

### Community Mirror Candidate: catboy.best

`catboy.best` is a Mino osu! beatmap mirror candidate. The public site describes Mino as an osu! beatmap mirror with osu!direct compatibility and lists `central.catboy.best`, `us.catboy.best`, and `sg.catboy.best` server locations.

Source: https://osz.direct/about

Manual endpoint checks on 2026-06-04:

- `HEAD https://catboy.best/osu/75`
  - Returned HTTP 404 with `application/json`.
- `GET https://catboy.best/osu/75` with a browser-like user agent
  - Returned HTTP 200.
  - `content-type: text/plain`.
  - Body began with `osu file format v3`.

Implication: `https://catboy.best/osu/{beatmap_id}` is a viable candidate for direct `.osu` mirror fallback, but design should not rely on `HEAD` for availability checks. Use `GET` and verify the fetched body against expected md5 before attachment. The provider shape should also allow alternate regional hosts or a URL template rather than hard-coding only `catboy.best`.

## Implementation Options

### Option A: Extend Existing Components

Extend `AppConfig`, `service_registry`, `worker_runtime`, and job registration while placing beatmap logic directly into existing service/job modules.

Pros:
- Minimal new composition patterns.
- Fastest path for a first implementation.
- Reuses existing taskiq, SQLAlchemy, and config conventions.

Cons:
- Existing composition files are already broad and could become harder to reason about.
- Beatmap source/freshness/status logic is distinct enough that placing too much inside existing modules would blur responsibilities.
- Testing source behavior would be less isolated.

Fit: Useful only for wiring and runtime extension. Not sufficient for the feature core.

### Option B: Create New Beatmap Components

Create dedicated domain models, repository interfaces/implementations, provider interfaces/adapters, service, jobs, and tests.

Pros:
- Clear ownership of beatmap status, source priority, fetch state, and eligibility rules.
- Easy to test provider behavior and repository contracts in isolation.
- Aligns with the project's repository/service/domain layering.
- Leaves score-submission and rank-management out of boundary.

Cons:
- More files and interfaces to design.
- Requires deliberate composition and worker-runtime integration.
- Provider adapter choice and licensing still need research.

Fit: Best fit for the domain complexity, with existing infrastructure reused at the edges.

### Option C: Hybrid Approach

Create new beatmap core components, but extend existing composition, taskiq registry, config, and future blob-storage service wiring.

Pros:
- Keeps beatmap logic isolated while respecting established application wiring.
- Reuses existing test/runtime patterns.
- Allows worker jobs to share the same taskiq registry and runtime lifecycle.
- Reduces risk of coupling score-submission to external source details.

Cons:
- Requires careful design of worker runtime dependencies.
- Needs clear event/result shapes to avoid leaking provider library types.
- Must coordinate with `blob-storage`, which is specified but not implemented yet.

Fit: Preferred design direction to evaluate in detail.

## Constraints and Integration Challenges

- `blob-storage` is a prerequisite but is not yet implemented in the codebase. Beatmap mirror implementation will either need to wait for it or use a temporary fake only in tests.
- Repository pattern and import-linter constraints mean jobs and services should not directly use SQLAlchemy models or sessions.
- Domain models should remain standard-library dataclasses and must not depend on provider-library response objects or Pydantic.
- Worker runtime currently builds only chat service dependencies. Beatmap jobs need a new worker-side runtime builder or a generalized worker composition approach.
- Bounded wait behavior needs design care so caller waits do not hold DB transactions or connections open.
- Fetch idempotency likely needs persisted fetch state or uniqueness constraints. The exact design is not requirements-level and should be decided in design.
- Official status vs local override affects future rank management. The schema and service shape must avoid official refresh overwriting local override data.
- Mirror trust is operationally sensitive. The default should remain safe, and diagnostics should expose when mirror data affects eligibility.
- Community mirror URL support should be treated as a last-resort file-source configuration concern. Requirements now prefer official or legacy `.osu` file sources first; osu!direct-compatible mirror URLs and osz archive extraction are fallback options whose endpoint shape and behavior remain design-phase work.
- Fallback trigger semantics need care. Rate limits, timeouts, and upstream server failures are good candidates for community mirror fallback; permanent not-found responses may need different handling to avoid accepting unrelated mirror data.

## Complexity and Risk

- Effort: L (1-2 weeks)
  - The feature spans domain modeling, persistence, external providers, worker jobs, blob attachment, config, and non-trivial status rules.

- Risk: Medium-High
  - The main risks are external API client licensing, source behavior differences, `.osu` fetch/checksum behavior, and coordination with not-yet-implemented `blob-storage`.

## Design Phase Recommendations

1. Prefer a hybrid approach: new beatmap core components plus existing composition/taskiq/config patterns.
2. Define internal provider interfaces before choosing an osu! API library, so provider library types do not leak into services or domain models.
3. Carry forward license review as a design blocker for adding `ossapi`, `aiosu`, or `osu.py` as a direct dependency.
4. Design beatmapset, beatmap, status, checksum lookup, fetch state, and file attachment persistence together; these are strongly coupled.
5. Keep `.osu` file fetch separate from metadata fetch, following the existing private-server reference and the user-approved worker split.
6. Define effective-status and eligibility as a small domain service/value object so score-submission and rank-management do not duplicate status rules.
7. Treat score result responses, pending score retry, Bancho polling notifications, and leaderboard updates as downstream design work.

## Research Needed for Design

- Confirm selected osu! API client license compatibility with Athena distribution goals.
- Verify exact v2/v1 wrapper method names and response fields for beatmap lookup, beatmapset lookup, status, checksum, and md5.
- Select and document the first external mirror provider and its response/status semantics.
- Confirm whether `https://osu.ppy.sh/osu/{beatmap_id}` should be the primary direct `.osu` file source and whether `https://old.ppy.sh/osu/{beatmap_id}` should remain a fallback.
- Determine whether osu!direct-compatible community mirror URLs should be supported in this spec as a last-resort `.osu` fallback or deferred to the future osu!direct spec.
- Define which direct `.osu` source failures trigger community mirror fallback: 429, timeout, 5xx, connection errors, and whether 404 should be excluded.
- Evaluate `https://catboy.best/osu/{beatmap_id}` as the first community `.osu` mirror fallback candidate, including GET-only behavior, regional host support, and expected md5 verification.
- Determine whether osz archive extraction is worth designing as a future fallback, and what checksum guarantees are required before extracted `.osu` files become available.
- Determine persisted fetch-state strategy for idempotent metadata and file jobs.
- Determine exact enum mapping for osu! API v2, API v1, mirror, and Athena internal statuses.
- Confirm how `blob-storage` implementation exposes stream write/read and deduplication outcomes once implemented.

---

## Design Discovery Addendum

Generated at: 2026-06-04T20:01:59+09:00

### Summary

- **Feature**: `beatmap-mirror`
- **Discovery Scope**: Complex Integration
- **Key Findings**:
  - Athena has no existing beatmap implementation, but has repository, SQLAlchemy, taskiq, config, and packet queue patterns that fit a hybrid design.
  - Official osu! API v2 supports beatmap lookup by id/checksum and beatmapset lookup. Official rank status values include graveyard, wip, pending, ranked, approved, qualified, and loved.
  - Direct `.osu` retrieval works through `https://osu.ppy.sh/osu/{beatmap_id}` and `https://old.ppy.sh/osu/{beatmap_id}`. `catboy.best/osu/{beatmap_id}` is viable as GET-only mirror fallback.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Extend existing composition only | Add beatmap logic directly to existing services/jobs | Small initial surface | Blurs distinct beatmap responsibilities | Rejected for core logic |
| New beatmap subsystem | Dedicated domain, repository, providers, service, jobs | Clean ownership and testability | More files and wiring | Good fit for core |
| Hybrid | New beatmap core with existing config, repository, taskiq, and composition patterns | Clear boundary while reusing infrastructure | Requires careful worker runtime wiring | Selected |

## Design Decisions

### Decision: Use Provider Ports Before Committing to an osu! API Library

- **Context**: User prefers a Python osu! API library, but candidate packages surfaced license concerns.
- **Alternatives Considered**:
  1. Add `ossapi` directly.
  2. Add `aiosu` directly.
  3. Build provider ports and select a concrete adapter after license approval.
- **Selected Approach**: Define `BeatmapMetadataProvider` and `BeatmapFileProvider` ports. Use an approved client adapter if license-compatible; otherwise use the existing `httpx` dependency for a thin official API adapter.
- **Rationale**: Keeps domain and service code stable while avoiding premature GPL or AGPL dependency commitment.
- **Trade-offs**: Design has one extra adapter layer, but provider-library types cannot leak into domain code.
- **Follow-up**: License review remains mandatory before adding a new osu! API client dependency.

### Decision: Prefer Direct `.osu` Sources Before Community Mirror

- **Context**: `https://osu.ppy.sh/osu/{beatmap_id}` and `https://old.ppy.sh/osu/{beatmap_id}` return `.osu` attachment responses.
- **Alternatives Considered**:
  1. Use community mirror first.
  2. Use official/current direct endpoint first, legacy second, mirror last.
  3. Download osz and extract `.osu`.
- **Selected Approach**: Use current direct endpoint first, legacy direct endpoint second, configured community mirror third, and leave osz extraction for future fallback.
- **Rationale**: Direct `.osu` endpoints avoid archive extraction and stay close to bancho.py's source separation.
- **Trade-offs**: Direct source rate limits can still happen, so mirror fallback remains useful for temporary failures.
- **Follow-up**: Treat 429, timeout, connection errors, and 5xx as fallback candidates; do not automatically fallback on 404.

### Decision: Persist Fetch State Instead of Requiring Fetch Completion Events

- **Context**: Requirements need pending, failed, stale, and available states. Downstream score-submission may later need asynchronous resumption.
- **Alternatives Considered**:
  1. Publish mandatory domain events for every fetch result.
  2. Store fetch state and let downstream features poll or subscribe later.
  3. Couple beatmap jobs directly to score-submission retry.
- **Selected Approach**: Persist fetch state in `beatmap_fetch_states`; no mandatory event delivery in this spec.
- **Rationale**: Keeps beatmap mirror independent from downstream score workflows and still supports bounded wait.
- **Trade-offs**: Downstream async wakeups are deferred to score-submission design.
- **Follow-up**: score-submission can add Valkey result notification without changing beatmap state ownership.

## Risks & Mitigations

- API client license mismatch - isolate behind provider ports and delay dependency addition.
- Direct source rate limiting - cache-first service, status refresh policy, and mirror fallback for temporary failures.
- Mirror data trust - default mirror status does not grant eligibility; md5 verification required for files.
- Blob storage dependency not implemented - keep beatmap file attachment design dependent on the Blob Storage Service contract and implement after blob-storage.

## References

- [osu! API v2 documentation](https://osu.ppy.sh/docs/) - beatmap lookup, beatmapset lookup, and rank status values.
- [bancho.py beatmap implementation](https://github.com/osuAkatsuki/bancho.py/blob/master/app/objects/beatmap.py) - cache-first metadata, direct `.osu` fetch, md5 verification.
- [ossapi PyPI](https://pypi.org/project/ossapi/) - candidate osu! API wrapper and license metadata.
- [aiosu PyPI](https://pypi.org/project/aiosu/) - candidate async osu! API wrapper and license metadata.
- [osu.py documentation](https://osupy.readthedocs.io/) - candidate osu! API v2 wrapper.
- [Mino about page](https://osz.direct/about) - catboy.best mirror context and osu!direct compatibility claim.
