# Athena Monorepo Layout

## Status

Accepted baseline as of 2026-07-30.

このtreeはfrontend実装後のtargetを含む。Initial monorepo migrationでは`apps/athena_web`、root pnpm files、Web用Nix module、`tests/system`を作成しない。

## Ownership principles

- `apps/`はproduct/release boundaryを表す。
- Rootはworkspace orchestration、cross-workspace policy、long-lived decisionを所有する。
- Runtime dependencyと実装固有資料はowner workspaceへ置く。
- Test、type stub、migration、environment exampleはconsumerまたはdistributionとcolocateする。
- `packages/`は独立build artifact、複数の実consumer、異なるtoolchainを閉じ込める必要があるmoduleだけを置く。
- Generated stateとmachine固有設定はversioned source treeへ混在させない。

## Target tree

```text
athena/
├── apps/
│   ├── athena_server/
│   │   ├── src/
│   │   │   ├── osu_server/
│   │   │   └── athena_cli/
│   │   ├── tests/
│   │   ├── typings/
│   │   ├── alembic/
│   │   ├── docs/
│   │   ├── alembic.ini
│   │   ├── pyproject.toml
│   │   ├── default.nix
│   │   ├── .env.example
│   │   ├── AGENTS.md
│   │   └── README.md
│   └── athena_web/                  # 最初のfrontend feature実装時に作成
│       ├── src/
│       ├── public/
│       ├── tests/
│       ├── docs/research/
│       ├── package.json
│       ├── default.nix
│       ├── .env.example
│       ├── AGENTS.md
│       └── README.md
├── packages/
│   └── athena_crypto/
│       ├── src/
│       ├── tests/
│       ├── Cargo.toml
│       ├── pyproject.toml
│       ├── default.nix
│       ├── AGENTS.md
│       └── README.md
├── tests/
│   └── system/
├── tools/
│   └── gitlint/
│       ├── rules/
│       └── tests/
├── infra/
│   └── development/
│       ├── nginx/
│       ├── cloudflared/
│       └── hosts.example
├── docs/
│   ├── adr/
│   └── research/
├── scripts/
│   └── agent-worktree.sh
├── .agents/
├── .claude/
├── .codex/
├── .github/
├── .kiro/
├── .env.example
├── .envrc
├── .gitignore
├── .gitlint
├── .python-version
├── .worktreeinclude
├── AGENTS.md
├── CLAUDE.md
├── CONTEXT.md
├── README.md
├── LICENSE
├── flake.nix
├── flake.lock
├── justfile
├── process-compose.yml
├── pyproject.toml
├── uv.lock
├── package.json                     # frontend workspace作成時に追加
├── pnpm-workspace.yaml              # frontend workspace作成時に追加
├── pnpm-lock.yaml                   # frontend workspace作成時に追加
└── skills-lock.json
```

`tests/system/`は最初のcross-workspace testを追加する時点でprivate test workspaceとして作成する。空directoryや将来用packageは先に作らない。

## Local generated state

```text
.state/
├── certs/
├── cloudflared/
├── nginx/
├── postgres/
└── valkey/
```

`.state/`、`.venv/`、Web dependency/build outputはGitへ追加せず、linked worktree間でも共有しない。

## Tool ownership

| Owner | Responsibility |
| --- | --- |
| Root Flake | System toolchain、workspace dev shell、Nix build/check composition |
| Workspace `default.nix` | 現在のServer、cryptoと将来追加するWeb固有のNix module |
| uv | Python workspace dependency resolutionとroot `uv.lock` |
| pnpm | Frontend workspace作成後のJavaScript dependency resolutionとroot `pnpm-lock.yaml` |
| Cargo/Maturin | `athena_crypto`のRust/Python extension build |
| Just | Repositoryで唯一の公開task interface |
| process-compose | Cross-workspace process graph、readiness、shutdown、logs |

