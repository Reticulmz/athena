# Athena Server Workspace

`apps/athena_server` owns the ASGI app, taskiq worker, Athena CLI, Alembic
migrations, server tests, server-only typings, and stable/lazer/first-party API
runtime documentation.

Use the repository root as the command entry point so the same Just recipes run
locally and in CI:

```bash
nix develop
just setup
just dev
just quality
just test
just db-migrate
just migration-check
```

`just dev` starts the credential-free core profile: PostgreSQL, Valkey, app,
worker, and Nginx. `just dev-tunnel` is only for Cloudflare tunnel work after
`just tunnel-setup` has prepared worktree-local tunnel state.

osu!direct search defaults to `OSU_DIRECT_SEARCH_BACKEND=auto`: startup uses
ParadeDB `pg_search` when available, then Meilisearch when configured with
`OSU_DIRECT_EXTERNAL_INDEX_BACKEND=meilisearch`, and finally PostgreSQL
`tsvector`. Set it to `paradedb`, `meilisearch`, or `tsvector` to require one
backend explicitly.

Hybrid search is enabled by default. Local results are supplemented by
Hinamizawa then Nerinyan when a page is incomplete, id-range coverage is missing
or out of range, or page 0 needs refresh. Tune with
`OSU_DIRECT_UPSTREAM_SEARCH_WAIT_SECONDS` and
`OSU_DIRECT_UPSTREAM_SEARCH_FIRST_PAGE_REFRESH_SECONDS`.

Beatmap metadata fetch is DB-heavy and is throttled per worker process with
`BEATMAP_METADATA_FETCH_MAX_CONCURRENCY`. Keep it at or below
`DATABASE_POOL_SIZE`; `DATABASE_MAX_OVERFLOW` is only a burst allowance.

Server-specific direct commands are for focused debugging inside `nix develop`:

```bash
uv run python -m osu_server
uv run taskiq worker osu_server.worker:broker
uv run athena config check --env development
uv run --directory apps/athena_server alembic revision --autogenerate -m "describe change"
```

Authoritative server references:

- [docs/architecture.md](docs/architecture.md): layer and placement contract.
- [docs/stable-compatibility-guide.md](docs/stable-compatibility-guide.md): stable processing and persistence guide.
- [docs/stable-compatibility-matrix.md](docs/stable-compatibility-matrix.md): stable packet and endpoint inventory.
- [tests/README.md](tests/README.md): server test ownership and fixture guidance.
