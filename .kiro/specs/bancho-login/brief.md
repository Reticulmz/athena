# Brief: bancho-login

## Problem
stable クライアントが接続してログインし、セッションを確立できないとサーバーとして機能しない。PoC の最小ゴール。

## Current State
foundation で骨格、bancho-protocol でパケット基盤が整った状態。認証ロジックとログインエンドポイントは未実装。

## Desired Outcome
- stable クライアントが POST `/` でログインリクエストを送信できる
- AuthService がユーザー名 + MD5 パスワードを検証できる
- argon2id(md5) でパスワードハッシュを保存・照合できる
- SessionStore (Redis) にセッショントークンを保存できる
- ログイン成功時に S2C パケットストリーム（UserID, ProtocolVersion, ChannelInfo 等）を返却できる
- ログイン失敗時に適切なエラーレスポンスを返却できる
- User ドメインモデルと UserRepository が存在する
- 実際の stable クライアントで接続・ログインが確認できる（E2E）

## Approach
設計書の認証フロー + bancho-documentation Wiki の Login ページに従い実装。POST `/` → body parse → AuthService.login() → SessionStore.create() → S2C packet stream response。

## Scope
- **In**: POST `/` エンドポイント、リクエストボディパース（username\npassword_md5\nclient_info）、AuthService（verify_password, create_session）、User ドメインモデル、UserRepository (Protocol + SQLAlchemy 実装)、SessionStore (Redis)、ログイン応答パケット構築、Alembic マイグレーション（users テーブル）、新規ユーザー自動登録（PoC 用）
- **Out**: ログイン後のパケットポーリング (`GET /`)、チャット、プレゼンス配信、ban/restrict チェック

## Boundary Candidates
- 新規ユーザー自動登録を PoC 限定にするかどうか
- ログイン応答に含めるパケットの最小セット

## Out of Boundary
- パケットポーリングループ（次の spec）
- チャンネル自動参加のビジネスロジック
- プレゼンス通知の他ユーザーへの配信

## Upstream / Downstream
- **Upstream**: foundation (DI, DB, Redis, config), bancho-protocol (パケット定義, ディスパッチ)
- **Downstream**: チャット実装、プレゼンス配信、パケットポーリング

## Existing Spec Touchpoints
- **Extends**: なし
- **Adjacent**: foundation (UserRepository は repositories/ に配置), bancho-protocol (ログイン応答パケット)

## Constraints
- パスワード: stable クライアントは MD5 で送信 → サーバーは argon2id(md5) で保存・照合
- argon2-cffi 使用（passlib 不使用）
- セッショントークンは Redis に保存、TTL 付き
- ログインレスポンスは bancho バイナリパケットストリーム
