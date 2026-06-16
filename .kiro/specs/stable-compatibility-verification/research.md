# Research & Design Decisions

## Summary

- **Feature**: `stable-compatibility-verification`
- **Discovery Scope**: Extension
- **Key Findings**:
  - Stable Surface は既に host-based routing と stable transport packages に集約されているため、検証機能は runtime handler を変更せず外側から観測する設計にできる。
  - getscores は既存 fixture と formatter/parser tests がある一方、score row / personal best は未整備であり、この spec では known gap として表現する必要がある。
  - Lekuruu/osu.py は getscores / leaderboard 用の任意 probe には使えるが、Athena の必須依存にせず、利用不可時は optional evidence として skip / unavailable にする。

## Research Log

### 既存 Stable Surface と routing

- **Context**: Requirements 1, 4, 5, 6, 7 の対象 surface と接続先を確認するため。
- **Sources Consulted**:
  - `src/osu_server/composition/application.py`
  - `src/osu_server/transports/stable/bancho/*`
  - `src/osu_server/transports/stable/web_legacy/*`
- **Findings**:
  - bancho は `c.$DOMAIN`, `c<int>.$DOMAIN`, `ce.$DOMAIN` の Host route で `POST /` を受ける。
  - web legacy は `osu.$DOMAIN` の Host route で `/users`, `/web/bancho_connect.php`, `/web/osu-osz2-getscores.php`, `/web/osu-submit-modular-selector.php` を受ける。
  - path fallback は registration のみで、getscores と score submit は stable Host identity が必要になる。
- **Implications**:
  - `--base-url` は実接続先、`domain` は Host identity として分ける必要がある。
  - verification client は URL と `Host` header を別々に扱う。

### Score Submit response contract

- **Context**: Requirements 4.1-4.5 の field coverage と既存実装の境界を確認するため。
- **Sources Consulted**:
  - `src/osu_server/transports/stable/web_legacy/mappers/score_submit.py`
  - `src/osu_server/transports/stable/web_legacy/score_submit.py`
  - `tests/unit/transports/web_legacy/test_score_submit_mapper.py`
  - `tests/integration/transports/web_legacy/test_score_submit_e2e.py`
- **Findings**:
  - `StableScoreSubmitMapper` は multipart request を command input に写し、completed outcome を pipe-delimited chart response に変換する。
  - response は beatmap metadata line、Beatmap Ranking chart、Overall Ranking chart の 3 行構成を持つ。
  - score, max combo, accuracy, pp, online score id は response に出せるが、global rank / user total score / leaderboard projection 由来の値は現状では 0 または unavailable 相当になる。
- **Implications**:
  - verification は score submit mapper の出力を再実装せず、response parser と field assertion で欠落を検出する。
  - user-stats / beatmap-leaderboards をこの spec に吸収しない。

### Getscores response contract

- **Context**: Requirements 5.1-5.5 の fixture coverage と known gaps を確認するため。
- **Sources Consulted**:
  - `src/osu_server/transports/stable/web_legacy/getscores.py`
  - `src/osu_server/transports/stable/web_legacy/mappers/getscores.py`
  - `src/osu_server/services/queries/scores/beatmap_score_listing.py`
  - `tests/fixtures/web_legacy/getscores/*`
  - `tests/unit/transports/web_legacy/test_getscores_fixtures.py`
  - `tests/unit/transports/web_legacy/test_getscores_formatter.py`
  - `tests/integration/test_getscores_endpoint.py`
- **Findings**:
  - query parser は checksum, filename, beatmapset id hint, mode, mods, leaderboard type, request version, song select, anti-cheat signal を扱う。
  - formatter は unavailable `-1|false`, update available `1|false`, header response を返す。
  - existing MVP header は score count 0 で、score rows と personal best は未実装である。
- **Implications**:
  - evidence catalog は existing fixture tests を mandatory evidence として参照する。
  - score row / personal best は verification gap として表示する。

### CLI と runtime guardrails

- **Context**: Requirements 6, 7, 8, 9 の CLI behavior を既存 CLI に合わせるため。
- **Sources Consulted**:
  - `src/athena_cli/main.py`
  - `src/athena_cli/commands/dev.py`
  - `src/athena_cli/context.py`
  - `src/athena_cli/errors.py`
  - `tests/integration/athena_cli/test_cli_dev.py`
