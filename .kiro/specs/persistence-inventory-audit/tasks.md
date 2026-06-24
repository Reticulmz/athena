# Implementation Plan

> **Docs-audit exemption**: This spec is a documentation-only audit. "Deliverable" means markdown table updates and cross-reference sections, not code artifacts. All tasks produce docs changes to `docs/stable-compatibility-matrix.md` and evidence records in `.kiro/specs/persistence-inventory-audit/research.md`. No `src/`, `tests/`, or `alembic/` changes are produced.

- [x] 1. Evidence gathering from existing Athena code
- [x] 1.1 Read existing domain modules, SQLAlchemy models, and alembic migrations to establish the evidence base for each Persistence Inventory row
  - Read `src/osu_server/domain/` module structure (identity, chat, beatmaps, scores, storage) and record module-level file inventory
  - Read `src/osu_server/repositories/sqlalchemy/models/` for all table definitions and column coverage
  - Read `alembic/versions/` migration files for schema evolution history
  - Record which durable facts are covered by existing tables and which are missing, per Persistence Inventory area
  - Identify any durable data in existing Athena models that has no corresponding Persistence Inventory row; record as new row candidate
  - Done: evidence summary exists in `research.md` for all 13 Persistence Inventory areas, including new row candidates if any
  - _Requirements: 1.1, 1.2, 1.4, 3.1, 7.1, 7.2_
  - _Boundary: 調査ログ_

- [x] 2. Audit Partial rows (existing code covers some facts)
- [x] 2.1 Audit Identity/login and Permissions/moderation rows
  - Compare existing user, role models against the durable facts listed in the table
  - Update domain owner to module level (e.g. `identity/users.py`, `identity/roles.py`, `identity/authentication.py`)
  - Record gap: activation, supporter/donor, latest activity (note: durable, throttled write), profile projection
  - Record gap: infringement history, report/audit logs, moderation audit
  - Update status to reflect actual code coverage
  - Done: Identity and Permissions rows have module-level owner, accurate status, and durable-fact-level gap entries
  - _Requirements: 1.1, 2.1, 3.1, 3.2, 4.1, 4.5, 4.6, 7.1, 7.2_
  - _Boundary: テーブル行更新_

- [x] 2.2 Audit Social graph and Chat/channels rows
  - Compare existing friend, channel models against table facts
  - Update domain owner (e.g. `identity/friends.py`, `chat/channels.py`)
  - Record gap: blocks, read-state for social; history, filters for chat
  - Done: Social and Chat rows have module-level owner, accurate status, and gap entries
  - _Requirements: 1.1, 2.1, 3.1, 3.2, 4.1, 7.1, 7.2_
  - _Boundary: テーブル行更新_

- [x] 2.3 Audit Beatmaps and Scores/leaderboard rows
  - Compare existing beatmap, beatmap_leaderboard, score, score_performance, personal_best models
  - Update domain owner (e.g. `beatmaps/models.py`, `scores/score.py`, `scores/leaderboards.py`)
  - Record gap: osu!direct, ratings, comments, favourites for beatmaps; RX/AP family, complete rows for scores
  - Note leaderboard projection as "read model rebuilt from scores"
  - Done: Beatmaps and Scores rows have module-level owner, accurate status, read model annotation, and gap entries
  - _Requirements: 1.1, 2.1, 2.4, 3.1, 3.2, 4.1, 6.4, 7.1, 7.2, 8.1_
  - _Boundary: テーブル行更新_

- [x] 2.4 Audit User stats/rankings and Replays/media metadata rows
  - Compare existing models for stats projection and replay_file_attachments, blob
  - Identify dual-owner situation in both rows
  - Record gap: rank projection, rank history for stats; screenshot/avatar metadata for replays
  - Done: Both rows have accurate status and dual-owner annotation with primary/dependency distinction
  - _Requirements: 1.1, 2.1, 2.4, 3.1, 3.2, 4.1, 7.1, 7.2_
  - _Boundary: テーブル行更新_

