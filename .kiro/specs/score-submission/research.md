# Research & Design Decisions

## Summary
- **Feature**: `score-submission`
- **Discovery Scope**: Complex Integration
- **Key Findings**:
  - stable modular submit は duplicate `score` part を使い、1 つ目が暗号化 score payload、2 つ目が replay binary として扱われる実装が Akatsuki、Ripple、Titanic で一致している。
  - score 保存、PP 計算、leaderboard、user stats は強く結合しているが、Athena では transport、service、worker、repository、projection formatter を分けると既存の layered architecture に収まる。
  - Ranked/Approved は ranked PP と stats、Loved は leaderboard-only、failed play は scores に保存しつつ PP/best/leaderboard から除外する設計が互換実装と要件の両方に合う。

## Research Log

### Athena 既存構成と統合点
- **Context**: score submission は web legacy endpoint、beatmap mirror、blob storage、worker、getscores、bancho user stats にまたがる。
- **Sources Consulted**:
  - `src/osu_server/services/legacy_getscores_service.py`
  - `src/osu_server/transports/web_legacy/getscores.py`
  - `src/osu_server/services/beatmap_mirror_service.py`
  - `src/osu_server/jobs/beatmap_fetch.py`
  - `src/osu_server/services/blob_storage_service.py`
  - `src/osu_server/transports/bancho/protocol/s2c/login.py`
  - `src/osu_server/transports/bancho/protocol/types.py`
- **Findings**:
  - getscores は header-only で score count `0` を返す段階で、score row provider は未実装。
  - beatmap mirror は `BeatmapResolveOptions(require_osu_file=True/False)` と file fetch job を既に持つ。
  - Blob storage service は replay binary と `.osu` file body の保存先として再利用できる。
  - user stats packet は `ranked_score`、`accuracy`、`play_count`、`total_score`、`rank`、`pp` を wire format として持つ。
- **Implications**:
  - score-submission は beatmap mirror を拡張せず、`.osu` prefetch と submit fallback の呼び出し側になる。
  - replay body は score domain の attachment metadata を持ち、実 body は blob storage に置く。
  - getscores は既存 parser/header formatter を保ち、score row provider と personal best provider を追加する。

### stable modular request decoding
- **Context**: user が提示した request shape には duplicate `score`、`s`、`fs`、`iv`、`token`、`pass`、`osuver` など長い opaque/binary-like field が含まれる。
- **Sources Consulted**:
  - `/tmp/athena-research-bancho-py/app/api/domains/osu.py`
  - `/tmp/athena-research-bancho-py/app/objects/score.py`
  - `/tmp/athena-research-lets/handlers/submitModularHandler.pyx`
  - `/tmp/athena-research-deck/app/routes/web/scoring.py`
  - `/tmp/athena-research-deck/app/helpers/score.py`
- **Findings**:
  - Akatsuki、Ripple、Titanic は `/web/osu-submit-modular-selector.php` を primary endpoint として扱う。
  - duplicate `score` part は互換上重要で、score payload と replay payload を part order で区別する。
  - AES key は `osuver` ありなら `osu!-scoreburgr---------{osuver}`、なければ旧 key というパターンが複数実装で確認できる。
  - decrypted score payload は beatmap checksum、username、score checksum、hit counts、score、max combo、perfect、grade、mods、passed、mode、client version/client flags を含む colon-separated data として扱われる。
- **Implications**:
  - parser は Starlette form data を raw field list として受け、duplicate field を失わない実装にする。
  - `pass` は password-md5 credential として使うが raw persistence/logging は禁止する。
  - `token` は audit hash 以上の扱いに留め、authorization の単独根拠にしない。

#### stable modular form field evidence

