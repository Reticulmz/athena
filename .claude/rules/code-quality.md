## Code Quality

- **Follow the Rails Way**: Adhere to Rails' philosophy and conventions as the top priority. Before introducing custom implementations or patterns borrowed from other frameworks, always consider the standard Rails solution first.
- Prefer idiomatic Rails conventions and design patterns.
- Prefer Hotwire (Turbo + Stimulus) over heavy JavaScript frameworks.
- Make intent explicit: avoid magic numbers and opaque conditionals.
- Understand root causes; avoid hacky workarounds.
- Avoid designs that become tech debt; prioritize extensibility and readability.
- NEVER hardcode credentials in source files. Use Rails credentials or environment variables.

### Design Principles
- **SOLID**: Single responsibility, Open-closed, Liskov substitution, Interface segregation, Dependency inversion.
- **DRY**: Avoid logic duplication, but favor clarity over forced abstraction.
- **KISS**: Keep it simple. No unnecessary abstraction or complexity.
- **YAGNI**: Do not implement features that are not yet needed.

### Quality Assurance

#### Completion Criteria
- Before reporting "done", critically review your own implementation for overlooked issues.
- Run `bin/rubocop` and relevant tests (`bin/rails test`).
- Only report completion after all checks pass.

#### Self-Review Loop
- After writing code, always review it yourself as if performing a code review.
- Check for: logic errors, edge cases, N+1 queries, security issues, Rails convention violations, readability, test coverage, and adherence to the design principles above.
- If any issues are found, fix them and review again.
- Repeat this review → fix → review loop until no issues remain.
- Only then report the work as complete. Quality is not negotiable — do not stop at "it works".

#### Protect Existing Tests
- When tests fail, suspect the implementation first—not the tests.
- Never casually disable or modify test code.
- If a spec change requires test updates, confirm with the user first.

#### Documentation Sync
- When adding or changing functionality, update related documentation (or propose a documentation task).