- **Findings**:
  - CLI は Typer で構成され、`dev` subcommand は `src/athena_cli/commands/dev.py` に集約されている。
  - `change-password` は `resolve_context` と `selected_environment_variable` を使い、production を prompt 前に拒否する。
  - `CliUserError` と `map_cli_error` が user error と exit code の統一経路になっている。
- **Implications**:
  - `stable-verify` は同じ `dev.py` に command entrypoint を置き、production rejection を network request 前に実行する。
  - reporting は stdout、user error は stderr + exit code に揃える。

### Typer と HTTPX の利用確認

- **Context**: 新しい CLI command と local HTTP probe の既存依存利用を確認するため。
- **Sources Consulted**:
  - `pyproject.toml`
  - Typer docs via Context7: `/websites/typer_tiangolo`
  - HTTPX docs via Context7: `/websites/python-httpx`
- **Findings**:
  - Athena は `typer>=0.26.7` と `httpx>=0.28.1` を既に依存に持つ。
  - Typer は `Annotated[..., typer.Option]` と `CliRunner` による test pattern が既存コードと一致する。
  - HTTPX は client-level headers、per-request headers、timeouts、`RequestError` handling を提供する。
- **Implications**:
  - `pyproject.toml` や `uv.lock` の変更は不要。
  - local probe は HTTPX client に閉じ、connection failure を verification result に変換する。

### Lekuruu/osu.py optional probe

- **Context**: Requirements 5.5 と user decision で言及された headless stable client probe の扱いを確認するため。
- **Sources Consulted**:
  - <https://github.com/Lekuruu/osu.py/blob/main/README.md>
  - <https://github.com/Lekuruu/osu.py/blob/main/pyproject.toml>
  - <https://github.com/Lekuruu/osu.py/blob/main/osu/game.py>
  - <https://github.com/Lekuruu/osu.py/blob/main/osu/api/client.py>
- **Findings**:
  - README は package が osu! stable client の online functionality の一部を emulate し、custom server は `server` attribute で指定できるとしている。
  - GitHub main の `pyproject.toml` は package name `osu`, version `1.5.1`, license `MIT`, dependencies `requests`, `python-dateutil`, `psutil` を宣言している。
  - `WebAPI.get_scores` は `/web/osu-osz2-getscores.php` に stable-like query を送信し、`ScoreResponse.from_string` で parse する。
  - `Game` initialization は version / executable hash が未指定の場合、client version や update check のため外部 `osu.ppy.sh` に触る経路を持つ。
- **Implications**:
  - osu.py は score submit には使わない。getscores / leaderboard optional probe に限定する。
  - Athena の必須依存には追加しない。`import osu` が失敗した場合、optional probe は skip / unavailable とする。
  - 外部 network に依存しないため、probe config は version と executable hash を明示できる場合のみ osu.py adapter を実行する。

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| CLI-owned verifier package | `athena_cli.stable_verification` が evidence catalog、probe runner、reporting を持つ | server runtime に影響しない。production guardrails を CLI context と共有できる | CLI package が stable transport の知識を持つ | Selected |
| Server-side verification endpoint | Athena app に検証専用 endpoint を追加する | HTTP で実行しやすい | production exposure risk。stable runtime surface を増やす | Rejected |
| Pytest-only fixtures | tests 配下だけで golden / contract を管理する | CI は軽い | AI エージェントが local target を headless client 的に確認しにくい | Partial only |
| osu.py first verifier | osu.py を primary verification engine にする | stable client emulator に近い | score submit 非対応。外部 network と dependency 追加リスク | Rejected as mandatory |

## Design Decisions

### Decision: Verification tooling は CLI boundary に置く

- **Context**: 検証は runtime behavior を観測するものであり、server runtime の責務ではない。
- **Alternatives Considered**:
  1. `osu_server` 配下に verification package を追加する。
  2. `athena_cli` 配下に dev-only verification package を追加する。
- **Selected Approach**: `src/athena_cli/stable_verification/` に検証モデル、catalog、client、verifier、reporter を置く。
- **Rationale**: import-linter の server runtime does not depend on CLI 方向を守り、検証機能が production app に混ざらない。
- **Trade-offs**: CLI 側が stable wire knowledge を持つが、runtime transport の変更より risk が低い。
- **Follow-up**: task generation で CLI package から SQLAlchemy / Valkey に直接触れないことを明示する。

### Decision: Evidence catalog と verifier result を共通 model 化する

