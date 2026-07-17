# Research Notes

## Summary

- **Feature**: `web-legacy-leaderboard-endpoint`
- **Discovery Scope**: Extension
- **Key Findings**:
  - Real stable client requests for `/web/osu-osz2-getscores.php` use query fields `s`, `vv`, `v`, `c`, `f`, `m`, `i`, `mods`, `h`, `a`, `us`, and `ha`.
  - Official response fixtures show this endpoint returns submitted beatmap header metadata even when Pending, WIP, or Graveyard are not score-leaderboard eligible.
  - `osuAkatsuki/bancho.py` confirms `us` / `ha` authentication, `i` as beatmapset id, `v` as leaderboard type, and getscores status values, but official fixtures take precedence where behavior differs.

## Research Log

### Existing Athena Integration Points

- **Context**: The design must add a web legacy endpoint without widening score-submission or beatmap-mirror boundaries.
- **Sources Consulted**: `composition/application.py`, `composition/endpoints.py`, `composition/lifespan.py`, `composition/service_registry.py`, `transports/web_legacy/*`, `services/beatmap_mirror_service.py`, `repositories/interfaces/beatmap_repository.py`, `domain/beatmap.py`.
- **Findings**:
  - `osu.$DOMAIN` web routes are already isolated from `c.$DOMAIN` bancho routes.
  - Callable transport handlers are registered through DI and exposed through `app.state`.
  - `BeatmapMirrorService` supports checksum and beatmapset resolution with `BeatmapResolveOptions(require_osu_file=False, wait_timeout_seconds=...)`.
  - Current repository lookup supports checksum and beatmapset id, but not exact filename within a beatmapset.
- **Implications**:
  - Add a Starlette route only under `osu.$DOMAIN`.
  - Reuse the future/shared legacy auth service from `beatmap-info-endpoint`, but keep getscores query parsing and response formatting separate.
  - Add a narrow repository read contract for filename plus beatmapset id fallback and UpdateAvailable detection.

### Observed Stable Request Fields

- **Context**: User captured real stable requests with mitmproxy/mitmweb.
- **Sources Consulted**: User-provided request fixtures for Ranked, Loved, Qualified, Pending, WIP, Graveyard, NotSubmitted, Taiko, Catch, Mania, and Standard variants.
- **Findings**:
  - `c` is the 32-character beatmap checksum/md5 and is the strongest identity key.
  - `i` matches the response beatmapset id, not beatmap id.
  - `f` is the `.osu` filename and can be used with `i` to detect same-set filename matches.
  - `m` changes requested gameplay mode and affects official score rows, but the same beatmap header is returned across converted modes.
  - `mods`, `s`, `v`, and `vv` are relevant to future score row selection, but the MVP has no score rows.
  - `us` and `ha` are the credential fields for this endpoint; `h` is not the password field here.
- **Implications**:
  - Parse all observed fields into a typed request object.
  - Do not reject known beatmap header responses solely because `m`, `mods`, `s`, `v`, or `vv` are unusual.
  - Treat malformed non-identity fields as diagnostics rather than as header blockers.

### Official Response Fixtures

- **Context**: Compatibility must follow official stable behavior over private-server shortcuts.
- **Sources Consulted**: User-provided official responses from `osu.ppy.sh`.
- **Findings**:
  - NotSubmitted returns `-1|false`.
  - Pending, WIP, and Graveyard return a multi-line header response with status `0`.
  - Ranked returns status `2`, Qualified returns `4`, Loved returns `5`.
  - Score count is present in the first line; MVP can set it to `0` when no rows are returned.
  - Response body must exclude HTTP chunk framing markers such as chunk size and final chunk `0`.
- **Implications**:
  - Header visibility must be based on submitted/visible status, not score eligibility.
  - Getscores status mapping must be endpoint-specific.
  - Formatter fixtures must store application bodies only.

### Reference Implementation: bancho.py

- **Context**: User pointed to `osuAkatsuki/bancho.py` `getScores`.
- **Sources Consulted**:
  - https://github.com/osuAkatsuki/bancho.py/blob/0651b54c66daa839c1bb3998e4f9a8d1173e144d/app/api/domains/osu.py
