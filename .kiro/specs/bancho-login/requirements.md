# Requirements Document

## Introduction

osu! stable クライアントのアカウント登録およびログインフローを実装する。プレイヤーがゲーム内からアカウントを作成し、ログインしてセッションを確立し、サーバーとの接続を維持できるようにする。bancho-protocol（パケット基盤）と foundation（DI, DB, Redis, config）の上に構築する。

## Boundary Context
- **In scope**: アカウント登録（`POST /users`、リアルタイムバリデーション含む）、ログイン認証（`POST /`）、ログイン応答パケットストリーム、ポーリング stub（空レスポンス返却）、User モデル・永続化、RBAC（ロール・権限計算・クライアントフラグ変換）、セッション管理（作成・TTL・延長・再ログイン時の旧セッション破棄）、国判定（Cloudflare ヘッダ）、パスワードセキュリティ（argon2id(md5) ハッシュ・HIBP・カスタム禁止リスト）、登録バリデーション（本家準拠）、client_info パース・保存、禁止ユーザー名の DB 管理
- **Out of scope**: ポーリングでの C2S パケット処理（次 spec）、チャット、プレゼンス配信、ban/restrict チェック、GeoIP フォールバック、メール認証フロー・メール送信、RBAC 管理機能（ロール CRUD UI）、ログインエラーコード -2（バージョン）/ -3,-4（BAN）/ -6（サポーター専用）/ -7（パスワードリセット）の分岐処理、レート制限
- **Adjacent expectations**:
  - bancho-protocol が提供する S2C パケットビルダー関数群および PacketDispatcher が利用可能であること
  - foundation が提供する DI コンテナ、SessionStore（Redis/InMemory）、DB エンジン、AppConfig が利用可能であること

## Requirements

### Requirement 1: アカウント登録

**Objective:** As a プレイヤー, I want ゲーム内の登録フォームからアカウントを作成したい, so that サーバーにログインしてプレイできるようになる

#### Acceptance Criteria

1. When プレイヤーがユーザー名・メールアドレス・パスワードを含む登録リクエストを送信した場合, athena shall アカウントを作成し、成功レスポンスとして `ok` を返却する
2. When アカウント作成が成功した場合, athena shall ユーザーにデフォルトロールを自動的に付与する
3. When アカウント作成が成功した場合, athena shall ユーザー名の正規化済みバージョン（小文字化 + スペース→アンダースコア変換）を保存する
4. If バリデーションエラーが1つ以上存在する場合, then athena shall フィールド別のエラーメッセージを含むエラーレスポンスを返却し、アカウントは作成しない
5. If ユーザー名が既に使用されている場合（正規化後の一致で判定）, then athena shall ユーザー名重複エラーを返却する
6. If メールアドレスが既に使用されている場合, then athena shall メール重複エラーを返却する
7. If ユーザー名が禁止ユーザー名リストに含まれる場合, then athena shall ユーザー名使用不可エラーを返却する

### Requirement 2: 登録リアルタイムバリデーション

**Objective:** As a プレイヤー, I want 登録フォーム入力中にバリデーション結果を即座に確認したい, so that 送信前に問題を修正できる

#### Acceptance Criteria

1. When バリデーションのみモード（`check=1`）で登録リクエストを受信した場合, athena shall 全バリデーションルールを適用し、結果を返却するが、アカウントは作成しない
2. When 作成モード（`check=0`）で登録リクエストを受信した場合, athena shall バリデーション通過後にアカウントを作成する
3. The athena shall バリデーションのみモードと作成モードで同一のバリデーションルールを適用する

### Requirement 3: 登録入力バリデーション

**Objective:** As a サーバー運営者, I want 登録入力値を厳密に検証したい, so that 不正・脆弱なアカウント作成を防止できる

#### Acceptance Criteria

1. athena shall ユーザー名を 2〜15文字に制限し、使用可能文字を英数字・アンダースコア・スペース・ハイフン（`[a-zA-Z0-9_ -]+`）とする
2. If ユーザー名にスペースとアンダースコアが同時に含まれる場合, then athena shall バリデーションエラーを返却する
3. athena shall パスワードを 8〜32文字に制限する
4. If パスワードに含まれるユニーク文字数が4未満の場合, then athena shall バリデーションエラーを返却する
5. athena shall メールアドレスの形式を標準的なパターンで検証する
6. athena shall 禁止ユーザー名リストを永続化し、サーバー再起動後も維持する

### Requirement 4: パスワードセキュリティ

**Objective:** As a サーバー運営者, I want パスワードを安全に保存・照合し、漏洩済みパスワードの使用を防ぎたい, so that ユーザーアカウントのセキュリティを確保できる

#### Acceptance Criteria

1. When アカウント登録時にパスワードを受信した場合, athena shall パスワードを MD5 ハッシュに変換した上で argon2id でハッシュして保存する
2. When ログイン時にクライアントから MD5 ハッシュ化されたパスワードを受信した場合, athena shall 保存済みの argon2id ハッシュと照合して認証を行う
3. athena shall 平文パスワードおよび MD5 ハッシュをデータベースに永続化しない
4. If 登録時にパスワードが HIBP（Have I Been Pwned）データベースに漏洩パスワードとして登録されている場合, then athena shall 漏洩パスワードである旨のエラーを返却する
5. If HIBP API に到達できない場合, athena shall カスタム禁止パスワードリストのみでチェックを実施し、登録処理を継続する
6. athena shall カスタム禁止パスワードリストを管理可能にする

### Requirement 5: ログイン認証

**Objective:** As a プレイヤー, I want ゲームクライアントからユーザー名とパスワードでログインしたい, so that サーバーに接続してセッションを確立できる

