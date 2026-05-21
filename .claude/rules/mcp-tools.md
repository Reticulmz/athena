## MCP Tools

### Context7

- Fetch latest docs via Context7 before using/introducing any library.
- Never rely solely on training data. APIs may have changed.

### Serena

- Activate "keebdb" with `activate_project` at conversation start.
- First choice for code reading: `get_symbols_overview` → `find_symbol` → `find_referencing_symbols` → `search_for_pattern`.
- Read entire files only as last resort. Get symbol overview first, then read specific parts with `include_body=True`.
- For edits: `replace_symbol_body`, `insert_before_symbol`, `insert_after_symbol`.
- Check `read_memory` for project-specific information.
