# Requirements Document

## Introduction

osu! bancho 互換のチャットシステムを構築する。DB 管理のパブリック常設チャンネル、プライベートメッセージ（PM）、内蔵 BanchoBot とコマンドシステムを実装し、bancho バイナリプロトコル経由でのチャット送受信を完全に動作させる。ChatService をプロトコル非依存のオーケストレーターとして設計し、将来の IRC サーバー・Bot API・Lazer/WebUI 対応への拡張を可能にする。

## Boundary Context

- **In scope**:
  - パブリック常設チャンネルの DB 管理（CRUD）
  - ロールベースのチャンネルアクセス制御（read / write / manage の3権限）
  - チャンネル参加・離脱・メッセージ配信
  - プライベートメッセージ（PM）送受信
  - 全メッセージの非同期 DB 永続化
  - 内蔵 BanchoBot（予約ユーザー）と CommandService フレームワーク
  - 初期コマンド: `!roll`, `!help`
  - Rate Limit（自動スパム防止）と Silence チェック（発言禁止）
  - ログインフローの動的チャンネルリスト送信
  - ユーザー切断時のチャンネルメンバーシップ掃除
  - C2S 4パケット + S2C 3パケット新規実装

- **Out of scope**:
  - マルチプレイ / スペクテイター用一時チャンネル → 各システムの spec で ChannelService を呼び出す設計
  - IRC サーバー実装 → 別 spec（irc-server）
  - 外部 Bot 接続用 API → 別 spec（bot-api）
  - チャンネル管理 REST API エンドポイント → 別 spec（channel-management-api）
  - メッセージ履歴取得 API（Lazer / WebUI 向け）→ 別 spec（chat-history-api）
  - WebUI → 別リポジトリ
  - Silence 付与・解除の管理操作 → 別 spec（moderation-system）
  - Channel Ban / Global Ban → 別 spec（moderation-system）
  - `!where`, `!stats`, `!report`, `!mp` 等の追加コマンド → 各依存システム実装後に追加

- **Adjacent expectations**:
  - SessionStore（既存）がユーザー別セッション管理を提供すること
  - PacketQueue（既存）がユーザー別 S2C パケットバッファを提供すること
  - EventBus（既存）がドメインイベントの発火と購読を提供すること
  - PermissionService（既存）がユーザーの Privileges 算出を提供すること
  - PacketDispatcher（既存）がハンドラの登録と呼び出しを提供すること
  - LifecycleListeners / UserDisconnected イベント（既存）がユーザー切断通知を提供すること
  - OnlineUsersService（既存）がオンラインユーザー列挙を提供すること
  - taskiq ワーカー基盤（既存）がジョブキューを提供すること

## Requirements

### Requirement 1: チャンネル定義と管理

**Objective:** As a サーバー管理者, I want チャンネルを DB で動的に作成・変更・削除したい, so that サーバー運用中にチャンネル構成を柔軟に変更できる

#### Acceptance Criteria

1. The Bancho server shall チャンネルを名前・トピック・権限・自動参加フラグ・レートリミット設定を持つエンティティとして管理する
2. The Bancho server shall チャンネルの作成・取得・更新・削除操作をサービス層で提供する
3. The Bancho server shall チャンネル名を `#` で始まる英小文字・数字・アンダースコア・ハイフンの組み合わせに制限する
4. If 既に存在するチャンネル名で作成を試みた場合, the Bancho server shall エラーを返す
5. The Bancho server shall チャンネル種別を識別する列挙型を定義する（PUBLIC を実装、MULTIPLAYER / SPECTATOR / TEMPORARY は将来用に予約）
6. The Bancho server shall 初期シードとして `#osu`（自動参加、全員 read/write）と `#announce`（自動参加、read: 全員、write: 管理者のみ）を提供する

### Requirement 2: チャンネルアクセス制御

**Objective:** As a サーバー管理者, I want チャンネルごとに閲覧・書き込み・管理の権限を設定したい, so that 権限を持つユーザーのみが適切なチャンネルにアクセスできる

#### Acceptance Criteria

1. The Bancho server shall チャンネルごとに read_privileges・write_privileges・manage_privileges の3つの権限レベルを持つ
2. The Bancho server shall 各権限レベルを既存の Privileges ビットフラグで表現する
3. When ユーザーがチャンネルへの参加をリクエストした場合, the Bancho server shall ユーザーの権限と read_privileges のビット演算で参加可否を判定する
4. When ユーザーがチャンネルにメッセージを送信した場合, the Bancho server shall ユーザーの権限と write_privileges のビット演算で送信可否を判定する
5. When ユーザーがチャンネルのトピック変更等の管理操作を実行した場合, the Bancho server shall ユーザーの権限と manage_privileges のビット演算で操作可否を判定する
6. When ユーザーが read_privileges を満たさないチャンネルへの参加をリクエストした場合, the Bancho server shall チャンネル拒否通知を返す

