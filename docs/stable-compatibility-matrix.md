# Stable Compatibility Matrix

This document is the source-of-truth checklist for Athena's osu! stable
compatibility work. Its purpose is to prevent missing required stable packets,
legacy endpoints, request forms, and response formats while keeping the README
short.

Athena is still a proof of concept. A checked or implemented row means the
repository has code for that surface, not that the behavior is production-ready
or fully compatible with every stable client edge case.

## Source-Of-Truth Policy

Use this document as the input for GitHub Projects and implementation issues.
GitHub Projects should track execution state; this file should track the canonical
inventory.

Every stable compatibility item should eventually have:

- a stable packet, endpoint, request shape, or response shape identifier,
- an implementation status that describes runtime code state only,
- the owning module or planned module,
- reference paths from the relevant implementation family,
- verification evidence through tests, golden fixtures, or real-client probes.

Reference sources, in order of preference:

1. Lekuruu `bancho-documentation` wiki for Bancho packet IDs, primitive wire
   types, and struct layouts.
2. Observed stable client traffic.
3. Athena's own compatibility tests and fixtures.
4. Reference implementations listed below, split by stable surface ownership.
5. Athena design notes in `bancho_server_design.md` and `CONTEXT.md`.

Reference implementations are comparison targets, not architecture targets.
Athena should preserve compatible behavior without copying their process-global
state, large dispatch files, or persistence coupling.

## Release/Update Audit Row Contract

Release/update rows keep the existing `Status` column as runtime implementation
state. Audit policy is recorded separately so `Missing`, `Candidate`, or
`Implemented` is not overwritten by compatibility classification.

Use this structured note form in the row's Notes cell unless a future matrix
section explicitly adds dedicated columns:

```text
Audit: stable_compatibility_route_classification=<value>;
response_shape=<value>;
evidence_source=<source-list>;
stable_operational_dependency=<value>;
stable_fixture_requirement=<value>.
```

The audit fields have these meanings:

| Field | Meaning |
| --- | --- |
| `stable_compatibility_route_classification` | Stable compatibility policy for the route, such as `required-no-update`, `deferred`, or `needs-reference`. This is not the runtime implementation status. |
| `response_shape` | Selected client-observable response shape for no-update rows, or `deferred` when the response contract is intentionally not selected yet. |
| `evidence_source` | Source names used to justify the selected classification and response shape. Use `needs-reference` when evidence is insufficient. |
| `stable_operational_dependency` | Operational decision required before implementation, using the values below. This does not approve proxying or artifact hosting. |
| `stable_fixture_requirement` | Downstream fixture handoff state: shared fixture identifier, `deferred`, `not-required`, or `needs-reference`. |

### Operational Dependency Matrix

Use these operational dependency values for release/update audit rows:

| Value | Meaning |
| --- | --- |
| `none` | The audited policy does not require external proxying or hosted release artifacts. |
| `proxy-decision-required` | Implementing the route would require an explicit decision about external proxying. |
| `hosted-artifact-decision-required` | Implementing the route would require an explicit decision about Athena-hosted release artifacts. |

If evidence cannot support a stable route classification, set
`stable_compatibility_route_classification` to `needs-reference` and do not
invent a response contract. If a row appears to need both proxying and hosted
artifacts, keep it at `needs-reference` until evidence separates the
operational dependency.

## Reference Implementation Map

Use these repositories to audit stable packets, endpoints, request forms, and
response formats. Record the specific file path or route/handler name in the
relevant issue before implementing behavior.

| Repository | Use for | Notes |
| --- | --- | --- |
| `osuAkatsuki/bancho.py` | Integrated stable behavior across bancho packets and legacy web endpoints. | Treat as broad comparison coverage because it is an all-in-one server backend. Do not copy its global-state or large-dispatch structure. |
| `osuRipple/lets` | Legacy web endpoints, request parameters, and response body compatibility. | Use primarily for `/web/*.php` behavior and score/beatmap legacy forms. |
| `osuRipple/pep.py` | Bancho server packets and runtime session behavior. | Use primarily for C2S/S2C packet handling and online-state flows. |
| `osuTitanic/deck` | Legacy web endpoints, request parameters, and response body compatibility. | Use primarily as a modern stable client API comparison point. |
| `osuTitanic/titanic` | Bancho server packets and multi-client stable behavior. | Use primarily for packet coverage, session behavior, and long-tail client compatibility. |
| `sutekina/osu-gulag` | Avatar/static/media route variants and ppy/mirror proxy behavior. | Use as secondary evidence for static hosting choices, not as an architecture target. |
| `SunriseCommunity/Sunrise` | Avatar/static/media, direct, and update route variants in a C# implementation. | Use as secondary evidence for route aliases and request-key behavior. |

When references disagree, prefer observed stable client behavior. If traffic is
not available, compare at least two implementations and document the chosen
Athena behavior in the implementation issue.

## Status Labels

| Status | Meaning |
| --- | --- |
| `Implemented` | The surface has a runtime implementation and at least basic verification. |
| `Partial` | The surface exists but key stable behavior is known to be missing. |
| `Builder` | S2C packet builder exists, but runtime emission may still be incomplete. |
| `Declared` | Packet ID exists in the enum, but payload parsing/building or runtime behavior is missing. |
| `Missing` | No meaningful implementation exists yet. |
| `Candidate` | Likely stable surface that needs confirmation from docs, traffic, or reference code. |
| `Out of scope` | Known surface intentionally excluded from the current stable scope. |

## Current Stable Surfaces

These surfaces are tracked by `src/athena_cli/stable_verification/catalog.py`.

| Surface | Status | Evidence |
| --- | --- | --- |
| Registration | Implemented | `tests/integration/test_registration_flow.py` |
| Bancho login | Implemented | `tests/integration/test_login_flow.py` |
| Packet polling | Implemented | `tests/integration/test_polling_e2e.py` |
| Chat | Implemented | `tests/integration/test_chat_e2e.py` |
| Getscores | Partial | known leaderboard row gap, getscores fixtures |
| Score submit | Partial | known rank/user-stat projection gaps |
| Akatsuki Relax/Autopilot leaderboards | Missing | compatibility extension; `bancho.py` separates vanilla, Relax, and Autopilot mode families. |

## C2S Packet Coverage

