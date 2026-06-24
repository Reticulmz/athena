# 調査ログ: persistence-inventory-audit

## 調査スコープ

Persistence Inventory Coverage テーブル全行について、以下の2段階で照合を実施した。

1. **既存 Athena コード** (domain modules, SQLAlchemy models, alembic migrations) との照合
2. **Reference implementation ソースコード確認** (bancho.py, titanic, lets/pep.py の実際の GitHub ソースコードを WebSearch + GitHub code search で確認)

## Reference Implementation Sources

| Reference | Source | 確認方法 |
|-----------|--------|---------|
| osuAkatsuki/bancho.py | `migrations/base.sql`, `app/repositories/*.py` | GitHub code search via subagent |
| osuTitanic/titanic | `migrations/*.up.sql` | GitHub code search via subagent |
| osuTitanic/deck | Web frontend (no own schema) | GitHub code search via subagent |
| osuRipple/lets | SQL query patterns in handlers | GitHub code search via subagent |
| osuRipple/pep.py | SQL query patterns in handlers | GitHub code search via subagent |

## Reference-Backed Evidence per Area

### 1. Identity and login

| Durable fact | bancho.py | titanic | Ripple (pep.py/lets) | Athena status |
|---|---|---|---|---|
| user id | `users.id` (int auto_increment) | `users.id` (serial) | `users.id` | Covered (`users.id`) |
| username / safe name | `users.name`, `users.safe_name` | `users.name`, `users.safe_name` | `users.username`, `users.username_safe` | Covered |
| password hash | `users.pw_bcrypt` (char 60) | `users.pw` (char 60, bcrypt) | `users.password_md5` (bcrypt v2 or md5+salt v1) | Covered (`users.password_hash`) |
| email | `users.email` | `users.email` | (separate table or users) | Covered |
| country | `users.country` (char 2) | `users.country` (varchar) | `users_stats.country` | Covered |
| activation state | `users.priv` bitfield includes PENDING_VERIFICATION | `users.activated` (boolean) | `users.privileges` includes PENDING_VERIFICATION | **Missing** |
| latest activity | `users.latest_activity` (unix timestamp) | `users.latest_activity` (timestamp) | `users.latest_activity` (unix timestamp) | **Missing** (durable, throttled write) |
| preferred mode | `users.preferred_mode` (int) | `users.preferred_mode` (int) | (not found in users table) | **Missing** |
| play style | `users.play_style` (int bitfield: mouse/tablet/keyboard/touch) | `users.playstyle` (int) | (not found) | **Missing** |
| supporter/donor end | `users.donor_end` (unix timestamp) | `users.supporter_end` (timestamp) | `users.donor_expire` (unix timestamp) | **Missing** |
| bot account flag | (not separate, uses priv bitfield) | `users.bot` (boolean) | (not found) | **Missing** |
| custom badge | `users.custom_badge_name`, `users.custom_badge_icon` | (profile_badges table) | `user_badges` + `badges` tables | **Missing** |
| clan | `users.clan_id`, `users.clan_priv` | (not found) | (not found) | **Missing** (not stable scope) |
| avatar hash | (not in users) | `users.avatar_hash`, `users.avatar_last_changed` | (not in DB, file-based) | **Missing** |

### 2. Permissions and moderation

| Durable fact | bancho.py | titanic | Ripple | Athena status |
|---|---|---|---|---|
| privilege bitfield | `users.priv` (int) | `groups` + `groups_entries` tables | `users.privileges` bitfield + `privileges_groups` | Covered (roles.permissions IntFlag) |
| silence end | `users.silence_end` (unix timestamp) | `users.silence_end` (timestamp) | `users.silence_end` (unix timestamp) | **Missing** |
| restricted/banned | `users.priv` bitfield | `users.restricted` (boolean) | `users.privileges` bitfield + `users.ban_datetime` | **Missing** |
| infringement logs | (not found in bancho.py schema) | `infringements` table (id, user_id, action, length, is_permanent, description) | (not found) | **Missing** |
| reports | (not found in bancho.py schema) | `reports` table (id, target_id, sender_id, reason, resolved) | `reports` table (from_uid, to_uid, reason, chatlog) | **Missing** |
| audit/admin logs | `logs` table (from, to, action, msg) | `logs` table (level, type, message) | (not found as table) | **Missing** |

