## Git Commit Rules

### Format: Conventional Commits
```
<type>[optional scope]: <description>

[optional body]
```

- **Type** (English): `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`, `build`, `ci`, `revert`
- **Description**: Max 50 chars, no trailing period, in Japanese.
- **Body** (optional): Blank line before body; describe reason, context, and impact.
- **Breaking changes**: Append `!` after type (e.g., `feat!:`).

### Commit Message Proposals
- Include file count summary (X added, Y modified, Z deleted) alongside the file list.
- Helps user verify correct staging in IDE.

### Prohibited
- Emoji, slang, vague wording (`update`, `fix`, `change`, `modify`, `更新`, `修正`, `変更`, `対応`, `wip`)
- One commit per change; propose splitting if spanning multiple types.
