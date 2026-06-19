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
| `String` | `0x00` for empty, or `0x0b` + ULEB128 byte length + UTF-8 bytes | Implemented as `BanchoString`. |
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
| `String` | Empty string is `0x00`; non-empty is `0x0b`, ULEB128 byte length, then UTF-8 bytes. |
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
| `UserPresence` | `sInt user_id`, `String username`, `char timezone_plus_24`, `char country_id`, `char permissions_or_mode` where value is `permissions | (mode << 5)`, `float longitude`, `float latitude`, `sInt rank`. |
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
- Full presence state, status broadcasting, rank/stat projection, and requested
  status responses are incomplete.

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
| Unavailable | `-1|false` |
| Update available | `1|false` |
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

- Use a compatibility no-op/proxy policy for the initial implementation.
- `/web/check-updates.php` and simple release manifest routes should return a
  stable-compatible no-update response unless target-client traffic proves a
  proxy to ppy or hosted release manifest is needed.
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

Reference file/media behavior:

| Endpoint | Request | Response |
| --- | --- | --- |
| `/d/<filename>`, `/bss/<filename>` | `<filename>` starts with set id; suffix `n` on the id requests no-video package. Present in `deck`. | Streams `.osz` bytes. 404 for invalid/missing, 451 for unavailable. Headers include `Content-Disposition`, `Content-Length`, and `Last-Modified`. |
| `/s/<filename>` | `<filename>` starts with set id. Present in `lets`. | 302 redirect to a download URL in the reference implementation; keep separate fixtures if Athena chooses to stream locally instead. |
| `/osu/<query>`, `/web/maps/<query>` | Query may be beatmap id, `.osu` filename, or checksum. | Raw `.osu` bytes with `Content-Disposition` and `Last-Modified`; 404 when unresolved. |
| `b.$DOMAIN/<path>` in bancho.py | Any path. | 301 redirect to `https://b.ppy.sh<path>`; useful fallback when Athena does not host bmap assets. |
| `/mt/<filename>`, `/thumb/<filename>`, `/images/map-thumb/<filename>` | Filename key before first dot; optional `c=<checksum>`. | JPEG background bytes. 404 when missing. Adds `Cache-Control: public, max-age=86400` when `c` is present. |
| `/preview/<filename>`, `/mp3/preview/<filename>` | Numeric filename key before first dot; optional `c=<checksum>`. | MP3 preview bytes. 404 when invalid/missing. Adds the same one-day cache header when `c` is present. |

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
  `/difficulty-rating`, root `/update*` aliases, external avatar host variants,
  and private-server-only endpoints like coins/benchmark,
- Akatsuki-compatible Relax/Autopilot score-submit, getscores, stats, and rank
  projection fixtures if Athena chooses to support those extension boards.