### 3. Client integrity

| Durable fact | bancho.py | titanic | Ripple | Athena status |
|---|---|---|---|---|
| osu path hash | `client_hashes.osupath` (char 32, PK) | `clients.executable` (char 32, PK) | (not in hw_user) | **Missing** |
| network adapters hash | `client_hashes.adapters` (char 32, PK) | `clients.adapters` (char 32, PK) | `hw_user.mac` (MD5) | **Missing** |
| unique id | `client_hashes.uninstall_id` (char 32, PK) | `clients.unique_id` (char 32, PK) | `hw_user.unique_id` | **Missing** |
| disk serial hash | `client_hashes.disk_serial` (char 32, PK) | `clients.disk_signature` (char 32, PK) | `hw_user.disk_id` | **Missing** |
| occurrence count | `client_hashes.occurrences` (upsert +1) | (not found) | `hw_user.occurencies` (upsert +1) | **Missing** |
| latest time | `client_hashes.latest_time` (datetime) | (not found) | (not found) | **Missing** |
| verified hashes | (not found) | `clients_verified` (type, hash) | (not found) | **Missing** |
| banned flag | (not found) | `clients.banned` (boolean) | (not found) | **Missing** |
| login history | `ingame_logins` (userid, ip, osu_ver, osu_stream, datetime) | `logins` (user_id, time, ip, osu_version) | `ip_user` (userid, ip, occurencies) | **Missing** |

### 4. Social graph

| Durable fact | bancho.py | titanic | Ripple | Athena status |
|---|---|---|---|---|
| friends | `relationships` (user1, user2, type='friend') | `relationships` (user_id, target_id, status=0) | `users_relationships` (user1, user2) | Covered |
| blocks | `relationships` (user1, user2, type='block') | `relationships` (user_id, target_id, status=1) | (not found) | **Missing** |
| friend-only DM | (not in DB) | `users.friendonly_dms` (boolean) | (not found) | **Missing** |
| DM read status | (not found) | (not found) | (not found) | **Missing** (not confirmed in any reference) |
| mail/DM records | `mail` table (from_id, to_id, msg, time, read) | `direct_messages` (sender_id, target_id, message, time) | (not found as table) | Covered (private_messages table) |

### 5. Chat and channels

| Durable fact | bancho.py | titanic | Ripple | Athena status |
|---|---|---|---|---|
| channel definitions | `channels` (name, topic, read_priv, write_priv, auto_join) | `channels` (name, topic, read_permissions, write_permissions) | `bancho_channels` (name, description, public_read, public_write) | Covered |
| persisted messages | (not found as table) | `messages` (sender, target, message, time) | (not found as table) | Covered (channel_messages) |
| chat filters | (not found in schema) | `filters` (name, pattern, replacement, block, timeout_duration) | (not found) | **Missing** |

### 6. Beatmaps and beatmapsets

| Durable fact | bancho.py | titanic | Ripple | Athena status |
|---|---|---|---|---|
| beatmap id, set id, md5 | `maps.id`, `maps.set_id`, `maps.md5` | `beatmaps.id`, `beatmaps.set_id`, `beatmaps.md5` | `beatmaps.beatmap_id`, `beatmaps.beatmapset_id`, `beatmaps.beatmap_md5` | Covered |
| filename | `maps.filename` | `beatmaps.filename` | `beatmaps.file_name` | **Missing** on beatmap model (only on file_attachment) |
| play/pass counts | `maps.plays`, `maps.passes` | `beatmaps.playcount`, `beatmaps.passcount` | `beatmaps.playcount`, `beatmaps.passcount` | **Missing** |
| favourites | `favourites` (userid, setid, created_at) | `favourites` (user_id, set_id, created_at) | (not found in lets) | **Missing** |
| ratings | `ratings` (userid, map_md5, rating) | `ratings` (user_id, set_id, map_checksum, rating) | `beatmaps_rating` (beatmap_md5, user_id, rating) | **Missing** |
| osz filesize | (not in maps) | `beatmapsets.osz_filesize`, `beatmapsets.osz_filesize_novideo` | (not found) | **Missing** |

### 7. Scores and leaderboard

