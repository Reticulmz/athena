# Gap Analysis: athena-cli-management

## 概要

`athena-cli-management` は、既存の環境別設定読み込み、DB 作成 helper、Alembic migration、devenv task を統合し、`athena` 管理 CLI に集約する brownfield feature である。現状は DB 管理の一部だけが暫定 CLI として存在し、CLI package、console script、対話型 env wizard、設定生成 helper、CLI 境界検査は未実装である。

## Current State Investigation

### 既存資産

- `src/osu_server/config.py`
  - `AppConfig` が `DATABASE_URL`、`VALKEY_URL`、`ENVIRONMENT`、osu! API、blob、beatmap mirror などの設定 schema と validation を持つ。
  - `load_config()` は `ENVIRONMENT` を見て `.env.<environment>` を読む。
  - process environment は pydantic-settings により dotenv より優先される。
- `src/osu_server/infrastructure/database/admin.py`
  - `create_database_if_missing()`、`maintenance_url_for()`、`to_asyncpg_url()`、`quote_identifier()` が存在する。
  - `athena db create` の中核処理として再利用可能。
- `src/osu_server/db.py`
  - `python -m osu_server.db create` の暫定 argparse CLI が存在する。
  - production では DB 作成を拒否する。
  - 本 feature では削除対象。
- `alembic/env.py`
  - `load_config()` から DB URL を読み、asyncpg URL に変換して migration を実行する。
  - `athena db migrate --env ...` から `alembic upgrade head` を subprocess 実行する方針と相性が良い。
- `devenv.nix`
  - `db:test:create`、`db:test:migrate`、`test` task が存在する。
  - 現状は `python -m osu_server.db create`、`alembic upgrade head`、`pytest tests/` を直接呼ぶ。
  - devenv dynamic port から `test_database_url` / `test_valkey_url` を組み立てる既存 wrapper ロジックがある。
- `pyproject.toml`
  - wheel package は `src/osu_server` のみ。
  - `[project.scripts]` は未定義。
  - `typer` / `InquirerPy` は未導入。
  - import-linter root package は `osu_server` のみ。
- Tests
  - `tests/unit/infrastructure/test_config.py` が `.env.<environment>` 読み込み、required field、validation を検証している。
  - `tests/unit/infrastructure/test_database_admin.py` が DB admin helper を検証している。
  - CLI 用テストは未存在。

### 既存パターンと制約

- 設定は `AppConfig` に集約され、環境別 dotenv は `load_config()` の責務。
- production target は PostgreSQL + asyncpg。SQLite などの別 driver は暗黙導入しない。
- `services` / `transports` / `jobs` は DB session や raw SQL を直接扱わない方針。
- CLI は新しい transport 境界として扱うが、今回の feature では state-changing user/blob 管理は scope 外。
- import-linter で server runtime が CLI に依存しないことを検査する必要がある。
- strict basedpyright のため、Typer / prompt / subprocess 周りの型境界に注意が必要。

## Requirement-to-Asset Map

| Requirement | Existing Assets | Gap |
|---|---|---|
| 1. 管理 CLI 入口 | なし。暫定 `src/osu_server/db.py` のみ | Missing: `athena_cli` package、console script、command group、help/error behavior |
| 2. 共通環境選択 | `load_config()` が `ENVIRONMENT` を読む | Missing: CLI 共通 `--env` 処理、unsupported env validation、production 表示 |
| 3. 対話型 env 初期化 | `AppConfig` schema / validation | Missing: wizard、section selection、DSN parts、secret input、pre-write validation |
| 4. 非対話 env 初期化 / example | `AppConfig.model_fields` で schema 参照可能 | Missing: env renderer、required/default 判定、non-interactive missing value handling |
| 5. env 上書き安全性 | `.env.*` は gitignore 済み | Missing: file existence check、force/confirmation、production overwrite rule |
| 6. DB 作成 | `create_database_if_missing()` | Partial: CLI wrapper と confirmation/error reporting が不足 |
| 7. DB migrate/setup | `alembic/env.py` が `load_config()` 対応済み | Missing: CLI command、subprocess 実行、setup orchestration、failure propagation |
| 8. config check | `AppConfig` validation | Missing: CLI command、production unsafe local default 判定、error formatting |
| 9. test | `pytest` 設定、devenv task | Missing: CLI command、db setup 前処理、複数 `--path`、exit code propagation |
| 10. devenv task compatibility | `devenv.nix` task と dynamic defaults | Partial: task 名はあるが CLI wrapper ではない |
| 11. 暫定入口廃止 | `src/osu_server/db.py` | Missing: 削除、docs/shell hints 更新、old path 非動作化 |
| 12. CLI/server 境界 | import-linter contracts | Partial: `athena_cli` root package と forbidden contract が不足 |

