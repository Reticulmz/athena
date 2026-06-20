# Stable Compatibility Guide

This guide describes the osu! stable compatibility surfaces Athena needs to
serve, with the request formats, response formats, processing flows, reference
sources, and known implementation gaps that should guide future work.

The companion checklist is
[stable-compatibility-matrix.md](stable-compatibility-matrix.md). Use the matrix
to track coverage. Use this guide to understand what each surface is supposed to
do and what Athena must implement.

## Scope

This document covers osu! stable clients only:

- HTTP Bancho transport on `c.$DOMAIN`, `c<int>.$DOMAIN`, and `ce.$DOMAIN`.
- Bancho binary C2S and S2C packets.
- Legacy web endpoints under `/web/*.php`.
- Stable static/media endpoints used by the client for beatmaps, replays,
  avatars, screenshots, update checks, and osu!direct-like flows.

This document does not define lazer REST API v2 or SignalR behavior except when a
stable workflow eventually needs shared domain data.

## Reference Sources

Use references in this order:

1. Lekuruu `bancho-documentation` wiki for Bancho packet IDs, primitive wire
   types, and struct layouts.
2. Observed stable client traffic captured from a real client.
3. Athena implementation and tests.
4. Reference implementations:
   - `osuAkatsuki/bancho.py` for integrated Bancho plus legacy web behavior.
   - `osuRipple/lets` for legacy web endpoints.
   - `osuRipple/pep.py` for Bancho packet/session behavior.
   - `osuTitanic/deck` for legacy web endpoints.
   - `osuTitanic/titanic` for deployment routing and Bancho/static split.
   - `sutekina/osu-gulag` and `SunriseCommunity/Sunrise` as additional
     external evidence for avatar, static media, direct, and update behavior.
5. Athena design notes in `bancho_server_design.md` and `CONTEXT.md`.

Reference implementation paths used while writing this guide:

| Repository | Relevant paths |
| --- | --- |
| Lekuruu wiki | `Protocol.md`, `Login.md`, `PacketEnums.md`, `Types/*.md`, `Packets/Client/*.md`, `Packets/Server/*.md` |
| Athena | `src/osu_server/transports/stable/bancho`, `src/osu_server/transports/stable/web_legacy`, `src/athena_cli/stable_verification` |
| bancho.py | `app/api/domains/cho.py`, `app/api/domains/osu.py`, `app/packets.py`, `app/objects/player.py`, `app/objects/match.py`, `migrations/base.sql`, `app/repositories/*.py` |
| lets | `lets.py`, `handlers/*`, `objects/beatmap.pyx`, `objects/score.pyx`, `objects/scoreboard.pyx` |
| pep.py | `handlers/mainHandler.pyx`, `constants/packetIDs.py`, `constants/serverPackets.py`, `helpers/packetHelper.pyx`, `objects/osuToken.py`, `objects/match.py` |
| deck | `app/routes/web/*`, `app/routes/static/*`, `app/helpers/chart.py`, `app/helpers/score.py` |
| titanic | `migrations/*.up.sql`, `services/caddy/Caddyfile` |

Public GitHub source files inspected for static/media behavior:

- `osuTitanic/deck`: `app/routes/static/avatars.py`,
  `app/routes/static/beatmapsets.py`, `app/routes/static/screenshots.py`
- `osuTitanic/titanic`: `services/caddy/Caddyfile`
- `osuAkatsuki/bancho.py`: `app/api/domains/map.py`,
  `app/api/domains/osu.py`
- `sutekina/osu-gulag`: `domains/ava.py`, `domains/map.py`,
  `domains/osu.py`, `ext/nginx.conf`
- `SunriseCommunity/Sunrise`: `AssetsController.cs`,
  `DirectController.cs`, `WebController.cs`, `AssetBanchoService.cs`,
  `UserFileService.cs`, `RequestKey.cs`

Do not copy architecture from reference implementations. Athena should preserve
wire-compatible behavior while keeping its own modular monolith boundaries.
Likewise, reference database schemas are evidence of durable facts needed by
stable workflows, not schema templates to copy.

## Persistence Reference Policy

Reference implementations are useful because production servers reveal what they
had to store to answer stable clients over time. Athena should use that evidence
to define durable domain concepts and read models, then implement them through
the repository and Unit of Work boundaries already used by this project.

Do not import table shapes directly from `bancho.py`, `lets`, `pep.py`, `deck`,
or `titanic`. Their schemas reflect their own deployment history and coupling.
For every new Athena table or projection, document which stable packet or
endpoint needs it, which response fields it supports, and which command or query
repository owns it.

The stable persistence inventory should include at least these durable facts:

| Area | Durable facts observed in references | Why stable needs it |
| --- | --- | --- |
| Identity and login | user id, username and safe name, password hash, email, country, activation state, latest activity, preferred mode, play style, supporter/donor end, bot account | login reply, registration, BanchoBot identity, presence country, permissions, user lookup |
| Permissions and moderation | privilege/group entries, Bancho permission bits, silence end, restricted/banned flags, infringements, reports, audit logs | login denial, chat/channel authorization, silence packets, restrictions, operator workflows |
| Client integrity | client hashes from login, executable/path hashes, adapters, unique id, disk signature, verified hardware exceptions, login history | client validation, multi-account policy, score submit consistency checks, abuse investigations |
| Social graph | friends, blocks, friend-only DM setting, direct message records and read status | friends list packet, add/remove friend packets, private-message delivery and rejection |
| Chat and channels | channel definitions, read/write permissions, autojoin flags, persisted messages, chat filters | login channel list, `#osu` autojoin behavior, join/leave responses, moderation review |
| Beatmaps and beatmapsets | beatmap id, set id, md5, filename, status, metadata, mode, difficulty values, play/pass counts, favourites, ratings, comments, mirror/resource URLs | getscores, beatmap info replies, osu!direct/search, downloads, comments, ranking eligibility |
| Scores and leaderboard | score id, user id, beatmap id or md5, score checksum, client version/hash, mode, mods, hit counts, grade, combo, pp, accuracy, status, submitted time, replay md5, fail time, ruleset family, Relax/Autopilot leaderboard mode where enabled | score submit, leaderboard rows, personal best overwrite, replay retrieval, user stats projection, Akatsuki-compatible RX/AP boards |
| User stats and ranks | total score, ranked score, pp, accuracy, play count, playtime, max combo, total hits, grade counts, global rank, country rank, rank history | user stats packets, presence panels, profile/ranking output |
| Replays and media | replay object metadata, replay view counts, screenshots, avatar hashes, beatmap files, seasonal assets, update files | replay download, screenshot endpoints, avatar/static endpoints, update checks |
| Static/media delivery | screenshot id/user/created/hidden, avatar hash and last-change time, beatmap background key, preview audio key, `.osu` file key, `.osz` full/no-video sizes, content length, last-modified time, mirror URL, download-server routing | `/ss/*`, `/a/*`, `/mt/*`, `/thumb/*`, `/preview/*`, `/osu/*`, `/d/*`, `/bss/*` |
| Release/update files | official release version, release file hash, patch URL, full URL, timestamp, extra file md5, extra download key, localization filename/language | `/web/check-updates.php`, `/release/update*`, `/release/<file>`, `/release/Localisation/*` |
| Achievements and notifications | achievement definitions, unlock records, badges/profile badges, notifications | score-submit unlock flow, profile display, future notification packets |
| Multiplayer and tournaments | match records, match events, pool definitions, pool maps, slot/host/team state when retained for audit | multiplayer packet family, tournament packet family, operator review |

Volatile online state still belongs in Valkey or runtime state where possible:
session tokens, packet queues, online presence, current status, spectating
links, live match state, and transient lobby membership. Persist only the facts
needed for reconnects, auditability, user-visible history, or stable web
responses.

## Bancho HTTP Transport

Stable Bancho traffic uses HTTP POST requests to `/` on a Bancho host. Athena
routes these hosts in `src/osu_server/composition/application.py`:

| Host | Path | Purpose |
| --- | --- | --- |
| `c.$DOMAIN` | `POST /` | Login or packet polling. |
| `c<int>.$DOMAIN` | `POST /` | Stable fallback Bancho hosts. |
| `ce.$DOMAIN` | `POST /` | Stable fallback Bancho host. |

Additional Bancho host aliases observed in `osuTitanic/titanic` are
`cho.$DOMAIN`, `mahbahowc.$DOMAIN`, and `server.$DOMAIN`. Athena does not
currently route these aliases; keep them as host-routing candidates until real
target-client traffic proves they are needed or explicitly out of scope.

The transport has two modes:

| Mode | Request signal | Athena workflow |
| --- | --- | --- |
| Login | No `osu-token` header | `LoginWorkflow` |
| Polling | `osu-token` header present | `PollingWorkflow` |

### Login Request Format

The stable client sends a UTF-8 body with three non-empty lines:

```text
<username>
<password_md5>
<client_info>
```

Athena parses this in
`src/osu_server/transports/stable/bancho/parsers/login.py`.

The `client_info` line is pipe-delimited:

```text
<osu_version>|<utc_offset>|<display_city>|<client_hashes>|<pm_private>
```

| Field | Type | Meaning |
| --- | --- | --- |
| `osu_version` | string | Stable client version string. |
| `utc_offset` | int string | Client timezone offset. Athena clamps this to `-24..24`. |
| `display_city` | `0` or `1` | Whether the client allows city display. |
| `client_hashes` | string | Client hash bundle. Must be preserved for future client integrity policy. |
| `pm_private` | `0` or `1` | Whether non-friend private messages should be blocked. |

The `client_hashes` field is colon-delimited in the Lekuruu login reference:

| Subfield | Meaning |
| --- | --- |
| executable name hash | MD5 of the executable name such as `osu!.exe`. |
| network interfaces | Physical addresses joined with dots, or `runningunderwine`. |
| network interfaces hash | MD5 of physical addresses. |
| uninstall id hash | MD5 of the `Software\osu!\UninstallID` registry value. |
| disk signature hash | MD5 of the disk drive signature. |

Processing flow:

1. Decode the request body as UTF-8.
2. Validate username and password hash are present.
3. Parse and validate `client_info`.
4. Resolve country from headers.
5. Execute the identity login command.
6. On failure, return only `LoginReply` with a negative login result.
7. On success, create a session token, build initial S2C packet stream, fire
   `UserConnected`, and return `cho-token` plus `cho-protocol` headers.

Login response headers:

| Header | Meaning |
| --- | --- |
| `cho-token` | Session token the stable client sends as `osu-token` on later polls. |
| `cho-protocol` | Bancho protocol version. Athena uses `PROTOCOL_VERSION`. |

Login response body:

- A concatenated Bancho S2C packet stream.
- On success, it should include protocol version, login reply, permissions,
  own presence/stats, friends list, channel list, online presence bundle, and
  channel info complete. Lekuruu recommends sending protocol version before
  other packets, and the stable client only leaves the "Receiving Data" state
  after it can join `#osu`.
- Athena has builders for many of these packets in
  `protocol/s2c/login.py`, but presence/stat completeness is still partial.

`LoginReply` body is a signed 32-bit integer. Positive values are user ids.
Negative values are stable client error codes:

| Code | Meaning |
| --- | --- |
| `-8` | Device verification required. |
| `-7` | Password was reset. |
| `-6` | Test build without supporter permission. |
| `-5` | Server-side error. |
| `-4` | Account not activated. |
| `-3` | Account banned. |
| `-2` | Client update required. |
| `-1` | Username/password incorrect. |

### Polling Request Format

Polling requests include:

| Request part | Format |
| --- | --- |
| Header | `osu-token: <cho-token>` |
| Body | Zero or more concatenated C2S Bancho packets. |

Processing flow:

1. Reject oversized bodies.
2. Resolve the session from `osu-token`.
3. If no session exists, return `LoginReply(authentication failed)`.
4. Refresh session TTL.
5. Parse all C2S packets from the request body.
6. Dispatch each packet to its registered handler.
7. Drain queued S2C packets for the user.
8. Refresh packet queue TTL and return the concatenated packet bytes.

The stable client may send several C2S packets in one HTTP request. A dispatcher
must never assume one request equals one packet.

## Bancho Binary Packet Envelope

Use Lekuruu `Protocol.md` as the struct source. The current HTTP Bancho packet
envelope is:

| Size | Type | Field |
| --- | --- | --- |
| 2 | unsigned short little-endian | Packet ID |
| 1 | boolean | Compression flag |
| 4 | unsigned int little-endian | Content size |
| variable | bytes | Packet content |

If the compression flag is true, the content is gzip-compressed. Athena currently
writes uncompressed packets through `protocol/writer.py`; compression support
should be tracked before claiming complete compatibility.

The polling body is a sequence of envelopes. The response body is also a sequence
of envelopes.

## Bancho Primitive Types

Use Lekuruu `Types/*.md` as the source for struct details.

