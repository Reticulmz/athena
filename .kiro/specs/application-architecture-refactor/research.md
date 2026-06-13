# Research & Design Decisions

## Summary

- **Feature**: `application-architecture-refactor`
- **Discovery Scope**: Complex Integration
- **Key Findings**:
  - 現行の `composition/service_registry.py` と `composition/worker_runtime.py` は app/worker の依存構築を別々に手組みしており、test 切り替えや lifecycle、worker runtime の責務が肥大化している。
  - SQLAlchemy repository は各 method が session と commit/rollback を所有しており、score submission のような複数 repository をまたぐ command を 1 つの business outcome として扱いにくい。
  - `domain/role.py` と `services/permission_service.py` は内部 authorization と stable client-visible permission を混在させている。stable/lazer/API 互換表現は transport mapper へ寄せる必要がある。
  - Dishka は provider, scope, finalization を持つ DI framework として app/worker/test の composition root を整理できる。Starlette 連携は公式 docs が案内する `starlette-dishka`、taskiq 連携は `dishka.integrations.taskiq` を使う。

## Research Log

### 現行 composition と lifecycle

- **Context**: 旧 `Container.resolve()` / `get_singleton()` と `service_registry` の完全廃止を前提に、現状の責務集中を確認した。
- **Sources Consulted**:
  - `src/osu_server/infrastructure/di/container.py`
  - `src/osu_server/infrastructure/di/providers.py`
  - `src/osu_server/composition/service_registry.py`
  - `src/osu_server/composition/lifespan.py`
  - `src/osu_server/composition/worker_runtime.py`
  - `src/osu_server/worker.py`
- **Findings**:
  - `Container` は singleton lock, eager initialize, shutdown hook を自前実装しているが、scope は singleton/transient のみで request lifetime を表現できない。
  - `service_registry.py` は repository, service, transport handler, listeners, job registration, startup validation を 1 ファイルに集約している。
  - app 側は `config.environment == "test"` 分岐で in-memory provider を登録しており、provider replacement と production branch が分離されていない。
  - worker 側は taskiq state に手組み service を詰めており、app composition と provider 定義を共有できていない。
- **Implications**:
  - DI は `composition/providers/` を composition root とし、runtime ごとの provider set を明示する。
  - app/worker/test は同じ provider contract を共有し、test は provider replacement で差し替える。
  - 旧 `infrastructure/di`、`composition/service_registry.py`、`composition/worker_runtime.py` は互換 facade なしで削除対象にする。

### Dishka と ASGI/Worker integration

