# Requirements Document

## Introduction

Athena には osu! stable の song select で呼ばれる legacy leaderboard endpoint が必要である。stable client は `/web/osu-osz2-getscores.php` を使って、プレイ前に beatmap の submitted 状態、ranked status、表示名、rating、leaderboard rows を問い合わせる。現在 Athena にはこの endpoint がなく、client には `404 Not Found` や取得失敗として見えるため、ランキング実装前でも song select の leaderboard 領域に server-known beatmap metadata を表示できない。

この仕様は `web-legacy-leaderboard-endpoint` の MVP として、ランキング行を返さない beatmap header response を定義する。対象は `osu.$DOMAIN` 上の `GET /web/osu-osz2-getscores.php`、`us` / `ha` credential による認証、stable query parsing、checksum-first beatmap lookup、metadata-only resolution、bounded wait、getscores 専用 status mapping、stable-compatible text response、fixture-backed compatibility validation である。

## Boundary Context

- **In scope**:
  - osu web domain 上の stable client 向け `GET /web/osu-osz2-getscores.php`。
  - `us` / `ha` credentials と active bancho session による request authorization。
  - observed stable query fields: `s`, `vv`, `v`, `c`, `f`, `m`, `i`, `mods`, `h`, `a`, `us`, `ha` の parsing。
  - checksum/md5 を最優先し、filename と beatmapset id hint を fallback に使う single beatmap lookup。
  - missing metadata に対する metadata-only resolution request と configured bounded wait。
  - submitted beatmap に対する stable-compatible beatmap header response。
  - NotSubmitted、unknown、unresolved、UpdateAvailable の stable-compatible short response。
  - delimiter-safe artist/title formatting and `text/plain; charset=UTF-8` response。
  - real stable client request / official response fixtures と reference implementation findings に基づく validation。

- **Out of scope**:
  - leaderboard ranking rows。
  - personal best row。
  - score repository、score persistence、best-score calculation、placement calculation。
  - PP、star rating calculation、score mode/mod filtering。
  - replay availability and replay download behavior。
  - score submission and leaderboard update workflows。
  - osu!direct search/download and beatmapset archive proxy。
  - beatmap upload、local id allocation、rank-management approval workflows。

- **Adjacent expectations**:
  - `beatmap-mirror` provides beatmap / beatmapset metadata resolution, effective status, NotSubmitted state, and metadata fetch state.
  - `beatmap-info-endpoint` may provide shared compatibility evidence for lookup priority and stable metadata behavior, but this endpoint owns its own getscores wire response.
  - Future score / leaderboard features may add score rows, personal best rows, leaderboard type filtering, mode filtering, mods filtering, replay flags, and score count without changing this MVP's beatmap header contract.
  - Future PP or star-rating cache features may populate currently neutral/empty header fields, but this MVP must not block on those features.

## Requirements

### Requirement 1: Stable Getscores Endpoint Scope

**Objective:** As a stable client user, I want song select leaderboard requests to receive a stable-compatible response, so that server-known beatmaps do not appear as endpoint failures before ranking rows exist.

#### Acceptance Criteria

1. When stable client sends a request to `/web/osu-osz2-getscores.php` on the osu web domain, the Web Legacy Leaderboard Endpoint shall process it as a stable getscores request.
2. If the request is sent to a non-osu web domain, then the Web Legacy Leaderboard Endpoint shall not require a path-based fallback route for this feature.
3. The Web Legacy Leaderboard Endpoint shall limit this MVP to beatmap header, unavailable, and update-available responses.
4. The Web Legacy Leaderboard Endpoint shall not provide leaderboard ranking rows, personal best rows, score persistence, PP calculation, replay behavior, score submission behavior, osu!direct behavior, or beatmap upload behavior.

### Requirement 2: Legacy Getscores Authentication

**Objective:** As an operator, I want getscores requests to use stable web credentials and session presence, so that beatmap metadata responses are only served to authenticated active clients.

#### Acceptance Criteria

1. When a getscores request contains valid `us` and `ha` credentials for a user with an active bancho session, the Web Legacy Leaderboard Endpoint shall authorize the request.
2. If `us` or `ha` is missing or invalid, then the Web Legacy Leaderboard Endpoint shall reject the request as an authentication failure.
3. If the authenticated user has no active bancho session, then the Web Legacy Leaderboard Endpoint shall reject the request as an authentication failure.
4. While a request is unauthorized, the Web Legacy Leaderboard Endpoint shall not disclose beatmap status, beatmap identity, rating, or lookup diagnostics in the response body.
5. The Web Legacy Leaderboard Endpoint shall not treat the `h` query field as the user password credential for this endpoint.