## Options

### Option A: 既存 `osu_server` 内に CLI を拡張する

- 例: `src/osu_server/cli` を追加し、console script を `osu_server.cli.main:app` にする。
- ✅ 既存 package 設定の変更が少ない。
- ✅ `osu_server.config` や DB helper に近い。
- ❌ CLI transport が server package に混ざる。
- ❌ 将来 `osu_server` → `athena_server` rename 前の境界確立という目的に弱い。
- ❌ `src/osu_server/db.py` の暫定入口と責務が近くなり、分離が曖昧になる。

### Option B: 新しい `athena_cli` package を作る

- 例: `src/athena_cli` を正式 package とし、console script を `athena_cli.main:app` にする。
- ✅ CLI transport と server runtime の境界が明確。
- ✅ `osu_server` が CLI に依存しないことを import-linter で検査しやすい。
- ✅ 将来の `athena_server` rename への前段として自然。
- ✅ user admin / blob gc など将来の運用 CLI 拡張に耐える。
- ❌ packaging、known-first-party、import-linter root package の更新が必要。
- ❌ CLI 用 composition / config support の境界設計が必要。

### Option C: `scripts/` など非 package CLI として実装する

- ✅ 初期実装は最小。
- ❌ console script として配布しづらい。
- ❌ import-linter / basedpyright / packaging の対象から漏れやすい。
- ❌ 正式な運用ツールという要求に合わない。

## 推奨方向（Design Phase で確定）

Option B が最も要求と整合する。`athena_cli` を root project の正式 package として追加し、server runtime から CLI への依存を禁止する。CLI は command routing / prompt / presentation を担当し、設定生成や DB helper など再利用可能な純粋処理は `osu_server` 側の support module に置く案が有力である。

## Technical Needs / Missing Capabilities

### Packaging / Dependency

- `typer` を通常 dependency に追加する必要がある。
- `InquirerPy` を通常 dependency に追加する必要がある。
- `[project.scripts] athena = ...` が必要。
- wheel packages に `src/athena_cli` を追加する必要がある。
- Ruff isort の `known-first-party` に `athena_cli` を追加する必要がある。

### CLI Command Surface

- `athena env init <environment>`
- `athena env example`
- `athena db create --env <environment>`
- `athena db migrate --env <environment>`
- `athena db setup --env <environment>`
- `athena config check --env <environment>`
- `athena test --env test [--path ...]`

### Configuration Support

- `AppConfig.model_fields` 由来で env example を出す仕組み。
- required/default/optional/secret/list の扱い。
- `.env.<environment>` writer。
- generated env content を write 前に validation する仕組み。
- production unsafe local default 判定。

### DSN Builder

- Database connection parts から PostgreSQL DSN を組み立てる helper。
- Valkey connection parts から Redis/Valkey DSN を組み立てる helper。
- password masking と file output の分離。
- query parameter や special character encoding の扱い。

### Prompt Layer

- section selection checkbox。
- text input / confirm / secret input。
- non-interactive mode では prompt layer を通さず同じ env generation core を使う必要がある。

### Database / Migration / Test Runner

- `db create` は既存 `create_database_if_missing()` を利用可能。
- `db migrate` は `ENVIRONMENT` を設定した上で `alembic upgrade head` を subprocess 実行するのが自然。
- `db setup` は create + migrate の orchestration。
- `test` は setup + pytest の orchestration と exit code propagation。

### Boundary Validation

- import-linter に `athena_cli` を root package として追加する。
- `osu_server` -> `athena_cli` を forbidden にする contract が必要。
- `athena_cli` -> `osu_server` は許可するが、Design Phase で許可範囲を絞るか検討が必要。

## Constraints / Risks

- **Typer / InquirerPy 型安全性**: third-party prompt libraries の戻り値型が弱い可能性がある。Protocol wrapper や typed adapter が必要になるかもしれない。
- **Pydantic field introspection**: `AppConfig.model_fields` から env var 名・required/default を生成する設計は可能だが、list / optional / secret 判定は明示 metadata がないと曖昧になる。
- **Production safety**: Requirements は production DB create に確認を要求するが、具体的な `--yes` / prompt 動作は design で決める必要がある。
- **Subprocess environment**: Alembic / pytest に正しく `ENVIRONMENT`、`DATABASE_URL`、`VALKEY_URL` を渡す必要がある。
- **devenv defaults**: dynamic port は `devenv.nix` でしか分からないため、CLI に devenv 知識を入れない設計が必要。
- **Current uncommitted state**: 既に `devenv.nix`、DB helper、config 周辺などに変更があるため、実装時は既存変更を壊さないよう差分管理が必要。

