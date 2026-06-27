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

- `src/osu_server/domain`: transport-independent business language and policies.
- `src/osu_server/services/commands`: state-changing workflows and transaction timing.
- `src/osu_server/services/queries`: read-only display, search, and compatibility views.
- `src/osu_server/repositories`: persistence ports and concrete memory, SQLAlchemy,
  and Valkey implementations.
- `src/osu_server/transports`: stable, lazer, and first-party protocol adapters.
- `src/osu_server/jobs`: taskiq task adapters.
- `src/osu_server/composition`: Dishka provider graph and runtime integration.

See [docs/architecture.md](docs/architecture.md) for the full boundary contract.

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
- ruff, basedpyright strict mode, pytest, and import-linter for quality gates

## Local Development

Enter the development shell and sync dependencies:

```bash
nix develop
uv sync
```

The flake shell resolves the current git worktree root and keeps `.venv`,
`.state`, and generated certificates inside that worktree. uv package caches
are shared through `UV_CACHE_DIR`, defaulting to `$HOME/.uv/cache/athena`.

Create an environment file:

```bash
cp .env.example .env.development
```

The required runtime values are:

```dotenv
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/athena
VALKEY_URL=redis://localhost:6379
```

Start local services and processes from the Nix shell:

```bash
process-compose up
```

Useful direct commands:

```bash
uv run python -m osu_server
uv run taskiq worker osu_server.worker:broker
uv run athena db setup --env development
uv run athena config check --env development
```

## Quality Gates

Run the local quality gate:

```bash
./scripts/ci.sh quality
```

Run the test gate:

```bash
./scripts/ci.sh test
```

Run both:

```bash
./scripts/ci.sh all
```

Before committing, run:

```bash
prek run --all-files
```

## Database

Apply migrations:

```bash
uv run alembic upgrade head
```

Create a new migration after changing SQLAlchemy models:

```bash
uv run alembic revision --autogenerate -m "describe change"
```

The development environment also exposes database helper tasks:

```bash
scripts/dev-tasks.sh db:test:create
scripts/dev-tasks.sh db:test:migrate
scripts/dev-tasks.sh db:test:run
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
in [docs/stable-compatibility-matrix.md](docs/stable-compatibility-matrix.md).
That matrix is the source of truth for stable compatibility progress; this README
only summarizes the current direction so the two documents do not drift.
The processing and data-shape guide lives in
[docs/stable-compatibility-guide.md](docs/stable-compatibility-guide.md).

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
./scripts/agent-worktree.sh <task-slug> --agent codex
```

By default, worktrees are created under the repo-sibling
`../athena_worktree/<task-slug>` directory.

Local files listed in `.worktreeinclude` are copied from the current checkout
into the target worktree after creation or reuse. This keeps ignored development
files such as `.env.development` and `.env.test` available in agent worktrees
without committing secrets.

For non-trivial changes, use a pull request as the integration boundary. Run local
checks in the task worktree, push the branch, let GitHub CI validate it, then merge
only after checks pass and the final diff has been reviewed.

## Documentation

- [docs/architecture.md](docs/architecture.md): architecture and placement rules.
- [docs/stable-compatibility-matrix.md](docs/stable-compatibility-matrix.md): stable
  packet and endpoint compatibility inventory.
- [docs/stable-compatibility-guide.md](docs/stable-compatibility-guide.md): stable
  request, response, processing, and persistence guide.
- [bancho_server_design.md](bancho_server_design.md): stable protocol and design notes.
- [AGENTS.md](AGENTS.md): coding-agent instructions, conventions, and workflow rules.