### Requirement 3: Stable Query Parsing

**Objective:** As a stable client compatibility maintainer, I want the endpoint to accept observed stable query shapes, so that song select behavior is not broken by incorrect parameter assumptions.

#### Acceptance Criteria

1. When a getscores request includes `c`, the Web Legacy Leaderboard Endpoint shall preserve it as the requested beatmap checksum/md5.
2. When a getscores request includes `f`, the Web Legacy Leaderboard Endpoint shall preserve it as the requested beatmap filename.
3. When a getscores request includes `i`, the Web Legacy Leaderboard Endpoint shall preserve it as a beatmapset id hint rather than treating it as a beatmap id.
4. When a getscores request includes `m`, the Web Legacy Leaderboard Endpoint shall preserve it as the requested gameplay mode.
5. When a getscores request includes `mods`, the Web Legacy Leaderboard Endpoint shall preserve it as the requested mods value.
6. When a getscores request includes `s`, `vv`, or `v`, the Web Legacy Leaderboard Endpoint shall preserve those values for compatibility and future leaderboard behavior.
7. When a getscores request includes `a`, the Web Legacy Leaderboard Endpoint shall preserve whether the anti-cheat signal is present.
8. If non-identity query fields are malformed, then the Web Legacy Leaderboard Endpoint shall make the parse issue observable to operators without preventing a known beatmap header response solely for that reason.
9. If identity query fields are missing enough data to identify or resolve a beatmap, then the Web Legacy Leaderboard Endpoint shall return a stable unavailable response.

### Requirement 4: Lookup Priority and Identity Rules

**Objective:** As a stable client user, I want the requested beatmap to resolve to the correct server beatmap, so that renamed files or beatmapset hints do not return the wrong metadata.

#### Acceptance Criteria

1. When request checksum/md5 is present, the Web Legacy Leaderboard Endpoint shall use checksum lookup as the highest-priority beatmap identity.
2. If checksum lookup resolves a beatmap and filename or beatmapset hint disagrees, then the Web Legacy Leaderboard Endpoint shall prefer the checksum result.
3. If checksum lookup does not resolve a beatmap and filename plus beatmapset id hint can identify a submitted beatmap, then the Web Legacy Leaderboard Endpoint shall use that result for fallback behavior.
4. If only beatmapset id hint is available, then the Web Legacy Leaderboard Endpoint shall not use it alone to select a difficulty.
5. If lookup inputs conflict, then the Web Legacy Leaderboard Endpoint shall make the conflict observable to operators without disclosing internal diagnostics in the stable response.
6. The Web Legacy Leaderboard Endpoint shall not infer beatmap id from arbitrary filename fragments.

### Requirement 5: Metadata Resolution and Bounded Wait

**Objective:** As a stable client user, I want known beatmaps to return quickly and unknown beatmaps to get a short resolution opportunity, so that song select remains responsive while metadata can still be populated.

#### Acceptance Criteria

1. When the requested beatmap is already known, the Web Legacy Leaderboard Endpoint shall return the appropriate stable response without waiting for external metadata.
2. When the requested checksum or beatmapset-hinted filename is unknown, the Web Legacy Leaderboard Endpoint shall request metadata resolution for the lookup target.
3. While metadata resolution is pending, the Web Legacy Leaderboard Endpoint shall wait only within the configured bounded wait behavior before responding.
4. If metadata resolution completes within the bounded wait and yields a submitted beatmap, then the Web Legacy Leaderboard Endpoint shall return a beatmap header response.
5. If metadata resolution completes within the bounded wait and confirms NotSubmitted, then the Web Legacy Leaderboard Endpoint shall return the stable unavailable response.
6. If metadata resolution remains pending after the bounded wait, then the Web Legacy Leaderboard Endpoint shall return the stable unavailable response.
7. If metadata resolution fails without usable beatmap metadata, then the Web Legacy Leaderboard Endpoint shall return the stable unavailable response.
8. The Web Legacy Leaderboard Endpoint shall not require `.osu` file body availability to produce this MVP response.

### Requirement 6: UpdateAvailable Behavior

**Objective:** As a stable client user, I want outdated local beatmaps to be distinguished from unsubmitted beatmaps, so that the client can show an update-needed state when metadata indicates the map exists with a different checksum.

#### Acceptance Criteria

