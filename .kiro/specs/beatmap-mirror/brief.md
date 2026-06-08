# beatmap-mirror Brief

## Problem

Athena needs an authoritative beatmap metadata and `.osu` file resolution layer before score submission can be implemented safely. Score processing depends on beatmap identity, checksum verification, ranked status, leaderboard eligibility, and access to the `.osu` file for PP and star rating calculation. Without a dedicated beatmap mirror boundary, score submission, rank management, WebUI workflows, and future lazer compatibility would duplicate external API calls and status rules.

## Desired Outcome

Provide a beatmap cache and resolver that treats osu! API data as authoritative, uses mirrors only as fallback, stores `.osu` files through `blob-storage`, and exposes stable eligibility decisions to downstream score and leaderboard features.

The feature should support resolving beatmaps by `beatmap_id`, `beatmapset_id`, and checksum/md5. Cached DB records should be returned synchronously when usable. Missing, stale, mirror-sourced, or file-missing records should enqueue idempotent worker jobs and optionally allow callers to wait for a bounded time.

## Scope

### In

- Beatmap and beatmapset metadata persistence.
- Lookup by beatmap id, beatmapset id, and checksum/md5.
- Provider priority:
  - Primary: osu! API v2.
  - Fallback: osu! API v1.
  - Last resort: external mirror.
- Use of an external Python osu! API client through an Athena-owned provider adapter, with final library selection handled during design/research after license compatibility review.
- AppConfig-managed osu! API credentials.
- Development and production require osu! API credentials when API providers are enabled; tests use fake providers.
- Mirror-derived records are marked as fallback/unverified and should trigger an API refresh on later access.
- Configurable mirror trust policy:
  - Default: mirror status is not used for leaderboard or PP eligibility.
  - Operator override: mirror status may be used for eligibility when explicitly enabled.
- Separate worker jobs for metadata fetch and `.osu` file fetch.
- `.osu` file body storage through `blob-storage`.
- Beatmap-owned attachment table for `.osu` files, such as `beatmap_file_attachments`.
- `.osu` checksum verification before attaching a blob.
- Freshness rules by effective status:
  - `Ranked`, `Approved`, `Loved`: stable or very long refresh interval.
  - `Qualified`, `Pending`, `WIP`: shorter refresh interval.
  - `Graveyard`: longer refresh interval than pending-like states.
  - Mirror-sourced records: refresh from API on next access when possible.
- Separate official status and local override status:
  - `official_status`
  - `official_status_source`
  - `official_status_verified`
  - `local_status_override`
  - `effective_status`
- API refresh updates official status only and must not overwrite local overrides.
- `Approved` remains representable for official/legacy imports, but local rank management must not be able to assign it.
- Score-submission eligibility projection:
  - `accepts_scores`
  - `has_leaderboard`
  - `awards_ranked_pp`
  - `awards_loved_pp`
  - `requires_osu_file_for_pp`
  - `is_officially_verified`
- Initial eligibility:
  - `Ranked` and `Approved`: accepts scores, has leaderboard, awards ranked PP.
  - `Loved`: accepts scores, has leaderboard, awards loved PP.
  - `Qualified`: accepts scores, has leaderboard, no PP.
  - `Pending`, `WIP`, `Graveyard`, `NotSubmitted`, `Unknown`: no score acceptance, no leaderboard, no PP.
  - Failed scores are accepted only when the beatmap accepts scores; they are not leaderboard, best-score, ranked PP, or loved PP eligible.
- Service result should include fetch state, not only beatmap data:
  - metadata status: fresh, stale, pending fetch, failed.
  - file status: available, pending fetch, missing, failed.
  - source and verification flags.
  - last fetch and next refresh timestamps.
- Bounded wait support for callers, with a default expectation around 3 seconds and an upper bound around 5 seconds for higher-level specs.
- Domain or infrastructure events for metadata/file fetch completion, if useful for downstream retry and notification flows.

### Out

- Score submission payload parsing, score persistence, PP calculation, leaderboard update, pending score retry, and score result response formatting.
- WebUI screens for beatmap request or rank management.
- BanchoBot rank/request commands.
- Rank request queues and approval workflow.
- Full S3 blob backend implementation.
- Replay, screenshot, or image upload behavior.
- Final beatmap database column design. Exact tables, indexes, enum representation, constraints, and repository methods are design-phase work.

## Source and Existing Implementation Notes

- `bancho.py` separates beatmap metadata fetching from `.osu` file fetching and verifies the `.osu` md5 before use. Athena should preserve that separation while storing `.osu` bodies in `blob-storage` instead of direct feature-owned files.
- `bancho.py` also uses cache-first beatmap lookup behavior. Athena should use the database as the authoritative cache and leave memory caching as a future extension point.
- Existing Athena polling uses a per-user packet queue. Score-submission can later emit result summary notifications through that queue, but beatmap-mirror should not know about score payloads or Bancho result packets.

## Downstream Notes

- `score-submission` should persist the received score payload before processing so a beatmap fetch delay cannot lose the score.
- `score-submission` should normally attempt a bancho.py-like result response when processing finishes inside its bounded async wait.
- If score processing exceeds the wait budget, it should return a queued/received/retrying response and continue asynchronously.
- Worker completion notification should use Valkey for short-lived result signaling, while the score DB remains the source of truth.
- Online polling notifications should be best-effort result summaries, not the authoritative score result.

## Dependencies

- Upstream: `blob-storage`
- Downstream: `score-submission`, `leaderboard`, `beatmap-rank-request`, `beatmap-rank-management`, `web-ui`

## Open Questions for Design

- Which Python osu! API library is acceptable after license review and API surface verification?
- How should v2/v1/mirror provider adapters map external status values into Athena's internal enum?
- What exact DB schema should represent beatmapsets, beatmaps, official status, local override, checksum lookup, and `.osu` attachments?
- What external mirror provider should be supported first?
- Should metadata/file fetch completion events be pure domain events, Valkey messages, taskiq chaining, or a combination?