| Type | Wire format | Athena status |
| --- | --- | --- |
| `String` | Presence byte `0x00` for absent/empty, or `0x0b` followed by ULEB128 byte length and UTF-8 bytes. `0x0b 0x00` is therefore a present zero-length string; stable C2S chat payloads have been observed using it for the empty sender field, so Athena accepts it when parsing. | Implemented as `BanchoString`. |
| `Message` | `String sender`, `String message`, `String target`, `i32 sender_id` for modern stable | Implemented. |
| `IntList` | `u16 count` followed by `i32[count]` | Implemented. |
| `Channel` | `String name`, `String topic`, `i16 user_count` | Implemented. |
| `StatusUpdate` | `u8 status`, `String status_text`, `String beatmap_md5`, `i32 mods`, `u8 play_mode`, `i32 beatmap_id` | Implemented for current stable status shape. |
| `Status` | Stable status enum values `0..13`; see struct reference below. | Missing implementation. |
| `Mode` | Stable play mode enum `0..3`. | Missing implementation. |
| `Mods` | Stable mod bitmask, including ScoreV2 and key mods. | Missing full audit/conversion tests. |
| `Grade` | Stable score grade enum values `XH..N`. | Missing implementation. |
| `ButtonState` | Replay frame input bitmask. | Missing. |
| `PresenceFilter` | Receive-updates filter values `0..2`. | Missing. |
| `QuitState` | User quit reason/state values `0..2`. | Missing canonical builder support. |
| `ReplayAction` | Replay/spectator frame action values `0..8`. | Missing. |
| `ReplayFrame` | Replay frame data. | Missing. |
| `ScoreFrame` | Multiplayer/spectator score frame data. | Missing. |
| `UserPresence` | User identity, timezone/country/permissions/mode, longitude/latitude, rank | Builder exists. |
| `UserPresenceBundle` | Online user id bundle | Implemented through `IntList`, but needs canonical naming and golden tests. |
| `UserStats` | User status plus ranked score, accuracy, play count, total score, rank, pp | Builder exists, projection incomplete. |
| `Match` | Multiplayer room state including slots, teams, mods, beatmap, freemod | Missing. |
| `MatchJoin` | Match id plus password payload for join/create flows | Missing. |
| `BeatmapInfo` | Beatmap info entry for replies | Missing. |
| `ReplayFrameBundle` | Spectator frames and score frames | Missing. |
| `BeatmapInfoRequest` | Filename list plus beatmap id list. | Missing. |
| `BeatmapInfoReply` | Count plus `BeatmapInfo` rows. | Missing. |

Implementation rule: when adding a packet parser or builder, first mirror the
Lekuruu struct in a local type, then add a golden encode/decode test. Use
reference implementations only to clarify behavior around the struct.

S2C 45/46 ordering must follow Lekuruu packet file names: 45 is
`AllPlayersLoaded` and 46 is `MatchStart`. Athena's `ServerPacketID` enum is
covered by a regression test for this ordering; keep that test in place before
adding multiplayer packet builders.

Athena also currently emits `USER_QUIT` as the old 4-byte `UserId` form. The
modern stable packet is `UserId` plus `QuitState`; keep this marked partial until
the extra byte is implemented or a deliberate old-client compatibility policy is
documented.

### Bancho Struct Field Reference

This section normalizes the current Lekuruu `Types/*.md` layouts into an
implementation checklist. Historical shapes should be used only when Athena
intentionally targets an older client build.

Lekuruu notation maps to Athena protocol primitives as follows:

| Notation | Wire size | Implementation target |
| --- | --- | --- |
| `char` / `u8` | 1 byte | `int` constrained to `0..255` |
| `bool` | 1 byte | `bool` encoded as `0` or `1` |
| `sShort` / `uShort` | 2 bytes | little-endian `int` with signedness preserved |
| `sInt` / `uInt` | 4 bytes | little-endian `int` with signedness preserved |
| `sLongLong` | 8 bytes | little-endian signed `int` |
| `float` / `double` | 4 / 8 bytes | little-endian Python `float` |
| `String` | variable | `BanchoString` |

Golden encode/decode fixtures are required before implementing packet handlers
that depend on these structs. Pay special attention to `UserPresence`
`permissions | (mode << 5)` packing and the C2S/S2C `ScoreFrame` size
difference.

| Type | Current stable layout or values |
| --- | --- |
| `String` | Empty/absent string is `0x00`; present string is `0x0b`, ULEB128 byte length, then UTF-8 bytes. C2S chat parsing also accepts present zero-length strings as `0x0b 0x00`, matching the observed stable client empty sender payload. |
| `Message` | `String sender`, `String message`, `String target`, `sInt sender_id`. |
| `IntList` | `uShort length`, then `sInt[length]`. |
| `Channel` | `String name`, `String topic`, `sShort user_count`. |
| `Status` | `0 Idle`, `1 Afk`, `2 Playing`, `3 Editing`, `4 Modding`, `5 Multiplayer`, `6 Watching`, `7 Unknown`, `8 Testing`, `9 Submitting`, `10 Paused`, `11 Lobby`, `12 Multiplaying`, `13 OsuDirect`. |
| `Mode` | `0 Osu`, `1 Taiko`, `2 Fruits`, `3 Mania`. |
| `Mods` | Bitmask: `NoMod=0`, `NoFail=1`, `Easy=2`, `Hidden=8`, `HardRock=16`, `SuddenDeath=32`, `DoubleTime=64`, `Relax=128`, `HalfTime=256`, `Nightcore=512`, `Flashlight=1024`, `Autoplay=2048`, `SpunOut=4096`, `Relax2/Autopilot=8192`, `Perfect=16384`, `Key4=32768`, `Key5=65536`, `Key6=131072`, `Key7=262144`, `Key8=524288`, `KeyMod=1015808`, `FadeIn=1048576`, `Random=2097152`, `Cinema=4194304`, `Target=8388608`, `Key9=16777216`, `KeyCoop=33554432`, `Key1=67108864`, `Key3=134217728`, `Key2=268435456`, `ScoreV2=536870912`, `Mirror=1073741824`. Lekuruu names bit 8192 `Relax2`; Akatsuki/bancho.py names it `Autopilot`. |
| `Grade` | `0 XH`, `1 SH`, `2 X`, `3 S`, `4 A`, `5 B`, `6 C`, `7 D`, `8 F`, `9 N`. |
| `ButtonState` | Bitmask: `None=0`, `Left1=1`, `Right1=2`, `Left2=4`, `Right2=8`, `Smoke=16`. |
| `PresenceFilter` | `0 NoPlayers`, `1 All`, `2 Friends`. |
| `QuitState` | `0 Gone`, `1 OsuRemaining`, `2 IrcRemaining`. |
| `ReplayAction` | `0 Standard`, `1 NewSong`, `2 Skip`, `3 Completion`, `4 Fail`, `5 Pause`, `6 Unpause`, `7 SongSelect`, `8 WatchingOther`. |
| `StatusUpdate` | `Status`, `String status_text`, `String beatmap_md5`, 4-byte `Mods`, `Mode`, `sInt beatmap_id`. |
| `ReplayFrame` | `ButtonState`, legacy byte, `float mouse_x`, `float mouse_y`, `sInt time`. |
| `ScoreFrame` | `sInt time`, `char slot_id`, six `uShort` hit counts, `sInt total_score`, `uShort max_combo`, `uShort current_combo`, `bool perfect`, `char current_hp`, `char tag_byte`, `bool scorev2_enabled`, optional `double combo_portion`, optional `double bonus_portion`. C2S 47 is documented as 28 bytes, while S2C 48 is 45 bytes because the server fills slot/tag/ScoreV2 fields. |
| `ReplayFrameBundle` | `sInt extra`, `uShort frame_count`, `ReplayFrame[frame_count]`, `ReplayAction`, optional `ScoreFrame`, `uShort sequence`. `extra` is spectated user id or mania random seed. |
| `UserPresence` | `sInt user_id`, `String username`, `char timezone_plus_24`, `char country_id`, `char permissions_or_mode` where value is `permissions OR (mode << 5)`, `float longitude`, `float latitude`, `sInt rank`. The low five permission bits are client-visible display rank; do not pass Athena's full internal privilege mask through this field. |
| `UserPresenceBundle` | `sShort length`, then `sInt[length]` user ids. |
| `UserStats` | `sInt user_id`, `StatusUpdate`, `sLongLong ranked_score`, `float accuracy`, `sInt play_count`, `sLongLong total_score`, `sInt rank`, `uShort pp`. |
| `BeatmapInfo` | `sShort request_index`, `sInt beatmap_id`, `sInt beatmapset_id`, `sInt thread_id`, `char ranked`, `Grade osu`, `Grade fruits`, `Grade taiko`, `Grade mania`, `String md5`. Request index is the filename index, or `-1` for id-based requests. |
| `BeatmapInfoRequest` | `sInt filename_count`, `String[filename_count] filenames`, `sInt id_count`, `sInt[id_count] beatmap_ids`. |
| `BeatmapInfoReply` | `sInt count`, `BeatmapInfo[count]`. |
| `Match` | `sShort match_id`, `bool in_progress`, `char match_type`, `sInt mods`, `String name`, `String password`, `String beatmap_text`, `sInt beatmap_id`, `String beatmap_checksum`, 16 slot status bytes, 16 slot team bytes, `sInt` player ids for non-empty slots, `sInt host_user_id`, `char mode`, `char scoring_type`, `char team_type`, `bool freemod`, optional 16 per-slot mod ints, `sInt match_seed`. |
| `MatchJoin` | `sInt match_id`, `String password`. |

### Bancho Packet Payload Reference

The matrix tracks implementation status; this table records the payload shape
that parser/builder work must use. Empty means the packet has no content bytes in
the modern HTTP Bancho protocol.

| C2S packet ids | Payload |
| --- | --- |
| `0 STATUS_CHANGE` | `StatusUpdate`. Lekuruu file name is `ChangeStatus`; treat `STATUS_CHANGE` as Athena's alias. |
| `1 SEND_MESSAGE`, `25 SEND_PRIVATE_MESSAGE`, `82 SET_AWAY_MESSAGE` | `Message`. |
| `2 EXIT` | `sInt is_updating`. |
| `3 REQUEST_STATUS`, `4 PONG`, `17 STOP_SPECTATING`, `21 CANT_SPECTATE`, `29 PART_LOBBY`, `30 JOIN_LOBBY`, `33 LEAVE_MATCH`, `39 MATCH_READY`, `44 MATCH_START`, `49 MATCH_COMPLETE`, `52 MATCH_LOAD_COMPLETE`, `54 MATCH_NO_BEATMAP`, `55 MATCH_NOT_READY`, `56 MATCH_FAILED`, `59 MATCH_HAS_BEATMAP`, `60 MATCH_SKIP`, `77 MATCH_CHANGE_TEAM`, `98 PRESENCE_REQUEST_ALL` | Empty. |
| `16 START_SPECTATING`, `73 ADD_FRIEND`, `74 REMOVE_FRIEND`, `87 MATCH_INVITE` | `sInt user_id`. |
| `18 SEND_FRAMES` | `ReplayFrameBundle`. |
| `20 ERROR_REPORT` | `String error_report`. |
| `31 CREATE_MATCH`, `41 MATCH_CHANGE_SETTINGS`, `50 MATCH_CHANGE_BEATMAP`, `90 MATCH_CHANGE_PASSWORD` | `Match`. |
| `32 JOIN_MATCH` | `MatchJoin`. |
| `38 MATCH_CHANGE_SLOT`, `40 MATCH_LOCK`, `70 MATCH_TRANSFER_HOST` | `sInt slot_id`. |
| `47 MATCH_SCORE_UPDATE` | 28-byte client `ScoreFrame`; server assigns slot id before broadcasting S2C 48. |
| `51 MATCH_CHANGE_MODS` | 4-byte `Mods` bitmask. |
| `63 JOIN_CHANNEL`, `78 LEAVE_CHANNEL` | `String channel_name`. |
| `68 BEATMAP_INFO` | `BeatmapInfoRequest`. |
| `79 RECEIVE_UPDATES` | 4-byte `PresenceFilter`. |
| `85 STATS_REQUEST`, `97 PRESENCE_REQUEST` | `IntList` player ids. `STATS_REQUEST` is limited to 32 ids in the wiki; `PRESENCE_REQUEST` to 256. |
| `93 TOURNAMENT_MATCH_INFO`, `108 TOURNAMENT_JOIN_MATCH_CHANNEL`, `109 TOURNAMENT_LEAVE_MATCH_CHANNEL` | `sInt match_id`. |
| `99 CHANGE_FRIENDONLY_DMS` | One-byte enabled flag in Athena and the wiki table's size column; wiki labels the datatype as `sInt`, so keep a golden fixture for the exact width. |

| S2C packet ids | Payload |
| --- | --- |
| `5 LOGIN_REPLY` | `sInt user_id_or_error_code`. |
| `6 COMMAND_ERROR`, `8 PING`, `19 VERSION_UPDATE`, `23 GET_ATTENTION`, `37 MATCH_JOIN_FAIL`, `45 ALL_PLAYERS_LOADED`, `53 MATCH_ALL_PLAYERS_LOADED`, `58 MATCH_COMPLETE`, `61 MATCH_SKIP`, `62 UNAUTHORIZED`, `80 MONITOR`, `84 IRC_ONLY`, `89 CHANNEL_INFO_COMPLETE`, `102 VERSION_UPDATE_FORCED`, `104 ACCOUNT_RESTRICTED`, `106 MATCH_ABORT` | Empty or documented as unused/no-payload. |
| `7 SEND_MESSAGE`, `88 INVITE`, `100 USER_DM_BLOCKED`, `101 TARGET_IS_SILENCED` | `Message`. |
| `9 IRC_CHANGE_USERNAME`, `10 IRC_QUIT`, `24 ANNOUNCE`, `64 CHANNEL_JOIN_SUCCESS`, `66 CHANNEL_REVOKED`, `76 MENU_ICON`, `91 MATCH_CHANGE_PASSWORD`, `105 RTX`, `107 SWITCH_TOURNAMENT_SERVER` | `String`; `MENU_ICON` is `<image_url>|<outlink>` on modern clients. |
| `11 USER_STATS` | `UserStats`. |
| `12 USER_QUIT` | Modern form is `sInt user_id`, `QuitState`; Athena currently emits only `user_id`. |
| `13 SPECTATOR_JOINED`, `14 SPECTATOR_LEFT`, `22 CANT_SPECTATE`, `34 LOBBY_JOIN`, `35 LOBBY_PART`, `42 FELLOW_SPECTATOR_JOINED`, `43 FELLOW_SPECTATOR_LEFT`, `57 MATCH_PLAYER_FAILED`, `81 MATCH_PLAYER_SKIPPED`, `94 USER_SILENCED`, `95 USER_PRESENCE_SINGLE` | `sInt user_id` or `slot_id` as named by the packet. |
| `15 SPECTATE_FRAMES` | `ReplayFrameBundle`. |
| `26 MATCH_UPDATE`, `27 NEW_MATCH`, `36 MATCH_JOIN_SUCCESS`, `46 MATCH_START` | `Match`. |
| `28 MATCH_DISBAND` | `sInt match_id`. |
| `48 MATCH_SCORE_UPDATE` | 45-byte server `ScoreFrame`. |
| `50 MATCH_TRANSFER_HOST` | Empty; recipient becomes host. |
| `65 CHANNEL_AVAILABLE`, `67 CHANNEL_AVAILABLE_AUTOJOIN` | `Channel`. |
| `69 BEATMAP_INFO_REPLY` | `BeatmapInfoReply`. |
| `71 LOGIN_PERMISSIONS` | `sInt` permission bitmask. |
| `72 FRIENDS_LIST` | `IntList`; the wiki packet page lists the `IntList` payload as 4 bytes because the content itself is dynamic. |
| `75 PROTOCOL_VERSION` | `sInt protocol_version`; latest wiki value is 19. |
| `83 USER_PRESENCE` | `UserPresence`. |
| `86 RESTART` | `sInt reconnect_after_ms`. |
| `92 SILENCE_INFO` | `sInt seconds_remaining`. |
| `96 USER_PRESENCE_BUNDLE` | `UserPresenceBundle`. |
| `103 SWITCH_SERVER` | `sInt required_idle_seconds`. |