### Requirement 3: チャンネル参加と離脱

**Objective:** As a osu! クライアント, I want チャンネルに参加・離脱したい, so that 会話に参加したり退出したりできる

#### Acceptance Criteria

1. When クライアントから JOIN_CHANNEL パケット（ClientPacketID = 63）を受信した場合, the Bancho server shall 権限チェック後にユーザーをチャンネルメンバーとして登録する
2. When チャンネル参加が成功した場合, the Bancho server shall CHANNEL_JOIN_SUCCESS パケット（ServerPacketID = 64）を当該ユーザーに送信する
3. When クライアントから LEAVE_CHANNEL パケット（ClientPacketID = 78）を受信した場合, the Bancho server shall ユーザーをチャンネルメンバーから削除する
4. When チャンネル離脱が成功した場合, the Bancho server shall CHANNEL_REVOKED パケット（ServerPacketID = 66）を当該ユーザーに送信する
5. If 存在しないチャンネルへの参加がリクエストされた場合, the Bancho server shall CHANNEL_REVOKED パケットを返す
6. If 既に参加済みのチャンネルへの参加がリクエストされた場合, the Bancho server shall エラーなく冪等に処理する
7. The Bancho server shall チャンネルごとの現在参加者数を動的に算出して提供する

### Requirement 4: チャンネルメッセージ配信

**Objective:** As a osu! クライアント, I want チャンネルにメッセージを送信し、他のメンバーからのメッセージを受信したい, so that リアルタイムでチャットできる

#### Acceptance Criteria

1. When クライアントから SEND_MESSAGE パケット（ClientPacketID = 1）を受信した場合, the Bancho server shall メッセージを送信者以外のチャンネルメンバー全員に S2C SEND_MESSAGE パケット（ServerPacketID = 7）で配信する
2. When チャンネルメッセージが送信された場合, the Bancho server shall 送信者名・メッセージ内容・チャンネル名・送信者 ID を含むパケットを配信する
3. If ユーザーが参加していないチャンネルにメッセージを送信した場合, the Bancho server shall メッセージを棄却する
4. If ユーザーが write_privileges を満たさないチャンネルにメッセージを送信した場合, the Bancho server shall メッセージを棄却する

### Requirement 5: プライベートメッセージ

**Objective:** As a osu! クライアント, I want 他のユーザーに直接メッセージを送りたい, so that 個別にコミュニケーションできる

#### Acceptance Criteria

1. When クライアントから SEND_PRIVATE_MESSAGE パケット（ClientPacketID = 25）を受信した場合, the Bancho server shall メッセージを宛先ユーザーに S2C SEND_MESSAGE パケットで配信する
2. When 宛先ユーザーがオンラインの場合, the Bancho server shall メッセージをリアルタイムで配信する
3. When 宛先ユーザーがオフラインの場合, the Bancho server shall メッセージを永続化のみ行い、エラーを送信者に返さない
4. If 存在しないユーザー宛に PM を送信した場合, the Bancho server shall 送信者にエラー通知を返す

### Requirement 6: メッセージ永続化

**Objective:** As a サーバー運営者, I want 全てのチャットメッセージを永続的に保存したい, so that メッセージ履歴の閲覧やモデレーション対応に利用できる

#### Acceptance Criteria

1. When チャンネルメッセージが送信された場合, the Bancho server shall メッセージを非同期にデータベースへ永続化する
2. When プライベートメッセージが送信された場合, the Bancho server shall メッセージを非同期にデータベースへ永続化する
3. The Bancho server shall チャンネルメッセージとプライベートメッセージを別々のテーブルに格納する
4. The Bancho server shall メッセージの永続化処理がリアルタイム配信の速度に影響を与えないこと
5. The Bancho server shall 宛先ユーザーがオフラインの PM も永続化する

### Requirement 7: BanchoBot

**Objective:** As a osu! クライアント, I want サーバー内蔵の Bot がコマンドに応答したい, so that ゲーム情報の取得やユーティリティ機能が使える

#### Acceptance Criteria

1. The Bancho server shall 予約ユーザー（user_id = 1, username = "BanchoBot"）としてシステム Bot を管理する
2. The Bancho server shall BanchoBot ユーザーを通常のログイン認証では使用不可にする
3. When BanchoBot がメッセージを送信する場合, the Bancho server shall BanchoBot の user_id と username を送信者情報として使用する

### Requirement 8: コマンドシステム

**Objective:** As a osu! クライアント, I want `!` プレフィックスのコマンドを実行したい, so that チャット内からユーティリティ機能を利用できる

#### Acceptance Criteria