#### Acceptance Criteria

1. When プレイヤーがユーザー名・MD5 パスワード・client_info を含むログインリクエストを送信した場合, athena shall 認証情報を検証し、成功時にセッションを作成する
2. When 認証が成功した場合, athena shall セッショントークンを `cho-token` レスポンスヘッダとして返却する
3. When ログインリクエストを受信した場合, athena shall client_info（osu_version, utc_offset, display_city, client_hashes, pm_private）の全フィールドをパースしてセッションデータに保存する
4. If ユーザーが存在しない、またはパスワードが不一致の場合, then athena shall 認証失敗（コード -1）を返却する（原因を区別しない）
5. If サーバー内部エラーが発生した場合, then athena shall サーバーエラー（コード -5）を返却する
6. athena shall ログインエラーコードとして -1〜-7 の全コードを定義し、この spec で未実装のコード（-2, -3, -4, -6, -7）はプレースホルダーとして保持する
7. When 同一エンドポイントにリクエストを受信した場合, athena shall `cho-token` ヘッダの有無でログインリクエストとポーリングリクエストを判別する
8. When 既にログイン中のユーザーが再度ログインした場合, athena shall 既存のセッションを破棄し、新しいセッションを作成する（シングルセッション、後勝ち）

### Requirement 6: ログイン応答パケットストリーム

**Objective:** As a プレイヤー, I want ログイン成功時にクライアントが接続状態を正しく表示してほしい, so that サーバーに接続できたことを確認できる

#### Acceptance Criteria

1. When 認証が成功した場合, athena shall ユーザー ID を含む login_reply パケットを返却する
2. When 認証が成功した場合, athena shall protocol_version パケットを返却する
3. When 認証が成功した場合, athena shall ユーザーの有効権限から変換したクライアント用フラグを含む login_permissions パケットを返却する
4. When 認証が成功した場合, athena shall ログインユーザー自身の user_presence パケット（utc_offset および検出された国コードを含む）を返却する
5. When 認証が成功した場合, athena shall ログインユーザー自身の user_stats パケットを返却する（統計値は初期値）
6. When 認証が成功した場合, athena shall channel_info パケットおよび channel_info_end パケットを返却する
7. When 認証が成功した場合, athena shall friends_list パケットを返却する（空リスト）
8. When 認証が成功した場合, athena shall silence_end パケットを返却する（サイレンス期間 0）
9. When 認証が成功した場合, athena shall user_presence_bundle パケットを返却する
10. athena shall 全応答パケットを単一のバイナリストリームとして結合し、レスポンスボディとして返却する

### Requirement 7: 接続維持（ポーリング stub）

**Objective:** As a プレイヤー, I want ログイン後もクライアントが接続状態を維持してほしい, so that サーバーから即座に切断されない

#### Acceptance Criteria

1. When `cho-token` ヘッダ付きのポーリングリクエストを受信した場合, athena shall セッションの存在を確認し、空のレスポンスボディを返却する
2. When 有効なポーリングリクエストを受信した場合, athena shall セッションの有効期限を延長する
3. If `cho-token` に対応するセッションが存在しない場合, then athena shall 再ログインを促すレスポンスを返却する
4. While セッションに対するポーリングが一定時間途絶えた場合, athena shall セッションを自動的に失効させる

### Requirement 8: ロールベースアクセス制御（RBAC）

**Objective:** As a サーバー運営者, I want ユーザーの権限をロールベースで柔軟に管理したい, so that 将来的な権限拡張や管理 UI 追加に対応できる

#### Acceptance Criteria

1. athena shall ユーザーに複数のロールを割り当て可能にする
2. athena shall 各ロールにビットフラグ形式の権限セットを持たせる
3. When ユーザーの有効権限を計算する場合, athena shall 割り当てられた全ロールの権限を OR 結合して算出する
4. athena shall ロールに順序（position）を持たせ、ロール階層を表現可能にする
5. When ログイン応答の login_permissions パケットを構築する場合, athena shall 内部権限をクライアントが理解するフラグ形式（Normal, Moderator, Supporter, Peppy, Developer）に変換する
6. athena shall 初期ロール（デフォルトロール、管理者ロール等）をデータベース初期化時に作成する
7. athena shall メール未認証状態を権限モデル内で表現可能にする（この spec ではメール認証をスキップし、登録時に即アクティブとする）

### Requirement 9: 国判定

**Objective:** As a プレイヤー, I want ログイン時に自分の国が正しく検出されてほしい, so that プロフィールに正確な国旗が表示される

#### Acceptance Criteria

1. When ログインリクエストを受信した場合, athena shall リクエストヘッダからプレイヤーの国コードを検出する
2. When 国コードが検出できた場合, athena shall user_presence パケットの country フィールドに反映する
3. If 国コードがリクエストヘッダから取得できない場合, then athena shall 国コードを「不明」として処理する

### Requirement 10: セッション管理

**Objective:** As a プレイヤー, I want セッションが安定して維持され、意図しない切断が起きないでほしい, so that 快適にプレイし続けられる

#### Acceptance Criteria

1. When ログインが成功した場合, athena shall ログイン時にパースした全データ（ユーザー情報、client_info、国コード等）をセッションに格納する
2. athena shall セッションに TTL（有効期限）を設定し、ポーリングのたびに TTL を延長する
3. When 既にログイン中のユーザーが再ログインした場合, athena shall 古いセッションを破棄してから新しいセッションを作成する
4. If セッションが TTL 期限切れで失効した場合, then athena shall 関連するセッションデータを自動的に削除する