## C2S Packet Processing Families

The complete packet inventory is in
[stable-compatibility-matrix.md](stable-compatibility-matrix.md). This guide
groups packets by behavior.

### Status And Presence

Packets:

- `STATUS_CHANGE` (0)
- `REQUEST_STATUS` (3)
- `STATS_REQUEST` (85)
- `PRESENCE_REQUEST` (97)
- `PRESENCE_REQUEST_ALL` (98)
- S2C `USER_STATS`, `USER_PRESENCE`, `USER_PRESENCE_SINGLE`,
  `USER_PRESENCE_BUNDLE`, `USER_QUIT`

Current Athena behavior:

- `STATUS_CHANGE` is decoded and used to request beatmap file warmup.
- `PRESENCE_REQUEST` is decoded and responds with `USER_PRESENCE` for requested
  online users.
- `PRESENCE_REQUEST_ALL` is decoded and responds with online `USER_PRESENCE`
  packets plus a `USER_PRESENCE_BUNDLE`.
- Status broadcasting, rank/stat projection, and requested status responses are
  incomplete.

Required processing:

1. Parse `StatusUpdate`.
2. Validate the session is allowed to publish gameplay state.
3. Persist/update volatile presence state in Valkey.
4. Derive beatmap warmup request from beatmap id or checksum.
5. Broadcast `USER_STATS` or presence packets to interested clients according to
   receive-update filters.
6. Answer explicit status/presence requests with the requested users or full
   presence bundle.

### Chat And Channels

Packets:

- C2S `SEND_MESSAGE`, `SEND_PRIVATE_MESSAGE`, `JOIN_CHANNEL`, `LEAVE_CHANNEL`,
  `SET_AWAY_MESSAGE`
- S2C `SEND_MESSAGE`, `CHANNEL_JOIN_SUCCESS`, `CHANNEL_AVAILABLE`,
  `CHANNEL_AVAILABLE_AUTOJOIN`, `CHANNEL_REVOKED`, `CHANNEL_INFO_COMPLETE`,
  `USER_DM_BLOCKED`, `TARGET_IS_SILENCED`

Current Athena behavior:

- Channel send, private send, join, and leave are implemented.
- Friend-only DM rejection is implemented.
- Away messages, silenced-target responses, and complete login channel list
  semantics need review.

Required processing:

1. Parse `Message` or channel `String`.
2. Authorize channel read/write or private-message delivery.
3. Apply chat filters and stable content truncation policy.
4. Route commands beginning with the configured command prefix to BanchoBot.
5. Persist durable chat messages through command/job boundaries where required.
6. Enqueue S2C `SEND_MESSAGE` to all recipients.
7. For channel joins, enqueue `CHANNEL_JOIN_SUCCESS` or `CHANNEL_REVOKED`.
8. For away messages, store the sender's away text and send a bot confirmation.

Lekuruu notes that the client only displays the "Welcome to Bancho!" state after
joining `#osu`, so login/channel autojoin behavior is compatibility-critical.

### Friends And PM Privacy

Packets:

- C2S `ADD_FRIEND`, `REMOVE_FRIEND`, `CHANGE_FRIENDONLY_DMS`
- S2C `FRIENDS_LIST`, `USER_DM_BLOCKED`

Current Athena behavior:

- Add/remove friend and session-level friend-only DM preference are implemented.
- Login-time friend list builder exists.

Required processing:

1. Parse target user id or boolean preference.
2. Mutate durable friend relationship where appropriate.
3. Update session DM preference.
4. Ensure login response emits `FRIENDS_LIST`.
5. Ensure PM send checks target privacy and sender friendship state.

### Spectator

Packets:

- C2S `START_SPECTATING`, `STOP_SPECTATING`, `SEND_FRAMES`, `CANT_SPECTATE`
- S2C `SPECTATOR_JOINED`, `SPECTATOR_LEFT`, `SPECTATE_FRAMES`,
  `FELLOW_SPECTATOR_JOINED`, `FELLOW_SPECTATOR_LEFT`, `CANT_SPECTATE`

Current Athena behavior:

- Missing.
- S2C `ALL_PLAYERS_LOADED` (45) and `MATCH_START` (46) now follow Lekuruu and
  are guarded by enum tests.

Required processing:

1. Track who is spectating whom in Valkey.
2. Create or join a hidden spectator chat channel such as reference
   implementations' `#spect_<host_id>` pattern.
3. Notify the host with `SPECTATOR_JOINED` and existing spectators with
   `FELLOW_SPECTATOR_JOINED`.
4. Relay frame bundles from host to spectators.
5. On stop/disconnect, remove spectator state, leave hidden channel, and notify
   host/fellow spectators.
6. Handle cannot-spectate responses.

Reference behavior exists in `osuRipple/pep.py` under `objects/osuToken.py` and
spectator event handlers.

### Multiplayer

Packets:

- Lobby: `JOIN_LOBBY`, `PART_LOBBY`
- Match lifecycle: `CREATE_MATCH`, `JOIN_MATCH`, `LEAVE_MATCH`,
  `MATCH_CHANGE_SLOT`, `MATCH_READY`, `MATCH_NOT_READY`, `MATCH_LOCK`,
  `MATCH_CHANGE_SETTINGS`, `MATCH_START`, `MATCH_LOAD_COMPLETE`,
  `MATCH_SCORE_UPDATE`, `MATCH_COMPLETE`, `MATCH_CHANGE_BEATMAP`,
  `MATCH_CHANGE_MODS`, `MATCH_NO_BEATMAP`, `MATCH_FAILED`,
  `MATCH_HAS_BEATMAP`, `MATCH_SKIP`, `MATCH_TRANSFER_HOST`,
  `MATCH_CHANGE_TEAM`, `MATCH_INVITE`, `MATCH_CHANGE_PASSWORD`
- Tournament: `TOURNAMENT_MATCH_INFO`, `TOURNAMENT_JOIN_MATCH_CHANNEL`,
  `TOURNAMENT_LEAVE_MATCH_CHANNEL`

Current Athena behavior:

- Missing.

Required processing:

1. Model match state from Lekuruu `Types/Match.md`.
2. Store volatile match/lobby state in Valkey.
3. Create hidden match chat channel such as `#multi_<match_id>`.
4. Implement lobby stream and match room streams.
5. Enforce host-only actions for settings, lock, password, transfer, and start.
6. Broadcast S2C match update packets after every state change.
7. Track load, skip, fail, score frame, and completion state per slot.
8. Dispose empty non-tournament matches and notify lobby/room subscribers.

Reference behavior exists in `osuRipple/pep.py` under `objects/match.py` and
`handlers/mainHandler.pyx`.

### Beatmap Info Packet Flow

Packets:

- C2S `BEATMAP_INFO`
- S2C `BEATMAP_INFO_REPLY`

Current Athena behavior:

- Missing.

Required processing:

1. Parse `BeatmapInfoRequest` from Lekuruu wiki.
2. Resolve each filename/checksum through beatmap metadata providers.
3. Return `BeatmapInfoReply` rows for known beatmaps.
4. Keep stable rank status mapping consistent with getscores.

## Legacy Web Endpoints

Stable web endpoints live on `osu.$DOMAIN` under `/web/*.php`, plus static/media
paths used by the client. Athena currently implements only a small subset.

### Audit Scope Index

Issue #32 covers the legacy web-family path inventory, not runtime route
implementation. Treat every `/web/*.php` exact path and the
`/rating/ingame-rate*.php` aliases as in-scope. Keep release, static, media,
and download overlaps as adjacent context so later matrix and guide updates do
not merge their body policy into the legacy web audit.

| Guide update target | In-scope exact paths | Adjacent context to keep separate |
| --- | --- | --- |
| Bancho reachability | `/web/bancho_connect.php` | Stable login and packet polling live on `/` host routes, not in this path inventory. |
| Modern getscores | `/web/osu-osz2-getscores.php` | Leaderboard projections and RX/AP extension policy are separate behavior inputs. |
| Legacy getscores aliases | `/web/osu-getscores.php`, `/web/osu-getscores2.php`, `/web/osu-getscores3.php`, `/web/osu-getscores4.php`, `/web/osu-getscores5.php`, `/web/osu-getscores6.php` | Modern `/web/osu-osz2-getscores.php` formatting must not be reused for aliases without per-path evidence. |
| Modern score submit selector | `/web/osu-submit-modular-selector.php` | Replay storage, stat projection, and worker durability remain score submission behavior inputs. |
| Legacy score submit aliases | `/web/osu-submit-modular.php`, `/web/osu-submit.php`, `/web/osu-submit-new.php` | Modern selector parsing and response mapping must not be reused for aliases without per-path evidence. |
| Session candidate | `/web/osu-session.php` | `bancho.py` lists the route as unhandled; keep it as a grouped-row candidate until a Reference Route Inventory exact row or traffic evidence is found. |
| Replay download PHP route | `/web/osu-getreplay.php` | `/web/replays/{id}` is a non-PHP replay download alias from `lets`. |
| Update check PHP route | `/web/check-updates.php` | `/release/update*`, root `/update*`, `/patches.php`, release file, filter, and localisation routes remain release-update context. |
| osu!direct search and set lookup | `/web/osu-search.php`, `/web/osu-search-set.php` | `/web/maps/{query}`, `/d/*`, `/s/*`, `/bss/*`, `/osu/*`, and download host aliases remain file/download context. |
| Legacy beatmap info | `/web/osu-getbeatmapinfo.php` | Bancho packet 68/69 and file delivery behavior remain separate compatibility surfaces. |
| Beatmap checksum status | `/web/osu-getstatus.php` | `.osu` and `.osz` bytes, thumbnails, preview audio, and mirror routing remain static/media/download context. |
| OSZ2/hash helpers | `/web/osu-gethashes.php`, `/web/osu-osz2-getfileinfo.php`, `/web/osu-osz2-getrawheader.php`, `/web/osu-osz2-getfilecontents.php`, `/web/osu-magnet.php` | `.osu` and `.osz` bytes, thumbnails, preview audio, and mirror routing remain static/media/download context. |
| Screenshot upload and client diagnostics | `/web/osu-screenshot.php`, `/web/osu-ss.php`, `/web/osu-error.php` | `/ss/*` serving routes remain media delivery context. |
| Ratings | `/web/osu-rate.php`, `/rating/ingame-rate.php`, `/rating/ingame-rate2.php` | Durable rating state belongs to follow-up implementation work. |
| Comments and favourites | `/web/osu-comment.php`, `/web/osu-addfavourite.php`, `/web/osu-getfavourites.php` | Durable comment/favourite state belongs to follow-up implementation work. |
| Stats and friends | `/web/osu-stat.php`, `/web/osu-statoth.php`, `/web/osu-getfriends.php` | Stats projection and friend read models belong to follow-up implementation work. |
| Social/status no-op candidates | `/web/osu-markasread.php`, `/web/osu-checktweets.php`, `/web/lastfm.php` | Durable social/read-marker state belongs to follow-up implementation work. |
| Seasonal UI | `/web/osu-getseasonal.php` | Dynamic seasonal asset management remains follow-up scope. |
| Title/menu UI | `/web/osu-title-image.php`, `/assets/menu-content.json`, `/menu-content.json` | Avatar routes and other title/menu static bytes remain static/menu context. |
| Login preflight | `/web/osu-login.php` | Main Bancho login remains on the Bancho HTTP transport. |
| Private-server currency and benchmark | `/web/coins.php`, `/web/osu-benchmark.php` | Private-server currency and benchmark diagnostics stay outside current normal-play compatibility. |
| Beatmap submission | `/web/osu-osz2-bmsubmit-getid.php`, `/web/osu-osz2-bmsubmit-upload.php`, `/web/osu-osz2-bmsubmit-post.php`, `/web/osu-get-beatmap-topic.php`, `/web/osu-bmsubmit-getid5.php`, `/web/osu-bmsubmit-getid4.php`, `/web/osu-bmsubmit-getid3.php`, `/web/osu-bmsubmit-getid2.php`, `/web/osu-bmsubmit-getid.php`, `/web/osu-bmsubmit-upload.php`, `/web/osu-bmsubmit-novideo.php`, `/web/osu-bmsubmit-post3.php`, `/web/osu-bmsubmit-post2.php`, `/web/osu-bmsubmit-post.php` | Beatmap submission workflow implementation is deferred from P0 core login/play scope. |