| Field | Observed / referenced behavior | Evidence | Athena decision |
|-------|--------------------------------|----------|-----------------|
| `score` duplicate | modular endpoint can carry two `score` parts: first base64 encrypted score payload, second replay upload | Akatsuki/bancho.py `parse_form_data_score_params()` requires exactly two `score` parts; Deck/Titanic uses `form.getlist('score')`, first item as score string and last item as replay upload | preserve order and require score payload plus replay part for normal stable modular submissions |
| `iv` | required for decrypting encrypted score payload and encrypted client fields | Akatsuki form parameter `iv_b64`; lets requires `score`, `iv`, `pass`; Deck/Titanic decrypts when `iv` is present | required for encrypted modular score parsing |
| `osuver` | changes AES key to `osu!-scoreburgr---------{osuver}` | lets and Deck/Titanic switch key when present; Akatsuki requires `osuver` on modular selector | use `osuver` key when present; preserve legacy key path only for compatibility evidence and tests |
| `pass` | password-md5 credential | Akatsuki `pw_md5`; lets `password`; Deck/Titanic form/query `pass` | use only for credential check; never persist or log raw |
| `x` | exited/quit signal | Akatsuki `exited_out`; lets `quit_`; Deck/Titanic `exited` | store pass/fail context and use with `ft` for failed/exited behavior |
| `ft` | fail time in milliseconds | Akatsuki `fail_time`; lets `failTime`; Deck/Titanic `failtime` | parse as bounded integer and preserve for failed play/playtime policy |
| `fs` | encrypted visual settings / fun spoiler-like payload | Akatsuki `visual_settings_b64`; Deck/Titanic `fun_spoiler` and decrypts it with score key | decrypt when applicable, retain only per redaction/audit policy |
| `s` | encrypted client hash / anti-cheat client signal | Akatsuki `client_hash_b64`; Deck/Titanic `client_hash`; lets uses decrypted score plus client checks elsewhere | decrypt and compare to session material when available; otherwise diagnostic only |
| `bmk` | updated beatmap hash / notepad-hack signal | Akatsuki `updated_beatmap_hash`; lets checks `bmk` with `bml`; user sample includes `bmk` | preserve/hash for audit and future validation; do not make MVP depend on it |
| `sbk` | storyboard md5 | Akatsuki optional `storyboard_md5`; user sample includes `sbk` | preserve/hash or ignore according to raw field policy |
| `c1` | unique client ids / client identity signal | Akatsuki `unique_ids`; user sample contains two-part value separated by `|` | preserve redacted/hash form and compare only when session material exists |
| `st` | score time / timestamp-like submit signal | Akatsuki `score_time`; user sample includes numeric string | parse/preserve as client signal, not authoritative server submit time |
| `i` | Flashlight screenshot / cheat screenshot | Akatsuki optional file `fl_cheat_screenshot`; Deck/Titanic optional `flashlight_screenshot` | accept as optional opaque binary with safety limits; anti-cheat handling out-of-scope |
| `token` | present in observed request; Akatsuki models token as a header with unresolved handling notes, not a stable authorization source | user sample has long token field; Akatsuki comment asks whether token should be allowed; no consulted implementation treats it as sufficient login by itself | accept only as opaque/audit hash if present; token alone never authorizes |

Score payload after AES decrypt is still treated as colon-separated data. Deck/Titanic parses fields as map checksum, username, score checksum, `300/100/50/geki/katu/miss`, score, max combo, perfect, grade, mods, passed, mode, and optional version/flags. Akatsuki parses the first two fields separately, then builds `Score.from_submission(score_data[2:])`.

### authorization と replay/anti-cheat 境界
- **Context**: forged submit を防ぐには credential だけでなく active session と payload identity の照合が必要。
- **Sources Consulted**:
  - Akatsuki `submit_modular_selector` implementation
  - Ripple submit handler
  - Titanic scoring route
- **Findings**:
  - Akatsuki は password-md5 login、active session、client hash、client unique id、online checksum を複合的に検証する。
  - Ripple は session absence を retryable response にする分岐を持つが、authorization の strictness は実装差がある。
  - replay frame validation や anti-cheat 判定は各実装で重い独自処理があり、今回の scope から外すのが妥当。
- **Implications**:
  - Athena MVP は password-md5、active bancho session、decrypted username/user id consistency を P0 とする。
  - client detail comparison は session に material がある場合だけ strict に適用し、material がない場合は diagnostic に残して MVP を止めない。
  - replay validation は size/type/basic persistence までとし、anti-cheat spec に分離する。

