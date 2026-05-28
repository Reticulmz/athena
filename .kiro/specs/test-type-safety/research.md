# Research & Design Decisions

## Summary

- **Feature**: `test-type-safety`
- **Discovery Scope**: Extension
- **Key Findings**:
  - CI は `ruff` と `pytest tests/ -v` を実行しているが、型チェックは `uv run basedpyright src/` のみで `tests/` が CI 対象外だった。
  - pre-commit は `devenv.nix` 由来で生成され、既に `uv run basedpyright src/ tests/` と unit pytest gate を持つ。編集対象は生成物の `.pre-commit-config.yaml` ではなく `devenv.nix`。
  - `tests/` の型回避は 31 ファイル以上に分散し、主なカテゴリはファイルレベル pyright 抑制、`AsyncMock`、`type: ignore`、`cast`、Starlette/httpx/Valkey/Caterpillar/structlog 由来の型不足である。

## Research Log

### CI と pre-commit の品質ゲート

- **Context**: 7.1-7.7 を満たすため、現行 CI と pre-commit の差分を確認した。
- **Sources Consulted**:
  - `.github/workflows/ci.yml`
  - `.pre-commit-config.yaml`
  - `devenv.nix`
- **Findings**:
  - CI quality job は `ruff check src/ tests/`、`ruff format --check src/ tests/`、`uv run basedpyright src/`、`uv run lint-imports` を個別に実行する。
  - CI test job は Postgres 16 と Redis 7 を service として起動し、`uv run pytest tests/ -v` を実行する。
  - `.pre-commit-config.yaml` は `git-hooks.nix` 生成物であり、直接編集対象ではない。
  - `devenv.nix` は basedpyright、import-linter、unit pytest、gitlint、ruff、ruff-format などの hook source である。
- **Implications**:
  - `scripts/ci.sh` を品質ゲートの実行契約にし、CI workflow は同スクリプトを呼ぶ。
  - pre-commit 変更は `devenv.nix` を通じて行い、生成物の `.pre-commit-config.yaml` は手編集しない。
  - CI の type check は `src/ tests/` に拡張する。

### テスト型回避の分布

- **Context**: 2.1-6.3 を満たすため、既存テストの型回避パターンを調査した。
- **Sources Consulted**:
  - `rtk grep "# pyright|pyright: ignore|type: ignore|from typing import Any|typing import .*Any|AsyncMock|cast\\(" tests`
  - `rtk basedpyright src/ tests/`
- **Findings**:
  - ファイルレベル pyright 抑制は `tests/conftest.py`、integration、e2e、logging、lifecycle、bancho protocol などに分散している。
  - `AsyncMock` は HIBP/httpx、PasswordService、AuthService、LifecycleHandlers、LifecycleListeners、health check、login handler などで使用されている。
  - `type: ignore[arg-type]` は dataclass の `**kwargs` builder と structlog processor 入力で発生している。
  - `type: ignore[misc]` は frozen dataclass の不変性テストで直接代入に使われている。
  - `cast("list[TEncodable]", keys)` は Valkey cleanup helper 周辺で発生している。
  - `basedpyright src/ tests/` の先頭エラーは Starlette `TestClient` の `Response` 型で `status_code` や `headers` が unknown になる問題だった。
- **Implications**:
  - 単一の修正方針では不十分であり、カテゴリ別に helper/fake/stub/production typing repair を選択する。
  - テスト double は既存 in-memory 実装を最優先し、足りない外部境界だけ `tests/support` の typed fake に閉じ込める。
  - Starlette/httpx/Valkey/Caterpillar 由来の型不足は `typings/` または typed wrapper を優先する。

### 既存の型付き代替実装

- **Context**: 3.2 と 4.3 を満たすため、mock を置換できる既存実装を調査した。
- **Sources Consulted**:
  - `src/osu_server/repositories/memory/`
  - `src/osu_server/infrastructure/state/memory/`
  - `src/osu_server/infrastructure/messaging/memory.py`
  - `src/osu_server/repositories/interfaces/`
  - `src/osu_server/infrastructure/state/interfaces/`
- **Findings**:
  - InMemoryUserRepository、InMemoryRoleRepository、InMemoryChannelRepository、InMemorySessionStore が存在する。
  - InMemoryPacketQueue、InMemoryChannelStateStore、InMemoryRateLimiter、InMemoryEventBus が存在する。
  - Protocol は repositories/state/messaging/country に分散しており、テスト double はこれらの Protocol に準拠させられる。