| Durable fact | bancho.py | titanic | Ripple | Athena status |
|---|---|---|---|---|
| score row | `scores` (full row with mode encoding 0-8 for vn/rx/ap) | `scores` (full row, separate mode/status) | `scores` (full row, is_relax flag) | Covered |
| fail time | (not found in scores) | `scores.failtime` (int nullable) | (not found) | **Missing** |
| replay md5 | (not in scores, online_checksum only) | `scores.replay_md5` (char 32 nullable) | (not found) | **Missing** (Athena uses sha256 on replay) |
| client flags | `scores.client_flags` (int, anticheat) | (not found in scores) | (not found) | **Missing** |
| time elapsed | `scores.time_elapsed` (int, milliseconds) | (not found) | `scores.playtime` (seconds) | **Missing** |
| online checksum | `scores.online_checksum` (char 32) | `scores.score_checksum` (char 32) | (not found as column) | Covered |
| replay views | (in stats table) | `scores.replay_views` (int) | (not found on scores) | **Missing** on score (exists on stats in bancho.py) |
| score status | `scores.status` (SubmissionStatus enum) | `scores.status` (smallint) | `scores.completed` (0-3 enum) | Covered (leaderboard_eligible) |

### 8. User stats (split from rankings)

| Durable fact | bancho.py | titanic | Ripple | Athena status |
|---|---|---|---|---|
| total/ranked score | `stats.tscore`, `stats.rscore` | `stats.tscore`, `stats.rscore` | `users_stats.total_score_{mode}`, `users_stats.ranked_score_{mode}` | **Missing** |
| pp | `stats.pp` | `stats.pp` | `users_stats.pp_{mode}` | **Missing** |
| accuracy | `stats.acc` | `stats.acc` | `users_stats.avg_accuracy_{mode}` | **Missing** |
| play count | `stats.plays` | `stats.playcount` | `users_stats.playcount_{mode}` | **Missing** |
| playtime | `stats.playtime` | `stats.playtime` | `users_stats.playtime_{mode}` | **Missing** |
| max combo | `stats.max_combo` | `stats.max_combo` | (not found) | **Missing** |
| total hits | `stats.total_hits` | `stats.total_hits` | `users_stats.total_hits_{mode}` | **Missing** |
| grade counts | `stats.xh_count/x_count/sh_count/s_count/a_count` | Same + `b_count/c_count/d_count` | (not found) | **Missing** |
| replay views | `stats.replay_views` | `stats.replay_views` | `users_stats.replays_watched_{mode}` | **Missing** |

### 9. User rankings (split from stats)

| Durable fact | bancho.py | titanic | Ripple | Athena status |
|---|---|---|---|---|
| global/country rank | Derived from Redis ZSETs at runtime, not in DB | `stats.rank` (int), `stats.peak_rank` | Derived from Redis ZSETs at runtime | **Missing** |
| rank history | (not found in DB) | `profile_rank_history` (user_id, time, mode, global_rank, country_rank, score_rank) | (not in DB) | **Missing** |

Note: bancho.py and Ripple derive ranks from Redis sorted sets at runtime, not from persistent tables. Only titanic persists rank history in `profile_rank_history`.

### 10. Replays and media metadata

| Durable fact | bancho.py | titanic | Ripple | Athena status |
|---|---|---|---|---|
| replay storage | File-based (.osr files stored on disk/S3) | File-based | File-based, S3 with `s3_replay_buckets` table | Covered (replay_file_attachments + blobs) |
| replay view counts | `stats.replay_views` (per-user aggregate) | `scores.replay_views` (per-score) | `users_stats.replays_watched_{mode}` | **Missing** |
| screenshot metadata | (not in DB, file-based) | `screenshots` (id, user_id, created_at, hidden) | (not in DB, random filenames) | **Missing** |
| avatar metadata | (not in DB) | `users.avatar_hash`, `users.avatar_last_changed` | (not in DB) | **Missing** |

### 11. Static/media delivery

No reference implementation stores delivery routing in the database. All use filesystem paths, hardcoded URLs, or external CDN configuration.

- bancho.py: file-based serving, no DB routing
- titanic: `resource_mirrors` table (url, type, server, priority) + `beatmapsets.download_server` (smallint)
- Ripple: external Cheesegull/mirror API, no DB routing

### 12. Release/update files

