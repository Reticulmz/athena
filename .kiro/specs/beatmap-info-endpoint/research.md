# Research Notes

## Summary

- **Feature**: `beatmap-info-endpoint`
- **Discovery Scope**: Extension
- **Key Findings**:
  - Real stable client requests for `/web/osu-getbeatmapinfo.php` use JSON body with `Filenames` and `Ids`; observed `Filenames` entries can be original `.osu` filenames without checksum.
  - Official response fixture shows line order is not guaranteed; the first response field is the association mechanism.
  - Existing Athena beatmap mirror supports id/checksum metadata resolution, but filename fallback requires a narrow repository read extension.

## Research Log

### Existing Athena Integration Points

- **Context**: Design must extend web legacy transport without changing beatmap mirror ownership.
- **Sources Consulted**: `composition/application.py`, `composition/endpoints.py`, `composition/service_registry.py`, `transports/web_legacy/*`, `services/beatmap_mirror_service.py`, `repositories/interfaces/beatmap_repository.py`.
- **Findings**:
  - Host-based routing already separates `osu.$DOMAIN` from `c.$DOMAIN`.
  - Callable transport handlers are registered through DI and exposed through `app.state`.
  - Beatmap mirror exposes `resolve_by_beatmap_id` and `resolve_by_checksum` with bounded wait and `.osu` file option.
  - Repository interface lacks filename lookup.
- **Implications**:
  - Add a handler plus app-state adapter for this endpoint.
  - Keep stable parser/formatter in `transports/web_legacy`.
  - Add a small `get_beatmap_by_filename` repository read contract.

### Build vs Adopt

- **Context**: Request parsing could use Pydantic or a custom dataclass parser.
- **Sources Consulted**: Project steering, existing domain dataclass guidance, observed client fixtures.
- **Findings**:
  - The feature needs tolerant legacy parsing and typed internal entries.
  - Existing steering favors dataclasses for domain/value objects and boundary validation at transports.
- **Implications**:
  - Use a small dataclass parser and explicit parse result instead of introducing a framework-specific model.

## Reference Implementations

- `osuTitanic/deck`
  - `app/routes/web/beatmapinfo.py`
  - `app/routes/web/beatmaps.py`
  - `app/helpers/bss.py`
  - 関連 findings: batch `Filenames` / `Ids` handling、response fields、`Ids` response index behavior、grade projection、upload flow が同じ beatmap / beatmapset domain tables を使う方針、sequence-based local id allocation。
  - Source: https://github.com/osuTitanic/deck

- `osuAkatsuki/bancho.py`
  - `app/api/domains/osu.py`
  - 関連 findings: `/web/osu-getbeatmapinfo.php` は batch filename/id input を受け、`index|beatmap_id|beatmapset_id|md5|status|grades` を返し、unknown maps を skip し、per-mode grades を含める。
  - Source: https://github.com/osuAkatsuki/bancho.py

## Compatibility Questions To Validate

- `/web/osu-getbeatmapinfo.php` の real stable client requests を採取し、parser fixtures として保存する。
- `Filenames` と `Ids` の追加 request body variants が存在するか確認する。
- filename entries が checksum、id、path、または original filename のどれを含むか追加 fixture で確認する。
- unresolved entries を omit した場合の client behavior を確認する。
- Ranked、Approved、Loved、Qualified、Pending-like、unavailable maps に対して stable client が期待する status values を確認する。

## Observed Stable Client Fixture: `osu-getbeatmapinfo.php`

- Observed request target:
  - `POST /web/osu-getbeatmapinfo.php?u=PlayerOne&h=<password_md5>`
  - Host: `osu.example.com`
- Observed request body:

```json
{
  "Filenames": [
    "Forte Escape - Zeroize (Nemis) [Hard].osu",
    "Forte Escape - Zeroize (Nemis) [Insane].osu",
    "Forte Escape - Zeroize (Nemis) [NeMiX].osu",
    "Forte Escape - Zeroize (Nemis) [Normal].osu"
  ],
  "Ids": []
}
```

- Initial finding: real client request body can be JSON with `Filenames` as original `.osu` filenames and `Ids` as an array.
- This fixture does not include checksum/md5 in `Filenames`; filename fallback is therefore required for this endpoint.

## Observed Official Response Fixture: `osu-getbeatmapinfo.php`

- Observed request target:
  - `POST /web/osu-getbeatmapinfo.php?u=PlayerOne&h=<password_md5>`
  - Host: `osu.ppy.sh`
  - User-Agent: `osu!`
- Observed request body:

```json
{
  "Filenames": [
    "STEREO DIVE FOUNDATION - PEACEKEEPER (TV Size) (tmk) [Endless Journey].osu",
    "STEREO DIVE FOUNDATION - PEACEKEEPER (TV Size) (tmk) [Futsuu].osu",
    "STEREO DIVE FOUNDATION - PEACEKEEPER (TV Size) (tmk) [Kantan].osu",
    "STEREO DIVE FOUNDATION - PEACEKEEPER (TV Size) (tmk) [Muzukashii].osu",
    "STEREO DIVE FOUNDATION - PEACEKEEPER (TV Size) (tmk) [Oni].osu"
  ],
  "Ids": []
}
```

