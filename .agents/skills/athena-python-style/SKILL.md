---
name: athena-python-style
description: Athena Python implementation style. Use before writing, editing, reviewing, or debugging first-party Python, Python tests, local .pyi stubs, migrations, or Python lint/type/docstring policy in this repository.
---

# Athena Python Style

Read [../../../docs/agent-python.md](../../../docs/agent-python.md) before the
first Python edit. That file is the source of truth for Athena Python style,
docstrings, type safety, stubs, and lint policy.

Apply these defaults while reading it:

- Target Python 3.14+ for new first-party Python.
- Do not write new code as if Python 3.11 or 3.12 were the style ceiling.
- Prefer modern type syntax and tools: built-in generics, `|`, `type`
  statements, `typing.Self`, `typing.override`, `typing.TypeIs`, and
  `typing.ReadOnly`.
- Prefer `match`/`case` for closed, shape-driven branching; keep `if`/`elif`
  for simple predicates and range checks.
- Avoid compatibility shims for Python versions below 3.14.

Completion: `docs/agent-python.md` has been read, scoped `AGENTS.md` files for
touched paths have been read, and Python changes follow the 3.14+ policy.