### score schema、failed play、Loved/Qualified behavior
- **Context**: scores に何を保存し、どの projection へ反映するかを決める必要がある。
- **Sources Consulted**:
  - `/tmp/athena-research-bancho-py/app/repositories/scores.py`
  - `/tmp/athena-research-bancho-py/migrations/base.sql`
  - `/tmp/athena-research-ripple/migrations/0.php`
  - `/tmp/athena-research-ripple/osu.ppy.sh/web/osu-submit-modular.php`
  - `/tmp/athena-research-lets/objects/score.pyx`
  - `/tmp/athena-research-peace/core/db/src/peace/migration/versions/init_tables.rs`
  - `/tmp/athena-research-peace/core/db/src/peace/entity/scores_standard.rs`
  - `/tmp/athena-research-peace/core/db/src/peace/entity/leaderboard_standard.rs`
  - `/tmp/athena-research-peace/core/db/src/peace/entity/user_stats_standard.rs`
- **Findings**:
  - Akatsuki は score status として failed/submitted/best を持ち、failed play も score record として保存する。
  - Akatsuki/bancho.py は単一 `scores` table に `mode` column を持ち、`stats` は `(id, mode)` primary key で vanilla/RX/AP を含む mode axis を表現している。
  - 初期 osuripple/ripple は単一 `scores` table に `play_mode` を持つ一方、global leaderboard は `leaderboard_std`、`leaderboard_taiko`、`leaderboard_ctb`、`leaderboard_mania` に物理分割し、`users_stats` は mode ごとの column 群を持つ。
  - osuRipple/lets は単一 `scores` table に `play_mode` と relax flag を持ち、scoreboard query と user stats/cache でも game mode と relax axis を条件にしている。
  - Loved は vanilla stable では PP ではなく score metric の leaderboard として扱われ、ranked PP は awarded されない。
  - Pure-Peace/peace は mode/playstyle ごとに scores、PP、leaderboard、user_stats table を物理分割している。
  - peace の score schema は score md5、map md5、score version、score、accuracy、combo、mods、hit counts、playtime、perfect、status、grade、client flags、client version、verified/invisible を含む。
- **Implications**:
  - Athena は Akatsuki/bancho.py、初期 osuripple/ripple、osuRipple/lets に近い単一 `scores` table + axis column を採用し、Pure-Peace/peace の scores 物理分割は採用しない。
  - leaderboard/user stats は初期 Ripple や peace の物理分割も参考になるが、Athena では projection table に axis column を持たせて repository contract を単純化する。
  - `ruleset`、`playstyle`、`category` axis を明示的に分けることで、bancho.py の packed mode number より repository query と将来拡張を読みやすくする。
  - failed play は `scores` に保存し、replay がある場合は attachment を保存するが、PP/best/leaderboard/rank projection から除外する。
  - Qualified は leaderboard-only、no ranked PP として明示する。Pending/WIP/Graveyard/NotSubmitted/Unknown は authenticated gameplay record として保存可能だが leaderboard/ranked stats には出さない。
  - exited/failed play の playtime は `ft` を milliseconds として受け取り、seconds に変換して activity stats に使う。`x` は exit/quit classification であり、時間値そのものではない。
  - lets は `quit_ or failed` の場合に `failTime // 1000` を playTime に入れ、Deck/Titanic は passed でなければ `failtime // 1000` を elapsed time にし、Akatsuki/bancho.py は failed の `time_elapsed` に `fail_time` を使って stats.playtime に反映する。
  - `ft` は音源開始基準の可能性があるため、譜面長に対して明らかに大きい値は sanity limit で丸めるか reliable duration として扱わない。

### submit response と getscores rows
- **Context**: stable client に返す response は retry behavior と song select 表示に影響する。
- **Sources Consulted**:
  - Titanic scoring route response construction
  - Ripple `getScoresHandler.pyx`
  - Akatsuki score/getscore behavior
- **Findings**:
  - completed response は chart text を `|` と newline で構成し、beatmap chart と overall chart を返す実装がある。
  - Ripple score row は `scoreID|playerName|score_or_pp|maxCombo|c50|c100|c300|cMiss|cKatu|cGeki|fullCombo|mods|playerUserID|rank|date|1` のような stable row shape を使う。
  - leaderboard row ordering は score descending が stable-compatible default として妥当。
  - PP display は実装差があり、stable response format 上安全に出せる場合に限定するのがよい。
- **Implications**:
  - response formatter は completed、accepted-pending、retryable、terminal reject を明示的な result kind から生成する。
  - getscores score row provider は score descending を default とし、PP は field compatibility が fixture で確認できる場合のみ表示する。