## Research Needed for Design Phase

- Typer の subcommand、global option、testing `CliRunner` の現在の推奨 API。
- InquirerPy の checkbox / secret / confirm / validation の型付けと testability。
- Pydantic v2 `model_fields` から required/default/annotation を安全に扱う方法。
- `pydantic-settings` の env var naming と `env_prefix=""` 時の alias / field name 変換の詳細。
- subprocess 実行時の stdout/stderr passthrough と exit code propagation のテスト方針。

## Effort / Risk

- **Effort: L**
  - CLI package、dependencies、prompt wizard、env generation、DB/migrate/test orchestration、devenv wrapper、import-linter 変更まで含むため複数領域にまたがる。
- **Risk: Medium**
  - 中核は既存設定・DB helper の再利用で実現可能だが、interactive prompt の testability、Pydantic schema introspection、production safety の仕様化に注意が必要。

## Design Phase Recommendations

1. `athena_cli` を正式 package とする Option B を第一候補にする。
2. CLI は transport として command routing / prompt / presentation を担当し、設定生成 core と DSN builder は再利用可能な support module に分離する。
3. `db migrate` はまず subprocess で `alembic upgrade head` を呼び、Alembic API 直接統合は避ける。
4. `devenv.nix` は task 名を維持し、dynamic default を環境変数として CLI に渡す thin wrapper にする。
5. state-changing user/blob 管理や audit log は今回の design に含めず、roadmap の後続 spec に委譲する。

---

# Design Discovery Log

## Summary

- **Feature**: `athena-cli-management`
- **Discovery Scope**: Extension / Complex Integration
- **Key Findings**:
  - `athena_cli` は `osu_server` と分離した CLI transport package として追加し、server runtime から CLI への依存を import-linter で禁止する。
  - Typer は明示的な subcommand group 登録、callback option、`CliRunner` testing に適している。InquirerPy は checkbox / secret / confirm / validation を提供するが、戻り値型を CLI adapter で閉じ込める必要がある。現行 `pyproject.toml` には両依存が未導入のため、具体バージョンは実装時に `uv add` / lock 更新で確定する。
  - env generation は interactive / non-interactive で同一 core を共有し、`AppConfig` validation を write 前 gate として使う。

## Research Log

### Typer command group と testing

- **Context**: `athena` console script と nested command group、CLI tests の設計が必要だった。
- **Sources Consulted**: Typer official documentation, local `pyproject.toml`
- **Findings**:
  - `typer.Typer()` と `app.add_typer(sub_app, name="...")` で明示的に command group を登録する。
  - `@app.callback()` は global option や shared state setup に使える。
  - `typer.testing.CliRunner` は CLI invocation と simulated input のテストに使える。
- **Implications**: Root CLI App は Typer に寄せ、help/unknown command behavior は Typer 標準に委譲する。CLI orchestration 自体は typed support modules に分離して unit test する。

### InquirerPy prompt layer

- **Context**: 対話型 env wizard で checkbox、secret、confirm、validation が必要だった。
- **Sources Consulted**: InquirerPy official documentation, local `pyproject.toml`
- **Findings**:
  - checkbox prompt は `Choice` と `validate` を使える。
  - secret prompt と confirm prompt が提供されている。
  - classic `prompt([...])` と alternate `inquirer.*(...).execute()` の両方がある。
- **Implications**: InquirerPy の raw result を直接 command 実装へ流さず、`PromptAdapter` Protocol と dataclass result に変換する。non-interactive mode は prompt layer を通らない。

### Existing integration points

- **Context**: 既存 config / DB / devenv 実装をどこまで再利用するか決める必要があった。
- **Sources Consulted**: `src/osu_server/config.py`, `src/osu_server/infrastructure/database/admin.py`, `alembic/env.py`, `devenv.nix`, `pyproject.toml`
- **Findings**:
  - `load_config()` は `ENVIRONMENT` から `.env.<environment>` を読む。
  - `create_database_if_missing()` は idempotent DB create に再利用できる。
  - Alembic env は `load_config()` を使うため subprocess 実行と相性が良い。
  - devenv dynamic defaults は Nix 側でしか自然に表現できない。
  - 現行 task は `ATHENA_TEST_DATABASE_URL` / `ATHENA_TEST_VALKEY_URL` を override 入力として受けるが、CLI に渡す最終契約は `DATABASE_URL` / `VALKEY_URL` / `ENVIRONMENT=test` である。