1. If checksum lookup fails but filename and beatmapset id hint identify the same submitted beatmap with a different checksum, then the Web Legacy Leaderboard Endpoint shall return the stable update-available response.
2. When the Web Legacy Leaderboard Endpoint returns update-available, the Web Legacy Leaderboard Endpoint shall use `1|false` as the response body.
3. If filename and beatmapset id hint do not identify a submitted beatmap, then the Web Legacy Leaderboard Endpoint shall not return update-available solely from filename similarity.
4. When update-available is detected, the Web Legacy Leaderboard Endpoint shall make that condition observable to operators.

### Requirement 7: Unavailable and NotSubmitted Behavior

**Objective:** As a stable client user, I want unavailable beatmaps to receive a stable-compatible short response, so that endpoint availability is not confused with a submitted beatmap header.

#### Acceptance Criteria

1. If the requested beatmap is NotSubmitted, then the Web Legacy Leaderboard Endpoint shall return `-1|false`.
2. If the requested beatmap is unknown after lookup and bounded wait, then the Web Legacy Leaderboard Endpoint shall return `-1|false`.
3. If the requested beatmap resolution fails without usable metadata, then the Web Legacy Leaderboard Endpoint shall return `-1|false`.
4. If the requested beatmap cannot be identified from supported identity fields, then the Web Legacy Leaderboard Endpoint shall return `-1|false`.
5. The Web Legacy Leaderboard Endpoint shall not use `404 Not Found` to represent NotSubmitted, unknown, pending-after-wait, or failed metadata states.

### Requirement 8: Submitted Beatmap Header Response

**Objective:** As a stable client user, I want submitted beatmaps to return the beatmap header even when ranking rows are unavailable, so that song select can display server-known beatmap information.

#### Acceptance Criteria

1. When the requested beatmap is submitted and visible to stable clients, the Web Legacy Leaderboard Endpoint shall return a multi-line beatmap header response.
2. When the requested beatmap is Ranked, Approved, Qualified, Loved, Pending, WIP, or Graveyard, the Web Legacy Leaderboard Endpoint shall treat it as eligible for the MVP header response.
3. When the requested beatmap has a status that should not be visible as submitted to stable clients, the Web Legacy Leaderboard Endpoint shall return the stable unavailable response.
4. The Web Legacy Leaderboard Endpoint shall include getscores status value, failed flag, beatmap id, beatmapset id, score count, beatmap offset, formatted artist/title, and rating line in the header response.
5. The Web Legacy Leaderboard Endpoint shall set score count to `0` while ranking rows are out of scope.
6. The Web Legacy Leaderboard Endpoint shall set the failed flag to `false` while failed-score leaderboard behavior is out of scope.
7. The Web Legacy Leaderboard Endpoint shall set rating to `0` while rating or star-rating data is unavailable in this MVP.
8. The Web Legacy Leaderboard Endpoint shall include empty personal best and score rows sections while those rows are out of scope.

### Requirement 9: Getscores Status Mapping

**Objective:** As a stable client compatibility maintainer, I want Athena's effective beatmap statuses to map to the stable getscores status values, so that client display matches observed stable behavior.

#### Acceptance Criteria

1. When the requested beatmap is NotSubmitted, unknown, or unresolved, the Web Legacy Leaderboard Endpoint shall map it to getscores status `-1`.
2. When the requested beatmap is Pending, WIP, or Graveyard, the Web Legacy Leaderboard Endpoint shall map it to getscores status `0`.
3. When the requested beatmap is UpdateAvailable, the Web Legacy Leaderboard Endpoint shall map it to getscores status `1`.
4. When the requested beatmap is Ranked, the Web Legacy Leaderboard Endpoint shall map it to getscores status `2`.
5. When the requested beatmap is Approved, the Web Legacy Leaderboard Endpoint shall map it to getscores status `3`.
6. When the requested beatmap is Qualified, the Web Legacy Leaderboard Endpoint shall map it to getscores status `4`.
7. When the requested beatmap is Loved, the Web Legacy Leaderboard Endpoint shall map it to getscores status `5`.
8. The Web Legacy Leaderboard Endpoint shall keep getscores status mapping independent from other legacy endpoint status mappings when their wire values differ.

### Requirement 10: Parse-Only Leaderboard Controls

**Objective:** As a future leaderboard implementer, I want stable leaderboard controls to be preserved without affecting the MVP header, so that later score rows can extend the endpoint without changing request compatibility.

#### Acceptance Criteria