Current enum source: `ClientPacketID` in
`src/osu_server/transports/stable/bancho/protocol/enums.py`.

| ID | Packet | Status | Notes |
| --- | --- | --- | --- |
| 0 | `STATUS_CHANGE` | Partial | Decoded for beatmap file warmup; full presence and user-stat propagation is missing. Lekuruu packet file is named `ChangeStatus`; `STATUS_CHANGE` is Athena's alias. |
| 1 | `SEND_MESSAGE` | Implemented | Channel message handler exists. |
| 2 | `EXIT` | Implemented | Session cleanup and disconnect event exist. |
| 3 | `REQUEST_STATUS` | Missing | Needed for targeted status refresh. |
| 4 | `PONG` | Implemented | Keepalive no-op exists. |
| 16 | `START_SPECTATING` | Missing | Spectator state and frame relay missing. |
| 17 | `STOP_SPECTATING` | Missing | Spectator state and notifications missing. |
| 18 | `SEND_FRAMES` | Missing | Spectator frame relay missing. |
| 20 | `ERROR_REPORT` | Missing | Client error-report ingestion missing. |
| 21 | `CANT_SPECTATE` | Missing | Spectator failure propagation missing. |
| 25 | `SEND_PRIVATE_MESSAGE` | Implemented | Private message handler exists. |
| 29 | `PART_LOBBY` | Missing | Multiplayer lobby missing. |
| 30 | `JOIN_LOBBY` | Missing | Multiplayer lobby missing. |
| 31 | `CREATE_MATCH` | Missing | Multiplayer match lifecycle missing. |
| 32 | `JOIN_MATCH` | Missing | Multiplayer match lifecycle missing. |
| 33 | `LEAVE_MATCH` | Missing | Multiplayer match lifecycle missing. |
| 38 | `MATCH_CHANGE_SLOT` | Missing | Multiplayer slot state missing. |
| 39 | `MATCH_READY` | Missing | Multiplayer ready state missing. |
| 40 | `MATCH_LOCK` | Missing | Multiplayer slot lock state missing. |
| 41 | `MATCH_CHANGE_SETTINGS` | Missing | Multiplayer match settings missing. |
| 44 | `MATCH_START` | Missing | Multiplayer start flow missing. |
| 47 | `MATCH_SCORE_UPDATE` | Missing | Multiplayer live score update missing. |
| 49 | `MATCH_COMPLETE` | Missing | Multiplayer completion flow missing. |
| 50 | `MATCH_CHANGE_BEATMAP` | Missing | Multiplayer beatmap state missing. |
| 51 | `MATCH_CHANGE_MODS` | Missing | Multiplayer mod state missing. |
| 52 | `MATCH_LOAD_COMPLETE` | Missing | Multiplayer load state missing. |
| 54 | `MATCH_NO_BEATMAP` | Missing | Multiplayer beatmap availability state missing. |
| 55 | `MATCH_NOT_READY` | Missing | Multiplayer ready state missing. |
| 56 | `MATCH_FAILED` | Missing | Multiplayer failure state missing. |
| 59 | `MATCH_HAS_BEATMAP` | Missing | Multiplayer beatmap availability state missing. |
| 60 | `MATCH_SKIP` | Missing | Multiplayer skip vote flow missing. |
| 63 | `JOIN_CHANNEL` | Implemented | Channel join handler exists. |
| 68 | `BEATMAP_INFO` | Missing | Beatmap info reply flow missing. |
| 70 | `MATCH_TRANSFER_HOST` | Missing | Multiplayer host transfer missing. |
| 73 | `ADD_FRIEND` | Implemented | Friend relationship command exists. |
| 74 | `REMOVE_FRIEND` | Implemented | Friend relationship command exists. |
| 77 | `MATCH_CHANGE_TEAM` | Missing | Multiplayer team state missing. |
| 78 | `LEAVE_CHANNEL` | Implemented | Channel leave handler exists. |
| 79 | `RECEIVE_UPDATES` | Missing | Presence/update subscription behavior missing. |
| 82 | `SET_AWAY_MESSAGE` | Missing | Away message state missing. |
| 85 | `STATS_REQUEST` | Missing | Requested user stats response missing. |
| 87 | `MATCH_INVITE` | Missing | Multiplayer invite flow missing. |
| 90 | `MATCH_CHANGE_PASSWORD` | Missing | Multiplayer password update missing. |
| 93 | `TOURNAMENT_MATCH_INFO` | Missing | Tournament support missing. |
| 97 | `PRESENCE_REQUEST` | Missing | Targeted presence response missing. |
| 98 | `PRESENCE_REQUEST_ALL` | Missing | Full presence response missing. |
| 99 | `CHANGE_FRIENDONLY_DMS` | Implemented | Active-session DM preference update exists. |
| 108 | `TOURNAMENT_JOIN_MATCH_CHANNEL` | Missing | Tournament support missing. |
| 109 | `TOURNAMENT_LEAVE_MATCH_CHANNEL` | Missing | Tournament support missing. |

## S2C Packet Coverage

Canonical source: Lekuruu `bancho-documentation` wiki packet files and
`PacketEnums.md`. Cross-check Athena's `ServerPacketID` in
`src/osu_server/transports/stable/bancho/protocol/enums.py` before
implementation.

