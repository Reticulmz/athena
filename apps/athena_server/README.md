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