- **Implications**:
  - 既存 in-memory 実装を再利用し、不足分だけ scoped fake を追加する。
  - Protocol 名とメソッド署名の不一致がテストで見つかった場合は `src/` の Protocol 修正を許容する。

### 外部ライブラリ型スタブ

- **Context**: 5.1-5.4 を満たすため、既存の型スタブ配置を確認した。
- **Sources Consulted**:
  - `typings/glide/`
  - `typings/glide_shared/`
  - `typings/httpx/`
  - `.agents/rules/type-safety-policy.md`
- **Findings**:
  - 既に Valkey Glide と httpx の自前スタブが `typings/` 配下に存在する。
  - 型安全ポリシーはコミュニティ stub、`basedpyright --createstub`、手動補完、最終手段のインライン抑制という優先順を定めている。
- **Implications**:
  - 新しい外部型補完も `typings/<package>/` に統一する。
  - 外部由来の抑制は、stub/wrapper 検討後に回避不能な1行だけに限定する。

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Patch-only cleanup | 各テストファイルで suppress を個別削除する | 変更量が小さい | 再発防止と CI 統一が弱い | 不採用 |
| Shared typed test support | 既存 in-memory 実装を優先し、共通 fake/helper/factory を最小限追加する | suppress を構造的に減らせる | support 層が肥大化する可能性 | 採用 |
| Full test framework abstraction | すべての fixture/fake を共通 DSL 化する | 統一感は高い | 過剰設計で tasks が重くなる | 不採用 |

## Design Decisions

### Decision: CI 基準を `scripts/ci.sh` に集約する

- **Context**: CI とローカル実行の差分を減らし、7.1-7.7 を満たす。
- **Alternatives Considered**:
  1. CI YAML に個別コマンドを維持する。
  2. `scripts/ci.sh` を品質ゲートの実行契約にする。
- **Selected Approach**: `scripts/ci.sh quality|test|all|fix` を追加し、CI workflow は `quality` と `test` を呼ぶ。
- **Rationale**: ローカルで CI 相当を再現でき、CI と手元のコマンド drift を抑えられる。
- **Trade-offs**: CI YAML 単体の可読性は下がるが、実行契約は1箇所に集約される。
- **Follow-up**: `test` は Postgres/Redis の起動を担当しないため、CI services または devenv services が前提であることを明記する。

### Decision: `AsyncMock` は既存 in-memory 実装と typed fake に置換する

- **Context**: `AsyncMock` が `Any` を流入させ、3.1-3.4 に反する。
- **Alternatives Considered**:
  1. `AsyncMock(spec=...)` を維持する。
  2. 既存 in-memory 実装と Protocol 準拠 fake/stub に置換する。
- **Selected Approach**: アプリ内依存は in-memory 実装を優先し、外部境界や呼び出し観測が必要な場合だけ typed fake を使う。
- **Rationale**: テスト対象の契約が明示され、`Any` 流入を境界で止められる。
- **Trade-offs**: 一部テストは呼び出し回数 assertion から状態/結果 assertion へ書き換える必要がある。
- **Follow-up**: 単一テスト専用 fake はテストファイル内に閉じ、2ファイル以上で再利用されるものだけ `tests/support/` に置く。

### Decision: 外部ライブラリ型不足は `typings/` と wrapper を優先する

- **Context**: Starlette/httpx/Valkey/Caterpillar/structlog 由来の unknown/Any が残る。
- **Alternatives Considered**:
  1. ファイルレベル pyright 抑制を残す。
  2. 自前 stub または typed wrapper で境界を補う。
- **Selected Approach**: 既存 stub 調査、`typings/` 補完、typed wrapper の順に解決し、回避不能な場合だけ理由付き1行抑制を許可する。
- **Rationale**: 例外を境界に閉じ込め、テスト全体の型診断を信頼できる状態にできる。
- **Trade-offs**: スタブ保守が必要になる。
- **Follow-up**: 追加/補完した stub は `basedpyright src/ tests/` で実効性を確認する。

### Decision: runtime-only な型回避は専用 helper に局所化する