1. When `!` で始まるメッセージを受信した場合, the Bancho server shall コマンドとして解釈し、登録済みのコマンドハンドラに委譲する
2. When コマンドメッセージが送信された場合, the Bancho server shall コマンドメッセージ自体も他のチャンネルメンバーに配信する
3. When `!roll` コマンドを受信した場合, the Bancho server shall 0 から指定された最大値（デフォルト 100）までのランダムな整数を BanchoBot から返信する
4. When `!help` コマンドを受信した場合, the Bancho server shall 利用可能なコマンド一覧を BanchoBot から返信する
5. When チャンネルでコマンドが実行された場合, the Bancho server shall BanchoBot の応答を同じチャンネルに送信する
6. When PM でコマンドが実行された場合, the Bancho server shall BanchoBot の応答を PM で送信者に返信する
7. If 未登録のコマンドが実行された場合, the Bancho server shall 「不明なコマンド」メッセージを BanchoBot から返信する
8. The Bancho server shall コマンドハンドラをデコレータまたは登録パターンで追加可能にする

### Requirement 9: Rate Limit

**Objective:** As a サーバー運営者, I want チャットのスパムを自動的に防止したい, so that チャット品質が維持される

#### Acceptance Criteria

1. The Bancho server shall 一定時間内のメッセージ送信数を制限する
2. The Bancho server shall Rate Limit のデフォルト値をサーバー設定で指定可能にする
3. Where チャンネルに個別の Rate Limit 設定がある場合, the Bancho server shall サーバーデフォルトよりチャンネル固有の設定を優先する
4. If ユーザーが Rate Limit を超過した場合, the Bancho server shall 超過分のメッセージを静かに棄却する
5. The Bancho server shall Rate Limit をチャンネルメッセージと PM の両方に適用する

### Requirement 10: Silence チェック

**Objective:** As a osu! クライアント, I want サイレンス中に発言できないことが明示されたい, so that 自分の状態を理解できる

#### Acceptance Criteria

1. While ユーザーがサイレンス状態, the Bancho server shall 当該ユーザーからのチャンネルメッセージと PM を拒否する
2. While ユーザーがサイレンス状態, the Bancho server shall サイレンスの残り時間をクライアントに通知する
3. The Bancho server shall サイレンス状態のチェックをチャンネルメッセージと PM の両方に適用する

### Requirement 11: ログインフロー統合

**Objective:** As a osu! クライアント, I want ログイン時に利用可能なチャンネル一覧を受け取りたい, so that どのチャンネルに参加できるか分かる

#### Acceptance Criteria

1. When ユーザーがログインに成功した場合, the Bancho server shall ユーザーの権限に基づいてアクセス可能なチャンネル一覧を CHANNEL_AVAILABLE パケットで送信する
2. When ユーザーがログインに成功した場合, the Bancho server shall 自動参加フラグが有効なチャンネルを CHANNEL_AVAILABLE_AUTOJOIN パケットで送信する
3. When チャンネル一覧の送信が完了した場合, the Bancho server shall CHANNEL_INFO_COMPLETE パケットを送信する
4. The Bancho server shall ユーザーが read_privileges を満たさないチャンネルをチャンネル一覧に含めない
5. The Bancho server shall 各チャンネルの現在参加者数をチャンネル一覧に含める

### Requirement 12: ユーザー切断時のクリーンアップ

**Objective:** As a osu! クライアント, I want 切断したユーザーがチャンネルから正しく離脱したい, so that チャンネルの参加者情報が正確に保たれる

#### Acceptance Criteria

1. When ユーザー切断イベントが発生した場合, the Bancho server shall 当該ユーザーの全チャンネルメンバーシップを削除する
2. When メンバーシップが削除された場合, the Bancho server shall 各チャンネルの参加者数が自動的に反映されること
3. The Bancho server shall メンバーシップの削除処理がユーザー切断イベントの既存処理（USER_QUIT 配信等）と共存すること

### Requirement 13: メッセージバリデーション

**Objective:** As a osu! クライアント, I want 不正なメッセージが適切に処理されたい, so that チャットの安定性が維持される

#### Acceptance Criteria

1. If 空のメッセージが送信された場合, the Bancho server shall メッセージを棄却する
2. If 最大文字数を超えるメッセージが送信された場合, the Bancho server shall メッセージを棄却する
3. The Bancho server shall 最大文字数をサーバー設定で指定可能にする（デフォルト: 450 文字）

### Requirement 14: テスト要件

**Objective:** As a 開発者, I want チャットシステム全体に対する包括的なテストが整備されていたい, so that リグレッションを防止し、安全に機能を拡張できる

#### Acceptance Criteria