- [x] 3. Audit Missing rows (no existing code)
- [x] 3.1 Audit Client integrity and Static/media delivery rows
  - Assign provisional owner: "integrity: client hash validation", "storage: asset delivery routing"
  - Record all facts as missing with stable behavior references
  - Link to existing Issues where applicable (#29 client integrity, #21 static/media)
  - Done: Both rows have provisional owner in "domain: responsibility" format, Missing status, and fact-level gap entries
  - _Requirements: 1.1, 2.2, 2.3, 3.3, 4.1, 4.2, 4.3, 7.1_
  - _Boundary: テーブル行更新_

- [x] 3.2 Audit Release/update and Ratings/comments/favourites rows
  - Assign provisional owner for release/update area: "release: update policy and artifact delivery"
  - For ratings/comments/favourites, verify comment target type in reference implementations
  - Search bancho.py and lets for `/web/osu-comment.php` target parameter usage to determine if target is beatmap-only
  - If target is beatmap-only in stable scope, assign to `beatmaps`; otherwise note need for independent aggregate
  - Link to existing Issues (#25 release/update)
  - Done: Both rows have provisional owner (ratings with reference-backed decision), Missing status, and gap entries with Issue links
  - _Requirements: 1.1, 2.2, 2.3, 3.3, 4.1, 7.3, 7.4_
  - _Boundary: テーブル行更新_

- [x] 3.3 Audit Achievements/notifications and Multiplayer/tournaments rows
  - Assign provisional owner: "achievements: unlock and badge model", "multiplayer: match and tournament audit"
  - Record all facts as missing
  - Link to existing Issues: #27 multiplayer, #26 moderation (for notification overlap)
  - Done: Both rows have provisional owner, Missing status, and Issue links where applicable
  - _Requirements: 1.1, 2.2, 2.3, 3.3, 4.1, 4.3_
  - _Boundary: テーブル行更新_

- [x] 4. Row splitting, gap linking, and cross-reference
- [x] 4.1 Execute justified row splits
  - Split "User stats and rankings" into "User stats" (owner: scores projection) and "User rankings" (owner: rankings: rank projection and history)
  - Evaluate "Replays and media metadata" split based on evidence from task 2.4; if blob is unified storage, keep as one row with gap annotation
  - Record split reason for each split executed
  - Verify split does not break Area names referenced by sibling audits (#32-#35)
  - Done: Split rows exist in table with documented reasons; sibling audit Area name compatibility confirmed
  - _Requirements: 6.1, 6.2, 6.3, 8.2_
  - _Depends: 2.4_
  - _Boundary: 行分割_

- [x] 4.2 Map gaps to existing Issues and identify new child work
  - Link each gap to existing open Issues #17-#30 where applicable
  - For gaps not covered by existing Issues, describe new child work with epic/task outline at durable-fact granularity
  - Ensure durable/volatile distinction is noted for each gap
  - Done: Every gap entry has either an Issue link or a "new child work" description; no unlinked gaps remain
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 9.4, 9.5_
  - _Depends: 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 4.1_
  - _Boundary: Gap-to-Issue リンク_

- [x] 4.3 Add behavior-based cross-reference section
  - Create cross-reference section after Persistence Inventory Coverage table in `docs/stable-compatibility-matrix.md`
  - Include groups: login, score submit, getscores, replay download, static/media, moderation, multiplayer
  - For each behavior, list dependent durable data Areas and cross-domain dependencies (e.g. friend leaderboard depends on identity/friends and scores/leaderboards)
  - Done: Cross-reference section exists with all 7 behavior groups, each listing Area dependencies and cross-domain links
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 8.3_
  - _Depends: 4.1, 4.2_
  - _Boundary: Behavior クロスリファレンス_

- [x] 5. Validation
- [x] 5.1 Verify audit completeness and boundary compliance
  - Check every row has module-level or provisional owner
  - Check every row has current status backed by code evidence
  - Check no row is marked Implemented without full fact coverage evidence
  - Check Partial-to-Implemented transitions have explicit coverage rationale in gap column
  - Check every Partial/Missing row has durable-fact-level gap entries
  - Check behavior cross-reference covers all 7 required behavior groups
  - Check matrix and guide Persistence Reference Policy have no unaddressed contradictions; note any as unresolved gap
  - Check diff does not include `src/`, `tests/`, or `alembic/` changes
  - Done: All verification checks pass; any matrix/guide contradiction noted as unresolved gap
  - _Requirements: 1.3, 1.4, 3.4, 3.5, 8.1, 8.4, 9.1, 9.2, 9.3_
  - _Boundary: 監査専用境界_
