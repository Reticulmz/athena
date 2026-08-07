# CLAUDE.md

Claude Code reads this file, then imports the shared agent guidance.

@AGENTS.md

## Claude Code

- Keep durable project rules in `AGENTS.md` or the nearest scoped `AGENTS.md`.
  Keep this file for Claude-specific behavior only.
- Run `/context` when instruction loading looks wrong, then verify that
  `CLAUDE.md` and imported `AGENTS.md` files are present.
- Avoid large `@` imports here. Imported files load at session start and spend
  context even when the task does not need them.
- Remember that per-worktree `.state/` and `.venv/` are generated state.
- Use Serena for code structure reads, GitNexus for impact checks when
  available, and Context7 before relying on external library or cloud API
  details.
