# Brief: user-stats

## Problem

Stable client player はログイン直後のメニュー右上、オンラインユーザー一覧、`STATS_REQUEST` 応答で自分や他ユーザーの現在 stats を見たい。Athena は score と performance calculation を保存できるが、stable `USER_STATS` に必要な current projection がまだなく、PP、Accuracy、Lv、Global Rank、play count、score 系がゲーム内に出せない。

また、play time 系の集計は score submit 時の `ft` (fail time milliseconds) や譜面長など submit 時点の情報を失うと後から正確に復元しづらい。UserStats projection を作る前に、score ingestion 側で timing 情報を保存できる状態にする必要がある。

## Current State

- `score-ingestion` は Stable `/web/osu-submit-modular-selector.php` から score を受け付け、passed / failed score を保存する。
- `score-ingestion` requirements には failed play の `x` と `ft` を保存する要件があるが、現状の実装では `fail_time_ms` が永続化されていない。
- `score-pp-calculation` は current Performance Calculation を PP の source of truth として所有し、leaderboard / stats は必要に応じて current PP を read optimization として参照できる。
- `presence-stats-struct-fixtures` は stable `USER_STATS` wire format の fixtures / struct coverage を進めているが、実データ projection は別責務。
- `user-stats` spec directory はまだ存在せず、roadmap だけが Wave 3 の feature として `user-stats` を示している。

## Desired Outcome

Stable client login と stats request 時に、Athena が current user stats を返せる。初期対象は in-game 表示に必要な current value であり、Web 用の長期 snapshot / rank history graph は後続 scope に残す。

具体的には、ユーザーごとに以下を取得できる。

- PP: Best Performance 上位を official-like weight (`0.95 ** index`) で合算し、bonus PP は明示された policy に従う。
- Accuracy: eligible score / best score policy に基づく current accuracy。
- Lv: `total_score` から stable 互換の level calculation で算出する。
- Global Rank: current PP ranking に基づく rank。
- Play Count / Ranked Score / Total Score: score persistence から集計する。
- Play Time: score submit 時の timing 情報から nullable な `play_time_seconds` を蓄積できる。

## Approach

Chosen approach: prerequisite timing persistence plus current stats projection.

まず既存 `score-ingestion` の延長として `scores` に `fail_time_ms`、`play_time_seconds`、必要なら `play_time_source` を保存する。次に `user-stats` spec で command / query 境界を分け、score / performance を source of truth として current stats projection を構築する。

この順序により、UserStats は後から復元できない submit-time 情報を失わずに済む一方、rank history や Web graph snapshot のような別の時間軸 projection は後続 `user-ranking` に委譲できる。

## Scope

- **In**:
  - Score timing persistence prerequisite: `fail_time_ms`, nullable `play_time_seconds`, optional source enum/string.
  - Current user stats read model / query use-case.
  - Stable `USER_STATS` へ必要な current fields の mapping。
  - Login flow と `STATS_REQUEST` 系 flow から current stats を取得する統合。
  - Weighted PP calculation using current Performance Calculation rows for eligible best scores.
  - `total_score` based level calculation.
  - Current global rank calculation or projection for in-game display.
  - Tests for projection policy, repository contracts, SQLAlchemy adapters, memory adapters, and stable login/request integration.
- **Out**:
  - 89-day daily rank graph / Web 用 snapshot。
  - country rank and country history unless already trivial from current projection.
  - Beatmap leaderboard rows and personal best ownership changes.
  - PP calculation formula execution itself, owned by `score-pp-calculation`.
  - Replay parsing and anti-cheat validation.
  - Relax / Autopilot stats.
  - Public Web API / Lazer API response surfaces.

## Boundary Candidates

- Score timing persistence: score-ingestion command persistence owns submit-time timing data on Score.
- User stats projection: query-side read model owns current aggregate values from score and performance source data.
- Stable stats adapter: stable bancho transport maps current stats into `USER_STATS` packet fields.
- Ranking policy: current global rank ordering belongs with user stats / ranking read model, while time-series rank snapshots belong to later `user-ranking`.

## Out of Boundary

- Rank history snapshots are not part of the first in-game UserStats slice.
- Web UI graphing and TimescaleDB-style time-series optimization are not part of this spec.
- Performance calculation recalculation and formula profile migration remain in `score-pp-calculation`.
- Beatmap leaderboard projection remains in `beatmap-leaderboards`.

## Upstream / Downstream

- **Upstream**:
  - `score-ingestion`: Score source data, failed play records, submit-time timing persistence.
  - `score-pp-calculation`: current PP / star rating and provenance.
  - stable protocol struct work: `USER_STATS` packet shape.
- **Downstream**:
  - stable login and stats request flows.
  - `user-ranking`: daily snapshots and historical rank graph.
  - future Web App profile / user list surfaces.

## Existing Spec Touchpoints

- **Extends**:
  - `score-ingestion`: implement or finish persistence for `x` / `ft`, and add nullable play time fields needed by stats.
  - `score-pp-calculation`: read current Performance Calculation as PP source of truth, without mutating performance state.
- **Adjacent**:
  - `presence-stats-struct-fixtures`: packet shape / fixtures only, not stats projection ownership.
  - `beatmap-leaderboards`: per-beatmap ranking remains separate.
  - `user-ranking`: historical rank snapshots remain separate.

## Constraints

- Python domain models use standard `@dataclass(slots=True)`; no Pydantic in domain code.
- Command-side persistence goes through Unit of Work and command repository interfaces.
- Query-side stats reads use query repositories and do not mutate durable state.
- Transport adapters stay thin and must not import SQLAlchemy models or raw DB sessions.
- Production persistence target is PostgreSQL + asyncpg with Alembic migrations.
- Stable compatibility behavior must be backed by existing protocol evidence or focused tests before changing packet response shapes.
- Initial implementation should prioritize in-game current stats over Web history features.