### Final Audit Classification Contract

Use the matrix `Current status` column only for existing implementation or
inventory state such as `Implemented`, `Partial`, `Missing`, or `Candidate`.
Use the matrix `Final audit classification` column for Issue #32 legacy web
audit results. The final classification must be exactly one of `required`,
`compatibility no-op`, `deferred`, `out of scope`, or
`needs reference evidence`; non-legacy rows may use explicit `N/A`. `candidate`
is only a pre-audit status and must not remain as the final audited
classification.

Apply the final classifications with these rules:

| Final audit classification | Rule |
| --- | --- |
| `required` | Use only when current osu!stable P0 core login/play traffic needs real endpoint behavior. Do not mark a reference-only endpoint P0 `required` when current osu!stable traffic evidence is missing. |
| `compatibility no-op` | Use only when a route contract and exact empty, static, JSON, or sentinel response shape are confirmed and no dynamic behavior or durable mutation is needed. Unknown response shape cannot be `compatibility no-op`. |
| `deferred` | Use when the endpoint is a plausible compatibility surface, but implementation waits for a later milestone, operator policy, or product decision. Record that reason. |
| `out of scope` | Use when the endpoint belongs to removed workflow, private-server-specific behavior, adjacent release/static/media/download scope, or Athena product scope outside the audit. Record that reason. |
| `needs reference evidence` | Use when request parameters, response body, auth behavior, error sentinel, or target-client traffic evidence is incomplete. This is the default for unresolved alias variants, unknown response shape, and reference-only routes with no current osu!stable traffic evidence. |

Rows may leave `needs reference evidence` only with current osu!stable traffic,
official or semi-official protocol docs, existing reference implementations, or
Athena focused fixtures/tests. A success-only reference is not enough to infer
auth failure, not-found, malformed-request, or no-op response behavior.

### Endpoint Family Evidence Note Template

For each endpoint family note, use one table with the six evidence fields below.
Set every field's state to exactly one of `confirmed`, `unconfirmed`, or
`scope outside`. Use `scope outside` only when the endpoint family boundary
intentionally excludes that behavior; otherwise missing evidence is
`unconfirmed`.

`scope outside` is a field-level evidence state, not a final endpoint
classification. Use it when a confirmed route contract or explicit audit
boundary says that behavior has no branch for this endpoint family. For example,
an unauthenticated public route may mark Auth method and Auth failure response
as `scope outside` only when the documented request shape has no credential
field and no auth gate is expected. Do not use `scope outside` merely because
evidence is missing; unknown auth, params, response, or error behavior must stay
`unconfirmed`.

| Evidence field | Evidence state | Evidence note |
| --- | --- | --- |
| Auth method | `confirmed` / `unconfirmed` / `scope outside` | Source or boundary reason. |
| Required request params | `confirmed` / `unconfirmed` / `scope outside` | Source or boundary reason. |
| Success response | `confirmed` / `unconfirmed` / `scope outside` | Source or boundary reason. |
| Auth failure response | `confirmed` / `unconfirmed` / `scope outside` | Source or boundary reason. |
| Domain/data-not-found response | `confirmed` / `unconfirmed` / `scope outside` | Source or boundary reason. |
| Malformed request response | `confirmed` / `unconfirmed` / `scope outside` | Source or boundary reason. |

This is an audit note format only. Success-only evidence is not
implementation-ready until failure sentinel behavior and malformed request
behavior are also confirmed or explicitly marked `scope outside`.

### `/web/bancho_connect.php`

Method: `GET`

Common query parameters:

| Parameter | Meaning |
| --- | --- |
| `v` | Client version. |
| `u` | Username. |
| `h` | Password MD5. |
| `fail` | Active endpoint/fallback indicator. |
| `retry` | Whether the client is retrying. |
| `fx` | .NET framework version string. |
| `ch` | Client hash value in some newer clients. |

Current Athena response:

- HTTP 200 with an empty body.

Reference behavior:

- `lets` validates credentials and returns the user's country, `error: pass`,
  or `error: verify`.
- `deck` parses osu! build versions. Invalid versions return `XX`; clients on
  or before `20130915` receive the configured Bancho IP, while newer clients
  receive a lower-case country code.
- `bancho.py` declares parameters and effectively returns an empty response.
- `deck` implements the endpoint as a web route.

Athena decision:

- Keep reachability-only behavior for now.
- If real-client traffic or compatibility failures require pre-login validation,
  add it here without bypassing the main Bancho login command.
- Keep the final audit classification as `needs reference evidence` until the
  pre-login validation, country-code/IP response, and malformed-query contract
  are selected by focused fixtures or reference evidence.

Task 2.2 `/web/bancho_connect.php` evidence note:

| Evidence field | Evidence state | Evidence note |
| --- | --- | --- |
| Auth method | `scope outside` | Current Athena route intentionally delegates credential validation to Bancho login `POST /`; `src/osu_server/transports/stable/web_legacy/bancho_connect.py` reads `u` and `h` only as reachability context. |
| Required request params | `confirmed` | `v`, `u`, `h`, `fail`, `retry`, `fx`, and `ch` are documented from current parser/reference notes; Athena does not require them for the empty reachability response. |
| Success response | `confirmed` | Athena returns HTTP 200 with an empty body, but this only confirms the current route body. The Task 2.2 classification stays `needs reference evidence` until pre-login validation and country-code/IP variants are settled. |
| Auth failure response | `scope outside` | Auth failure is handled by the main Bancho login workflow unless future traffic proves pre-login validation is required here. |
| Domain/data-not-found response | `scope outside` | This endpoint is not a domain lookup route; no data-not-found branch is expected for the current reachability-only behavior. |
| Malformed request response | `unconfirmed` | No fixture proves whether malformed query combinations must still return the empty 200 response for all target stable builds. |

### `/users`

Method: `POST`

Stable account registration form fields:

| Field | Meaning |
| --- | --- |
| `user[username]` | Requested username. |
| `user[user_email]` | Email address. |
| `user[password]` | Plain password submitted by the stable registration form. |
| `check` | `1` for validation-only, `0` for account creation. |

Current Athena responses:

| Outcome | Response |
| --- | --- |
| Success | `200 OK`, body `ok` |
| Validation failure | `400`, JSON body `{"form_error": {"user": ...}}` |

Required processing:

1. Parse form fields.
2. Validate registration policy.
3. If `check=1`, return validation result without creating a user.
4. If `check=0`, create user through the identity command boundary.

Task 2.2 evidence note:

| Evidence field | Evidence state | Evidence note |
| --- | --- | --- |
| Auth method | `scope outside` | Registration is unauthenticated by design; the audit treats `POST /users` and local `POST /web/users` as adjacent required registration context, not as legacy PHP exact paths. |
| Required request params | `confirmed` | `user[username]`, `user[user_email]`, `user[password]`, and `check` are documented above and implemented by `src/osu_server/transports/stable/web_legacy/registration.py`. |
| Success response | `confirmed` | Current Athena success body is `ok` with HTTP 200. |
| Auth failure response | `scope outside` | No authenticated session or credential check exists for this registration form. |
| Domain/data-not-found response | `scope outside` | Registration validates submitted identity fields rather than looking up a pre-existing domain object. |
| Malformed request response | `unconfirmed` | Validation-failure JSON is documented, but malformed form fixture coverage and stable client branch evidence are not complete. |

### `/web/osu-osz2-getscores.php`

Method: `GET`

Common query parameters parsed by Athena:

| Parameter | Meaning |
| --- | --- |
| `us` | Username for stable credential check. |
| `ha` | Password MD5 for stable credential check. |
| `c` | Beatmap MD5 checksum. |
| `f` | Beatmap filename fallback. |
| `i` | Beatmapset id hint. |
| `m` | Ruleset/mode. |
| `mods` | Stable mod bitmask. |
| `v` | Leaderboard type: local/global, selected mods, friends, country. |
| `vv` | Leaderboard protocol/version value. |
| `s` | Song select/header-only flag. |
| `a` | Anti-cheat signal presence. |

Current Athena response bodies:

| Outcome | Body |
| --- | --- |
| Authentication failure | HTTP 401, empty body |
| Unavailable | `-1\|false` |
| Update available | `1\|false` |
| Header/rows | Stable text response with header, title line, personal best row, and score rows |

Current header response shape:

```text
<status>|false|<beatmap_id>|<beatmapset_id>|<score_count>||
0
[bold:0,size:20]<artist>|<title>
0
<personal_best_row>
<score_row_1>
...
```

Score row shape:

```text
<score_id>|<username>|<score>|<max_combo>|<n50>|<n100>|<n300>|<miss>|<katu>|<geki>|<perfect>|<mods>|<user_id>|<rank>|<submitted_at_epoch>|<has_replay>
```

Required processing:

1. Authenticate by stable credentials and active session.
2. Parse identity and leaderboard selection.
3. Resolve beatmap metadata by checksum or fallback filename/set id.
4. Request `.osu` file warmup without changing the immediate stable response.
5. Map internal beatmap rank status to stable wire status.
6. Query personal best and leaderboard rows.
7. Format text response exactly and avoid leaking internal provenance fields.

Known gaps:

- Full leaderboard rows depend on beatmap leaderboard projections.
- Friends and country leaderboards need domain/query support.
- Real-client fixtures should cover every response branch.
- Older `/web/osu-getscores.php` through `/web/osu-getscores6.php` aliases have
  per-version response differences in `deck`: some omit the osz2 update flag,
  some omit rating/difficulty fields, and the oldest route returns only legacy
  score rows separated by `:`. Do not point those aliases at the modern formatter
  without fixtures for each version.

Akatsuki-compatible extension requirement:

- `bancho.py` separates Relax and Autopilot boards by converting stable mods
  into expanded game modes: vanilla `0..3`, Relax `4..6`, and Autopilot `8`
  for osu!standard. Relax mania and Autopilot taiko/catch/mania are present in
  the enum but treated as unused.
- Athena should preserve vanilla stable behavior while keeping a documented
  read-model extension point for RX/AP leaderboards, personal bests, stats,
  ranks, and score-submit projections.
- RX/AP support must define whether ranking sorts by score or pp, how invalid
  mod combinations are filtered, and how these modes appear in stable
  getscores, first-party API responses, and future profile/ranking pages.

Task 2.2 evidence note:

| Evidence field | Evidence state | Evidence note |
| --- | --- | --- |
| Auth method | `confirmed` | Athena parses stable credentials from `us` and `ha`; current failure behavior is documented as HTTP 401 with an empty body. |
| Required request params | `confirmed` | Athena-handled params are documented above: `us`, `ha`, `c`, `f`, `i`, `m`, `mods`, `v`, `vv`, `s`, and `a`. |
| Success response | `confirmed` | The modern osz2 header/row text shape is documented above and implemented through `getscores.py` and `mappers/getscores.py`. |
| Auth failure response | `confirmed` | Current Athena auth failure response is HTTP 401 with an empty body; target-client fixture coverage is still missing. |
| Domain/data-not-found response | `confirmed` | Current Athena documents unavailable as `-1\|false` and update available as `1\|false`. |
| Malformed request response | `unconfirmed` | Malformed identity, checksum, mode/mod, friends leaderboard, and country leaderboard branches still need fixtures and traffic evidence. |

### Legacy getscores aliases

Endpoint candidates:

- `/web/osu-getscores6.php`
- `/web/osu-getscores5.php`
- `/web/osu-getscores4.php`
- `/web/osu-getscores3.php`
- `/web/osu-getscores2.php`
- `/web/osu-getscores.php`

Task 2.3 decision:

- Keep these as best effort support candidates for older stable clients.
- Classify each alias as `needs reference evidence` until alias-specific
  response fixtures and current target-client traffic evidence exist.
- Do not point these aliases at the modern `/web/osu-osz2-getscores.php`
  formatter without proving the response variant for that exact path.

Known reference distinctions:

| Alias group | Known distinction | Missing evidence |
| --- | --- | --- |
| `/web/osu-getscores6.php` through `/web/osu-getscores2.php` | `deck` exposes separate routes with per-version response differences such as omitted osz2 update flag or rating/difficulty fields. | Exact per-path row shape, auth failure sentinel, unavailable/update sentinels, malformed request behavior, and current-client traffic. |
| `/web/osu-getscores.php` | Oldest route is documented as legacy score rows separated by `:`. | Full success body, auth failure sentinel, data-not-found behavior, malformed request behavior, and current-client traffic. |

Task 2.3 legacy score submit aliases evidence note:

| Evidence field | Evidence state | Evidence note |
| --- | --- | --- |
| Auth method | `unconfirmed` | Do not assume the alias family is uniformly credentialed. Reference rows for `/web/osu-getscores3.php`, `/web/osu-getscores2.php`, and `/web/osu-getscores.php` use beatmap/query inputs without username/password fields; newer aliases still need exact per-path auth evidence and fixtures. |
| Required request params | `unconfirmed` | Exact accepted params per alias are unknown; do not assume the modern osz2 query parser is valid for every older path. |
| Success response | `unconfirmed` | Reference notes prove that variants exist, not that Athena has an implementation-ready body for each exact path. |
| Auth failure response | `unconfirmed` | Alias-specific auth failure status/body is unknown. |
| Domain/data-not-found response | `unconfirmed` | Missing beatmap, unavailable, and update-required sentinels may differ from the modern osz2 route and need fixtures. |
| Malformed request response | `unconfirmed` | Bad identity, checksum, mode/mod, and omitted parameter behavior has no per-alias fixture coverage. |

### `/web/osu-submit-modular-selector.php`

Method: `POST`

Request type: multipart form data.

Important multipart fields handled by Athena's parser/mapper:

| Field | Meaning |
| --- | --- |
| `score` | Encrypted score payload. Some clients send duplicate `score` fields; order must be preserved. |
| `iv` | Rijndael CBC initialization vector. |
| `osuver` | Client version. |
| `pass` | Password MD5. |
| `x` | Client hash. |
| replay file field | Replay bytes, when uploaded. |
| fail time field | Failure timestamp when the play failed. |
| `i` | Flashlight cheat screenshot, referenced by bancho.py/deck and not yet fully handled by Athena. |

Compatibility note: Athena's current multipart parser treats `x` as the client
hash for handled score-submit requests. The separate golden quit/failed fixtures
under `tests/fixtures/golden/` contain `x=1` plus a distinct `s` field; that
shape is evidence for future compatibility research and must not be treated as
supported without first defining how `x` and `s` map for that client variant.

Additional fields and variants observed in `deck` and `lets`:

| Field/source | Meaning |
| --- | --- |
| query `score` | Legacy score payload submitted as a query parameter. |
| duplicate multipart `score` fields | First entry is encrypted score data; later entry may be replay bytes. |
| `fs` | Fun spoiler / client-side signal retained by deck. |
| `pl` | Process list / client-side anti-abuse signal. |
| `ft` | Fail time. |
| query or form `pass` | Password MD5 on some submit variants. |

The encrypted score payload decrypts to a colon-delimited stable payload.
Athena supports two shapes:

Legacy 16-field shape:

```text
<user_id>:<username>:<beatmap_checksum>:<online_checksum>:<ruleset>:<mods>:<n300>:<n100>:<n50>:<geki>:<katu>:<miss>:<score>:<max_combo>:<perfect>:<passed>
```

Stable 16-19-field shape:

```text
<beatmap_checksum>:<username>:<online_checksum>:<n300>:<n100>:<n50>:<geki>:<katu>:<miss>:<score>:<max_combo>:<perfect>:<client_grade>:<mods>:<passed>:<ruleset>[:<client_submitted_at>[:<client_version>[:<client_checksum>]]]
```

Current Athena responses:

| Outcome | Body |
| --- | --- |
| Completed | Multi-line chart response. |
| Retryable or accepted pending | `error: yes` |
| Terminal failure | `error: no` |

Completed chart response structure:

```text
beatmapId:<beatmap_id>|beatmapSetId:<beatmapset_id>|beatmapPlaycount:<count>|beatmapPasscount:<count>|approvedDate:
chartId:beatmap|chartUrl:|chartName:Beatmap Ranking|achieved:<true_or_false>|rankBefore:|rankAfter:<rank>|maxComboBefore:<combo>|maxComboAfter:<combo>|accuracyBefore:<accuracy>|accuracyAfter:<accuracy>|rankedScoreBefore:<score>|rankedScoreAfter:<score>|ppBefore:<pp>|ppAfter:<pp>|onlineScoreId:<score_id>
chartId:overall|chartUrl:|chartName:Overall Ranking|rankBefore:<rank>|rankAfter:<rank>|rankedScoreBefore:<score>|rankedScoreAfter:<score>|totalScoreBefore:<score>|totalScoreAfter:<score>|maxComboBefore:<combo>|maxComboAfter:<combo>|accuracyBefore:<accuracy>|accuracyAfter:<accuracy>|ppBefore:<pp>|ppAfter:<pp>|achievements-new:<ids>|onlineScoreId:<score_id>
```

Required processing:

1. Parse multipart body with duplicate field preservation.
2. Decrypt the score payload using osu!'s Rijndael-256/CBC variant.
3. Parse stable score fields into domain score values.
4. Authenticate username/password/session consistency.
5. Validate hit counts, ruleset, mods, pass/fail state, replay uniqueness, and
   beatmap eligibility.
6. Store score and replay through command persistence boundaries.
7. Queue or execute PP calculation, leaderboard projection, user stats update,
   and achievement/notification follow-up.
8. Return a stable chart response or stable error sentinel.

Known gaps:

- Overall rank/stat fields are placeholders.
- Achievement output is not complete.
- Flashlight screenshot handling needs reference-backed implementation.
- Some post-submit work still needs stronger worker/retry guarantees.
- Relax and Autopilot submission paths need an explicit compatibility decision:
  Akatsuki maps stable `RX` and `AP` mod submissions into separate leaderboard
  mode families instead of mixing them with vanilla leaderboards.

Task 2.2 `/web/osu-submit-modular-selector.php` evidence note:

| Evidence field | Evidence state | Evidence note |
| --- | --- | --- |
| Auth method | `confirmed` | Athena authenticates score submit with the submitted stable credential material, including the `pass` password MD5 and decrypted score identity. |
| Required request params | `confirmed` | The handled multipart fields are documented above: `score`, `iv`, `osuver`, `pass`, `x`, replay bytes, fail time, and `i` for future screenshot handling. |
| Success response | `confirmed` | Current completed response is the multi-line chart body documented above and implemented through `score_submit.py` and `mappers/score_submit.py`. |
| Auth failure response | `unconfirmed` | Current sentinel mapping includes `error: yes` and `error: no`, but auth-specific branch fixtures and target-client interpretation are incomplete. |
| Domain/data-not-found response | `unconfirmed` | Missing beatmap, replay, duplicate score, and storage/durability branches need focused fixtures before this route is implementation-ready. |
| Malformed request response | `unconfirmed` | Multipart variant fixtures, duplicate-field handling fixtures, malformed encrypted payload fixtures, and older submit variant traffic are still missing. |

### Legacy score submit aliases

Endpoint candidates:

- `/web/osu-submit-modular.php`
- `/web/osu-submit.php`
- `/web/osu-submit-new.php`

Task 2.3 decision:

- Keep these as best effort support candidates for older stable clients.
- Classify each alias as `needs reference evidence` until alias-specific
  request shape, success body, failure sentinels, and target-client traffic are
  confirmed.
- Do not treat Athena's current
  `/web/osu-submit-modular-selector.php` mapper as covering these aliases.

Known reference distinctions:

| Exact path | Known distinction | Missing evidence |
| --- | --- | --- |
| `/web/osu-submit-modular.php` | Reference inventory lists a legacy modular submit route in `lets` and `deck`. | Whether the stable score payload is query or multipart, duplicate field behavior, replay field name, auth failure sentinel, and malformed request response. |
| `/web/osu-submit.php` | Reference inventory lists an older legacy score submit route in `deck`. | Exact payload shape, success body, retryable/terminal failure sentinel, and current-client traffic. |
| `/web/osu-submit-new.php` | Reference inventory lists an additional legacy score submit route in `deck`. | Exact payload shape, success body, retryable/terminal failure sentinel, and current-client traffic. |

Task 2.3 evidence note:

| Evidence field | Evidence state | Evidence note |
| --- | --- | --- |
| Auth method | `unconfirmed` | Password MD5 appears in legacy submit variants, but per-alias credential source and auth failure behavior are not confirmed for Athena. |
| Required request params | `unconfirmed` | Query-vs-form payload source, encrypted score field naming, replay field naming, and fail-time field naming are unresolved per alias. |
| Success response | `unconfirmed` | It is unknown whether each alias returns the same chart body as the selector route or an older response body. |
| Auth failure response | `unconfirmed` | Auth-specific `error: yes` / `error: no` mapping is not fixture-backed per alias. |
| Domain/data-not-found response | `unconfirmed` | Missing beatmap, duplicate score, storage failure, and replay failure behavior are unconfirmed per alias. |
| Malformed request response | `unconfirmed` | Malformed encrypted payloads, missing fields, duplicate fields, and old-client payload variants have no per-alias fixture coverage. |

### Replay Download

Endpoint candidates:

- `/web/osu-getreplay.php`
- `/web/replays/<id>` in `lets`

Current Athena behavior:

- Missing.

Required processing:

1. Authenticate if required by client route.
2. Parse score id from `c` and mode from `m`.
3. Resolve score id to a visible score and replay attachment.
4. Return raw replay bytes with a 200 response when present.
5. Return the reference-compatible missing replay status. `deck` returns 404
   for missing, hidden, or storage-missing replays.
6. When authenticated, update latest activity and replay-view counters with a
   cooldown so repeated self or duplicate views are not counted.

Task 2.2 `/web/osu-getreplay.php` evidence note:

| Evidence field | Evidence state | Evidence note |
| --- | --- | --- |
| Auth method | `unconfirmed` | The audit has not confirmed whether current target builds require credentials for `/web/osu-getreplay.php`. |
| Required request params | `unconfirmed` | Expected replay lookup params such as score id `c` and mode `m` are documented as required processing, but exact current-client request shape remains unconfirmed. |
| Success response | `unconfirmed` | Replay bytes are the expected behavior, but Athena has no route and no golden success fixture for `/web/osu-getreplay.php`. |
| Auth failure response | `unconfirmed` | No reference-backed auth failure sentinel has been selected for Athena. |
| Domain/data-not-found response | `unconfirmed` | `deck` returns 404 for missing, hidden, or storage-missing replays, but Athena needs target-path evidence before locking this contract. |
| Malformed request response | `unconfirmed` | Malformed score id, mode, and missing parameter behavior has no fixture coverage. |

### `/web/osu-session.php`

Method: `POST`

Current Athena behavior:

- Missing.

Task 2.2 decision:

- Keep this as `needs reference evidence`. The current matrix has a grouped
  candidate row, but no Athena route, no exact Reference Route Inventory row,
  and no current target-client traffic confirmation for this path.

Task 2.2 `/web/osu-session.php` evidence note:

| Evidence field | Evidence state | Evidence note |
| --- | --- | --- |
| Auth method | `unconfirmed` | No current-client request capture or exact reference row confirms how this endpoint authenticates. |
| Required request params | `unconfirmed` | Required form/query fields are unknown. |
| Success response | `unconfirmed` | Success body and status code are unknown. |
| Auth failure response | `unconfirmed` | Auth failure sentinel is unknown. |
| Domain/data-not-found response | `unconfirmed` | Domain-specific missing-data behavior is unknown. |
| Malformed request response | `unconfirmed` | Malformed request behavior is unknown. |

### Update And Release Endpoints

Endpoint candidates:

- `/web/check-updates.php`
- `/release/update`
- `/release/update.php`
- `/release/update2.php`
- `/release/patches.php`
- root `/update`
- root `/update.php`
- root `/update2.php`
- root `/patches.php`
- `/release/filter.txt`
- `/release/Localisation/<filename>`
- `/release/<language>/<filename>`
- `/release/<filename>`

Current Athena behavior:

- Missing.

Athena decision:

- Use a no-update compatibility no-op for `/web/check-updates.php` with the
  stable-compatible JSON array body `[]`. This is the initial Athena policy
  selected by the release/update audit and fixture handoff
  `check_updates_no_update_json_array`.
- Keep proxying, update metadata, and `nope` variants out of the initial
  policy. They require a future operational decision rather than changing the
  selected no-update body.
- Release manifest routes can use the no-update/no-op response shapes recorded
  by the release/update audit: empty body for `/release/update`,
  `/release/update2.php`, and `/release/patches.php`, and `0` for
  `/release/update.php`.
- Release file hosting remains out of the core server path until Athena
  intentionally supports stable client update artifact distribution.

Reference request and response shapes from `deck`:

| Endpoint | Request | Response |
| --- | --- | --- |
| `/web/check-updates.php` | `action=check|path|error`, `stream=cuttingedge|stable40|beta40|stable` | `[]` in `deck`; `bancho.py` returns an empty body. |
| `/release/update` | `t=<time>`, `v=<current_version>` | Newline-separated file rows: `<filename> <md5> - noup <filename>` plus extra rows `<filename> <md5> <description> extra <download>`. Empty string means no update data. |
| `/release/update.php` | `f=<filename>`, `h=<checksum>`, `t=<ticks>` | `0` in `deck` until file checks are implemented. |
| `/release/update2.php` | no required query in `deck` | Empty string. |
| `/release/patches.php` | none | Empty string until patch data is derived. |
| `/release/<filename>` | optional `v=<checksum>` | Release, patch, or extra file bytes with `Content-Disposition`, `Content-Length`, and sometimes `Last-Modified`. |
| `/release/filter.txt` | none | Proxies `https://m1.ppy.sh/release/filter.txt`. |
| `/release/Localisation/<filename>` | optional version query key | Proxies `https://m1.ppy.sh/release/Localisation/<filename>?<version>`. |
| `/release/<language>/<filename>` | `<filename>` must end with `.dll` | Stored localization DLL bytes. |

`lets` takes a proxy-oriented approach for `/web/check-updates.php`: it forwards
all query parameters to `https://osu.ppy.sh/web/check-updates.php`, returns
`nope` for `action=put`, and returns an empty body on errors. Athena should not
proxy or host release artifacts by default; that requires a separate operational
decision because it changes external dependency and storage behavior.

Required processing:

1. Parse client version and update channel.
2. Return no-update or update metadata in stable-compatible body format.
3. Serve release files if Athena chooses to host stable update artifacts.

For private server use, this may be intentionally minimized, but the decision
must be explicit because stable clients call these endpoints.

Task 3.2 Update check PHP route evidence note:

| Evidence field | Evidence state | Evidence note |
| --- | --- | --- |
| Auth method | `scope outside` | No auth requirement is documented for `/web/check-updates.php` in the reference notes. |
| Required request params | `confirmed` | `action=check|path|error` and `stream=cuttingedge|stable40|beta40|stable` are documented above from `deck`; proxy-style `lets` behavior forwards all query params. |
| Success response | `confirmed` | Initial Athena no-update compatibility returns `[]`; release/update audit records fixture handoff `check_updates_no_update_json_array` and keeps proxy/nope variants as future operational policy. |
| Auth failure response | `scope outside` | No auth branch is expected from the documented request shape. |
| Domain/data-not-found response | `scope outside` | This endpoint is an update policy route, not a domain object lookup route. |
| Malformed request response | `unconfirmed` | Missing action/stream, unknown action, and proxy-error behavior need fixtures before implementation. |