### PP calculation dependency
- **Context**: PP と star rating は既存実装では未導入で、外部 calculator の選定が必要。
- **Sources Consulted**:
  - `/tmp/athena-research-rosu-pp-py/README.md`
  - `/tmp/athena-research-rosu-pp-py/pyproject.toml`
  - `/tmp/athena-research-rosu-pp-py/rosu_pp_py.pyi`
  - Titanic `requirements.txt`
- **Findings**:
  - `rosu-pp-py` は Python `>=3.11` 対応で、Athena の Python 3.14 target と合う。
  - Titanic は `rosu-pp-py==4.0.2` を使っている。
  - API は `rosu.Beatmap(path=...)` または bytes/content と `rosu.Performance(..., lazer=False).calculate(beatmap)` を提供する。
  - `Beatmap.is_suspicious()` があり、重い/不正な譜面ファイルへの防御に使える。
- **Implications**:
  - Athena は `rosu-pp-py` を採用候補とし、worker 側 `PerformanceService` に閉じ込める。
  - `importlib.metadata.version("rosu-pp-py")` を provenance に保存する。
  - stable score は `lazer=False` で計算し、`.osu` attachment id と formula profile を保存する。

### async processing と idempotency
- **Context**: submit response は短時間で返す必要がある一方、PP 計算と projection 更新は重い。
- **Sources Consulted**:
  - Athena `src/osu_server/jobs/beatmap_fetch.py`
  - Athena `src/osu_server/worker.py`
  - Ripple retryable handling
  - Akatsuki duplicate checksum lock
- **Findings**:
  - Athena には taskiq worker と idempotent beatmap fetch job pattern がある。
  - stable client は submission failure 後に retry する可能性があり、raw body ではなく canonical gameplay fingerprint で dedupe する必要がある。
  - Akatsuki/Ripple は checksum/lock を使って duplicate score を避ける。
- **Implications**:
  - app process は parse/auth/store/replay/enqueue までを行い、bounded wait 内に worker completion を観測できたら completed response を返す。
  - `score_submissions` は canonical fingerprint、processing state、result snapshot を持つ。
  - duplicate completed は snapshot から response を再生成し、duplicate pending は pending/retryable response を返す。

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Transport-heavy synchronous submit | endpoint 内で parse、PP、stats、leaderboard まで完了する | 実装ファイル数が少ない | response timeout、transaction肥大化、retry duplicate、layer violation のリスクが高い | 不採用 |
| Service + worker pipeline | app は保存と enqueue、worker が PP/projection、repository が finalization を担当 | bounded response、retry安全、既存 taskiq pattern と一致 | pending response と result snapshot が必要 | 採用 |
| table per ruleset/playstyle | Pure-Peace/peace のように mode ごとに scores/PP/leaderboard/stats を分割 | hot path index が単純 | Alembic/Repository が増殖し、RX/AP 予約軸の追加が重い | 不採用 |
| split projections only | 初期 osuripple/ripple のように scores は単一、leaderboard や user stats は mode ごとに物理分割する | leaderboard query が単純 | stats column/table が増え、category と playstyle 追加時の migration が重い | 不採用 |
| unified score and projection tables with axes | Akatsuki/bancho.py、初期 osuripple/ripple、osuRipple/lets の単一 scores 方針に近く、projection も `ruleset`、`playstyle`、`category` column で統一する | Athena の repository pattern と再計算に合い、物理 table の増殖を避ける | index 設計が重要 | 採用 |

## Design Decisions

### Decision: global/country user rank は materialized snapshot として最初から持つ
- **Context**: stable `user_stats` packet に rank が必要であり、Web ランキングも初期から必須である。
- **Alternatives Considered**:
  1. rank を毎回 `COUNT(*) + 1` で計算する。
  2. score submit ごとに下位 user の rank を逐次更新する。
  3. `user_stats` を canonical source とし、window function で `user_rank_projections` を bulk rebuild する。
- **Selected Approach**: `user_rank_projections` を score-submission の owned projection として作り、worker が window function で global/country rank snapshot を rebuild する。projection が存在しない、または stale な場合のみ `COUNT(*) + 1` fallback を許可する。
- **Rationale**: Web ranking と stable login packet の read path を軽くでき、submit ごとの大量 UPDATE を避けられる。
- **Trade-offs**: rank は snapshot なので数分程度の遅延を許容する必要がある。rebuild job と staleness diagnostics が必要。
- **Scope Note**: ここでいう mods 別 global rank は score mod combination 別ではなく、Ripple/Akatsuki 系の `mod_mode` に相当する `playstyle` 別 rank、つまり vanilla/RX/AP rank を指す。
- **Follow-up**: Web ranking API/UI spec は `user_rank_projections` を canonical read model として参照する。RX/AP の score 受付、検出、stats 更新は `relax-autopilot-scoring` 側で実装し、この spec は schema axis と projection contract を予約する。

