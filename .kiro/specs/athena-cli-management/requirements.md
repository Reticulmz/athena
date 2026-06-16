# Requirements Document

## Project Description (Input)
Athena の開発者と運用者は、現在 `devenv tasks run db:test:create` や `python -m osu_server.db create`、`alembic upgrade head` など複数の入口を使い分けてローカル環境、テスト DB、環境ファイルを管理している。今後 `osu_server` を `athena_server` へ rename する前段階として、サーバー本体とは分離された `athena_cli` 境界を追加し、root `pyproject.toml` 管理のまま Typer ベースの管理 CLI に運用タスクを集約する。`devenv` task は新しい `athena` CLI 経由に置き換え、`.env.example` から `.env.development`、`.env.test`、`.env.production` を安全に生成し、DB 作成、マイグレーション、セットアップ、テスト、設定検証を一貫したコマンドで実行できるようにする。

## Requirements
<!-- Will be generated in /kiro-spec-requirements phase -->

### 追加要件: development/test user role management

#### Requirement 13

**User Story:** 運用者として、development/test 環境でユーザーの単一 role を Athena CLI から変更し、ログイン中 session の認可状態にも反映したい。

##### Acceptance Criteria

1. WHEN operator runs `athena dev change-role <username> <role-name> --env development|test` THEN Athena SHALL replace the user's assigned roles with the requested role.
2. WHEN the target user has an active session THEN Athena SHALL refresh that session's privileges and role_ids from the persisted role assignment.
3. WHEN no active session exists THEN Athena SHALL keep the role change successful and report that no active session was refreshed.
4. WHEN the target environment is production THEN Athena SHALL reject the command before loading config or changing state.
5. WHEN the target user is the system user THEN Athena SHALL reject the command and preserve existing role assignments.