1. When `v` is provided, the Web Legacy Leaderboard Endpoint shall preserve it as the requested leaderboard type.
2. When `vv` is provided, the Web Legacy Leaderboard Endpoint shall preserve it as the leaderboard protocol or view version marker.
3. When `s` is provided, the Web Legacy Leaderboard Endpoint shall preserve it as the song-select/editor request flag.
4. When `m` is provided, the Web Legacy Leaderboard Endpoint shall preserve it as the requested mode without using it to reject an otherwise known beatmap header response in this MVP.
5. When `mods` is provided, the Web Legacy Leaderboard Endpoint shall preserve it as the requested mods without using it to filter score rows in this MVP.
6. The Web Legacy Leaderboard Endpoint shall not vary the MVP beatmap header solely because of `s`, `vv`, `v`, `m`, or `mods`.

### Requirement 11: Stable Response Formatting

**Objective:** As a stable client compatibility maintainer, I want response bodies to preserve the legacy text shape, so that the stable client can parse beatmap header responses safely.

#### Acceptance Criteria

1. When the Web Legacy Leaderboard Endpoint returns a known beatmap header response, the Web Legacy Leaderboard Endpoint shall use `text/plain; charset=UTF-8`.
2. When the Web Legacy Leaderboard Endpoint returns a known beatmap header response, the Web Legacy Leaderboard Endpoint shall format the first line as `status|false|beatmap_id|beatmapset_id|0||`.
3. When the Web Legacy Leaderboard Endpoint returns a known beatmap header response, the Web Legacy Leaderboard Endpoint shall include a beatmap offset line after the first line.
4. When the Web Legacy Leaderboard Endpoint returns a known beatmap header response, the Web Legacy Leaderboard Endpoint shall format the display line as `[bold:0,size:20]artist|title`.
5. When the Web Legacy Leaderboard Endpoint returns a known beatmap header response, the Web Legacy Leaderboard Endpoint shall include a rating line after the display line.
6. When the Web Legacy Leaderboard Endpoint returns a short unavailable or update-available response, the Web Legacy Leaderboard Endpoint shall use `text/plain; charset=UTF-8`.
7. When artist or title contains the pipe delimiter, the Web Legacy Leaderboard Endpoint shall replace that delimiter before writing the stable response body.
8. When artist or title contains line breaks, the Web Legacy Leaderboard Endpoint shall replace those line breaks before writing the stable response body.
9. The Web Legacy Leaderboard Endpoint shall not include HTTP chunk framing markers in application response fixtures or formatter expectations.

### Requirement 12: Security and Operator Observability

**Objective:** As an operator, I want suspicious or malformed getscores requests to be observable without leaking credentials, so that compatibility and security issues can be diagnosed safely.

#### Acceptance Criteria

1. When query field `a` indicates an anti-cheat signal, the Web Legacy Leaderboard Endpoint shall make that signal observable to operators.
2. When request credentials are logged or diagnosed, the Web Legacy Leaderboard Endpoint shall redact password md5 and raw credential values.
3. When metadata lookup returns unavailable, update-available, conflict, or pending-after-wait outcomes, the Web Legacy Leaderboard Endpoint shall make the outcome observable to operators.
4. When parse failures occur, the Web Legacy Leaderboard Endpoint shall make the failure observable to operators without exposing password md5.
5. The Web Legacy Leaderboard Endpoint shall not expose internal source, verification, policy, fetch-state, or override provenance fields in stable response bodies.

### Requirement 13: Compatibility Evidence and Validation

**Objective:** As a maintainer, I want endpoint behavior to be grounded in real stable client and reference-server evidence, so that compatibility assumptions remain testable.

#### Acceptance Criteria

1. The Web Legacy Leaderboard Endpoint shall have validation coverage based on real stable client request fixtures for `/web/osu-osz2-getscores.php`.
2. The Web Legacy Leaderboard Endpoint shall have validation coverage based on official response fixtures for Ranked, Loved, Qualified, Pending, WIP, Graveyard, converted-mode requests, and NotSubmitted behavior.
3. Where reference implementation behavior differs from observed official behavior, the Web Legacy Leaderboard Endpoint shall prefer observed official behavior for stable compatibility.
4. The Web Legacy Leaderboard Endpoint shall document reference implementation findings used for request fields, status values, authentication parameter names, and response shape.
5. When future stable fixture evidence contradicts provisional behavior, the Web Legacy Leaderboard Endpoint shall treat real stable client and official response behavior as the compatibility authority.
