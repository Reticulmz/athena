# Athena

Athena is an osu! bancho-compatible private server implemented as a Python modular
monolith.

The project is built around a specific design goal: address common pain points in
existing bancho server implementations by keeping the codebase Pythonic,
well-partitioned, easy to deploy, and ready for horizontal scaling where runtime
state needs to leave a single process.

Stable osu! clients are the current compatibility focus through the bancho binary
protocol and legacy `/web/*.php` endpoints. Lazer and first-party API packages are
kept as explicit transport boundaries so their runtime behavior can evolve without
pulling stable compatibility concerns into the core domain.

## Project Status

Athena is an early-stage proof-of-concept project. It is not production-ready, and
many features expected from a complete osu! private server are still missing or
only partially implemented.

The current codebase is primarily useful as an architecture and compatibility
experiment: it validates whether a Pythonic modular monolith can keep bancho
compatibility concerns, domain logic, persistence, workers, and runtime state in
clear boundaries while remaining practical to deploy.

## Design Goals

- Preserve externally observable stable-client behavior while improving internal
  ownership boundaries.
- Keep deployment simple with a single service codebase, PostgreSQL, Valkey, and
  taskiq workers.
- Make horizontal scaling practical by moving shared runtime state, queues, and
  pub/sub concerns into infrastructure boundaries instead of process globals.
- Keep business rules transport-independent with dataclass domain models and
  command/query use-cases.
- Prefer clear, idiomatic Python over framework-heavy or compatibility-driven
  code structure.

## Architecture

Athena is a layered modular monolith with hexagonal adapters, a command/query
use-case split, and Unit of Work controlled command persistence.

```text
composition -> runtime adapters -> command/query use-cases -> repositories -> infrastructure
                                    command/query use-cases -> domain -> shared
```

Core package responsibilities:

- `apps/athena_server/src/osu_server/domain`: transport-independent business language and policies.
- `apps/athena_server/src/osu_server/services/commands`: state-changing workflows and transaction timing.
- `apps/athena_server/src/osu_server/services/queries`: read-only display, search, and compatibility views.
- `apps/athena_server/src/osu_server/repositories`: persistence ports and concrete memory, SQLAlchemy,
  and Valkey implementations.
- `apps/athena_server/src/osu_server/transports`: stable, lazer, and first-party protocol adapters.
- `apps/athena_server/src/osu_server/jobs`: taskiq task adapters.
- `apps/athena_server/src/osu_server/composition`: Dishka provider graph and runtime integration.

See [apps/athena_server/docs/architecture.md](apps/athena_server/docs/architecture.md) for the full boundary contract.

## Tech Stack

- Python 3.14+
- uv for package and environment workflows
- Nix flake for local services and reproducible development shells
- Starlette and FastAPI for ASGI boundaries
- Caterpillar for bancho binary protocol modeling
- Pydantic v2 and pydantic-settings for API/configuration I/O
- SQLAlchemy 2.0 async, asyncpg, and Alembic for PostgreSQL persistence
- Valkey with `valkey-glide` for cache, state, queue, and pub/sub infrastructure
- taskiq and taskiq-redis for background jobs
- Dishka for dependency composition
- ruff, interrogate, basedpyright strict mode, pytest, and import-linter for quality gates

## Local Development

Enter the development shell and run explicit worktree setup:

```bash
nix develop
just setup
```

The flake shell resolves the current git worktree root. `just setup` performs the
locked uv sync, installs worktree-local hooks, prepares `.state/`, and generates
development ingress files for that worktree. uv package caches are shared through
`UV_CACHE_DIR`, defaulting to `$HOME/.uv/cache/athena`.

Create an environment file:

```bash
cp apps/athena_server/.env.example apps/athena_server/.env.development
```

The required runtime values are:

```dotenv
DATABASE_URL=postgresql://localhost:5432/athena
VALKEY_URL=redis://localhost:6379
```

Start the credential-free core development profile:

```bash
just dev
```

If an older worktree-local PostgreSQL cluster already exists, reset it before
starting the PostgreSQL 18 profile:

```bash
rm -rf .state/postgres
just dev
```

Use the optional tunnel profile only after Cloudflare tunnel state has been set up:

```bash
just tunnel-setup
just dev-tunnel
```

Server-specific runbook details live in
[apps/athena_server/README.md](apps/athena_server/README.md). Crypto package
build and artifact details live in
[packages/athena_crypto/README.md](packages/athena_crypto/README.md).

## Quality Gates

Run the local quality gate:

```bash
just quality
```

Run only the docstring quality gate:

```bash
just docstrings
```

