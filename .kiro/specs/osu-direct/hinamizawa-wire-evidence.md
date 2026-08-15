# Hinamizawa Wire Evidence

Primary sources:
- [Aeris Integration](https://mirror.hinamizawa.ai/docs/aeris-integration)
- [Beatmap Search](https://mirror.hinamizawa.ai/docs/beatmap-search)

## Wire Split

| Concern | Aeris direct `/api/v1/aeris/search` | Hinai JSON `/api/v1/hinai/search` |
| --- | --- | --- |
| Body | Plain text. Line 0 is a count; `101` means more pages, `0` means no results, `<0` means an in-band error. `search-set` returns one row and no count line. | Flat CheeseGull JSON array. No count line. |
| Query text | `q` is URL-encoded text. `Newest`, `Top Rated`, and `Most Played` mean "no query" plus that sort. | `query` is the text search string. |
| Rank/status | `r` is the stable dropdown code: `0` ranked, `2` pending, `3` qualified, `4` all, `5` graveyard, `7` ranked-played, `8` loved. | `status` is CheeseGull status: `0` pending, `1` ranked, `2` approved, `3` qualified, `4` loved; omit for all. v2 is the only hinai JSON shape that also names `graveyard`. |
| Mode | `m=-1` all, else `0..3`. | `mode=-1` all in v1; v2 uses `0..3`. |
| Sort | Stable quick buttons arrive as `q=Newest`, `q=Top Rated`, or `q=Most Played`. | `sort` accepts `ranked_desc`, `plays_desc`, `favourites_desc`, `title_asc`, and `friends` on v1. |
| Paging | `p` is 0-based page. | v1 uses `amount` + `offset` (`1..100`, default `100`); v2 uses `limit` + `page` (`1..100`, default `50`/`0`). |
| Count semantics | Trust the count line, not a fixed page size. `101` is the "more pages" sentinel. | Use array length for v1. v2 returns `total_count` and `total_pages`. |

## Stable Row Inputs

To format one stable row from v1 JSON, use:

- set-level: `SetID`, `Artist`, `Title`, `Creator`, `RankedStatus`, `LastUpdate`, `HasVideo`, `ChildrenBeatmaps`
- child-level: `DiffName`, `DifficultyRating`, `Mode`

`RankedStatus` maps straight into the stable row status field: `1` ranked, `2` approved, `3` qualified, `4` loved, anything else pending.

Everything else in the sample JSON is optional for stable row formatting. The Aeris wire fills the remaining stable slots with fixed values: `filename={SetID}.osz`, `rating=10.00`, `threadId=0`, `hasStoryboard=0`, `filesize=0`, and `filesizeNoVideo=0`. The difficulty list is the comma-joined child list.

## Set-Level Dates

osu! API v2 Beatmapset exposes set-level `submitted_date`, `ranked_date`, and `last_updated`. Athena stores these separately from row `updated_at`; Stable direct `LastUpdate` uses set-level `official_last_updated_at` first and falls back to child `official_last_updated_at`.

## Implementation Note

If Athena consumes `/api/v1/hinai/search`, translate stable `p` as `offset = p * 100` with `amount = 100` for the normal 100-row page. `r=5` graveyard uses the JSON status value `-2`.

Direct `r` to v1 `status` collapse points: `r=0` or `r=7` -> `status=1`, `r=2` -> `status=0`, `r=3` -> `status=3`, `r=5` -> `status=-2`, `r=8` -> `status=4`. The v1 documentation says `r=4`/All can omit `status`, but Athena expands All into `status=0,1,2,3,4` requests so a source-side default cannot collapse the stable All filter back to Ranked.

Direct quick query to v1 `sort` collapse points: `Newest` -> `sort=ranked_desc`, `Top Rated` -> `sort=favourites_desc`, `Most Played` -> `sort=plays_desc`. The v1 JSON lane has no rating sort, so `Top Rated` uses the closest documented engagement sort until Athena owns a rating source.

## Evidence Pointers

- Aeris direct wire contract, parameters, count line, and 14-field row shape: [Aeris Integration](https://mirror.hinamizawa.ai/docs/aeris-integration) (see lines 117-177 and 306-370)
- CheeseGull JSON search contract, v1/v2 parameters, pagination, and example fields: [Beatmap Search](https://mirror.hinamizawa.ai/docs/beatmap-search) (see lines 209-274)
- osu! API v2 Beatmapset date field names: [Official osu! API docs](https://osu.ppy.sh/docs/index.html#beatmapset)