- **Context**: frozen dataclass の不変性テストは型システム上不正な代入を実行時に検証する必要がある。
- **Alternatives Considered**:
  1. `event.field = value  # type: ignore[misc]` を残す。
  2. 意図を表す helper に `object.__setattr__` などを閉じ込める。
- **Selected Approach**: `tests/support/runtime_assertions.py` に runtime-only helper を置き、テストは helper を呼ぶ。
- **Rationale**: 型チェッカー回避の目的が実行時保証の検証であることを明示できる。
- **Trade-offs**: helper 内部には慎重な型注釈が必要になる。
- **Follow-up**: helper は frozen/invariant assertion だけに使い、一般的な属性変更には使わない。

## Risks & Mitigations

- `tests/support/` が過剰な共通フレームワークになる — 2ファイル以上で同じ概念が必要な場合だけ共通化する。
- 外部 stub が実ライブラリから drift する — stub 変更時は該当ライブラリ境界のテストと `basedpyright src/ tests/` を必須にする。
- CI test のローカル再現で DB/Valkey 前提が抜ける — `scripts/ci.sh test` は services を起動せず、README/usage に前提を明示する。
- 型安全化の名目でプロダクト仕様が変わる — 既存テスト期待値を維持し、仕様変更は out of scope とする。


---

## Implementation Gap Analysis

### Requirement-to-Asset Map

| ID | Requirement | Current Asset / State | Gap / Constraint |
|:---|:---|:---|:---|
| 1 | Tests Strict Type Checking | `tests/` excluded from CI basedpyright | Missing: CI integration for `tests/` |
| 2 | Eliminate Suppressions | 31+ files with `# pyright` / `ignore` | Constraint: Massive tech debt in test code |
| 3 | Prevent Mock Any Leakage | `AsyncMock` used in core service tests | Missing: Typed fakes for HIBP, lifecycle, etc. |
| 4 | Typed Factories | `**kwargs` with `ignore` in domain tests | Missing: `tests/factories/` |
| 5 | External Library Stubs | `typings/` exists but incomplete | Gap: `TestClient`, `Valkey`, `Caterpillar` unknown types |
| 6 | Safe Runtime Exception Test | `type: ignore[misc]` for frozen objects | Missing: `tests/support/runtime_assertions.py` |
| 7 | Local CI Script | No unified script for quality/test | Missing: `scripts/ci.sh` |
| 8 | Documentation | Generic type policy exists | Missing: Test-specific safety patterns |

### Implementation Approaches

#### Option A: Incremental Cleanup (Extend Existing)
- **Rationale**: Fix files one by one by adding inline stubs and minor repairs.
- **Trade-offs**:
  - ✅ Low initial effort per file.
  - ❌ High duplication of stubs/fakes.
  - ❌ Hard to maintain consistency across 31+ files.

#### Option B: Structural Foundation (Hybrid - Recommended)
- **Rationale**: Create central `tests/support/` and `tests/factories/` first, then migrate tests.
- **Trade-offs**:
  - ✅ Clean separation and high reusability.
  - ✅ Addresses root cause of `Any` leakage and type corruption.
  - ❌ Requires initial infrastructure setup before seeing "Green" results.

### Complexity & Risk

- **Effort**: **M (3–7 days)**
  - 既存のテストファイル数が多く（31+）、一つずつ suppress を外して代替実装に置き換える作業に時間がかかる。
  - ツールチェーンの同期（CI/pre-commit）は比較的短時間で完了する。
- **Risk**: **Medium**
  - 外部ライブラリ（Caterpillar, Valkey Glide）の型定義が複雑で、自前 stub の維持コストや整合性がリスク。
  - プロダクトコード（DI, Protocol）の微修正が必要になる可能性があり、予期せぬ影響に注意が必要。

### Recommendations for Design Phase

- **Preferred Approach**: **Option B**. テスト基盤（scripts, support, factories, stubs）を先に固め、その後に各テストカテゴリ（Unit -> Integration -> E2E）を移行する。
- **Research Needed**:
  - `Starlette.TestClient` のレスポンス属性を `Unknown` にさせないための最適な stub 定義。
  - `Valkey-glide` の `delete` 引数などに渡す `list[TEncodable]` の型定義不整合の解決策。
  - `Caterpillar` の declarative type が `basedpyright` で `Unknown` と判定される問題の stub 補完。