### osu!direct And Beatmap File Endpoints

Endpoint candidates from references:

- `/web/osu-search.php`
- `/web/osu-search-set.php`
- `/d/<beatmapset_id>`
- `/s/<beatmapset_id>`
- `/bss/<beatmapset_id>`
- `/osu/<beatmap_id_or_filename_or_checksum>`
- `/web/maps/<filename>`
- `/mt/<filename>`, `/thumb/<filename>`, `/images/map-thumb/<filename>`
- `/preview/<filename>`, `/mp3/preview/<filename>`

Current Athena behavior:

- Beatmap mirror services exist internally.
- Stable osu!direct/search/download endpoints are missing.

Required processing:

1. Decide Athena's stable osu!direct compatibility scope.
2. Parse search query, mode, status, page, and set detail parameters.
3. Return text bodies matching stable expectations.
4. Serve `.osu`, `.osz`, thumbnail, and preview assets with stable-compatible
   status codes and headers.
5. Keep beatmap metadata/file warmup integrated with getscores and score submit.

Reference osu!direct search shapes from `deck`:

| Endpoint | Request | Response |
| --- | --- | --- |
| `/web/osu-search.php` | `q=<query>`, `m=<mode>`, `r=<display_mode>`, optional `p=<page>`, `u=<username>`, `h=<password>` or legacy `c=<password>` | First line is result count. Each result line is a pipe-delimited beatmapset row. Error is `-1\n<message>`. |
| `/web/osu-search-set.php` | One of `s=<set_id>`, `b=<beatmap_id>`, `c=<checksum>`, `t=<topic_id>`, or `p=<post_id>`, plus optional `u`, `h` | One pipe-delimited beatmapset row or HTTP 404/401. |

`deck` beatmapset row shape:

```text
<osz_filename>|<artist>|<title>|<creator>|<status>|<rating>|<last_update>|<set_id>|<topic_id>|<has_video>|<has_storyboard>|<osz_filesize>|<osz_filesize_novideo>|<version@mode,...>|<post_id>
```

Task 2.4 `/web/osu-search.php` and `/web/osu-search-set.php` evidence note:

| Evidence field | Evidence state | Evidence note |
| --- | --- | --- |
| Auth method | `unconfirmed` | `deck` documents optional `u`/`h` and legacy `c` credential fields, but current target-client auth usage and failure bodies are not fixture-backed. |
| Required request params | `confirmed` | Reference params for `/web/osu-search.php` and `/web/osu-search-set.php` are documented above; Athena still needs per-path parser fixtures before implementation. |
| Success response | `confirmed` | `deck` documents result-count plus beatmapset rows for search and one beatmapset row for set lookup. |
| Auth failure response | `unconfirmed` | `/web/osu-search-set.php` may return 401, but exact body/status behavior and `/web/osu-search.php` credential failure behavior need fixtures. |
| Domain/data-not-found response | `unconfirmed` | Search error `-1\n<message>` and set lookup 404 are reference-documented, but current-client interpretation and exact messages are unconfirmed. |
| Malformed request response | `unconfirmed` | Bad mode/status/page, missing selector, ambiguous selector, and malformed credential behavior have no Athena fixture coverage. |

Task 2.4 decision:

- Classify `/web/osu-search.php` and `/web/osu-search-set.php` as
  `needs reference evidence`. They are real osu!direct compatibility surfaces,
  but P0 vs later-milestone timing needs target-client traffic and
  failure-branch fixtures.
- Keep download and static/media serving paths as adjacent context. `/web/maps`
  starts with `/web/`, but it serves `.osu` bytes and belongs with file delivery
  policy rather than legacy PHP response-body classification.

Reference file/media behavior:

| Endpoint | Request | Response |
| --- | --- | --- |
| `/d/<filename>`, `/bss/<filename>` | `<filename>` starts with set id; suffix `n` on the id requests no-video package. Present in `deck`. | Streams `.osz` bytes. 404 for invalid/missing, 451 for unavailable. Headers include `Content-Disposition`, `Content-Length`, and `Last-Modified`. |
| `/s/<filename>` | `<filename>` starts with set id. Present in `lets`. | 302 redirect to a download URL in the reference implementation; keep separate fixtures if Athena chooses to stream locally instead. |
| `/osu/<query>`, `/web/maps/<query>` | Query may be beatmap id, `.osu` filename, or checksum. | Raw `.osu` bytes with `Content-Disposition` and `Last-Modified`; 404 when unresolved. |
| `b.$DOMAIN/<path>` in bancho.py | Any path. | 301 redirect to `https://b.ppy.sh<path>`; useful fallback when Athena does not host bmap assets. |
| `/mt/<filename>`, `/thumb/<filename>`, `/images/map-thumb/<filename>` | Filename key before first dot; optional `c=<checksum>`. | JPEG background bytes. 404 when missing. Adds `Cache-Control: public, max-age=86400` when `c` is present. |
| `/preview/<filename>`, `/mp3/preview/<filename>` | Numeric filename key before first dot; optional `c=<checksum>`. | MP3 preview bytes. 404 when invalid/missing. Adds the same one-day cache header when `c` is present. |

Task 2.4 adjacent file/media boundary note:

| Adjacent family | Paths | Boundary decision | Evidence gap |
| --- | --- | --- | --- |
| Beatmap file delivery | `/web/maps/{query}`, `/d/*`, `/s/*`, `/bss/*`, `/osu/*`, download host aliases | Not classified by Issue #32 final audit vocabulary; keep as adjacent static/media/download scope. | Missing route implementation, file byte fixtures, redirect/streaming policy, cache/header fixtures, and current-client traffic belong to the static/media/download follow-up. |
| Beatmap media delivery | `/mt/*`, `/thumb/*`, `/images/map-thumb/*`, `/preview/*`, `/mp3/preview/*` | Not classified by Issue #32 final audit vocabulary; keep as adjacent static/media/download scope. | Missing thumbnail/preview object model, 404 behavior, cache/header fixtures, and host-alias traffic belong to the static/media/download follow-up. |

Host routing observed in `osuTitanic/titanic`:

| Host | Routed paths |
| --- | --- |
| `s.$DOMAIN` | `/images/map-thumb/*`, `/images/*`, `/a/*`, `/thumb/*`, `/mt/*`, `/preview/*`, `/mp3/preview/*` |
| `b.$DOMAIN` | `/mt/*`, `/thumb/*`, `/images/map-thumb/*`, `/preview/*`, `/mp3/preview/*`, `/d/*` |
| `d.$DOMAIN`, `d.osu.$DOMAIN` | `/d/*` |
| `osu.$DOMAIN`, bare domain, `ha.$DOMAIN` | `/web/*`, `/rating/*`, `/release/*`, `/osu/*`, `/a/*`, `/forum/download.php`, `/ss/*`, `/d/*`, `/mt/*`, `/thumb/*`, `/images/map-thumb/*`, `/preview/*`, `/mp3/preview/*` |

### Legacy Beatmap Info And OSZ2 Helpers

Endpoint candidates:

- `/web/osu-getbeatmapinfo.php`
- `/web/osu-getstatus.php`
- `/web/osu-gethashes.php`
- `/web/osu-osz2-getfileinfo.php`
- `/web/osu-osz2-getrawheader.php`
- `/web/osu-osz2-getfilecontents.php`
- `/web/osu-magnet.php`

Current Athena behavior:

- Missing.

Reference request and response shapes from `deck`:

| Endpoint | Request | Response |
| --- | --- | --- |
| `/web/osu-getbeatmapinfo.php` | Query `u`, `h`; body model has `Filenames: list[str]` and `Ids: list[int]`. | Newline rows: `<filename_index>|<beatmap_id>|<set_id>|<md5>|<status>|<osu_grade>|<taiko_grade>|<catch_grade>|<mania_grade>`. Empty body for 0 or more than 100 requested maps. |
| `/web/osu-getstatus.php` | `c=<md5,md5,...>` with at most 60 checksums. | Newline rows: `<checksum>,<status>,<beatmap_id>,<set_id>,<topic_id>`. |
| `/web/osu-gethashes.php` | `s=<set_id>`. | `0` when unknown; otherwise `1|<BODY_HASH>|<META_HASH>`. |
| `/web/osu-osz2-getfileinfo.php` | `u`, `h`, `s=<set_id>`. | Pipe-delimited file entries plus final data offset line: `<filename>:<offset>:<size>:<hash>:<created_ticks>:<modified_ticks>|...\n<data_offset>`. |
| `/web/osu-osz2-getrawheader.php` | `u`, `h`, `s=<set_id>`. | Raw osz2 header bytes up to package data offset. |
| `/web/osu-osz2-getfilecontents.php` | `u`, `h`, `s=<set_id>`, `f=<filename>`. | Raw file bytes from the osz2 package. |
| `/web/osu-magnet.php` | `u`, `h`, `s=<set_id>`, `v=<no_video>`. | `deck` validates auth and map availability, then returns 501 because magnet support is not implemented. |

Task 2.4 `/web/osu-getbeatmapinfo.php` evidence note:

| Evidence field | Evidence state | Evidence note |
| --- | --- | --- |
| Auth method | `confirmed` | `deck` documents query credentials `u` and `h`; Athena still needs target-client traffic and fixture coverage. |
| Required request params | `confirmed` | `deck` documents body fields `Filenames` and `Ids`; exact body encoding and client limits need fixtures. |
| Success response | `confirmed` | Newline beatmap info rows are documented above. |
| Auth failure response | `unconfirmed` | Exact status/body for credential failure is not documented in this guide. |
| Domain/data-not-found response | `unconfirmed` | `deck` returns an empty body for 0 or more than 100 requested maps, but unknown-map row behavior still needs fixtures. |
| Malformed request response | `unconfirmed` | Malformed body, mixed filename/id selectors, and over-limit behavior need focused fixtures. |

Task 2.4 `/web/osu-getstatus.php` evidence note:

| Evidence field | Evidence state | Evidence note |
| --- | --- | --- |
| Auth method | `scope outside` | Reference request shape uses only checksum query `c`; no credential field is documented for this endpoint. |
| Required request params | `confirmed` | `c=<md5,md5,...>` with at most 60 checksums is documented above. |
| Success response | `confirmed` | Newline checksum status rows are documented above. |
| Auth failure response | `scope outside` | No auth branch is expected from the documented reference request shape. |
| Domain/data-not-found response | `unconfirmed` | Unknown checksum handling and status mapping need fixture-backed confirmation. |
| Malformed request response | `unconfirmed` | Empty checksum list, over-limit list, invalid md5, and mixed valid/invalid behavior have no Athena fixture coverage. |

Task 2.4 OSZ2/hash helper evidence note:

| Evidence field | Evidence state | Evidence note |
| --- | --- | --- |
| Auth method | `unconfirmed` | Some helper routes use `u`/`h`, while `/web/osu-gethashes.php` documents only `s`; per-path auth policy needs fixtures. |
| Required request params | `confirmed` | Reference params are documented above for hashes, file info, raw header, file contents, and magnet. |
| Success response | `confirmed` | Reference success text/byte shapes are documented above, including raw OSZ2 header and file bytes. |
| Auth failure response | `unconfirmed` | Per-helper credential failure body/status is not documented. |
| Domain/data-not-found response | `unconfirmed` | Unknown set/file behavior, storage-missing behavior, and `/web/osu-magnet.php` 501 policy need per-path fixtures. |
| Malformed request response | `unconfirmed` | Missing set id, invalid filename, traversal-like filename, and bad no-video value behavior are unconfirmed. |

Task 2.4 decision:

- Classify `/web/osu-getbeatmapinfo.php`, `/web/osu-getstatus.php`, and the
  OSZ2/hash helper routes as `needs reference evidence`.
- Do not implement or mark these routes complete in this audit. Missing
  implementation, missing fixtures, and missing traffic evidence remain
  follow-up work.

### Screenshots

Endpoint candidates:

- `POST /web/osu-screenshot.php`
- `POST /web/osu-ss.php`
- `GET /ss/<id>.<extension>` in `bancho.py`
- `GET /ss/<id>`
- `GET /ss/<id>/<checksum>`

Current Athena behavior:

- Missing.

Required processing:

1. Authenticate the uploader.
2. Accept screenshot form field `ss`.
3. Validate filename, size, and image type.
4. Store screenshot in blob storage.
5. Return a stable screenshot id or URL.
6. Serve screenshot bytes from `/ss/...`.

Reference upload behavior from `deck`:

| Endpoint | Request | Response |
| --- | --- | --- |
| `/web/osu-screenshot.php` | Query `u=<username>`, `p=<password>`; multipart file field `ss`; accepted upload names are `jpg`, `png`, and `ss`; max size is 4 MiB. | Body is numeric screenshot id. Invalid auth, size, or image type returns an HTTP error. |
| `/web/osu-ss.php` | Query `u=<user_id>`, `h=<password>`; multipart file field `ss`. | Returns 501 in `deck`; this was tied to the removed monitor packet path. |

Reference response variants:

| Reference | `/web/osu-screenshot.php` response |
| --- | --- |
| `deck` | Numeric screenshot id. |
| `lets` | Full screenshot URL such as `<server>/ss/<id>.jpg`; rate limit returns `no`. |
| `bancho.py` | Generated screenshot filename served later from `/ss/<id>.<extension>`. |

Athena should pick one response contract based on target client traffic and keep
the serving route compatible with that choice.

Reference serving behavior:

