## Code Quality

- **Follow established patterns**: 既存のコードベースの慣習とアーキテクチャパターンを最優先。独自実装を導入する前に、既存の解決策を確認する。
- Prefer idiomatic Python and async-first patterns.
- Make intent explicit: avoid magic numbers and opaque conditionals.
- Understand root causes; avoid hacky workarounds.
- Avoid designs that become tech debt; prioritize extensibility and readability.
- NEVER hardcode credentials in source files. Use pydantic-settings (AppConfig) or environment variables.

### Design Principles
- **SOLID**: Single responsibility, Open-closed, Liskov substitution, Interface segregation, Dependency inversion.
- **DRY**: Avoid logic duplication, but favor clarity over forced abstraction.
- **KISS**: Keep it simple. No unnecessary abstraction or complexity.
- **YAGNI**: Do not implement features that are not yet needed.
- **Library-first**: 車輪の再発明を避ける。機能を追加する前に以下の順で検討する:
  1. 目的を達成できる定評あるライブラリが存在するか探す
  2. プロジェクトの依存関係に既に含まれていないか確認する
  3. 上記いずれも存在しない場合のみ、自前実装する
  - 新規ライブラリ導入時は、プロジェクトに適切で思想が一致しているか独断せず、ユーザーの承認を得てから `uv add` する

### Quality Assurance

#### Completion Criteria
- Before reporting "done", critically review your own implementation for overlooked issues.
- Run `basedpyright src/`, `ruff check src/`, `ruff format --check src/`, and relevant tests (`pytest tests/`).
- Only report completion after all checks pass.

#### Self-Review Loop
- After writing code, always review it yourself as if performing a code review.
- Check for: logic errors, edge cases, security issues, layer violation (import-linter), type safety (basedpyright), readability, test coverage, and adherence to the design principles above.
- If any issues are found, fix them and review again.
- Repeat this review → fix → review loop until no issues remain.
- Only then report the work as complete. Quality is not negotiable — do not stop at "it works".

#### Protect Existing Tests
- When tests fail, suspect the implementation first—not the tests.
- Never casually disable or modify test code.
- If a spec change requires test updates, confirm with the user first.

#### Documentation Sync
- When adding or changing functionality, update related documentation (or propose a documentation task).