| ID | Packet | Status | Notes |
| --- | --- | --- | --- |
| 5 | `LOGIN_REPLY` | Builder | Login packet builder exists. |
| 6 | `COMMAND_ERROR` | Missing | Builder and runtime behavior missing. |
| 7 | `SEND_MESSAGE` | Builder | Chat delivery builder exists. |
| 8 | `PING` | Missing | Builder and runtime keepalive emission missing. |
| 9 | `IRC_CHANGE_USERNAME` | Missing | Rename flow missing. |
| 10 | `IRC_QUIT` | Missing | Quit notification builder missing. |
| 11 | `USER_STATS` | Builder | Builder exists; full stats projection is incomplete. |
| 12 | `USER_QUIT` | Partial | Athena broadcasts the old 4-byte user id form; modern stable adds a `QuitState` byte. |
| 13 | `SPECTATOR_JOINED` | Missing | Spectator support missing. |
| 14 | `SPECTATOR_LEFT` | Missing | Spectator support missing. |
| 15 | `SPECTATE_FRAMES` | Missing | Spectator support missing. |
| 19 | `VERSION_UPDATE` | Missing | Update flow missing. |
| 22 | `CANT_SPECTATE` | Missing | Spectator failure packet missing. |
| 23 | `GET_ATTENTION` | Missing | Moderation/admin attention flow missing. |
| 24 | `ANNOUNCE` | Builder | Notification builder exists. |
| 26 | `MATCH_UPDATE` | Missing | Multiplayer support missing. |
| 27 | `NEW_MATCH` | Missing | Multiplayer support missing. |
| 28 | `MATCH_DISBAND` | Missing | Multiplayer support missing. |
| 34 | `LOBBY_JOIN` | Missing | Multiplayer lobby support missing. |
| 35 | `LOBBY_PART` | Missing | Multiplayer lobby support missing. |
| 36 | `MATCH_JOIN_SUCCESS` | Missing | Multiplayer support missing. |
| 37 | `MATCH_JOIN_FAIL` | Missing | Multiplayer support missing. |
| 42 | `FELLOW_SPECTATOR_JOINED` | Missing | Spectator support missing. |
| 43 | `FELLOW_SPECTATOR_LEFT` | Missing | Spectator support missing. |
| 45 | `ALL_PLAYERS_LOADED` | Missing | Lekuruu marks this unused; prefer `MATCH_ALL_PLAYERS_LOADED` (53). Enum value is guarded by a regression test. |
| 46 | `MATCH_START` | Missing | Multiplayer start packet with `Match` payload. Enum value is guarded by a regression test. |
| 48 | `MATCH_SCORE_UPDATE` | Missing | Multiplayer support missing. |
| 50 | `MATCH_TRANSFER_HOST` | Missing | Multiplayer support missing. |
| 53 | `MATCH_ALL_PLAYERS_LOADED` | Missing | Multiplayer support missing. |
| 57 | `MATCH_PLAYER_FAILED` | Missing | Multiplayer support missing. |
| 58 | `MATCH_COMPLETE` | Missing | Multiplayer support missing. |
| 61 | `MATCH_SKIP` | Missing | Multiplayer support missing. |
| 62 | `UNAUTHORIZED` | Missing | Authorization failure packet missing. |
| 64 | `CHANNEL_JOIN_SUCCESS` | Builder | Channel join builder exists. |
| 65 | `CHANNEL_AVAILABLE` | Builder | Channel listing builder exists. |
| 66 | `CHANNEL_REVOKED` | Builder | Channel leave/revoke builder exists. |
| 67 | `CHANNEL_AVAILABLE_AUTOJOIN` | Builder | Autojoin channel builder exists. |
| 69 | `BEATMAP_INFO_REPLY` | Missing | Beatmap info flow missing. |
| 71 | `LOGIN_PERMISSIONS` | Builder | Login packet builder exists. |
| 72 | `FRIENDS_LIST` | Builder | Login/friends builder exists. |
| 75 | `PROTOCOL_VERSION` | Builder | Login packet builder exists. |
| 76 | `MENU_ICON` | Missing | Menu icon packet missing. |
| 80 | `MONITOR` | Missing | Monitor packet missing. |
| 81 | `MATCH_PLAYER_SKIPPED` | Missing | Multiplayer support missing. |
| 83 | `USER_PRESENCE` | Builder | Builder exists; full presence behavior incomplete. |
| 84 | `IRC_ONLY` | Missing | IRC-only mode packet missing. |
| 86 | `RESTART` | Missing | Restart notification packet missing. |
| 88 | `INVITE` | Missing | Multiplayer invite packet missing. |
| 89 | `CHANNEL_INFO_COMPLETE` | Builder | Channel listing terminator builder exists. |
| 91 | `MATCH_CHANGE_PASSWORD` | Missing | Multiplayer password packet missing. |
| 92 | `SILENCE_INFO` | Builder | Silence info builder exists; moderation workflow incomplete. |
| 94 | `USER_SILENCED` | Missing | Moderation workflow missing. |
| 95 | `USER_PRESENCE_SINGLE` | Missing | Targeted presence packet missing. |
| 96 | `USER_PRESENCE_BUNDLE` | Builder | Presence bundle builder exists. |
| 100 | `USER_DM_BLOCKED` | Builder | Private-message rejection builder exists. |
| 101 | `TARGET_IS_SILENCED` | Missing | Moderation workflow missing. |
| 102 | `VERSION_UPDATE_FORCED` | Missing | Forced update flow missing. |
| 103 | `SWITCH_SERVER` | Missing | Server switch flow missing. |
| 104 | `ACCOUNT_RESTRICTED` | Missing | Restriction workflow missing. |
| 105 | `RTX` | Missing | Unknown/rare stable packet; verify before implementing. |
| 106 | `MATCH_ABORT` | Missing | Multiplayer support missing. |
| 107 | `SWITCH_TOURNAMENT_SERVER` | Missing | Tournament support missing. |

## Bancho Struct Coverage