- bancho.py: no release/update tables
- titanic: `releases` table (name PK, version, description, known_bugs, supported, recommended, preview, downloads varchar[], hashes jsonb, screenshots varchar[], actions jsonb, created_at)
- Ripple: no release/update tables

### 13. Ratings/comments/favourites

| Durable fact | bancho.py | titanic | Ripple | Athena status |
|---|---|---|---|---|
| ratings | `ratings` (userid, map_md5, rating tinyint) | `ratings` (user_id, set_id, map_checksum, rating) | `beatmaps_rating` (beatmap_md5, user_id, rating) | **Missing** |
| comments target types | `comments.target_type` enum: 'replay', 'map', 'song' | `comments.target_type` varchar(6) | `comments`: nullable beatmap_id/beatmapset_id/score_id columns | **Missing** |
| favourites | `favourites` (userid, setid, created_at) | `favourites` (user_id, set_id, created_at) | (not found in lets) | **Missing** |

**Important finding**: Comments have multiple target types in all reference implementations. bancho.py uses enum 'replay', 'map', 'song'. Ripple uses separate nullable FK columns (beatmap_id, beatmapset_id, score_id). This means the stable `/web/osu-comment.php` `target` parameter does support replay/map/song targets, not just beatmaps. Owner assignment may need revision from `beatmaps` to an independent aggregate.

### 14. Achievements and notifications

| Durable fact | bancho.py | titanic | Ripple | Athena status |
|---|---|---|---|---|
| achievement definitions | `achievements` (id, file, name, desc, cond as Python lambda) | (not a separate table, stored as user achievements) | (not found as definitions table) | **Missing** |
| achievement unlocks | `user_achievements` (userid, achid) | `achievements` (user_id, name, category, filename, unlocked_at) | `users_achievements` (user_id, achievement_id, time) | **Missing** |
| badges | `users.custom_badge_name/icon` (2 columns on user) | `profile_badges` (id, user_id, badge_icon, badge_description, badge_url) | `badges` (id, name) + `user_badges` (user, badge) | **Missing** |
| notifications | (not found) | `notifications` (id, user_id, type, header, content, link, read, time) | (not found) | **Missing** |

### 15. Multiplayer and tournaments

| Durable fact | bancho.py | titanic | Ripple | Athena status |
|---|---|---|---|---|
| match records | **Not persisted** (entirely in-memory `app/objects/match.py`) | `mp_matches` (id, bancho_id, name, creator_id, created_at, ended_at) | (not found as table) | **Missing** |
| match events | (not persisted) | `mp_events` (match_id, time, type, data jsonb) | (not found) | **Missing** |
| tournament pools | `tourney_pools` (id, name, created_at, created_by) | (not found) | (not found) | **Missing** |
| tournament pool maps | `tourney_pool_maps` (map_id, pool_id, mods, slot) | (not found) | (not found) | **Missing** |

Note: bancho.py does NOT persist multiplayer match state. Only tournament pool definitions are durable.

## Key Findings from Reference Audit

1. **Comments target type is NOT beatmap-only**: All 3 references support replay/map/song (or equivalent) targets. Previous assignment to `beatmaps` domain needs correction.

2. **User stats are stored per-mode**: bancho.py uses composite PK (id, mode), Ripple uses suffix columns per mode, titanic uses composite PK. Athena has no stats table yet.

3. **Rankings are mostly runtime-derived**: bancho.py and Ripple use Redis ZSETs for rank. Only titanic persists rank history in `profile_rank_history`.

4. **Multiplayer is NOT persisted in bancho.py**: Entirely in-memory. Only titanic persists match records and events.

5. **Client integrity uses composite PK**: All references use (user_id + hash fields) as composite key with upsert occurrence counting.

6. **Screenshot metadata**: Only titanic has a `screenshots` table. bancho.py and Ripple use file-based storage with no DB metadata.

7. **Release files**: Only titanic has a `releases` table. bancho.py and Ripple have no release/update persistence.

8. **Replay view counts**: bancho.py tracks on stats (per-user aggregate), titanic tracks on scores (per-score). Different granularity.

9. **Score `fail_time`/`time_elapsed`**: bancho.py has `time_elapsed` (ms), titanic has `failtime` (nullable int). Ripple has `playtime` (seconds). Athena is missing all three.

10. **Client anticheat flags**: bancho.py stores `client_flags` on scores. Not found in titanic or Ripple scores tables.