1. The Bancho server shall 各サービス（ChatService, ChannelService, PrivateMessageService, CommandService）のメソッドを依存モックで直接呼び出すユニットテストを含む
2. The Bancho server shall チャンネル参加 → メッセージ送信 → 受信確認までの統合テストを含む
3. The Bancho server shall PM 送信 → 受信確認の統合テストを含む
4. The Bancho server shall コマンド実行 → BanchoBot 応答確認の統合テストを含む
5. The Bancho server shall HTTP POST リクエストから S2C レスポンスバイト列までの E2E テストを含む

## Design Decisions (from grill-me session)

### Q1: スコープ
- パブリック常設チャンネルのみ
- ChannelType enum は将来用に定義（PUBLIC / MULTIPLAYER / SPECTATOR / TEMPORARY）
- マルチプレイ/スペクテイターは将来 ChannelService を呼び出す設計

### Q2: メッセージ永続化
- パターン C: リアルタイム配信（即座）+ taskiq ワーカー経由で DB 永続化
- app プロセスは Valkey キューにジョブ投入、worker プロセスが DB に INSERT
- 全メッセージ（チャンネル・PM・オンライン/オフライン問わず）を常に永続化

### Q3: 権限モデル
- チャンネル単位のロールベース ACL
- Channel に read_privileges / write_privileges / manage_privileges（Privileges IntFlag）
- ユーザー単位のアクセス制御はロール追加で対応（チャンネル側の変更不要）

### Q5: Bot / コマンドシステム
- 内蔵 BanchoBot（user_id=1、DB に予約ユーザー）+ 将来の外部 Bot
- 外部 Bot も DB ユーザーとして管理（将来 BOT Privileges フラグ追加）
- CommandService を独立サービスとして設計
- コマンドプレフィックス: `!`（サーバー側処理）
- コマンドメッセージは全メンバーに配信（本家準拠）
- 初期実装: `!roll`, `!help` のみ
- 未実装コマンド: `!where`, `!stats`, `!report`, `!mp` 等（将来実装リスト）

### Q6: IRC / Bot API
- 外部 Bot は IRC + Bot API 両対応を将来像として想定
- 今回は ChannelService をプロトコル非依存に設計するのみ
- IRC サーバー実装・Bot API 設計はそれぞれ別 spec

### Q7: ランタイム状態
- Valkey Set 双方向インデックス
  - channel:{name}:members → Set{user_id}
  - user:{id}:channels → Set{channel_name}
- user_count は SCARD で動的算出
- メンバーシップの DB 永続化は不要（クライアントが再接続時に JOIN_CHANNEL を送る）

### Q8: デフォルトチャンネル
- `#osu`（auto_join, read/write: NORMAL）
- `#announce`（auto_join, read: NORMAL, write: ADMIN）
- その他は管理者が動的に追加

### Q9: WebUI / 管理 API
- 今回は ChatService の CRUD メソッド公開まで
- API エンドポイント設計は別 spec
- WebUI は別リポジトリ（osu-web + Admin 一体型）

### Q13: サービス構成
- ChatService（オーケストレーター）: ルーティング、Silence チェック、Rate Limit、コマンド判定、永続化トリガー
- ChannelService: チャンネル CRUD、メンバーシップ管理、権限チェック、チャンネル配信
- PrivateMessageService: 宛先検証、PM 配信
- CommandService: コマンドパース、実行、BanchoBot レスポンス生成

### Q15: ユーザー切断
- UserDisconnected イベントで全参加チャンネルからメンバーシップ削除
- Valkey Set から SREM するだけ（user_count は SCARD で自動反映）

### Q16: オフライン PM
- PM は常に DB 永続化（オンライン/オフライン問わず）
- オンラインならリアルタイム配信も行う、オフラインでもエラーにしない
- 履歴取得 API は Lazer/Web 対応の別 spec

### Q17: テーブル設計
- channel_messages と private_messages の分離テーブル
- クエリパターンとインデックス最適化が異なるため

### Q18: 実装パケット
- C2S: SEND_MESSAGE (1), SEND_PRIVATE_MESSAGE (25), JOIN_CHANNEL (63), LEAVE_CHANNEL (78)
- S2C 新規: SEND_MESSAGE (7), CHANNEL_JOIN_SUCCESS (64), CHANNEL_REVOKED (66)
- S2C 既存: CHANNEL_AVAILABLE (65), CHANNEL_AVAILABLE_AUTOJOIN (67), CHANNEL_INFO_COMPLETE (89)
- ログインフローのハードコード #osu を DB 読み出しに差し替え

### Q19: バリデーション / Rate Limit
- 最大文字数: Config（MESSAGE_MAX_LENGTH=450）
- 空メッセージ: ChatService で棄却
- チャンネル名: `#` + `[a-z0-9_-]`
- Rate Limit: Config グローバルデフォルト + DB チャンネル単位オーバーライド（nullable カラム）
- Silence: SessionData に silence_end フィールド、ChatService でチェック（付与/解除は別 spec）