### Decision: duplicate `score` part を order-aware に扱う
- **Context**: user 提示 request と複数実装で duplicate `score` が確認された。
- **Alternatives Considered**:
  1. Starlette form の最後の `score` だけ読む。
  2. duplicate part を preserving parser で受け、1 つ目を encrypted score payload、2 つ目を replay とする。
- **Selected Approach**: order-aware parser を transport 層に置く。
- **Rationale**: stable modular submit 互換に必要で、binary replay を text field と混同しない。
- **Trade-offs**: parser test fixture が必要。
- **Follow-up**: captured-compatible multipart fixture で part order と missing part behavior を検証する。

### Decision: score effect は category rules で一元化する
- **Context**: Ranked、Loved、Qualified、failed、future RX/AP で projection 先が変わる。
- **Alternatives Considered**:
  1. beatmap mirror の eligibility を直接 score effects に使う。
  2. score submission 側で `ScoreEffectPolicy` を定義し、beatmap effective status と pass/fail から effects を決める。
- **Selected Approach**: `ScoreEffectPolicy` を service/domain に置く。
- **Rationale**: Loved は leaderboard-only とする今回の要件が、既存 beatmap mirror の Loved PP eligibility と完全には一致しない。
- **Trade-offs**: status rule の revalidation point が増える。
- **Follow-up**: beatmap mirror の eligibility 変更時に score-submission design を再確認する。

### Decision: PP 計算は worker に閉じ込め `rosu-pp-py` を採用候補にする
- **Context**: score submit response budget と `.osu` file availability の不確実性がある。
- **Alternatives Considered**:
  1. app process で同期計算する。
  2. worker process で計算し、bounded wait で completion を待つ。
- **Selected Approach**: worker `PerformanceService` が `rosu-pp-py` を使う。
- **Rationale**: 重い処理を app から外し、pending/retryable response と再計算を可能にする。
- **Trade-offs**: result snapshot と processing state が必要。
- **Follow-up**: dependency pin と wheel availability を implementation task で確認する。

### Decision: `.osu` file 不足は三段構えで防ぐ
- **Context**: score submit 時点で `.osu` がないと PP が計算できない。
- **Alternatives Considered**:
  1. submit 時だけ fetch する。
  2. getscores、STATUS_CHANGE、submit fallback で prefetch/require を組み合わせる。
- **Selected Approach**: getscores non-blocking prefetch、STATUS_CHANGE prefetch、submit fallback bounded wait。
- **Rationale**: user と合意した architecture で、play 前から file fetch を進められる。
- **Trade-offs**: STATUS_CHANGE は presence-status 本体を所有しない最小 hook に限定する必要がある。
- **Follow-up**: presence-status spec が導入されたら hook boundary を再検証する。

## Risks & Mitigations
- stable response format の細部差異 — formatter fixture を implementation completion gate に含め、PP display は安全確認できるまで内部保存に限定する。
- raw credential/opaque field leak — parser 直後に redaction policy を適用し、raw `pass` と raw token を永続化しない。
- PP 計算 dependency の build/availability — worker-only dependency とし、PP failure は score 保存を壊さず recalculation state に残す。
- leaderboard/user stats projection drift — worker finalization を短い transaction に閉じ、projection rebuild repository method を持つ。
- beatmap status change 後の current projection inconsistency — submission-time status は score に保存し、current projections は effective status から rebuild 可能にする。

## References
- `Akatsuki/bancho.py` local clone: `/tmp/athena-research-bancho-py`
- `osuripple/ripple` local clone: `/tmp/athena-research-ripple`
- `osuRipple/lets` local clone: `/tmp/athena-research-lets`
- `osuTitanic/deck` local clone: `/tmp/athena-research-deck`
- `Pure-Peace/peace` local clone: `/tmp/athena-research-peace`
- `rosu-pp-py` local clone: `/tmp/athena-research-rosu-pp-py`
- Athena steering: `.kiro/steering/tech.md`, `.kiro/steering/roadmap.md`