- **Context**: Stable Surface 棚卸し、mandatory / optional 区別、reporting が同じ result language を必要とする。
- **Alternatives Considered**:
  1. surface ごとに個別の ad hoc output を返す。
  2. dataclass enum model で surface、evidence、result を統一する。
- **Selected Approach**: `StableSurface`, `EvidenceType`, `EvidenceScope`, `VerificationStatus`, `EvidenceEntry`, `SurfaceResult` を定義する。
- **Rationale**: requirements 1, 2, 9 の表現が揃い、JSON output と text output の両方を一貫して生成できる。
- **Trade-offs**: 小さな model layer が増える。
- **Follow-up**: status values は requirements の pass / fail / skip / known_gap / unavailable と一致させる。

### Decision: Mandatory evidence と optional probe を分離する

- **Context**: CI で常時守る軽量 verification と、開発者や AI エージェントが任意実行する headless probe は失敗条件が異なる。
- **Alternatives Considered**:
  1. optional probe failure も CI failure にする。
  2. mandatory evidence failure のみ run failure とし、optional unavailable は non-failing result にする。
- **Selected Approach**: `EvidenceScope.MANDATORY` と `EvidenceScope.OPTIONAL` を分け、runner が aggregate status を計算する。
- **Rationale**: osu.py availability や local server reachability が CI の必須条件にならない。
- **Trade-offs**: report を読む側は skip と fail の違いを理解する必要がある。
- **Follow-up**: report summary に mandatory failure count と optional skipped count を出す。

### Decision: user stats と leaderboard projection は known gap とする

- **Context**: score submit response は total score / rank / overall stats を含むが、roadmap では beatmap-leaderboards と user-stats が別 Wave 3 spec である。
- **Alternatives Considered**:
  1. この spec で provisional stats calculation を追加する。
  2. 現状返せる fields を検証し、projection 由来 fields は known gap / unavailable として表示する。
- **Selected Approach**: verification は response field の存在と stable parseability を検証し、値の source が未実装の場合は known gap として扱う。
- **Rationale**: scope creep を避け、stable response 形式の互換性検証を先に固定できる。
- **Trade-offs**: total score などの値の正しさは別 spec 完了まで full pass にならない。
- **Follow-up**: beatmap-leaderboards / user-stats 実装後に revalidation trigger とする。

### Decision: osu.py は optional adapter にする

- **Context**: user は Lekuruu/osu.py を headless client 的に使う案を示したが、score submit は対象外であり、dependency 追加には承認が必要。
- **Alternatives Considered**:
  1. `osu` package を dev dependency に追加する。
  2. optional import で利用可能な場合のみ getscores probe に使う。
- **Selected Approach**: `osu_py_probe.py` は optional import と config validation を行い、未導入・未設定時は `unavailable` を返す。
- **Rationale**: 既存 dependency 変更なしで設計を進められ、任意 probe の性質と合う。
- **Trade-offs**: 標準環境では osu.py probe は skip になる。
- **Follow-up**: dependency 追加が必要になった時点で別途ユーザー承認を得る。

## Risks & Mitigations

- Score submit fixture が raw replay や credential-like fields を含む — report は metadata のみ出し、raw payload と token を出力しない。
- Local target と Host identity の混同で route を誤検証する — target URL と Host identity を result preface に表示し、request builder で分離する。
- Optional osu.py が外部 network に触る — version / executable hash 未指定時は adapter を実行せず unavailable とする。
- Existing tests と verification tests が重複して意図不明になる — evidence catalog に existing test path と verification purpose を記録する。
- Future user-stats implementation 後に known gap が残る — revalidation trigger と traceability で更新対象を明示する。

## References

- `src/osu_server/composition/application.py` — stable Host routing.
- `src/osu_server/transports/stable/web_legacy/mappers/score_submit.py` — score submit response formatter.
- `src/osu_server/transports/stable/web_legacy/getscores.py` — getscores response formatter and diagnostics.
- `tests/fixtures/web_legacy/getscores/` — existing getscores golden fixtures.
- <https://typer.tiangolo.com/> — Typer command and testing patterns.
- <https://www.python-httpx.org/advanced/clients/> — HTTPX client headers.
- <https://www.python-httpx.org/quickstart/> — HTTPX request error handling.
- <https://github.com/Lekuruu/osu.py> — optional stable client emulator research.