Canonical source: Lekuruu `Types/*.md`. Struct rows should be implemented as
local transport wire types before packet handlers/builders depend on them.
Exact current field layouts and enum values are summarized in
[stable-compatibility-guide.md](stable-compatibility-guide.md#bancho-struct-field-reference).

| Type | Status | Blocking packet dependencies | Notes |
| --- | --- | --- | --- |
| `String` | Implemented | Chat, login, channel, match, beatmap info packets | Implemented as `BanchoString`. |
| `Message` | Implemented | C2S/S2C `SEND_MESSAGE`, private message packets | Used by chat C2S/S2C packets. |
| `IntList` | Implemented | `FRIENDS_LIST`, `USER_PRESENCE_BUNDLE` | Used by friends and presence bundle packets. |
| `Channel` | Implemented | `CHANNEL_AVAILABLE`, `CHANNEL_AVAILABLE_AUTOJOIN` | Used by channel list packets. |
| `StatusUpdate` | Implemented | C2S `STATUS_CHANGE`, S2C `USER_STATS` | Used by `STATUS_CHANGE`; behavior is still partial. |
| `Status` | Missing | `STATUS_CHANGE`, `USER_STATS` | Needs explicit enum/value audit for stable status values. |
| `Mode` | Missing | `STATUS_CHANGE`, `USER_STATS`, `USER_PRESENCE`, score modes | Needs stable mode enum and converted-mode policy audit. |
| `Mods` | Missing | `STATUS_CHANGE`, score submit, `MATCH`, leaderboard family policy | Needs stable mod bitmask coverage and conversion tests. |
| `Grade` | Missing | score submit, getscores, `BEATMAP_INFO_REPLY` | Needed for score submit, getscores, and leaderboard display. |
| `ButtonState` | Missing | `SEND_FRAMES`, `SPECTATE_FRAMES` | Needed by replay/spectator frame structs. |
| `PresenceFilter` | Missing | `RECEIVE_UPDATES` | Needed by update subscription behavior. |
| `QuitState` | Missing | `USER_QUIT` | Needed by modern `USER_QUIT`. |
| `ReplayAction` | Missing | `SEND_FRAMES`, `SPECTATE_FRAMES` | Needed by replay/spectator frame structs. |
| `ReplayFrame` | Missing | `SEND_FRAMES`, `SPECTATE_FRAMES` | Blocks spectator frame relay. |
| `ScoreFrame` | Missing | C2S 47 `MATCH_SCORE_UPDATE`, S2C 48 `MATCH_SCORE_UPDATE`, `SPECTATE_FRAMES` | Critical blocker for multiplayer/spectator score updates. |
| `ReplayFrameBundle` | Missing | C2S `SEND_FRAMES`, S2C `SPECTATE_FRAMES` | Critical blocker for spectator frame relay. |
| `BeatmapInfo` | Missing | C2S `BEATMAP_INFO`, S2C `BEATMAP_INFO_REPLY`, `/web/osu-getbeatmapinfo.php` | Needed by beatmap info request/reply flow. |
| `BeatmapInfoRequest` | Missing | C2S `BEATMAP_INFO` | Needed by C2S `BEATMAP_INFO`. |
| `BeatmapInfoReply` | Missing | S2C `BEATMAP_INFO_REPLY` | Needed by S2C `BEATMAP_INFO_REPLY`. |
| `UserPresence` | Partial | `USER_PRESENCE`, `USER_PRESENCE_SINGLE`, login presence bundle | Builder-local shape exists; needs canonical struct and golden tests. |
| `UserPresenceBundle` | Partial | `USER_PRESENCE_BUNDLE`, login online user list | Built as `IntList`; needs canonical naming and tests. |
| `UserStats` | Partial | `USER_STATS`, login stats, requested stats | Builder-local shape exists; stats projection is incomplete. |
| `Match` | Missing | `CREATE_MATCH`, `JOIN_MATCH`, `MATCH_UPDATE`, `NEW_MATCH`, `MATCH_START`, `MATCH_JOIN_SUCCESS` | Critical blocker for multiplayer packets. |
| `MatchJoin` | Missing | C2S `CREATE_MATCH`, C2S `JOIN_MATCH` | Needed by match join/create packet payloads. |

## Stable HTTP Endpoint Coverage

Implemented route source: `src/osu_server/composition/application.py`. Candidate
rows are derived from `osuRipple/lets` and `osuTitanic/deck`; confirm each by
target client traffic before making it a required Athena surface.

Candidate rows must not remain indefinite. For each candidate endpoint, create a
tracking issue that records whether target stable clients call it, then promote
it to `Implemented` / `Partial` / `Missing` when it is required, or demote it to
`Out of scope` when traffic and reference review show it is unnecessary.

| Method | Endpoint | Status | Notes |
| --- | --- | --- | --- |
| `POST` | `/` on `c.$DOMAIN`, `c<int>.$DOMAIN`, `ce.$DOMAIN` | Implemented | Bancho login and packet polling entrypoint. |
| `POST` | `/` on `cho.$DOMAIN`, `mahbahowc.$DOMAIN`, `server.$DOMAIN` | Candidate | Bancho host aliases observed in `osuTitanic/titanic`; not currently routed by Athena. |
| `POST` | `/users` on `osu.$DOMAIN` | Implemented | Stable registration endpoint. |
| `POST` | `/web/users` local fallback | Implemented | Development fallback route for registration. |
| `GET` | `/web/bancho_connect.php` | Partial | Reachability handshake only; credential validation is delegated to login. |
| `GET` | `/web/osu-osz2-getscores.php` | Partial | Stable response mapping exists; full score rows depend on leaderboard projections. |
| `POST` | `/web/osu-submit-modular-selector.php` | Partial | Score submission exists; rank/stat projection fields are incomplete. |
| `POST` | `/web/osu-submit-modular.php` | Candidate | Legacy score submit variant in `lets` and `deck`; decide whether target clients need it. |
| `POST` | `/web/osu-submit.php`, `/web/osu-submit-new.php` | Candidate | Older score submit variants in `deck`; likely legacy-only but should be explicitly scoped. |
| `POST` | `/web/osu-session.php` | Candidate | Listed as unhandled in `bancho.py`; verify whether target clients still call it. |
| `GET` | `/web/osu-getscores.php` through `/web/osu-getscores6.php` | Candidate | Older getscores variants in `deck`; decide target client build coverage. |
| `GET` | `/web/osu-getreplay.php` | Missing | Replay download flow missing. |
| `GET` | `/web/replays/<id>` | Candidate | Full replay route in `lets`; verify client usage. |
| `GET` | `/web/check-updates.php` | Missing | Stable update compatibility route in `lets`, `deck`, and `bancho.py`; initial Athena policy is no-update/no-op. Audit: stable_compatibility_route_classification=required-no-update; response_shape=[]; evidence_source=deck [] + bancho.py empty body + user-confirmed current osu!stable --devserver behavior; stable_operational_dependency=proxy-decision-required; stable_fixture_requirement=check_updates_no_update_json_array. Proxying to `osu.ppy.sh` remains a separate ppy proxying decision requirement, not the initial implementation default. |
| `GET` | `/release/update`, `/update` | Candidate | Stable release manifest route and root alias; initial Athena policy is no-update/no-op. Audit: stable_compatibility_route_classification=required-no-update; response_shape=empty body; evidence_source=stable-compatibility-guide `/release/update` empty string + research decision; stable_operational_dependency=none; stable_fixture_requirement=release_update_empty. The hosted update metadata or artifact distribution behavior is outside initial no-update policy. |
| `GET` | `/release/update.php`, `/update.php` | Candidate | Stable release file-check manifest route and root alias; initial Athena policy is no-update/no-op. Audit: stable_compatibility_route_classification=required-no-update; response_shape=0; evidence_source=stable-compatibility-guide `/release/update.php` `0` + research decision; stable_operational_dependency=none; stable_fixture_requirement=release_update_php_zero. The hosted update metadata or artifact distribution behavior is outside initial no-update policy. |
| `GET` | `/release/update2.php`, `/update2.php` | Candidate | Stable release secondary manifest route and root alias; initial Athena policy is no-update/no-op. Audit: stable_compatibility_route_classification=required-no-update; response_shape=empty body; evidence_source=stable-compatibility-guide `/release/update2.php` empty string + research decision; stable_operational_dependency=none; stable_fixture_requirement=release_update2_empty. The hosted update metadata or artifact distribution behavior is outside initial no-update policy. |
| `GET` | `/release/patches.php`, `/patches.php` | Candidate | Stable release patch manifest route and root alias; initial Athena policy is no-update/no-op. Audit: stable_compatibility_route_classification=required-no-update; response_shape=empty body; evidence_source=stable-compatibility-guide `/release/patches.php` empty string + research decision; stable_operational_dependency=none; stable_fixture_requirement=release_patches_empty. The hosted update metadata or artifact distribution behavior is outside initial no-update policy. |
| `GET` | `/release/<filename>`, `/release/filter.txt`, `/release/Localisation/<filename>`, `/release/<language>/<filename>` | Candidate | Release files/localization/filter routes in `deck`; proxy/hosting requires an explicit operational decision. |
| `GET` | `/web/osu-search.php`, `/web/osu-search-set.php` | Missing | osu!direct search and set details missing. |
| `GET` | `/d/<set>`, `/s/<set>`, `/bss/<set>`, `/osu/<map>`, `/web/maps/<file>`, `b.$DOMAIN/<path>`, `s.$DOMAIN/<path>`, `d.$DOMAIN/d/<set>` | Candidate | Beatmap download and `.osu` file routes from references. |
| `GET` | `/mt/*`, `/thumb/*`, `/images/map-thumb/*`, `/preview/*`, `/mp3/preview/*` | Candidate | Beatmap thumbnails and preview media routes from `deck`. |
| `POST` | `/web/osu-getbeatmapinfo.php` | Missing | Legacy web beatmap info endpoint in `deck`; separate from Bancho packet 68/69. |
| `GET` | `/web/osu-gethashes.php`, `/web/osu-osz2-getfileinfo.php`, `/web/osu-osz2-getrawheader.php`, `/web/osu-osz2-getfilecontents.php`, `/web/osu-magnet.php` | Candidate | osz2/hash/file-content helper endpoints in `deck`. |
| `POST` | `/web/osu-screenshot.php`, `/web/osu-ss.php` | Missing | Screenshot upload flow missing. |
| `GET` | `/ss/`, `/ss/<id>`, `/ss/<id>/<checksum>`, `/ss/<id>.<extension>` | Candidate | Screenshot serving routes from `deck` and `bancho.py`. |
| `GET` | `/a/`, `/a/<filename>`, `/forum/download.php`, `/assets/menu-content.json`, `/menu-content.json` | Candidate | Avatar and menu/static routes from `deck` and `titanic`. |
| `POST` | `/web/osu-error.php` | Candidate | Client error report route in `lets` and `deck`. |
| `GET` | `/web/osu-rate.php`, `/rating/ingame-rate.php`, `/rating/ingame-rate2.php` | Candidate | Beatmap rating routes from references. |
| `POST` | `/web/osu-comment.php` | Candidate | Beatmap/replay/comment route from references. |
| `GET` | `/web/osu-addfavourite.php`, `/web/osu-getfavourites.php` | Candidate | Favourite mutation/list routes from references. |
| `GET` | `/web/osu-stat.php`, `/web/osu-statoth.php` | Candidate | User stats lookup routes from `deck`. |
| `GET` | `/web/osu-getstatus.php` | Candidate | Beatmap checksum/status route from `deck`; request and response shape are documented in the guide. |
| `GET` | `/web/osu-getfriends.php` | Missing | Friend relationships exist through packets, but web route is absent. |
| `GET` | `/web/osu-markasread.php`, `/web/osu-checktweets.php`, `/web/lastfm.php` | Candidate | Compatibility no-op or social/status routes in references. |
| `GET` | `/web/osu-getseasonal.php` | Missing | Seasonal asset JSON route missing. |
| `GET` | `/web/osu-login.php` | Candidate | Web login route in `deck`; verify stable client usage. |
| `GET` | `/web/osu-title-image.php`, `/menu-content.json` | Candidate | Title/menu asset routes from `deck`. |
| `GET` | `/web/coins.php` | Candidate | Client-side currency route in `deck`; likely optional/private-server-specific. |
| `POST` | `/web/osu-benchmark.php` | Candidate | Client benchmark diagnostics route in `deck`; likely optional/private-server-specific. |
| `POST` | `/difficulty-rating` | Candidate | Present in `bancho.py`; verify whether stable clients or tooling rely on it. |
| mixed | beatmap submission endpoints under `/web/osu-bmsubmit-*` and `/web/osu-osz2-bmsubmit-*` | Candidate | Beatmap submission/upload routes in `deck`; likely out of initial server scope but should be explicit. |

## Akatsuki-Compatible Score Extensions

These are not baseline osu!stable requirements, but they are part of the
Akatsuki behavior set the project is using as an integrated reference. Keep them
visible so Athena does not accidentally design leaderboard persistence that
cannot support them later.

Decision status: RX/AP is not part of the initial vanilla stable compatibility
baseline, but score ingestion, leaderboard query repositories, and stats
projections must preserve a `leaderboard_family` or equivalent read-model key so
Athena can add separated vanilla, Relax, and Autopilot boards without a schema
redesign. The family belongs to score/stat projections, not to beatmap identity.

| Surface | Status | Requirement |
| --- | --- | --- |
| Relax score submit classification | Missing | Detect stable `Relax` mod (`128`) and map the submitted play to a separate Relax leaderboard family instead of vanilla. |
| Autopilot score submit classification | Missing | Detect stable `Autopilot` mod (`8192`) and map osu!standard plays to a separate Autopilot leaderboard family. |
| Expanded mode ids | Missing | Preserve a read-model policy for `vn!std=0`, `vn!taiko=1`, `vn!catch=2`, `vn!mania=3`, `rx!std=4`, `rx!taiko=5`, `rx!catch=6`, `ap!std=8`; Akatsuki declares `rx!mania=7` and `ap!taiko/catch/mania=9..11` but treats them as unused. |
| RX/AP getscores | Missing | `/web/osu-osz2-getscores.php` must be able to query personal best and top rows for the selected leaderboard family without mixing vanilla, Relax, and Autopilot rows. |
| RX/AP user stats and ranks | Missing | Stats projections need separate total/ranked score, pp, accuracy, play count, rank, country rank, and grade counts per supported leaderboard family. |
| RX/AP API/profile exposure | Candidate | First-party APIs and future profile/ranking pages should expose the same separated leaderboard families if Athena chooses Akatsuki-compatible RX/AP support. |

## Reference Route Inventory

This exact-path inventory is used to audit the grouped endpoint rows above.
Entries come from `osuTitanic/deck` route decorators, `osuTitanic/titanic`
host routing, and `osuAkatsuki/bancho.py` routes. Keep this list exact enough
for mechanical diff checks; implementation issues can still group related rows.

### Deck Web Routes

| Method | Endpoint | Area |
| --- | --- | --- |
| `GET` | `/web/bancho_connect.php` | connection |
| `GET` | `/web/check-updates.php` | update |
| `POST` | `/web/osu-error.php` | diagnostics |
| `POST` | `/web/osu-screenshot.php` | screenshots |
| `POST` | `/web/osu-ss.php` | screenshots/monitor |
| `GET` | `/web/osu-osz2-getscores.php` | leaderboards |
| `GET` | `/web/osu-getscores6.php` | legacy leaderboards |
| `GET` | `/web/osu-getscores5.php` | legacy leaderboards |
| `GET` | `/web/osu-getscores4.php` | legacy leaderboards |
| `GET` | `/web/osu-getscores3.php` | legacy leaderboards |
| `GET` | `/web/osu-getscores2.php` | legacy leaderboards |
| `GET` | `/web/osu-getscores.php` | legacy leaderboards |
| `POST` | `/web/osu-submit-modular-selector.php` | score submit |
| `POST` | `/web/osu-submit-modular.php` | score submit |
| `POST` | `/web/osu-submit.php` | legacy score submit |
| `POST` | `/web/osu-submit-new.php` | legacy score submit |
| `GET` | `/web/osu-getreplay.php` | replays |
| `GET` | `/web/osu-search.php` | osu!direct |
| `GET` | `/web/osu-search-set.php` | osu!direct |
| `POST` | `/web/osu-getbeatmapinfo.php` | beatmaps |
| `GET` | `/web/osu-getstatus.php` | beatmaps |
| `GET` | `/web/maps/{query}` | beatmap files |
| `GET` | `/web/osu-gethashes.php` | osz2 |
| `GET` | `/web/osu-osz2-getfileinfo.php` | osz2 |
| `GET` | `/web/osu-osz2-getrawheader.php` | osz2 |
| `GET` | `/web/osu-osz2-getfilecontents.php` | osz2 |
| `GET` | `/web/osu-magnet.php` | osz2 |
| `GET` | `/web/osu-getfriends.php` | social |
| `GET` | `/web/osu-addfavourite.php` | favourites |
| `GET` | `/web/osu-getfavourites.php` | favourites |
| `GET` | `/web/osu-rate.php` | ratings |
| `POST` | `/web/osu-comment.php` | comments |
| `GET` | `/web/osu-stat.php` | stats |
| `GET` | `/web/osu-statoth.php` | stats |
| `GET` | `/web/osu-markasread.php` | social |
| `GET` | `/web/osu-checktweets.php` | social |
| `GET` | `/web/osu-getseasonal.php` | seasonal |
| `GET` | `/web/osu-login.php` | login |
| `GET` | `/web/osu-title-image.php` | menu |
| `GET` | `/web/coins.php` | optional/private-server |
| `POST` | `/web/osu-benchmark.php` | diagnostics |
| `GET` | `/web/osu-osz2-bmsubmit-getid.php` | beatmap submission |
| `POST` | `/web/osu-osz2-bmsubmit-upload.php` | beatmap submission |
| `POST` | `/web/osu-osz2-bmsubmit-post.php` | beatmap submission |
| `GET` | `/web/osu-get-beatmap-topic.php` | beatmap submission |
| `POST` | `/web/osu-bmsubmit-getid5.php` | legacy beatmap submission |
| `POST` | `/web/osu-bmsubmit-getid4.php` | legacy beatmap submission |
| `POST` | `/web/osu-bmsubmit-getid3.php` | legacy beatmap submission |
| `POST` | `/web/osu-bmsubmit-getid2.php` | legacy beatmap submission |
| `POST` | `/web/osu-bmsubmit-getid.php` | legacy beatmap submission |
| `POST` | `/web/osu-bmsubmit-upload.php` | legacy beatmap submission |
| `GET` | `/web/osu-bmsubmit-novideo.php` | legacy beatmap submission |
| `POST` | `/web/osu-bmsubmit-post3.php` | legacy beatmap submission |
| `POST` | `/web/osu-bmsubmit-post2.php` | legacy beatmap submission |
| `POST` | `/web/osu-bmsubmit-post.php` | legacy beatmap submission |

### Static, Release, Rating, And Host Routes

| Method | Endpoint | Area |
| --- | --- | --- |
| `GET` | `/a/` | avatars |
| `GET` | `/a/{filename}` | avatars |
| `GET` | `/forum/download.php` | avatars |
| `GET` | `/mt/{filename}` | beatmap thumbnails |
| `GET` | `/thumb/{filename}` | beatmap thumbnails |
| `GET` | `/images/map-thumb/{filename}` | beatmap thumbnails |
| `GET` | `/preview/{filename}` | preview audio |
| `GET` | `/mp3/preview/{filename}` | preview audio |
| `GET` | `/d/{filename}` | beatmap downloads |
| `GET` | `/bss/{filename}` | beatmap downloads |
| `GET` | `/osu/{query}` | beatmap files |
| `GET` | `/ss/` | screenshots |
| `GET` | `/ss/{id}` | screenshots |
| `GET` | `/ss/{id}/{checksum}` | screenshots |
| `GET` | `/assets/menu-content.json` | menu |
| `GET` | `/menu-content.json` | menu host rewrite |
| `GET` | `/release/update` | update |
| `GET` | `/release/patches.php` | update |
| `GET` | `/release/update.php` | update |
| `GET` | `/release/update2.php` | update |
| `GET` | `/update` | root update alias |
| `GET` | `/update.php` | root update alias |
| `GET` | `/update2.php` | root update alias |
| `GET` | `/patches.php` | root update alias |
| `GET` | `/release/{filename}` | release files |
| `GET` | `/release/filter.txt` | release files |
| `GET` | `/release/Localisation/{filename}` | release files |
| `GET` | `/release/{language}/{filename}` | release files |
| `GET` | `/rating/ingame-rate.php` | ratings |
| `GET` | `/rating/ingame-rate2.php` | ratings |
| `GET` | `a.$DOMAIN/*` | avatar host rewrite to `/a{uri}` |
| `GET` | `a.$DOMAIN/avatar/*` | external avatar host variant |
| `GET` | `a.$DOMAIN/ss/*.jpg` | external screenshot host variant |
| `GET` | `b.$DOMAIN/d/*` | beatmap download host |
| `GET` | `b.$DOMAIN/mt/*` | beatmap thumbnail host |
| `GET` | `b.$DOMAIN/thumb/*` | beatmap thumbnail host |
| `GET` | `b.$DOMAIN/images/map-thumb/*` | beatmap thumbnail host |
| `GET` | `b.$DOMAIN/preview/*` | preview audio host |
| `GET` | `b.$DOMAIN/mp3/preview/*` | preview audio host |
| `GET` | `d.$DOMAIN/d/*` | beatmap download host |
| `GET` | `d.osu.$DOMAIN/d/*` | beatmap download host |
| `GET` | `s.$DOMAIN/images/map-thumb/*` | static host |
| `GET` | `s.$DOMAIN/images/*` | static image host |
| `GET` | `s.$DOMAIN/a/*` | static avatar host |
| `GET` | `s.$DOMAIN/thumb/*` | static thumbnail host |
| `GET` | `s.$DOMAIN/mt/*` | static thumbnail host |
| `GET` | `s.$DOMAIN/preview/*` | static preview host |
| `GET` | `s.$DOMAIN/mp3/preview/*` | static preview host |

### Lets Route Aliases

| Method | Endpoint | Area |
| --- | --- | --- |
| `GET` | `/d/{filename}` | beatmap downloads |
| `GET` | `/s/{filename}` | beatmap downloads |
| `GET` | `/web/replays/{id}` | replay download |
| `GET` | `/ss/{filename}` | screenshots |
| `GET` | `/p/changelog` | public web redirect/content |
| `GET` | `/p/verify` | verification redirect |
| `GET` | `/u/{user}` | profile redirect |

## Persistence Inventory Coverage

Reference database schemas and repository queries are useful for discovering
which durable facts production servers needed to answer stable clients. They are
not schema templates for Athena. Implement Athena tables through its domain,
repository, and Unit of Work boundaries, then verify that the observable stable
responses can be produced.

Primary schema references:

- `osuAkatsuki/bancho.py`: `migrations/base.sql`,
  `migrations/migrations.sql`, and `app/repositories/*.py`.
- `osuTitanic/titanic`: `migrations/*.up.sql`.
- `osuRipple/lets` and `osuRipple/pep.py`: query usage in legacy web and Bancho
  handlers, especially score, beatmap, relationship, client, and report flows.

GitHub discovery note: direct GitHub code search was attempted for additional
avatar/static/thumbnail implementations, but the authenticated API hit rate
limits during this audit. Public repository pages for `osuAkatsuki/bancho.py`
and `osuTitanic/deck` were reachable, and detailed route behavior was audited
from the local clones listed above.

| Area | Domain owner | Durable data to audit | Primary consumers | Current gap | Status |
| --- | --- | --- | --- | --- | --- |
| Identity and login | `domain/identity` user/session aggregates | user id, username/safe name, password hash, email, country, activation, latest activity, preferred mode, play style, supporter/donor state | Bancho login, registration, profile/user lookup | Core user/login data exists; activation/supporter/profile projection coverage is incomplete. | Partial |
| Permissions and moderation | `domain/identity` authorization plus moderation aggregate | role/group membership, Bancho permissions, silence end, restricted/banned state, infringement/report/audit logs | login replies, channel access, chat, restrictions, admin actions | Role/permission language exists; moderation audit and infringement history are incomplete. | Partial |
| Client integrity | stable compatibility client-integrity aggregate | client hashes, executable/path hashes, adapters, unique id, disk signature, verified hardware exceptions, login history | login validation, multi-account policy, score submit validation | No durable integrity model yet. | Missing |
| Social graph | identity relationship aggregate | friends, blocks, friend-only DMs, direct messages/read state | friend packets, private messages, DM privacy | Friend and DM preference support exists; blocks and read-state persistence are incomplete. | Partial |
| Chat and channels | `domain/chat` channel/message aggregates | channel definitions, read/write permissions, autojoin channels, persisted messages, chat filters | login channel list, channel join/leave, public/private chat | Channel/chat flows exist; persisted history and moderation filters are incomplete. | Partial |
| Beatmaps and beatmapsets | `domain/beatmaps` beatmap/beatmapset aggregates | beatmap id, set id, md5, filename, status, metadata, mode, difficulty stats, play/pass counts, mirrors/resources, favourites, ratings, comments | getscores, beatmap info packet, osu!direct, downloads, comments | Metadata and mirror boundaries exist; osu!direct, ratings, comments, and full file serving are incomplete. | Partial |
| Scores and leaderboard | `domain/scores` score plus leaderboard read model | score id, user id, beatmap id/md5, score checksum, client version/hash, mode, mods, hit counts, grade, combo, pp, accuracy, status, submitted time, replay md5, fail time, leaderboard family for vanilla/Relax/Autopilot where enabled | score submit, getscores, rankings, user stats, replay download, Akatsuki-compatible RX/AP boards | Submission path exists; complete rows, ranking projections, and RX/AP family separation are incomplete. | Partial |
| User stats and rankings | scores/stat projection read model | total/ranked score, pp, accuracy, play count, playtime, max combo, total hits, grade counts, rank, country rank, rank history | user stats packets, presence panels, profile/ranking views | Placeholder stats exist; rank/country-rank/history projections are incomplete. | Partial |
| Replays and media metadata | `domain/scores` replay plus `domain/storage` blob metadata | replay object key/checksum, replay view counts, screenshot metadata, avatar metadata, beatmap asset metadata, seasonal asset metadata, update file metadata | replay download, screenshot upload/download, avatar/static endpoints, updater | Object metadata model and endpoint coverage are missing. | Missing |
| Static/media delivery | `domain/storage` asset delivery read model | screenshot id, screenshot owner, created-at checksum, hidden/expiry flags, avatar hash, avatar update time, beatmap background key, preview audio key, `.osu` object key, `.osz` object key, full/no-video sizes, content length, last-modified time, mirror URL, download-server routing | `/ss/*`, `/a/*`, `/mt/*`, `/thumb/*`, `/preview/*`, `/osu/*`, `/d/*`, `/bss/*`, `/s/*` | Delivery routing, cache headers, and object lookup projections are missing. | Missing |
| Release/update files | release/update asset aggregate | release version, file hash, patch URL, full file URL, release timestamp, extra file md5, extra download key, localization language/file key | `/web/check-updates.php`, `/release/update*`, `/release/<file>`, root `/update*` and `/patches.php` aliases | Initial no-update/no-op policy is documented; hosted/proxy update storage is missing. | Missing |
| Ratings/comments/favourites | beatmap social aggregate | beatmap ratings by user, comments by target type/id, favourite set relationships, read markers | `/web/osu-rate.php`, `/rating/ingame-rate.php`, `/rating/ingame-rate2.php`, `/web/osu-comment.php`, `/web/osu-addfavourite.php`, `/web/osu-getfavourites.php`, `/web/osu-markasread.php` | Durable ratings/comments/favourites/read markers are missing. | Missing |
| Achievements and notifications | achievement/notification aggregates | achievement definitions/unlocks, notifications, user badges/profile badges | score submit unlock flow, profile display, notification packets | Achievement and notification models are missing. | Missing |
| Multiplayer and tournaments | multiplayer match/tournament aggregates | match records, match events, pool definitions, pool maps, host/slot/team settings as durable audit where needed | multiplayer packet family, tournament packet family | Runtime and durable multiplayer models are missing. | Missing |

Use `Replays and media metadata` for ownership of stored object facts and audit
metadata. Use `Static/media delivery` for HTTP routing, cache behavior, mirrors,
and response headers over those objects.

## GitHub Project Shape

Use a GitHub Project as the execution board for this matrix. Recommended fields:

| Field | Values |
| --- | --- |
| `Area` | `bancho-packet`, `bancho-struct`, `web-legacy`, `static-media`, `release-update`, `presence`, `chat`, `scores`, `beatmaps`, `multiplayer`, `spectator`, `moderation`, `client-integrity`, `ops` |
| `Stable surface` | Packet name or endpoint path. |
| `Reference status` | `needs-doc-audit`, `needs-traffic-capture`, `reference-confirmed` |
| `Reference implementation` | `bancho.py`, `lets`, `pep.py`, `deck`, `titanic`, `Lekuruu wiki`, or `observed-client`. |
| `Implementation status` | Same status labels as this document. |
| `Verification` | `none`, `unit`, `integration`, `fixture`, `real-client-probe` |
| `Priority` | `P0 core login/play`, `P1 normal gameplay`, `P2 social/multiplayer`, `P3 ops/polish` |

Recommended initial Project epics:

- Stable protocol inventory audit against documentation, real client traffic,
  `osuRipple/pep.py`, `osuTitanic/titanic`, and the bancho side of
  `osuAkatsuki/bancho.py`.
- Legacy `/web/*.php` endpoint inventory audit against traffic,
  `osuRipple/lets`, `osuTitanic/deck`, and the legacy web side of
  `osuAkatsuki/bancho.py`.
- Persistence inventory audit against `bancho.py` schemas, `titanic`
  migrations, and query usage in `lets` and `pep.py`.
- Request/response fixture extraction for each implemented endpoint.
- Bancho struct golden fixture extraction from Lekuruu `Types/*.md`.
- Match payload builder and golden fixtures for multiplayer packet implementation.
- Presence and user stats completion.
- Beatmap info, osu!direct, replay, and file-serving compatibility.
- Score, leaderboard, personal best, user stats, and rank projection completion.
- Multiplayer packet family.
- Spectator packet family.
- Moderation, restrictions, silence, and audit workflows.
- Real-client probe suite and golden fixture expansion.

Recommended dependency order:

1. Complete protocol, legacy web, and persistence inventory audits.
2. Extract struct and request/response golden fixtures from confirmed references.
3. Finish core presence, user stats, score, leaderboard, beatmap info, and file
   serving projections.
4. Implement multiplayer and spectator packet families after `Match`,
   `ScoreFrame`, and `ReplayFrameBundle` fixtures exist.
5. Add moderation, restrictions, release/update policy, and optional RX/AP
   compatibility once core stable gameplay behavior is fixture-backed.
6. Promote the real-client probe suite into CI after it can run deterministically
   against local services and seeded fixture data.

## Completion Rule

Do not call stable compatibility complete until all of these are true:

1. Every C2S enum row is either implemented, explicitly out of scope, or backed by
   a documented reason for deferral.
2. Every S2C enum row has a builder or an explicit reason it is not emitted.
3. Every Lekuruu `Types/*.md` struct is implemented, explicitly out of scope, or
   backed by a documented reason for deferral.
4. Every observed stable `/web/*.php`, static/media, and update/release request
   has a row in this document.
5. Every implemented stable surface has automated verification. Packet and
   wire-format surfaces require at least unit plus golden fixture coverage;
   HTTP endpoints require route integration plus response fixture coverage.
6. A real stable client probe has covered login, idle polling, chat, score submit,
   getscores, beatmap download/search scope, and reconnect behavior.

Promotion from `Partial` to `Implemented` requires explicit exit criteria in the
tracking issue. For example, getscores requires full header and row projection,
personal best handling, ranking status mapping, and fixture coverage; score
submit requires durable replay metadata, leaderboard reconciliation, stats/rank
projection, and real-client probe coverage for the response body.
