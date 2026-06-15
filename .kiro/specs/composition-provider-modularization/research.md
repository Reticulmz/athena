# Research & Design Decisions

## Summary

- **Feature**: `composition-provider-modularization`
- **Discovery Scope**: Extension
- **Key Findings**:
  - `CommonProviderSet` と `AppProviderSet` はそれぞれ shared runtime と app-only workflow の境界を越えて dependency wiring を抱えており、provider import hotspot になっている。
  - Athena の architecture rule は provider construction を `composition/providers/` 所有に固定しているため、Gemini 案の `domain/*/provider.py` や `infrastructure/provider.py` への移動は採用しない。
  - 既存の `make_async_container`、provider replacement、startup/lifecycle tests は分割後もそのまま検証軸として使える。
  - Dishka 1.10.1 の documented pattern は複数 provider の container 合成、`@provide` method、scope 指定、generator finalization、`override=True` replacement を自然に支える。

## Research Log

### 既存 provider graph の構成

- **Context**: `CommonProviderSet` と `AppProviderSet` の import 肥大化が実際に設計上の問題か確認した。
- **Sources Consulted**:
  - `src/osu_server/composition/providers/common.py`
  - `src/osu_server/composition/providers/app.py`
  - `src/osu_server/composition/providers/container.py`
  - `src/osu_server/composition/providers/test.py`
- **Findings**:
  - `common.py` は config、DB engine、session factory、Valkey、broker、HTTP client、state stores、session store、query repositories、Unit of Work、storage service、beatmap services、chat use-cases、score crypto、stable score submit mapper を同じ provider class に登録している。
  - `app.py` は identity/auth、chat app commands、beatmap mirror app integration、stable bancho workflows、stable web legacy handlers、score submission workflow を同じ provider class に登録している。
  - `container.py` はすでに複数 provider を `make_async_container` へ渡す形になっており、provider set を増やしても existing composition style から外れない。
- **Implications**:
  - `CommonProviderSet` の単純分割だけでは app-only import hotspot が残る。
  - 分割は app/worker shared provider と app-only provider の両方を対象にする。

### Architecture boundary の確認

- **Context**: Gemini review は provider を `domain/*` や `infrastructure/*` に置く案を提示していた。
- **Sources Consulted**:
  - `.claude/rules/architecture.md`
  - `.claude/rules/development.md`
  - `.kiro/steering/tech.md`
  - `pyproject.toml` import-linter contracts
- **Findings**:
  - Composition root は concrete adapters、repositories、services、transports、jobs を import して runtime graph を組んでよい。
  - App、worker、test graph は `src/osu_server/composition/providers/` が所有する。
  - Domain packages は repositories、infrastructure、services、transports、jobs、I/O libraries へ依存できない。
  - Services と repository interfaces も Dishka や composition へ依存しない。
- **Implications**:
  - provider definitions は `composition/providers/` から出さない。
  - feature/context 別の provider set を作る場合も、domain package 内 provider ではなく composition package 内 provider にする。

### 検証 surface の確認

- **Context**: provider 分割で既存 runtime behavior を壊さないため、どのテストが graph contract を押さえているか確認した。
- **Sources Consulted**:
  - `tests/unit/composition/test_common_provider_graph.py`
  - `tests/unit/composition/test_provider_replacement.py`
  - `tests/unit/composition/test_beatmap_mirror_composition.py`
  - `tests/unit/test_di_integration.py`
  - `tests/unit/transports/bancho/test_di_registration.py`
  - `tests/integration/test_app_startup.py`
- **Findings**:
  - App/worker container resolution、provider replacement、production provider が `environment == "test"` で分岐しないこと、beatmap mirror composition、stable transport handler resolution がテストされている。
  - `CommonProviderSet` module を直接 inspect するテストがあるため、分割後は production provider modules の一覧を新しい provider set へ更新する必要がある。
  - `enqueue_beatmap_fetch` は app provider module にあり、beatmap mirror app integration として移動対象になる。
