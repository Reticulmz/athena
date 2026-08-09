# AGENTS.md

Repository-level instructions for coding agents. Keep this file a router:
always-needed rules stay here, area-specific rules live in the nearest scoped
`AGENTS.md` or project skill.

## First Steps

1. Read the files you will change before editing them.
2. Check whether a listed skill directly matches the task. Load only the
   minimum relevant skills.
3. Load scoped guidance before touching these paths:
   - Server: `apps/athena_server/AGENTS.md` for
     `apps/athena_server/**`, server architecture, migrations, transports,
     jobs, or runtime wiring.
   - Crypto: `packages/athena_crypto/AGENTS.md` for
     `packages/athena_crypto/**`.
   - Python: `.agents/skills/athena-python-style/SKILL.md` for first-party
     Python, Python tests, local `.pyi` stubs, or Python lint/type/docstring
     policy.
4. If scoped guidance conflicts with this file, the closer guidance wins for
   files inside its scope.

Completion: every touched path has its scoped instructions loaded before the
first edit.

## Repository Map

- `apps/athena_server`: Python ASGI server, worker, database migrations,
  stable/lazer/API transports, and server tests.
- `packages/athena_crypto`: Rust/Python native extension distributed as
  `athena-crypto` and imported as `athena_crypto`.
- `tools/monorepo_migration`: repository validation and migration audit tools.
- `.kiro/steering` and `.kiro/specs`: steering and spec-driven work.

## Work Loop

- Use `rg` or semantic tools first for search.
- Treat `justfile`, config files, and `--help` output as command sources of
  truth. Run `just --list` when a command is unclear.
- Run project toolchain commands through `nix develop`.
- Run focused checks for narrow edits. For broad edits, prefer
  `just quality`, `just test`, and `just docstrings`.
- Before committing, run `nix develop --command prek run --all-files`.
- Report what changed, what was verified, and any checks not run.

## Core Commands

`just --list` is the command source of truth. These root public recipes are
stable entry points:

```bash
just setup
just dev
just dev-tunnel
just quality
just docstrings
just test
just build
just db-migrate
just migration-check
just audit-monorepo
just process-lifecycle-check
just worktree
```

## Worktrees And PRs

- Use a task worktree when work may run in parallel, touch overlapping files,
  generate artifacts, or involve multiple coding agents.
- Create agent worktrees with `just worktree <task-slug> --agent codex` unless
  custom setup is needed.
- Use repo-sibling paths under `../athena_worktree/` and agent-prefixed
  branches such as `codex/<task-slug>`.
- Keep each agent's changes inside its own worktree. Prefer one owner per file.
- For non-trivial code, test, spec, or multi-file documentation changes, use a
  pull request as the integration boundary.
- Do not merge PRs from the agent environment. The user merges in GitHub Web UI.
- Consider a PR ready only after CI passes, actionable comments are resolved,
  the final diff is reviewed, and relevant local checks have run.
- Do not remove a worktree with uncommitted, unpushed, or unmerged work unless
  the user explicitly approves discarding it.

Primary checkout invariant: `git config --show-origin --get core.worktree`
must return no value. If it points at a linked worktree, unset it before
pulling, stashing, branching, or editing from the primary checkout. If
`git rev-parse --show-toplevel` differs from `pwd -P`, diagnose
`core.worktree` first.

## Change Guardrails

- Ask before irreversible or broad actions such as DB drops, mass deletion,
  force pushes, or large config rewrites.
- Ask before editing project-wide config:
  `pyproject.toml`, `uv.lock`, `.python-version`,
  `apps/athena_server/alembic.ini`, `flake.nix`, `process-compose.yml`, CI,
  hook, linter, type-checker, or import-linter configuration.
- Dependency additions require approval. After approved dependency or
  environment changes, run the matching sync/update command.
- Preserve externally observable stable client and worker behavior unless the
  user explicitly requests a contract change.
- For stable/lazer request, response, packet, endpoint, or realtime shape
  changes, follow the evidence rule in `apps/athena_server/AGENTS.md`.

## Git And Commits

Use Conventional Commits:

```text
<type>[optional scope]: <Japanese description>

[optional body]
```

- Type must be English: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`,
  `test`, `chore`, `build`, `ci`, or `revert`.
- Description is Japanese, max 70 chars, no trailing period.
- Breaking changes append `!` after type, for example `feat!:`.
- Avoid vague descriptions such as `update`, `fix`, `change`, `modify`, `更新`,
  `修正`, `変更`, `対応`, or `wip`.
- Do not bypass hooks with `--no-verify`, `--no-gpg-sign`, or `-n`.
- Agent commits include footer `Agent-Model: <agent product> (<model name>)`;
  use `unknown` when the exact model is unavailable.
- Sequential Kiro task commits include footer
  `Kiro-Task: <spec-name> <task-number>`.

When hooks fail, re-stage formatter changes, retry once, then fix the root
cause if failure remains.

## Spec Work

- Check `.kiro/specs/` before feature work.
- When spawning Kiro sub-agents, use higher-reasoning models for spec
  creation, validation, review, verification, and debugging. Prefer
  `gpt-5.6-sol` with `xhigh` or `max`; use `.codex/agents/kiro-reviewer.toml`
  for task-local implementation review when available.
- For implementation sub-agents, use `gpt-5.5` with `xhigh` by default. Use
  `gpt-5.6-luna` with `xhigh`/`max` only when the user requests Luna, or use
  Sol when task risk justifies it.
- For multi-task Kiro specs, create `spec/<spec-name>` as the integration
  branch first. Branch parallel task worktrees from that spec branch, then
  integrate task branches back into it before opening the final PR to `main`.
- Kiro tasks are parallel only when the task number is marked with `(P)`. For
  unmarked tasks, stay on the spec branch and commit tasks sequentially instead
  of creating per-task worktrees.
- Keep `.kiro/steering/` aligned with implementation decisions.
- Use the Kiro skills in `.agents/skills/kiro-*/SKILL.md` when a Kiro workflow
  applies.
- Follow Requirements -> Design -> Tasks -> Implementation unless the user
  explicitly requests a fast-track path.
- Markdown written to spec files must use the language configured in that
  spec's `spec.json.language`.

## Agent Document Maintenance

- Keep root `AGENTS.md` under 200 lines.
- Move path-specific rules to the nearest scoped `AGENTS.md` or project skill.
- Keep each rule in one source of truth. Point to details instead of duplicating
  them.
- Store facts agents cannot cheaply infer: project contracts, gotchas, required
  checks, and workflow invariants.
- Leave command catalogs, dependency lists, and generated state details in their
  owning files unless the lookup is expensive or failure-prone.