The canonical docstring standard is [AGENTS.md](AGENTS.md). Ruff `D` checks Google
Style presence and format, while interrogate checks definition coverage. Section
types and meanings are reviewed against the canonical standard, implementation,
call sites, and relevant tests.

`just quality` runs Ruff, interrogate, basedpyright, and import-linter over the
workspace-owned source, test, stub, and repository-tooling inventory. The
generated pre-commit configuration is owned by `flake.nix`: it runs the uv
lockfile's Ruff formatter and linter for changed `.py` files, then invokes the
full docstring gate once. Changes limited to `.pyi` stubs do not trigger the
docstring gate.

Sphinx configuration, themes, generated output, and publishing belong to an
external documentation repository. Because Sphinx autodoc imports modules, that
repository owns Athena dependency installation, runtime environment, and module
selection. It can opt in to private, `__init__`, and dunder members when generating
their API reference.

Run the test gate:

```bash
just test
```

Build artifacts, check migrations, audit monorepo ownership, and run the explicit
development infrastructure checkpoint:

```bash
just build
just db-migrate
just migration-check
just audit-monorepo
just process-lifecycle-check
```

Before committing, run:

```bash
nix develop --command prek run --all-files
```

## Database

Apply migrations:

```bash
just db-migrate
```

Create a new migration after changing SQLAlchemy models:

```bash
uv run --directory apps/athena_server alembic revision --autogenerate -m "describe change"
```

The development environment also exposes database helper tasks:

```bash
just db-test-create
just db-test-migrate
just db-test-run
```

## Stable Client Compatibility

Stable support is split into two transport families:

- `transports/stable/bancho`: login, packet routing, packet parsing/building, and
  bancho workflow adaptation.
- `transports/stable/web_legacy`: legacy PHP-compatible endpoints such as
  registration, getscores, beatmap file resolution, and score submission.

Compatibility values that are stable-specific but not wire-format concerns live
under `domain/compatibility/stable`.

## Compatibility Roadmap

The detailed packet, endpoint, request, response, and persistence inventory lives
in [apps/athena_server/docs/stable-compatibility-matrix.md](apps/athena_server/docs/stable-compatibility-matrix.md).
That matrix is the source of truth for stable compatibility progress; this README
only summarizes the current direction so the two documents do not drift.
The processing and data-shape guide lives in
[apps/athena_server/docs/stable-compatibility-guide.md](apps/athena_server/docs/stable-compatibility-guide.md).

Current focus areas:

- Core stable login, packet polling, chat, friends, getscores, and score submit
  surfaces are implemented or partially implemented.
- Remaining stable work is tracked in the matrix across packet coverage,
  presence/stats, multiplayer, spectator, osu!direct, static/media delivery,
  update/release policy, leaderboard projections, and moderation workflows.
- Akatsuki-compatible Relax and Autopilot leaderboards are tracked as an
  explicit compatibility extension, not as a baseline osu!stable requirement.

## Agent Workflow

This repository is optimized for parallel coding-agent work. File-editing tasks
should use isolated git worktrees and agent-prefixed branches:

```bash
just worktree <task-slug> --agent codex
```

By default, worktrees are created under the repo-sibling
`../athena_worktree/<task-slug>` directory.

Local files listed in `.worktreeinclude` are copied from the current checkout
into the target worktree after creation or reuse. Entries are repository-root
pathspecs without Git pathspec magic. The script only copies files that are
ignored by the target worktree, keeping development files such as
`apps/athena_server/.env.development` and `apps/athena_server/.env.test` available without exposing them to `git add`.

For non-trivial changes, use a pull request as the integration boundary. Run local
checks in the task worktree, push the branch, let GitHub CI validate it, and report
readiness after checks pass and the final diff has been reviewed. PR merges are
performed by the user on GitHub Web UI.

## Documentation

- [apps/athena_server/README.md](apps/athena_server/README.md): server, worker, CLI, migration, and local operation runbook.
- [packages/athena_crypto/README.md](packages/athena_crypto/README.md): native crypto package build and artifact verification runbook.
- [docs/monorepo-layout.md](docs/monorepo-layout.md): repository workspace map and ownership boundaries.
- [apps/athena_server/docs/architecture.md](apps/athena_server/docs/architecture.md): architecture and placement rules.
- [apps/athena_server/docs/stable-compatibility-matrix.md](apps/athena_server/docs/stable-compatibility-matrix.md): stable
  packet and endpoint compatibility inventory.
- [apps/athena_server/docs/stable-compatibility-guide.md](apps/athena_server/docs/stable-compatibility-guide.md): stable
  request, response, processing, and persistence guide.
- [AGENTS.md](AGENTS.md): coding-agent instructions, workflow rules, and the
  canonical Python docstring standard.