- **Findings**:
  - `authenticate_player_session(Query, "us", "ha")` confirms credential names.
  - `LeaderboardType` maps `Local=0`, `Top=1`, `Mods=2`, `Friends=3`, `Country=4`.
  - `RankedStatus` values are `NotSubmitted=-1`, `Pending=0`, `UpdateAvailable=1`, `Ranked=2`, `Approved=3`, `Qualified=4`, `Loved=5`.
  - Missing checksum plus same filename/set can return `1|false` for update available.
  - bancho.py returns short `<status>|false` for ranked-below maps, while official fixtures return headers for Pending/WIP/Graveyard.
- **Implications**:
  - Adopt credential names, leaderboard type naming, and getscores status numeric values.
  - Prefer official fixture behavior for Pending/WIP/Graveyard header response.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Thin web legacy handler | Handler composes auth, query parser, resolver, formatter | Matches Athena transport pattern and isolates stable wire behavior | Adds several small transport files | Selected |
| Extend beatmap-info endpoint helpers directly | Share parser/formatter across beatmap-info and getscores | Less code at first | Request shape and status wire values differ | Rejected for parser/formatter; auth/lookup helpers may be shared |
| Implement full leaderboard now | Add score row provider and personal best rows | Closer to final endpoint | Pulls in score repository, placement, replay, and PP decisions | Rejected for MVP boundary |

## Design Decisions

### Decision: Header MVP Without Score Provider Port

- **Context**: The feature must make song select compatible before score persistence exists.
- **Alternatives Considered**:
  1. Add a score row provider port returning empty rows.
  2. Keep score rows entirely out of the MVP and hard-code score count `0`.
- **Selected Approach**: Do not add a score row provider in this spec.
- **Rationale**: The current requirements explicitly exclude ranking rows and personal best rows. A port with no implementation would be speculative.
- **Trade-offs**: Future leaderboard implementation will add a new boundary later.
- **Follow-up**: Future score/leaderboard spec should add score row provider, personal best provider, `v` filtering, `m` filtering, and `mods` filtering.

### Decision: Official Fixtures Override Reference Implementation Differences

- **Context**: bancho.py returns short responses for ranked-below statuses, but official fixtures return headers for Pending, WIP, and Graveyard.
- **Alternatives Considered**:
  1. Follow bancho.py exactly.
  2. Follow observed official behavior where available.
- **Selected Approach**: Use official fixture behavior for stable compatibility; use bancho.py for field names and status constants.
- **Rationale**: The target client behavior is official stable compatibility.
- **Trade-offs**: Private-server behavior may differ from bancho.py for Pending/WIP/Graveyard.
- **Follow-up**: Add fixture tests for each observed status.

### Decision: UpdateAvailable Requires Same Set and Filename

- **Context**: `1|false` should distinguish outdated local files from unsubmitted maps without creating false positives.
- **Alternatives Considered**:
  1. Return UpdateAvailable for any filename match.
  2. Require filename plus beatmapset id hint match.
  3. Never return UpdateAvailable in MVP.
- **Selected Approach**: Return `1|false` only when checksum misses and filename plus beatmapset id identify a submitted beatmap with a different checksum.
- **Rationale**: Beatmapset id constrains filename collision risk while matching observed request shape.
- **Trade-offs**: Requests without set id may fall back to unavailable rather than update available.
- **Follow-up**: Revisit if official fixtures show filename-only update detection.

## Risks & Mitigations

- Risk: Header responses for Pending/WIP/Graveyard conflict with existing eligibility rules — Mitigation: keep this mapper local to getscores response and do not reuse score eligibility.
- Risk: Filename fallback collision could identify the wrong beatmap — Mitigation: require beatmapset id hint for UpdateAvailable and do not use set id alone for difficulty selection.
- Risk: Credential md5 leaks through logs — Mitigation: redact `us`, `ha`, and raw query credential values in diagnostics.
- Risk: HTTP chunk framing gets mistaken for application body — Mitigation: store fixtures as decoded response body only.

## References

- https://github.com/osuAkatsuki/bancho.py/blob/0651b54c66daa839c1bb3998e4f9a8d1173e144d/app/api/domains/osu.py — immutable reference for `getScores`, credential names, leaderboard type values, and getscores status constants.
- `.kiro/specs/beatmap-info-endpoint/research.md` — adjacent stable request evidence and lookup priority discussion.
- `.kiro/specs/beatmap-mirror/requirements.md` — source metadata, effective status, and fetch-state expectations consumed by this endpoint.