- **Implications**:
  - 既存の graph resolution tests は分類名と expected types を更新して継続利用する。
  - 新規テストは「provider module の責務分類」と「旧 all-purpose provider へ wiring が残っていないこと」を補完する。

### Dishka documented patterns の確認

- **Context**: Provider 分割を Dishka の documented usage に沿わせるため、現在 lock されている dependency と Dishka docs を確認した。
- **Sources Consulted**:
  - `uv.lock` (`dishka 1.10.1`, `starlette-dishka 1.0.2`)
  - Dishka quickstart documentation
  - Dishka provider `provide` documentation
  - Dishka testing documentation
- **Findings**:
  - Dishka docs は複数 `Provider` を `make_container` / `make_async_container` に渡して graph を構築する例を示している。
  - Provider class は `scope = Scope.APP` のような class-level scope と、factory method の `@provide(scope=...)` を使える。
  - Generator provider は scope exit 時の finalization に使えるため、engine、client、broker の lifecycle 管理に合う。
  - `override=True` は testing replacement の documented mechanism として扱われている。
  - `Provider.provide` も同じ factory registration API だが、読みやすさでは method-level `@provide` が provider 分割後の責務表示に向いている。
- **Implications**:
  - 分割後の production provider は class-level `scope = Scope.APP` と `@provide` を標準にする。
  - Async generator finalization を使う managed dependency は `@provide` method として残す。
  - Test replacement helper は `override=True` 方針を維持する。

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| 現状維持 | `CommonProviderSet` と `AppProviderSet` に追記し続ける | 差分が少ない | import hotspot と merge conflict risk が残る | 採用しない |
| Domain-local provider | `domain/beatmaps/provider.py` のように domain package へ provider を置く | 一見 feature ごとにまとまる | domain が Dishka、repositories、services、infrastructure を import し、architecture contract に反する | 採用しない |
| Infrastructure-local provider | `infrastructure/provider.py` に低レベル dependency を置く | infrastructure import は局所化する | provider construction ownership が分散し、composition root の責任が曖昧になる | 採用しない |
| Hybrid composition provider sets | `composition/providers/` 内で layer 別と context 別に provider set を分ける | 境界規約を維持しつつ import hotspot を分散できる | provider set 数が増えるため container の列挙が重要になる | 採用 |
| Decorator-first rewrite | provider registration を原則 `@provide` 形式へ変える | method 単位の登録が見えやすく、分割後の provider 責務が明示される | generic alias registration など一部で explicit `provides` が必要になる可能性がある | 採用 |

## Design Decisions

### Decision: Provider ownership は composition package に固定する

- **Context**: Gemini review の配置案は domain/infrastructure へ provider を移す内容だった。
- **Alternatives Considered**:
  1. Domain package 内 provider - context ごとの import 局所化を優先する。
  2. Infrastructure package 内 provider - low-level dependency の近くに construction を置く。
  3. Composition package 内 provider - composition root が construction を所有し続ける。
- **Selected Approach**: すべての production provider set を `src/osu_server/composition/providers/` 配下に置く。
- **Rationale**: Existing architecture rule、import-linter contracts、service/domain independence に合う。
- **Trade-offs**: File path だけでは domain package の近くに見えないが、provider file name と class name で context を明示する。
- **Follow-up**: import-linter と provider module import tests で boundary drift を検出する。

### Decision: Hybrid 分割を採用する

- **Context**: infrastructure、repository、state、transport workflow は同じ粒度では分けにくい。
- **Alternatives Considered**:
  1. Layer-only 分割 - infrastructure、repositories、services、transports で分ける。
  2. Context-only 分割 - identity、chat、beatmaps、scores だけで分ける。
  3. Hybrid 分割 - shared infrastructure/repositories は layer 別、feature use-case/workflow は context 別に分ける。
- **Selected Approach**: shared provider sets は infrastructure、repositories、storage、beatmaps、chat、scores に分け、app-only provider sets は identity、chat app、beatmap app、score submission、stable bancho、stable web legacy に分ける。
- **Rationale**: DB/Valkey/Broker のような shared resources は context 所有にすると重複しやすく、stable workflow は transport family の境界でまとめる方が自然。
- **Trade-offs**: Provider set 数は増えるが、container factory が唯一の合成点になるため graph 全体の見通しは保てる。
- **Follow-up**: Task phase では shared provider sets と app-only provider sets を段階分けして実装する。