| Endpoint | Request | Response |
| --- | --- | --- |
| `/ss/<id>` | Numeric screenshot id. | 301 redirect to `/ss/<id>/<md5(created_at)>`; 404 if missing, hidden, or older than seven days. |
| `/ss/<id>/<checksum>` | Numeric screenshot id and checksum from creation timestamp. | PNG/JPEG image bytes with `Cache-Control: public, max-age=1209600, immutable`, `Date`, `Content-Disposition: inline`, and `Content-Length`. |
| `/ss/<screenshot_id>.<extension>` in `bancho.py` | 8-character screenshot id plus `jpg`, `jpeg`, or `png`. | File bytes from local screenshot storage or JSON 404. |

### Avatars And Menu Assets

Endpoint candidates:

- `/a/`
- `/a/<filename>`
- `/forum/download.php?avatar=<filename>`
- `/menu-content.json`
- `/assets/menu-content.json`

Current Athena behavior:

- Missing.

Reference request and response shapes from `deck` and `titanic`:

| Endpoint | Request | Response |
| --- | --- | --- |
| `/a/` | none | Default avatar `unknown` as `image/png`; 500 if storage lacks the default. |
| `/a/<filename>` | `filename` begins with user id, optionally followed by an underscore or extension; optional `s=<size>`, `c=<checksum>`. Allowed sizes are 25, 128, and 256, defaulting to 128. | User avatar or default avatar as `image/png`. Adds `Cache-Control: public, max-age=86400` when `c` is present. Resized avatars may be cached by user id and size. |
| `/forum/download.php` | `avatar=<filename>`. | Same as `/a/<filename>` at size 128. |
| `/menu-content.json` | none on `assets.$DOMAIN`; Titanic rewrites to `/assets/menu-content.json`. | Menu/title content JSON from deck. Athena should either provide a stable-compatible JSON or explicitly proxy/disable it. |

External references also show host-based avatar variants such as
`a.$DOMAIN/<id>[.<ext>]`, `a.$DOMAIN/avatar/<id>`, and screenshot-like
`a.$DOMAIN/ss/<id>.jpg`. Treat these as compatibility candidates until real
Athena target-client traffic proves which aliases are necessary.

Avatar hash is durable compatibility data. Some stats/profile responses include
filenames shaped like `<user_id>_<avatar_checksum>.png`, so avatar updates must
be reflected in any future stats/profile read model and cache invalidation.

### Ratings, Comments, Favourites, Stats, Status

Endpoint candidates:

- `/web/osu-rate.php`, `/rating/ingame-rate.php`, `/rating/ingame-rate2.php`
- `/web/osu-comment.php`
- `/web/osu-addfavourite.php`, `/web/osu-getfavourites.php`
- `/web/osu-stat.php`, `/web/osu-statoth.php`
- `/web/osu-getstatus.php`
- `/web/osu-getfriends.php`
- `/web/osu-markasread.php`
- `/web/osu-checktweets.php`
- `/web/lastfm.php`
- `/web/osu-getseasonal.php`
- `/menu-content.json`

Current Athena behavior:

- Mostly missing.
- Friend relationships exist through Bancho packets, but `/web/osu-getfriends.php`
  is not implemented.

Required processing:

1. Confirm which endpoints are called by target stable client builds.
2. Categorize each as required, compatibility no-op, or intentionally out of
   scope.
3. For required endpoints, document exact request parameters and response bodies
   from `lets`, `deck`, `bancho.py`, and traffic.
4. Add fixtures for each implemented response.

Reference request and response shapes from `deck`:

| Endpoint | Request | Response |
| --- | --- | --- |
| `/web/osu-rate.php` | `u=<username>`, `p=<password>`, `c=<beatmap_md5>`, optional `v=<0..10>`. | String sentinel: `auth fail`, `no exist`, `not ranked`, `owner`, `alreadyvoted\n<avg>`, `ok`, `no`, or `ok\n<avg>`. |
| `/rating/ingame-rate.php` | Same query shape as `/web/osu-rate.php`. | Same failure sentinels, but successful vote returns only `<avg>` and previous vote returns `alreadyvoted` without the average. |
| `/rating/ingame-rate2.php` | Same query shape as `/web/osu-rate.php`. | Same as `ingame-rate.php`, except previous vote returns `alreadyvoted\n<avg>`. |
| `/web/osu-comment.php` | Form `u`, `p`, `a=get|post`, `b=<beatmap_id>`, optional `r`, `m`, `s`, `comment`, `starttime`, `f`, `target`. | `get` returns newline comments; legacy rows are `<time>|<comment>`, newer rows are tab-delimited `<time>\t<Target>\t<format>\t<comment>`. `post` returns `<time>|<content>\n`. |
| `/web/osu-addfavourite.php` | `u`, `h`, `a=<set_id>`. | Human-readable success or limit/already-favourited string; HTTP errors for auth/missing map. |
| `/web/osu-getfavourites.php` | `u`, `h`. | Newline-separated beatmapset ids. |
| `/web/osu-stat.php`, `/web/osu-statoth.php` | `u=<username>`, either `c=md5(username + prettyplease!!!)` or `p=<password>`. | Pipe row: `<capped_score>|<accuracy>|<total_score>|<user_id>|<rank>|<user_id>_<avatar_checksum>.png`. |
| `/web/osu-getfriends.php` | `u`, `h`. | Newline-separated friend user ids. |
| `/web/osu-getstatus.php` | `c=<comma-separated-md5s>` up to 60 checksums. | Newline rows: `<checksum>,<status>,<beatmap_id>,<set_id>,<topic_id>`. |
| `/web/osu-markasread.php` | `u`, `h`, `channel=<name>`. | Empty 200 for public channels or successful DM read marking; 404 for unknown DM target. |
| `/web/osu-checktweets.php` | none. | Empty 200 or configured status message text. |
| `/web/osu-getseasonal.php` | none. | JSON array of seasonal background paths. |
| `/web/osu-title-image.php` | optional `c=<checksum>`, `l=1` for click redirect. | Image bytes, empty body, or redirect to configured menu URL. |
| `/assets/menu-content.json`, `/menu-content.json` | none. | JSON with `images` array containing `image`, `url`, `IsCurrent`, `begins`, `expires`. |
| `/web/osu-login.php` | `username`, `password`. | `1` on valid IRC-style login preflight, otherwise `0`. |
| `/web/coins.php` | `u`, `h`, `c=<count>`, `cs=md5(username + count + osuycoins)`, `action=earn|use|recharge`. | Current coin count as text; private-server-specific candidate. |
| `/web/osu-benchmark.php` | Form `u`, `p`, `s`, `f`, `r`, `c`, `h=<hardware-json>`. | Benchmark id as text; custom/private-server endpoint, not normal stable requirement. |

Task 2.5 ratings evidence note:

| Evidence field | Evidence state | Evidence note |
| --- | --- | --- |
| Auth method | `confirmed` | Reference routes use `u` plus `p`/password credential material. |
| Required request params | `confirmed` | `c=<beatmap_md5>` and optional `v=<0..10>` are documented for `/web/osu-rate.php` and `/rating/ingame-rate*.php`. |
| Success response | `confirmed` | Reference success sentinels and average variants are documented above. |
| Auth failure response | `confirmed` | `auth fail` is documented above, but Athena still needs focused fixtures. |
| Domain/data-not-found response | `confirmed` | `no exist`, `not ranked`, `owner`, and `alreadyvoted` sentinels are documented above, but per-path fixture coverage is missing. |
| Malformed request response | `unconfirmed` | Missing/invalid vote value, malformed checksum, and duplicate vote edge cases need fixtures. |

Task 2.5 comments and favourites evidence note:

| Evidence field | Evidence state | Evidence note |
| --- | --- | --- |
| Auth method | `confirmed` | Reference routes use `u` plus `p` or `h` credential material. |
| Required request params | `confirmed` | Comment `a=get|post`, beatmap/replay selectors, and favourite set id/list params are documented above. |
| Success response | `confirmed` | Comment rows, post response, favourite success text, and favourites list shape are documented above. |
| Auth failure response | `unconfirmed` | Exact auth failure status/body differs by route and needs fixtures. |
| Domain/data-not-found response | `unconfirmed` | Unknown beatmap/replay/set, favourite limit, and already-favourited behavior need per-path fixtures. |
| Malformed request response | `unconfirmed` | Bad selector, missing comment fields, oversized content, and malformed set ids have no Athena fixture coverage. |

Task 2.5 stats and friends evidence note:

| Evidence field | Evidence state | Evidence note |
| --- | --- | --- |
| Auth method | `confirmed` | Stats routes use `c=md5(username + prettyplease!!!)` or `p=<password>`; friends route uses `u` and `h`. |
| Required request params | `confirmed` | Required params and output row shapes are documented above. |
| Success response | `confirmed` | Stats pipe row and newline friend id list are documented above. |
| Auth failure response | `unconfirmed` | Exact failure body/status needs fixtures. |
| Domain/data-not-found response | `unconfirmed` | Unknown user, empty stats projection, empty friend list, and avatar hash fallback behavior need fixtures. |
| Malformed request response | `unconfirmed` | Bad checksum, missing user, malformed password hash, and projection-unavailable behavior have no fixture coverage. |

Task 2.5 social/status no-op evidence note:

| Evidence field | Evidence state | Evidence note |
| --- | --- | --- |
| Auth method | `unconfirmed` | `/web/osu-markasread.php` uses `u`/`h`, while `/web/osu-checktweets.php` has no documented auth; `/web/lastfm.php` lacks a documented shape here. |
| Required request params | `unconfirmed` | `channel=<name>` is documented for mark-as-read, but lastfm params and current-client usage are unconfirmed. |
| Success response | `unconfirmed` | Empty 200 or static status text is plausible for some routes, but exact no-op body is not confirmed for all paths. |
| Auth failure response | `unconfirmed` | Per-route auth failure behavior needs fixtures. |
| Domain/data-not-found response | `unconfirmed` | Unknown DM target/channel returns 404 for mark-as-read in the reference notes; other routes are unconfirmed. |
| Malformed request response | `unconfirmed` | Missing channel, bad user credentials, and unknown lastfm payload behavior need fixtures. |

Task 2.5 seasonal UI evidence note:

| Evidence field | Evidence state | Evidence note |
| --- | --- | --- |
| Auth method | `scope outside` | `/web/osu-getseasonal.php` has no documented auth requirement. |
| Required request params | `scope outside` | No request params are documented. |
| Success response | `unconfirmed` | Current osu!stable client traffic is confirmed by user report, and reference behavior is a JSON array of seasonal background paths. The exact empty-array body and cache contract still need a focused fixture before final `compatibility no-op` classification. |
| Auth failure response | `scope outside` | No auth branch is expected. |
| Domain/data-not-found response | `scope outside` | No domain error branch is expected; exact empty-array behavior needs fixture confirmation. |
| Malformed request response | `unconfirmed` | Cache headers and behavior with unexpected query params need a focused fixture. |

Task 2.5 title/menu evidence note:

| Evidence field | Evidence state | Evidence note |
| --- | --- | --- |
| Auth method | `scope outside` | `/web/osu-title-image.php`, `/assets/menu-content.json`, and `/menu-content.json` have no documented auth requirement. |
| Required request params | `confirmed` | Title image optional `c` and `l=1` plus menu JSON with no params are documented above. |
| Success response | `unconfirmed` | Title image may return bytes, empty body, or redirect; menu JSON returns a JSON `images` array. Exact target behavior and cache policy need fixtures. |
| Auth failure response | `scope outside` | No auth branch is expected for title/menu assets. |
| Domain/data-not-found response | `unconfirmed` | Missing image/menu asset and disabled menu policy need an explicit response decision. |
| Malformed request response | `unconfirmed` | Bad checksum param, redirect query variants, and unexpected menu JSON query params need fixtures. |

Task 2.5 login preflight evidence note:

| Evidence field | Evidence state | Evidence note |
| --- | --- | --- |
| Auth method | `confirmed` | `/web/osu-login.php` uses username/password preflight credentials in the reference notes. |
| Required request params | `confirmed` | Login `username` and `password` params are documented above. |
| Success response | `unconfirmed` | Reference notes return `1` on success, but current-client traffic and relationship to Bancho login need fixtures. |
| Auth failure response | `unconfirmed` | Reference notes return `0` on failure, but exact status/body and relationship to Bancho login need fixtures. |
| Domain/data-not-found response | `scope outside` | No separate domain not-found branch is documented for login preflight. |
| Malformed request response | `unconfirmed` | Missing login params and malformed credential behavior need fixtures. |

Task 2.5 private-server and beatmap submission decision:

| Family | Decision | Reason |
| --- | --- | --- |
| `/web/coins.php` | `out of scope` | Private-server currency is outside current osu!stable normal-play compatibility. Decision source: GitHub Issue #32 scope encoded in `.kiro/specs/legacy-web-endpoint-inventory-audit/requirements.md` Requirement 6.2 and `research.md` private-server finding. |
| `/web/osu-benchmark.php` | `out of scope` | Benchmark diagnostics are outside current osu!stable normal-play compatibility. Decision source: GitHub Issue #32 scope encoded in `.kiro/specs/legacy-web-endpoint-inventory-audit/requirements.md` Requirement 6.3 and `research.md` private-server finding. |
| Beatmap submission endpoints | `deferred` | Beatmap submission is planned after P0 core login/play and score compatibility, and this audit does not implement upload workflows. Decision source: GitHub Issue #32 scope encoded in `.kiro/specs/legacy-web-endpoint-inventory-audit/requirements.md` Requirement 6.1 and `design.md` non-goals; revisit when the core stable compatibility milestone is complete. |

Task 2.5 private-server currency and benchmark evidence note:

