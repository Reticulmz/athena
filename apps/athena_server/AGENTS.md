# Athena Server Agent Guidance

Follow root `AGENTS.md` ([../../AGENTS.md](../../AGENTS.md)) for repository-wide
rules. This file only records `apps/athena_server` workspace differences.

## Scope

- Source lives under `apps/athena_server/src`.
- Tests, fixtures, factories, and support code live under `apps/athena_server/tests`.
- Alembic configuration and revisions live under `apps/athena_server/alembic.ini` and `apps/athena_server/alembic`.
- Server-only third-party stubs live under `apps/athena_server/typings`.
- Runtime architecture and stable compatibility references live under `apps/athena_server/docs`.

## Commands

Run project gates from the repository root through `nix develop`:

```bash
just dev
just quality
just test
just db-migrate
just migration-check
```

Use direct `uv run` commands only for focused server debugging after the root
gate has defined the canonical behavior.

## Boundaries

- Keep runtime adapters thin; business behavior belongs in command/query use-cases.
- Keep domain code free of Pydantic, SQLAlchemy, Valkey, taskiq, Starlette, FastAPI, and Dishka.
- Keep SQLAlchemy sessions and concrete repositories behind repository and Unit of Work boundaries.
- Stable wire parsing/building belongs in `transports/stable`; stable-only compatibility semantics belong in `domain/compatibility/stable`.
