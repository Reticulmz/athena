# CLAUDE.md

Claude Code 向けのプロジェクト固有設定。汎用エージェント向けルールは AGENTS.md に記載。

@AGENTS.md

## Claude Code 固有

### 開発環境

- 環境構築: `nix develop` (direnv による自動ロードも可)
- サービス起動: `process-compose up`
- Python venv は `uv sync` が `.venv/` に自動作成 (per-worktree)
- 共有状態 (postgres, valkey, nginx) はメインリポジトリの `.state/` に配置
- pre-commit フック: `prek run --all-files`

### Worktree 運用

- `nix develop` + `nix-direnv` により worktree 間で Nix 評価結果がキャッシュされ、切り替えが高速
- `.state/` はメインリポジトリルートに配置し全 worktree で共有
- `.venv/` は各 worktree のローカルに作成される

### MCP ツール

- GitNexus: 変更前に `impact()` でブラストレディアスを確認
- Serena: コード読解は `get_symbols_overview` から開始
- Context7: ライブラリ利用前に最新ドキュメントを取得