- **Implications**: CLI は devenv を知らず、devenv task は `DATABASE_URL` / `VALKEY_URL` / `ENVIRONMENT` を整えて `uv run athena ...` を呼ぶ thin wrapper にする。

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| `osu_server` 内 CLI | `src/osu_server/cli` に command を追加 | package 変更が少ない | server runtime と CLI transport の境界が曖昧 | 将来 rename 前段として弱い |
| `athena_cli` package | `src/athena_cli` を正式 package として追加 | 境界が明確、import-linter で検査しやすい | packaging と root package 設定変更が必要 | 採用 |
| scripts CLI | `scripts/` などに非 package 実装 | 初期実装が小さい | console script / type checking / import-linter から漏れやすい | 不採用 |

## Design Decisions

### Decision: CLI は separate package として追加する

- **Context**: CLI は運用 transport であり、server runtime の起動経路とは責務が異なる。
- **Alternatives Considered**:
  1. `src/osu_server/cli` — 既存 package に近いが境界が曖昧。
  2. `src/athena_cli` — CLI transport を独立 package 化する。
- **Selected Approach**: `src/athena_cli` を追加し、root `pyproject.toml` の package / script / import-linter 設定を更新する。
- **Rationale**: 将来の `osu_server` → `athena_server` rename 前に CLI 境界を固定できる。
- **Trade-offs**: package 設定と boundary tests が増える。
- **Follow-up**: import-linter に `osu_server` -> `athena_cli` forbidden contract を追加する。

### Decision: env generation core を prompt layer から分離する

- **Context**: interactive と non-interactive が同じ env content validation を共有する必要がある。
- **Alternatives Considered**:
  1. command 関数内で prompt と generation を直書きする。
  2. prompt adapter と pure generation core を分離する。
- **Selected Approach**: PromptAdapter は入力収集のみ、EnvGenerator / DsnBuilder / EnvWriter が生成と検証を担当する。
- **Rationale**: 型安全、テスト容易性、non-interactive mode の再利用性が高い。
- **Trade-offs**: 小さな module が増える。
- **Follow-up**: task phase では adapter の raw `Any` を境界内で閉じ込めるテストを含める。

### Decision: migration と pytest は subprocess runner で扱う

- **Context**: Alembic と pytest は既に CLI として安定した entrypoint を持つ。
- **Alternatives Considered**:
  1. Alembic API / pytest API を直接呼ぶ。
  2. subprocess で既存 command を実行する。
- **Selected Approach**: `ProcessRunner` が `alembic upgrade head` と `pytest` を実行し、exit code を伝播する。
- **Rationale**: 既存の運用 command と出力挙動を保ち、内部 API coupling を避けられる。
- **Trade-offs**: subprocess env construction のテストが必要。
- **Follow-up**: stdout/stderr passthrough と exit code propagation を integration test で検証する。

## Risks & Mitigations

- Typer / InquirerPy の型境界が弱い — adapter と Protocol/dataclass で閉じ込め、command 層に raw prompt result を漏らさない。
- `AppConfig.model_fields` introspection が将来変わる — EnvSchemaProvider の unit test と `env example` integration test で drift を検出する。
- production overwrite / DB create の事故 — `--force` と explicit confirmation を分離し、production banner を出す。
- devenv wrapper と CLI の責務混同 — dynamic defaults は `devenv.nix` に残し、CLI は一般的な env var 入力のみ扱う。

## References

- Typer official documentation — https://typer.tiangolo.com/tutorial/subcommands/add-typer/ and https://typer.tiangolo.com/tutorial/testing/
- InquirerPy official documentation — https://inquirerpy.readthedocs.io/en/latest/pages/prompts/checkbox.html, https://inquirerpy.readthedocs.io/en/latest/pages/prompts/secret.html, and https://inquirerpy.readthedocs.io/en/latest/pages/prompts/confirm.html
- Local source — `pyproject.toml`, `src/osu_server/config.py`, `src/osu_server/infrastructure/database/admin.py`, `alembic/env.py`, `devenv.nix`
