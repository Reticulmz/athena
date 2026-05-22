# Implementation Plan

- [ ] 1. nginx リバースプロキシ設定 + hosts テンプレート

- [x] 1.1 nginx.dev.conf と hosts.example の作成
  - nginx.dev.conf: listen 80、全サブドメイン（c, c1, ce, c4-c6, osu, a, b, api）を単一 server ブロックで受付
  - proxy_pass http://127.0.0.1:8000 で athena に転送、Host ヘッダ保持
  - WebSocket 対応ヘッダ: proxy_http_version 1.1, Upgrade, Connection
  - HTTPS server ブロックをコメントアウト状態で含める（listen 443 ssl、証明書パス placeholder）
  - hosts.example: 全サブドメインの 127.0.0.1 エントリ + mkcert 手順コメント
  - `nginx -t -c nginx.dev.conf` で構文チェックが成功すること（nginx がインストール済みの場合）
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 3.2, 3.3, 5.1, 5.3_

- [ ] 2. config + ヘルスチェックエンドポイント

- [x] 2.1 config.py domain デフォルト変更 + ヘルスチェック実装
  - config.py の domain デフォルトを "localhost" → "athena.local" に変更
  - app.py にバージョン情報取得処理を追加: importlib.metadata.version("athena") + git rev-parse --short HEAD（起動時1回）
  - bancho routes（c.*）と web_legacy routes（osu.*）の GET / にヘルスレスポンスを返すハンドラを追加
  - レスポンス形式: `athena v{version} ({commit_hash})\n`、Content-Type: text/plain
  - ユニットテスト: ヘルスレスポンスにバージョン番号が含まれること、コミットハッシュまたは "unknown" が含まれること
  - `rtk uv run pytest tests/ -x` が全パスすること
  - _Requirements: 3.1, 4.1, 4.2, 4.3_

- [ ] 3. devenv 統合

- [x] 3.1 devenv.nix に nginx プロセスと mkcert パッケージを追加
  - processes.nginx: sysctl で非特権ポート 80 を有効化し、nginx.dev.conf でフォアグラウンド起動
  - after 依存: app プロセスの後に起動
  - error_log を stderr に出力（devenv コンソール表示）
  - packages に mkcert を追加
  - enterShell のメッセージに nginx 起動情報を追加
  - `devenv up` で nginx プロセスが起動することを確認
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 5.2_

- [ ] 4. スモークテスト

- [ ] 4.1 E2E スモークテスト
  - `devenv up` 後に `curl http://c.athena.local/` が 200 + バージョン文字列を返すことを手動確認
  - `curl http://osu.athena.local/` が 200 + バージョン文字列を返すことを手動確認
  - `curl -X POST http://c.athena.local/` がログインレスポンス（パケットストリームまたはエラー）を返すことを手動確認
  - 確認結果をこのタスクのチェックボックスに記録
  - _Requirements: 1.2, 1.3, 2.4, 4.1, 4.2_
  - _Depends: 1.1, 2.1, 3.1_