- **Context**: 新規 DI framework と Starlette/taskiq integration を設計に入れるため、公式 docs と package 存在を確認した。
- **Sources Consulted**:
  - [Dishka documentation](https://dishka.readthedocs.io/en/stable/)
  - [Dishka Starlette integration](https://dishka.readthedocs.io/en/stable/integrations/starlette.html)
  - [Dishka Taskiq integration](https://dishka.readthedocs.io/en/stable/integrations/taskiq.html)
  - [dishka PyPI](https://pypi.org/project/dishka/)
  - [starlette-dishka PyPI](https://pypi.org/project/starlette-dishka/)
  - `docs/adr/0002-adopt-dishka-for-composition-di.md`
- **Findings**:
  - Dishka は provider と scope を中心に dependency graph を構築し、APP scope の finalization で managed dependency を閉じられる。
  - Starlette integration は `starlette-dishka` パッケージ側に移されており、request scope と WebSocket session scope の管理を提供する。
  - taskiq integration は broker に container を設定し、task handler で依存を注入できる。
  - `starlette-dishka` は `dishka` と `starlette` を前提にするため、Athena では runtime dependency として両方を明示する。
- **Implications**:
  - `dishka` と `starlette-dishka` を runtime dependency に追加する。
  - scope は最初に `APP` と `REQUEST` の標準 scope だけを使う。custom scope は実装中に lifecycle gap が確認された場合の再設計対象にする。
  - services は Dishka の型を import しない。Dishka 依存は `composition/providers/`、Starlette/taskiq integration module、tests の provider replacement に閉じ込める。

### 永続化境界と Unit of Work

- **Context**: command-side consistency と query-side readiness を満たすため、現行 repository の transaction ownership を確認した。
- **Sources Consulted**:
  - `src/osu_server/repositories/interfaces/*.py`
  - `src/osu_server/repositories/sqlalchemy/*.py`
  - `src/osu_server/services/score_submission_service.py`
  - `src/osu_server/jobs/beatmap_fetch.py`
- **Findings**:
  - SQLAlchemy repository は method ごとに session を開き、書き込み method 内で commit/rollback している。
  - `ScoreSubmissionService` は submission 作成、score 作成、replay 作成、submission state 更新を複数 repository call で行うが、全体を 1 transaction として扱えない。
  - beatmap fetch job は repository と provider を直接持つ class と task adapter が同居しており、今後 command use-case と job adapter の境界が曖昧になりやすい。
- **Implications**:
  - command-side repository は UoW 内の repository として提供し、commit/rollback を repository から UoW へ移す。
  - query-side repository は transaction を要求しない read contract として分離する。
  - external I/O を含む command は、I/O wait 中に write transaction を保持しないよう、取得/検証 phase と mutation phase を use-case 内で分ける。

### domain language と compatibility

- **Context**: Bancho 固有の `ClientPermissions`、内部 `Privileges`、mods、stable/lazer/API 表現の置き場所を整理した。
- **Sources Consulted**:
  - `CONTEXT.md`
  - `src/osu_server/domain/role.py`
  - `src/osu_server/domain/mods.py`
  - `src/osu_server/domain/score/score.py`
  - `src/osu_server/services/permission_service.py`
- **Findings**:
  - `Role` は `permissions: Privileges` を持つが、`ClientPermissions` も同じ domain module に存在する。
  - `PermissionService.to_client_flags()` が stable client permission mapping を service に置いている。
  - `Mods` は IntFlag だが `Score.mods` は `int` であり、canonical model と wire input の境界が弱い。
  - glossary は Role, Privilege, Bancho Client Permission, Session Authorization Snapshot を定義済み。
- **Implications**:
  - core authorization は `domain/identity` に置き、stable client-visible permission は `domain/compatibility/stable` と stable transport mapper に隔離する。
  - `Score.mods` は `ModCombination` value object に置き換え、stable は int bitmask、lazer は JSON、first-party API は Athena-owned JSON から mapper で変換する。
  - lazer-only mods は core `Mod` に追加できるが、stable mapper が unsupported representation を明示する。

### transport family と将来 API

- **Context**: stable, lazer, first-party API, WebUI 管理 API の共存を前提に package boundary を整理した。
- **Sources Consulted**:
  - `src/osu_server/transports/bancho/*`
  - `src/osu_server/transports/web_legacy/*`
  - `src/osu_server/transports/api/__init__.py`
  - `src/osu_server/transports/signalr/__init__.py`
  - `.kiro/steering/roadmap.md`
- **Findings**:
  - 現状は `bancho`, `web_legacy`, `api`, `signalr` が root に並び、stable/lazer/first-party の分類が package 名から読み取りにくい。
  - root `transports/api` は将来 lazer API と first-party API のどちらを指すか曖昧になりやすい。
  - WebUI は別 repo 予定だが、Athena-owned public/admin API は同一 backend transport として必要になる。
- **Implications**:
  - `transports/stable/{bancho,web_legacy}`、`transports/lazer/{api,signalr}`、`transports/api/{public,admin}` に再編する。
  - services は transport family 名で分けない。transport は mapper と handler を持ち、domain/use-case input/output へ変換する。
  - transport 間の実装依存を import-linter で禁止する。

### import-linter と architecture documentation

- **Context**: 新 architecture を人間の記憶ではなく docs と validation で固定する必要がある。
- **Sources Consulted**:
  - `pyproject.toml`
  - `.kiro/steering/tech.md`
  - `.claude/rules/code-quality.md`
- **Findings**:
  - 既存 import-linter は broad layer contract を持つが、command/query、transport family 相互依存、old path residual を十分に表現していない。
  - docs は steering と ADR に断片的に存在するが、新 architecture の package placement guide は未作成。
- **Implications**:
  - `docs/architecture.md` を refactor completion gate にする。
  - `pyproject.toml` に command/query、transport family、jobs、domain I/O、legacy path residual の validation を追加する。
  - 実装完了時は docs と import-linter の境界説明が一致していることを検証する。

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Layered modular monolith with hexagonal adapters and CQRS boundary | モジュラモノリスを維持し、transport/job を adapter、services を command/query use-case、repositories を port/adapter として分離する | 既存のプロセス構成と相性がよく、外部挙動を保ったまま境界を強制できる | package migration と test 更新の範囲が広い | 採用 |
| Keep custom container and split service registry | 自前 DI を残し、registry を複数ファイルへ分割する | dependency 追加が不要 | scope/lifecycle/test replacement の問題が残り、再肥大化しやすい | 不採用 |
| Full event sourcing | command state を event log と projection へ再設計する | 将来の leaderboard/read model と相性がよい | 現行要件に対して過剰で、既存 external behavior 維持のリスクが高い | 不採用 |
| Separate read database | query-side を別 DB/projection store に分離する | leaderboard/stats の将来拡張に強い | 今回の out of scope。operation と migration の負担が増える | 不採用 |
| Transport-named services | `services/bancho`, `services/web_legacy` のように分ける | 入口から追いやすい | business meaning が client family に引きずられ、lazer/API 追加で重複する | 不採用 |
| Compatibility import facade migration | 旧 import path を alias で残して段階移行する | 短期の移行は楽 | 完全廃止要件と矛盾し、二重の作り方が残る | 不採用 |

## Design Decisions

### Decision: Dishka を composition DI として採用する

- **Context**: app/worker/test composition と managed lifecycle を明示し、旧 registry 肥大化を止める。
- **Alternatives Considered**:
  1. 自前 lightweight container 継続。
  2. `dependency-injector`。
  3. Lagom。
- **Selected Approach**: `dishka`、`starlette-dishka`、`dishka.integrations.taskiq` を使い、provider definitions を `composition/providers/` に集約する。
- **Rationale**: 型ヒント中心の constructor injection と明示 provider が Athena の方針に合う。Starlette/taskiq の公式 integration を使える。
- **Trade-offs**: Dishka の provider/scope 規約を team が学ぶ必要がある。DI library 依存を composition root に閉じ込めて service 可読性を守る。
- **Follow-up**: 実装時に pyproject/uv.lock の依存解決と strict type checking を通す。

### Decision: command/query use-case と repository package を分ける

- **Context**: leaderboard、stats、ranking、WebUI/API の read needs が score ingestion command と混ざることを避ける。
- **Alternatives Considered**:
  1. 現行 service/repository に method を追加し続ける。
  2. service だけ command/query に分け、repository は共通に残す。
  3. command/query service と command/query repository の両方を分ける。
- **Selected Approach**: `services/commands`, `services/queries`, `repositories/interfaces/{commands,queries}`, `repositories/{sqlalchemy,memory}/{commands,queries}` を作る。
- **Rationale**: mutation と presentation read の責務を package と import rule で区別できる。
- **Trade-offs**: repository interface 数は増えるが、用途ごとの contract が小さくなる。
- **Follow-up**: tasks では既存 service を機械的 move ではなく use-case 単位で改名/分割する。

### Decision: command-side persistence は Unit of Work が所有する

- **Context**: 複数 repository をまたぐ command の atomicity と failure observability を確保する。
- **Alternatives Considered**:
  1. repository method 内 commit を継続。
  2. service が SQLAlchemy session を直接持つ。
  3. UoW が repository set と transaction boundary を所有する。
- **Selected Approach**: `UnitOfWorkFactory` と `UnitOfWork` protocol を導入し、command service が明示的に `async with` で開始する。
- **Rationale**: services/jobs/transports は低レベル persistence resource を持たず、command consistency boundary を明示できる。
- **Trade-offs**: 既存 repository 実装を session-owned から UoW-owned へ移行する必要がある。
- **Follow-up**: external I/O を含む command は write transaction を保持する範囲を短くする設計を tests で固定する。

### Decision: bounded context で domain package を再編する

- **Context**: flat `domain` package と transport-compatible concept の混在を解消する。
- **Alternatives Considered**:
  1. 現行 flat domain を維持。
  2. transport 名で domain を分ける。
  3. identity/chat/beatmaps/scores/storage/compatibility/events の bounded context で分ける。
- **Selected Approach**: core domain は bounded context、client family semantics は `domain/compatibility/*` と transport mapper で扱う。
- **Rationale**: domain language が client wire format から独立し、stable/lazer/API の入力差分を mapper に閉じ込められる。
- **Trade-offs**: move 範囲は大きいが、旧 import facade は残さない。
- **Follow-up**: `CONTEXT.md` と `docs/architecture.md` の用語を一致させる。

### Decision: transport family は stable/lazer/first-party API で分ける

- **Context**: stable bancho/web legacy、lazer REST/SignalR、Athena-owned public/admin API を混同しない。
- **Alternatives Considered**:
  1. 現行 root transport packages を維持。
  2. `web_api` と `api` を併用。
  3. `transports/stable`, `transports/lazer`, `transports/api` へ整理する。
- **Selected Approach**: root `transports/api` は first-party API とし、lazer REST は `transports/lazer/api` に置く。
- **Rationale**: WebUI 管理 API と lazer compatibility API の責務が package 名から区別できる。
- **Trade-offs**: route assembly と tests の import path 更新が必要。
- **Follow-up**: transport family 間の implementation dependency を import-linter で禁止する。

### Decision: jobs は thin adapter に限定する

- **Context**: worker behavior を app と同じ use-case と composition boundary に乗せる。
- **Alternatives Considered**:
  1. job class が business logic と repository を持つ。
  2. jobs package を command service と同義にする。
  3. taskiq adapter は input adaptation/use-case invocation/outcome reporting のみを持つ。
- **Selected Approach**: `jobs/` は task registration と taskiq adapter、business/idempotency/persistence は command/query use-case に置く。
- **Rationale**: worker 専用ロジックの分岐を避け、app/worker の behavior consistency を保てる。
- **Trade-offs**: taskiq integration と provider setup が先に必要。
- **Follow-up**: task dependency missing は observable failure とし、silent return を避ける。

## Risks & Mitigations

- Package move が広範囲で import drift が起きる — old path residual check、import-linter、`rg` based validation、tests 更新を各 phase の完了条件にする。
- UoW 導入で外部 I/O 中に transaction を保持する危険 — command design で lookup/fetch phase と mutation phase を分離し、transaction duration を tests と review checklist で確認する。
- Dishka integration の型情報不足や provider graph error — provider definitions を小さく分け、startup composition test と basedpyright を completion gate にする。
- Domain compatibility 分離で stable response shape が変わる危険 — stable mapper tests と既存 integration tests を regression gate にする。
- 旧 facade を残さない方針により移行中の壊れ方が大きい — phase ごとに tests/import-linter を通すが、completion 時は old and new paths の二重支持を許可しない。

## References

- [Dishka documentation](https://dishka.readthedocs.io/en/stable/) — provider, scope, lifecycle の公式ドキュメント。
- [Dishka Starlette integration](https://dishka.readthedocs.io/en/stable/integrations/starlette.html) — Starlette integration と `starlette-dishka` の採用根拠。
- [Dishka Taskiq integration](https://dishka.readthedocs.io/en/stable/integrations/taskiq.html) — worker/task injection の採用根拠。
- [dishka PyPI](https://pypi.org/project/dishka/) — runtime dependency package の存在確認。
- [starlette-dishka PyPI](https://pypi.org/project/starlette-dishka/) — Starlette integration package の存在確認。
- `docs/adr/0002-adopt-dishka-for-composition-di.md` — DI framework 採用 ADR。
- `.kiro/steering/tech.md` — Athena の技術スタックと persistence 方針。
- `CONTEXT.md` — domain glossary と authorization terminology。