- Observed response body lines:

```text
0|5394746|2464628|046b348fa9babf41261ccc8aa14edbfc|1|N|N|N|N
4|5396809|2464628|8c392191ce3d35e081442a4a36e92925|1|N|N|N|N
3|5398004|2464628|cdcbe35ebaea6bb0f35de76f50b4b16f|1|N|N|N|N
1|5398063|2464628|5094f9ad6b0899c9e2a9206e72659c43|1|N|N|N|N
2|5398096|2464628|b722759a475e110ba67e57860f02928f|1|N|N|N|N
```

- Initial findings:
  - Response line format matches `index|beatmap_id|beatmapset_id|md5|status|grade_osu|grade_taiko|grade_catch|grade_mania`.
  - Response line order does not necessarily match request order; the index field is the stable association mechanism.
  - HTTP chunk framing values such as chunk size and final `0` are transport framing, not application response body content.

## Adjacent Stable Client Evidence

- 2026-06-05 に song selection の leaderboard 表示で `GET /web/osu-osz2-getscores.php` が送信されることを確認した。
- Observed query fields:
  - `s=0`
  - `vv=4`
  - `v=1`
  - `c=792aba64fc4d59851e2daac5b771f600`
  - `f=VINXIS - A Centralized View (Peter) [Shiinoha's Easy].osu`
  - `m=0`
  - `i=780932`
  - `mods=0`
  - `h=`
  - `a=0`
  - `us=PlayerOne`
  - `ha=<password_md5>`
- `c`, `i`, `f` が同時に送られており、checksum/md5、explicit beatmap id、filename の順で lookup する方針の参考 evidence になる。
- この endpoint は `beatmap-info-endpoint` の scope 外とし、後続の leaderboard / web legacy scores endpoint spec で扱う。

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Thin transport handler | Handler composes auth, parser, resolver, formatter | Fits existing Starlette/DI pattern, keeps stable specifics in transport | Requires small helper modules | Selected |
| Extend beatmap mirror to parse stable requests | Put request shape inside service layer | Fewer transport files | Leaks stable protocol into shared metadata service | Rejected |
| Dedicated endpoint microservice | Separate service for stable web endpoints | Strong isolation | Overkill for current monolith and violates simplicity | Rejected |

## Design Decisions

### Decision: Keep Stable Request and Response Rules in Web Legacy Transport

- **Context**: `osu-getbeatmapinfo.php` has stable-specific JSON body and pipe-delimited text response.
- **Alternatives Considered**:
  1. Put parser/formatter in beatmap mirror.
  2. Put parser/formatter in web legacy transport.
- **Selected Approach**: Parser and formatter live under `transports/web_legacy`.
- **Rationale**: Beatmap mirror remains protocol-independent and reusable by score, leaderboard, WebUI, and future APIs.
- **Trade-offs**: Transport layer has more helper files, but boundary is clearer.
- **Follow-up**: Reuse the lookup candidate concepts when designing `/web/osu-osz2-getscores.php`.

### Decision: Add Narrow Filename Lookup Contract

- **Context**: Real fixture sends original `.osu` filenames without md5.
- **Alternatives Considered**:
  1. Attempt external metadata lookup by filename.
  2. Persist and query original filename as fallback.
  3. Ignore filename-only requests.
- **Selected Approach**: Exact persisted filename fallback through repository.
- **Rationale**: Filename is necessary for observed client behavior but is not authoritative enough for external source search.
- **Trade-offs**: Existing metadata schema may need a nullable filename attribute.
- **Follow-up**: Future beatmap upload spec should decide long-term filename and local identity ownership.

### Decision: Response Line Order Is Not a Contract

- **Context**: Official response fixture returns lines in non-request order.
- **Alternatives Considered**:
  1. Force request order.
  2. Preserve any resolver order and rely on index field.
- **Selected Approach**: The formatter guarantees stable index values, not line order.
- **Rationale**: Matches official fixture and avoids unnecessary sorting as a compatibility requirement.
- **Trade-offs**: Tests must assert set/content with index mapping rather than list order unless order is intentionally chosen.
- **Follow-up**: Additional fixtures may verify whether id-based responses use `-1` consistently.

## Risks & Mitigations

- Filename collisions can return the wrong beatmap — keep checksum/id priority higher and treat filename as exact fallback only.
- Stable status numeric mapping is incomplete — fixture-test current known values and isolate mapper for correction.
- Logging credentials could leak password md5 — redact `u`/`h` query values in diagnostics.
- Beatmap mirror enqueue callback may not be wired in all runtimes — integration tests should verify pending behavior with configured runtime.

## References

- https://github.com/osuTitanic/deck — reference implementation for beatmap info and upload-related beatmap table behavior.
- https://github.com/osuAkatsuki/bancho.py — reference implementation for `/web/osu-getbeatmapinfo.php` response shape.