| Evidence field | Evidence state | Evidence note |
| --- | --- | --- |
| Auth method | `scope outside` | `/web/coins.php` and `/web/osu-benchmark.php` are classified `out of scope` for current normal-play compatibility, so their credential contracts are not implementation input for this audit. |
| Required request params | `scope outside` | Reference request shapes are documented above, but product scope excludes implementing or fixture-locking these private-server/diagnostic params in this audit. |
| Success response | `scope outside` | Reference success bodies are documented above, but Athena intentionally does not select a compatibility response contract while the family remains `out of scope`. |
| Auth failure response | `scope outside` | Auth failure behavior is not required while the family remains outside current product scope. |
| Domain/data-not-found response | `scope outside` | Currency balance and benchmark diagnostics do not become Athena domain contracts in this audit. |
| Malformed request response | `scope outside` | Malformed request behavior is not fixture scope unless product scope later includes these routes. |

Task 2.5 beatmap submission evidence note:

| Evidence field | Evidence state | Evidence note |
| --- | --- | --- |
| Auth method | `unconfirmed` | Beatmap submission is deferred until after core login/play/score compatibility; per-route credential material and failure behavior still need fixtures before implementation. |
| Required request params | `unconfirmed` | get-id, upload, post, novideo, and topic request variants are not fixture-backed for Athena. |
| Success response | `unconfirmed` | Upload/session ids, post success bodies, and topic lookup responses need route-specific reference evidence. |
| Auth failure response | `unconfirmed` | Auth failure status/body and retryability are unknown for each submission alias. |
| Domain/data-not-found response | `unconfirmed` | Beatmapset/topic not-found and duplicate upload behavior need future evidence. |
| Malformed request response | `unconfirmed` | Malformed multipart upload, missing metadata, and invalid topic/get-id payload behavior need future fixtures. |

Task 2.5 screenshots and diagnostics evidence note:

| Evidence field | Evidence state | Evidence note |
| --- | --- | --- |
| Auth method | `unconfirmed` | Screenshot references use `u` plus `p` or `h`, but `/web/osu-error.php` auth behavior is not yet separated per route. |
| Required request params | `unconfirmed` | Screenshot upload fields and size/type constraints are documented in the Screenshots section; `/web/osu-error.php` request body still needs detail. |
| Success response | `unconfirmed` | Screenshot response variants differ across `deck`, `lets`, and `bancho.py`; error report success body is not fixture-backed. |
| Auth failure response | `unconfirmed` | Per-route auth failure status/body needs fixtures. |
| Domain/data-not-found response | `unconfirmed` | Screenshot serving handoff and missing media behavior belong partly to adjacent `/ss/*` media scope. |
| Malformed request response | `unconfirmed` | Bad image type, oversized upload, missing file, and malformed error report behavior need fixtures. |

### Legacy Web Follow-up Checklist

This audit records follow-up work only; it does not complete route
implementation, fixture extraction, or real-client traffic capture. A family may
remain `required`, `compatibility no-op`, `deferred`, `out of scope`, or
`needs reference evidence` while one or more follow-up columns below still need a
separate issue.

| Endpoint family | Missing implementation follow-up | Missing fixture / reference-evidence follow-up | Missing current-client traffic follow-up |
| --- | --- | --- | --- |
| Bancho reachability | No new route work for the current empty-body route unless traffic proves pre-login validation is required. | Empty-body compatibility, country-code/IP response, and malformed-query fixtures. | Pre-login validation, country-code, and client retry behavior probes. |
| Modern getscores | Complete leaderboard row projections and remaining branch behavior. | Auth failure, unavailable, update-required, row/header, malformed identity, friends, and country fixtures. | Real-client probes for target leaderboard modes and selection branches. |
| Modern score submit selector | Complete rank/stat/achievement projection and post-submit durability gaps. | Auth sentinel, multipart variant, malformed encrypted payload, duplicate, and storage failure fixtures. | Real-client probes for submit success, failure, and retry interpretation. |
| Replay download PHP route | Add `/web/osu-getreplay.php` only after target path and auth contract are confirmed. | Replay bytes, auth failure, missing replay, malformed score id, and mode fixtures. | Confirm current client path choice between `/web/osu-getreplay.php` and adjacent replay aliases. |
| Session candidate | Add a route only if exact reference row or traffic proves the surface is still called; preserve the `bancho.py` unhandled-route trace as a reference lead. | Auth, params, success body, failure sentinel, and malformed request evidence. | Current target-client call confirmation for `/web/osu-session.php`. |
| Legacy getscores aliases | Add alias routes only after per-path response variants are confirmed. | Per-version row shape, auth failure, unavailable/update sentinels, not-found, and malformed request fixtures. | Older-client or target-client probes proving which aliases Athena should support. |
| Legacy score submit aliases | Add alias routes only after per-path payload and response contracts are confirmed. | Payload shape, success body, retryable/terminal failure sentinel, auth failure, and malformed payload fixtures. | Older-client or target-client probes proving which submit aliases remain needed. |
| Update check PHP route | Add `/web/check-updates.php` no-update behavior using the selected `[]` body; proxy/update metadata remains future operational policy. | `check_updates_no_update_json_array`, missing action/stream, and unknown action fixtures. Proxy response and `nope` variants are needed only if Athena later opts into that policy. | Target-client probes for update action and stream combinations. |
| osu!direct search and set lookup | Add search/set routes when P0 timing and read-model ownership are decided. | Auth variants, search/set success rows, 401/404/error sentinels, pagination, and malformed selector fixtures. | Current-client traffic proving P0 vs later-milestone timing. |
| Legacy beatmap info | Add route after request body encoding and Bancho packet relationship are confirmed. | Success rows, auth failure, over-limit, malformed body, and unknown beatmap fixtures. | Current-client probes for whether web beatmap info is still called. |
| Beatmap checksum status | Add route after checksum list limits and status mapping are fixture-backed. | Unknown checksum, invalid MD5, empty/over-limit list, mixed valid/invalid, and status mapping fixtures. | Current-client probes for checksum/status usage. |
| OSZ2/hash helpers | Add helper routes only after per-path file and auth contracts are confirmed. | Per-path auth, success bytes/text, file-not-found, storage-missing, magnet 501, and malformed params fixtures. | Current-client probes for OSZ2 helper and magnet usage. |
| Screenshot upload and client diagnostics | Add upload/error routes after upload and report body contracts are separated per path. | Upload success body, error report body, auth failure, oversized/bad file, missing file, and media handoff fixtures. | Current-client probes for screenshot, monitor screenshot, and error report flows. |
| Ratings | Add rating routes only after durable rating ownership and sentinels are confirmed. | Success, `auth fail`, `no exist`, `not ranked`, `owner`, `alreadyvoted`, and malformed vote fixtures. | Current-client probes for rating route usage. |
| Comments and favourites | Add comment/favourite routes after beatmap social ownership is planned. | Comment get/post, favourite add/list, auth failure, limit/already state, not-found, and malformed selector fixtures. | Current-client probes for comment and favourite workflows. |
| Stats and friends | Add stats/friends routes after projection ownership and friend read model are planned. | Stats row, avatar hash, auth failure, unknown user, empty stats, empty friends, and malformed credential fixtures. | Current-client probes for stats, other-stats, and web friends usage. |
| Social/status no-op candidates | Add no-op routes only after exact empty/static bodies are known. | Mark-as-read, checktweets, lastfm success/error bodies, unknown-channel, auth failure, and malformed request fixtures. | Current-client probes proving which social/status no-op candidates are called. |
| Seasonal UI | Add `/web/osu-getseasonal.php` only after the no-op JSON body and cache behavior are fixture-backed. | Empty JSON array, cache headers, unexpected query params, and dynamic seasonal asset management fixtures. | Current osu!stable call is confirmed; add probes only for query/cache variants. |
| Title/menu UI | Add title image and menu JSON only after target behavior is confirmed. | Image bytes, empty body, redirect, menu JSON body, cache policy, missing asset, and malformed query fixtures. | Current-client probes for title image and menu JSON usage. |
| Login preflight | Add `/web/osu-login.php` only after target behavior is confirmed. | Login `1`/`0`, auth failure, missing credential, malformed param, and Bancho-login relationship fixtures. | Current-client probes for web login preflight. |
| Beatmap submission | Implement after core login/play/score compatibility reaches the planned milestone. | Submit get-id/upload/post branch fixtures and topic lookup fixtures before implementation. | Beatmap submission traffic probes when the deferred workflow becomes active. |
| Private-server currency and benchmark | No active implementation issue while these remain `out of scope`. | Product-scope revalidation evidence if Athena later chooses to support them. | Traffic probes only after product scope changes. |

Task 5.1 coverage note: this checklist is the requirement 10.4 / 10.5 evidence
surface. Missing implementation, missing fixture/reference evidence, and
missing current-client traffic stay separate from audit completion, and the
matrix Task 5.1 verification table maps the remaining requirement IDs to the
matrix or guide section that proves them.

### Audit-only Boundary Verification

Task 4.2 keeps this spec as a documentation audit. The feature diff is expected
to remain limited to Kiro spec files, `CONTEXT.md`, and the stable
compatibility docs. It must not contain `src/`, `tests/`, runtime route stubs,
golden fixture files, or captured traffic artifacts.

Compatibility no-op rows still keep their own follow-up gaps. Existing partial
routes such as `/web/bancho_connect.php` need fixture and probe follow-up, while
seasonal and future social/status no-op candidates need separate route,
fixture, and probe work before they can be called implemented.

### Task 5.2 Markdown And Diff Review

Task 5.2 is the final docs review for the legacy web endpoint inventory audit.
It verifies Markdown readability, feature diff boundaries, and unresolved
follow-up reporting without changing runtime behavior.

| Review item | Result |
| --- | --- |
| Matrix headings | Reviewed: Stable HTTP Endpoint Coverage, Legacy Web Audit Scope Index, Task 2.2 through Task 5.1 audit sections, Reference Route Inventory, Coverage Rows Without Reference Exact Routes, and Persistence Inventory Coverage remain distinct headings. |
| Matrix tables | Reviewed: grouped coverage rows, exact path traceability rows, requirement coverage rows, and classification completeness rows retain header and separator rows and remain readable as Markdown tables. |
| Guide headings | Reviewed: Legacy Web Endpoints, Audit Scope Index, Final Audit Classification Contract, Endpoint Family Evidence Note Template, endpoint family evidence notes, Legacy Web Follow-up Checklist, and Audit-only Boundary Verification remain distinct headings. |
| Guide tables | Reviewed: evidence note tables keep the six required evidence fields, and the follow-up checklist keeps separate columns for missing implementation, missing fixture/reference evidence, and missing current-client traffic. |
| Feature diff boundary | Reviewed with `git diff --name-only main...HEAD`: the feature diff is limited to `.kiro/specs/legacy-web-endpoint-inventory-audit/*`, `CONTEXT.md`, `docs/stable-compatibility-guide.md`, and `docs/stable-compatibility-matrix.md`. |
| Runtime boundary | Clean: the feature diff does not include `src/`, `tests/`, runtime route stubs, golden fixture files, or captured traffic artifacts. |
| Unresolved follow-up reporting | Complete for this audit: unresolved work remains in the Legacy Web Follow-up Checklist and in `needs reference evidence`, `deferred`, or `out of scope` classifications rather than being treated as implemented. |

Docs-only audit completion condition: all Kiro tasks may be marked complete only
after the task list is checked, the feature diff remains within docs/spec/glossary
scope, full hooks pass, and the final validation report confirms no runtime,
fixture, or traffic-capture work entered this spec.

## Implementation Flow By Boundary

Use this boundary sequence for new stable work:

1. Add or update matrix row.
2. Record references: Lekuruu page for packet structs, reference implementation
   paths for behavior, or traffic fixture for observed client behavior.
3. Add parser/builder for wire shape in the local transport package.
4. Map transport input to a command/query dataclass.
5. Put business decisions in domain/services, not in the transport.
6. Persist durable changes through repositories and Unit of Work.
7. Put volatile session/presence/match/spectator state in Valkey-backed state
   interfaces.
8. Format the response at the stable transport boundary.
9. Add tests:
   - parser/builder golden test,
   - use-case test for business behavior,
   - integration or fixture test for stable response body.
10. Update the matrix status and evidence.

## Verification Requirements

Minimum verification before a stable surface is marked implemented:

- Request parser covers valid, malformed, and unknown-extra-field cases.
- Response formatter has a golden fixture.
- Integration test covers route/packet dispatch.
- Matrix row lists evidence.
- If the surface was derived from a reference implementation, the issue or doc
  names the exact reference path.

Before claiming stable compatibility complete:

- All C2S packets are implemented, explicitly out of scope, or documented as
  deferred with a reason.
- All S2C packets have builders or documented non-emission reasons.
- All Lekuruu `Types/*.md` structs are represented in the matrix.
- All observed `/web/*.php`, static/media, and update/release endpoints are
  represented in the matrix.
- Real stable client probes cover login, polling, chat, getscores, score submit,
  beatmap file/download scope, reconnect, and failure paths.

## Fixture Extraction Backlog

This document now records the stable packet, struct, endpoint, static/media, and
reference route inventory. Before implementing each missing surface, extract
golden fixtures for the exact branch being implemented:

- packet encode/decode bytes for every Lekuruu struct and packet payload,
  especially `Match`, `MatchJoin`, `ReplayFrameBundle`, `ScoreFrame`, and S2C
  45/46 enum correction cases,
- request/response fixtures for replay download, update/release policy,
  osu!direct search, beatmap info, screenshots, avatars, media, and old
  getscores/submit aliases,
- traffic confirmation for ambiguous candidates such as `/web/osu-session.php`,
  root `/update*` aliases, external avatar host variants, and private-server-only
  endpoints like coins/benchmark,
- product-scope revalidation for non-web out-of-scope diagnostics such as
  `/difficulty-rating` if Athena later chooses to support that surface,
- Akatsuki-compatible Relax/Autopilot score-submit, getscores, stats, and rank
  projection fixtures if Athena chooses to support those extension boards.