### Decision: `CommonProviderSet` は廃止し、`AppProviderSet` は marker に縮小する

- **Context**: 旧 class を残すと新しい wiring も旧 all-purpose provider へ戻りやすい。
- **Alternatives Considered**:
  1. `CommonProviderSet` を互換 wrapper として残す。
  2. `CommonProviderSet` を削除し、container factory が複数 provider set を列挙する。
  3. `CommonProviderSet` を小さな aggregator class にする。
- **Selected Approach**: `CommonProviderSet` は production wiring surface から削除し、`AppProviderSet` は `AppProviderGraph` marker だけを提供する小さな provider にする。
- **Rationale**: 旧 all-purpose provider へ戻る経路をなくし、変更箇所を責務別 provider file に固定できる。
- **Trade-offs**: 旧 class を直接 import している internal tests は更新が必要。
- **Follow-up**: `__init__.py` の public re-export も新しい provider set に更新する。

### Decision: Provider registration style は `@provide` を原則にする

- **Context**: Existing providers は `self.provide(..., provides=..., scope=Scope.APP)` を使っている。
- **Alternatives Considered**:
  1. 原則 `@provide` decorator へ変換し、必要な箇所だけ explicit registration を許可する。
  2. 現行の programmatic registration を小さな provider set 内で維持する。
  3. 例外なしですべて `@provide` decorator へ変換する。
- **Selected Approach**: 責務別 provider set では `@provide` decorator を標準にする。`async_sessionmaker[AsyncSession]` など Dishka の型解決で explicit `provides` が必要な箇所のみ、理由を残して programmatic registration を許可する。
- **Rationale**: Dishka docs の provider examples と一致し、分割後の provider は method 単位で依存登録が読める方が保守しやすく、all-purpose registration loop に戻りにくい。一方で generic alias や runtime annotation の扱いは実装時に安全性を優先する。
- **Trade-offs**: 一部の provider では decorator と explicit registration が混在する可能性があるが、混在理由が局所化されるため設計上の曖昧さは小さい。
- **Follow-up**: Task phase では decorator-first を標準タスクにし、programmatic registration が残る場合は該当型と理由を implementation note に残す。

## Risks & Mitigations

- Provider set 間で同じ type を二重提供する risk - container composition tests で duplicate provider failure を検出する。
- Provider set の分割で circular import が発生する risk - provider modules は sibling provider module を import せず、dependency は type annotation と container composition で接続する。
- Worker graph から app-only dependency が漏れる risk - `make_worker_container` は shared provider sets と worker marker のみを合成する。
- Stable score submit の mapper/use-case 境界が混ざる risk - stable mapper は stable web legacy provider、score command workflow は score submission provider に分離する。
- Test override helper が production 分割とずれる risk - `make_in_memory_runtime_provider_set` を新しい provider type expectations に合わせて更新する。

## References

- `.claude/rules/architecture.md` - Composition ownership、layer direction、placement guide。
- `.claude/rules/development.md` - Type safety、quality gate、config edit policy。
- `.kiro/steering/tech.md` - Dishka + starlette-dishka と `composition/providers/` ownership。
- `.kiro/specs/application-architecture-refactor/design.md` - Existing composition provider baseline。
- `https://dishka.readthedocs.io/en/stable/quickstart.html` - Provider、scope、複数 provider container composition の documented pattern。
- `https://dishka.readthedocs.io/en/stable/provider/provide.html` - `@provide` と generator finalization。
- `https://dishka.readthedocs.io/en/stable/advanced/testing/index.html` - Test provider / replacement pattern。
- `docs/gemini-code-1781532860646.md` - Provider bloat 問題提起。
- `docs/gemini-code-1781533898513.md` - Provider 分割案と採用しない配置案。
