# CLAUDE.md

Claude Code 向けのプロジェクト固有設定。汎用エージェント向けルールは AGENTS.md に記載。

@AGENTS.md

## Claude Code 固有

### 開発環境

- 環境構築: `nix develop` (direnv による自動ロードも可)
- 明示setup: `just setup`
- サービス起動: `just dev`
- tunnel付き起動: `just tunnel-setup` の後に `just dev-tunnel`
- Python venv は `just setup` がworktree-local `.venv/` に作成
- postgres、valkey、nginx、certificate、hook stateはper-worktree `.state/` に配置
- pre-commit フック: `nix develop --command prek run --all-files`

### Worktree 運用

- `nix develop` + `nix-direnv` により worktree 間で Nix 評価結果がキャッシュされ、切り替えが高速
- `.state/` と `.venv/` は各 worktree のローカルに作成される
- hook pathはworktree-local Git configで `.state/hooks` を指す

### MCP ツール

- GitNexus: 変更前に `impact()` でブラストレディアスを確認
- Serena: コード読解は `get_symbols_overview` から開始
- Context7: ライブラリ利用前に最新ドキュメントを取得