Root `pyproject.toml`はnon-package uv workspaceとrepository-wide Python development policyを所有する。`apps/athena_server/pyproject.toml`はserver distribution、runtime dependency、console script、server固有architecture validationを所有する。Frontend workspace作成後に追加するroot `package.json`はprivate workspace metadataだけを持つ。

## Documentation and agent guidance

- Root `README.md`はquick startとworkspace map、child READMEはworkspace固有runbookを所有する。
- Root `AGENTS.md`は共通規約、child AGENTS.mdは差分規約だけを所有する。
- ADRはroot `docs/adr/`で単一連番を維持する。
- Workspace固有architecture、protocol、researchはownerの`docs/`へ置く。
- `.kiro/specs/`はactive planとcompleted feature specificationの両方を保持する。lifecycleとauthorityは[spec README](../.kiro/specs/README.md)で定義する。

## Migration status and remaining cleanup

- Python server source、test、Alembic、server stub、CLI、docsは`apps/athena_server/`が所有する。
- Native crypto source、test、manifest、public typingは`packages/athena_crypto/`が所有する。Root uv workspaceは単一lockを使う。
- Root README/AGENTSはrepository overview、共通policy、Just task interfaceを所有し、server/crypto README/AGENTSはworkspace固有runbookと差分だけを所有する。
- Stable compatibility fixture、catalog、verification reportはserver owner配下のpathをcurrent evidenceとして参照する。
- Gitlint rule、development task gateway、tracked ingress templateの最終cleanupは後続Task 4.5/4.6で実施する。移行完了まで暫定artifactを削除せず、path consumer auditの理由付きallowlistで管理する。

## Deferred decisions

- `apps/athena_web/src/`内部のroute、feature、component、API adapter layout。
- HeroUI、shadcn/uiを含むUI component system。
- `apps/athena_web`、pnpm workspace、Web用Nix moduleの作成。
- Official PP calculator bindingとNativeAOT/runtime方式。

## Migration boundaries

### 1. Python workspace cutover

- `athena_crypto`を`packages/athena_crypto`へ移す。
- Server、CLI、test、Alembic、type stub、server docsを`apps/athena_server`へ移す。
- Root `pyproject.toml`をnon-package uv workspaceへ変更し、root `uv.lock`へ統合する。
- Import、config path、quality/test/import-linter設定を新しいownershipへ更新する。
- 旧import facadeや新旧directoryの長期併存は行わない。

### 2. Tooling and development infrastructure

- Root Flakeとserver/crypto `default.nix`を構成する。
- Root `justfile`を導入し、process-composeを公開task interfaceの背後へ置く。
- Development proxy/tunnel templateとgenerated `.state`を分離する。
- Gitlint ruleを`tools/`へ移し、`scripts/ci.sh`と`scripts/dev-tasks.sh`を削除する。
- GitHub ActionsをJust recipe経由へ変更し、独立したNix validationを追加する。

### 3. Documentation and backlog audit

- Root、server、cryptoのREADMEとAGENTS.md、およびClaude固有差分を新しいownershipへ更新する。Web用文書はfrontend workspace作成時に追加する。
- Kiro specのphase、task completion、実装状態を監査し、current instructionとhistorical evidenceを区別する。
- Root `TODO.md`の残項目はroadmap/specへ移管済みで、root backlog authorityとしては残さない。
- Stale path、重複規約、廃止commandをrepository全体で検査する。

Frontend workspace bootstrapはこのmigrationに含めず、最初のfrontend feature specとPRで行う。

## Related decisions

- [ADR 0013](adr/0013-organize-monorepo-apps-by-product-boundary.md)
- [ADR 0014](adr/0014-compose-nix-environments-from-workspace-modules.md)
- [ADR 0015](adr/0015-provide-local-and-cloudflare-development-ingress.md)
- [ADR 0016](adr/0016-use-apex-domain-for-web-app.md)
