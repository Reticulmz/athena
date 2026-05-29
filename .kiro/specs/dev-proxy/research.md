# Research & Design Decisions

## Summary
- **Feature**: `dev-proxy`
- **Discovery Scope**: Simple Addition（インフラ設定）
- **Key Findings**:
  - stable クライアントの `-devserver` はポート 80/443 固定。カスタムポート指定不可
  - WSL2 で非 root ポート 80 バインドは `sysctl net.ipv4.ip_unprivileged_port_start=80` で解決
  - devenv の `services.nginx` よりも `processes.nginx` + 手書き conf が柔軟

## Research Log

### osu! stable -devserver のポート制約
- **Context**: ローカル開発でポート 80 以外を使えるか
- **Sources**: bancho.py, ripple, titanic 等のプライベートサーバープロジェクト
- **Findings**:
  - `-devserver example.com` はドメインのみ指定可能。ポートは 80/443 固定
  - 全プライベートサーバーが nginx/caddy リバースプロキシを使用している
- **Implications**: nginx を :80 で listen し athena :8000 に転送する構成が必須

### WSL2 での非特権ポート 80 バインド
- **Context**: devenv プロセスを root なしで :80 にバインドする方法
- **Findings**:
  - `setcap` は nix store の immutable バイナリに使用不可
  - `sysctl net.ipv4.ip_unprivileged_port_start=80` で WSL2 カーネルパラメータ変更可能
  - WSL2 の `localhostForwarding=true`（デフォルト）で Windows ↔ WSL2 のポート転送は自動
- **Implications**: devenv.nix の processes.nginx exec で sysctl を先に実行

### devenv nginx 統合方式
- **Context**: `services.nginx` vs `processes.nginx`
- **Findings**:
  - `services.nginx` は virtualHosts 抽象化が厚く、osu! のサブドメインパターンに不適
  - `processes.nginx` + 手書き conf なら完全制御可能
  - conf ファイルをリポジトリに置けば devenv 以外でも使える
- **Implications**: `nginx.dev.conf` を手書きし `processes.nginx` で起動

## Design Decisions

### Decision: ハードコード conf
- **Context**: nginx.dev.conf にポートやドメインを変数化するか
- **Selected**: ハードコード（`proxy_pass http://127.0.0.1:8000`、`server_name *.athena.local`）
- **Rationale**: 直接読める、devenv 以外でも使える、変更頻度が極低

### Decision: ヘルスチェックのバージョン表示
- **Context**: GET / で返す情報の取得方法
- **Selected**: `importlib.metadata.version("athena")` + `git rev-parse --short HEAD`（起動時に1回取得）
- **Rationale**: バージョンは標準ライブラリで追加依存なし、コミットハッシュは開発中の動作確認に実用的

## Risks & Mitigations
- **sysctl 権限**: 初回 `sudo` が必要。WSL2 セッション中は維持される。回避不可能だがコスト最小
- **Windows hosts 編集権限**: 管理者権限が必要。hosts.example で手順を明示
