# Requirements Document

## Introduction

osu! stable クライアントが bancho バイナリプロトコル経由で送信する C2S（Client-to-Server）パケットを処理するハンドラインフラストラクチャと初期ハンドラを実装する。開発者がデコレータベースの宣言的パターンでパケットハンドラとイベントリスナーを追加できるフレームワークを構築し、PONG（keepalive 応答）と EXIT（切断）の2つの初期ハンドラを提供する。

## Boundary Context

- **In scope**:
  - 宣言的ルーティング基盤（デコレータによるハンドラ/リスナーのルート宣言と一括登録）
  - C2S パケットハンドラ用の基盤クラスと登録パターン
  - ドメインイベントリスナー用の基盤クラスと登録パターン（ハンドラと対称）
  - PONG / EXIT ハンドラの実装
  - ディスパッチャーへの user_id 伝達修正
  - ドメインイベント定義（ユーザー切断）
  - 例外隔離（ハンドラ失敗時の継続処理）
  - ユニット・統合・E2E の3レベルテスト

- **Out of scope**:
  - チャンネル関連ハンドラ（JOIN_CHANNEL, LEAVE_CHANNEL, SEND_MESSAGE 等）→ channel-system スペック
  - プレゼンス関連ハンドラ（STATUS_CHANGE, PRESENCE_REQUEST 等）→ presence-status スペック
  - マッチ関連ハンドラ → Phase 2 以降
  - ハンドラスキャフォールド生成ツール → 実装後の改善として検討

- **将来検討**:
  - PING（S2C）の定期送信メカニズム → presence-status 等で対応

- **Adjacent expectations**:
  - PacketDispatcher（既存）がハンドラの登録と呼び出しを提供すること
  - EventBus（既存）がイベントの発火と購読を提供すること
  - PacketQueue（既存）がユーザー別 S2C パケットバッファを提供すること
  - SessionStore（既存）がセッション管理を提供すること
  - LoginHandler の polling パイプライン（既存）が C2S パケットのパースとディスパッチを行うこと

## Requirements

### Requirement 1: 宣言的ルーティング基盤

**Objective:** As a 開発者, I want メソッドデコレータでルートキーとハンドラの対応を宣言できるようにしたい, so that ハンドラやリスナーの追加が直感的で登録漏れが起きにくい

#### Acceptance Criteria

1. The Bancho server shall メソッドにルートキーを宣言するデコレータ機構を提供する
2. The Bancho server shall デコレータで宣言されたメソッドをグループクラス定義時に自動収集する
3. When 開発者がルートグループインスタンスで一括登録を実行した場合, the Bancho server shall デコレータで宣言された全メソッドを対象レジストリに登録する
4. The Bancho server shall ルートグループクラスがコンストラクタで依存オブジェクトを受け取る構造を持つこと
5. When ルートグループに1つもデコレータ付きメソッドが存在しない状態で一括登録が実行された場合, the Bancho server shall 警告ログを出力する

### Requirement 2: C2S パケットハンドラ登録

**Objective:** As a 開発者, I want C2S パケットハンドラをドメイン単位でグループ化し、デコレータで宣言的に登録したい, so that ハンドラの追加と管理が整理され一貫性がある

#### Acceptance Criteria

1. The Bancho server shall ルーティング基盤を使用した C2S パケットハンドラ用の基盤クラスを提供する
2. When ハンドラグループの一括登録が実行された場合, the Bancho server shall 各デコレータ付きメソッドを既存のパケットディスパッチャーに登録する
3. When 一括登録が完了した場合, the Bancho server shall グループ名と登録ハンドラ数を構造化ログに記録する
4. If 同一パケット ID に対して重複登録が発生した場合, the Bancho server shall エラーを発生させる

### Requirement 3: ドメインイベントリスナー登録

**Objective:** As a 開発者, I want ドメインイベントリスナーをパケットハンドラと同じ宣言的パターンで登録したい, so that 学習コストが低く、コードベース全体に一貫性がある

#### Acceptance Criteria

1. The Bancho server shall ルーティング基盤を使用したイベントリスナー用の基盤クラスを提供する
2. When リスナーグループの一括登録が実行された場合, the Bancho server shall 各デコレータ付きメソッドを既存のイベントバスに購読登録する
3. The Bancho server shall リスナーグループの登録パターン（デコレータ宣言・コンストラクタ DI・一括登録）がハンドラグループと同一であること

### Requirement 4: ユーザー識別情報の伝達

**Objective:** As a パケットハンドラ, I want パケット送信元のユーザー ID を受け取りたい, so that ユーザー固有の処理を実行できる

#### Acceptance Criteria

1. When C2S パケットがディスパッチされた場合, the Bancho server shall パケットペイロードとユーザー ID をハンドラに渡す
2. The Bancho server shall ハンドラの呼び出しシグネチャを payload（バイト列）と user_id（整数）の2引数に統一する

### Requirement 5: PONG パケット処理

**Objective:** As a osu! クライアント, I want サーバーからの PING に対して PONG で応答した際に正しく受理されたい, so that セッションが維持される

#### Acceptance Criteria

1. When クライアントから PONG パケット（ClientPacketID = 4）を受信した場合, the Bancho server shall パケットを受理しエラーなく処理を完了する
2. When PONG パケットが処理された場合, the Bancho server shall デバッグレベルでログを記録する（高頻度パケットのため）

### Requirement 6: EXIT パケット処理

**Objective:** As a osu! クライアント, I want ゲームを終了した際にサーバーがセッションを適切にクリーンアップしたい, so that 他のユーザーに自分のオフライン状態が正しく伝わる

#### Acceptance Criteria

1. When クライアントから EXIT パケット（ClientPacketID = 2）を受信した場合, the Bancho server shall 該当ユーザーのセッションを削除する
2. When ユーザーが切断した場合, the Bancho server shall ドメインイベントを発火する
3. When ユーザー切断イベントが発火された場合, the Bancho server shall オンラインの全ユーザーに該当ユーザーの退出を通知する S2C パケットを配信する
4. When EXIT パケットが処理された場合, the Bancho server shall 情報レベルでログを記録する
5. If 既に削除済みのセッションに対して EXIT パケットを受信した場合, the Bancho server shall エラーなく安全に処理を完了する
6. The Bancho server shall ドメインイベント発火の成功・失敗に関わらずセッション削除を必ず実行する

### Requirement 7: ドメインイベント定義

**Objective:** As a 開発者, I want ユーザー切断などのドメインイベントがドメイン層に定義されていたい, so that ハンドラとリスナーが疎結合に連携できる

#### Acceptance Criteria

1. The Bancho server shall ユーザー切断イベントをドメイン層のユーザードメイン配下に定義する
2. The Bancho server shall ドメインイベントを不変のデータ構造として定義する
3. The Bancho server shall ドメインイベントにイベント発生元のユーザー ID を含める

### Requirement 8: 例外隔離

**Objective:** As a osu! クライアント, I want 1つのパケット処理が失敗しても他のパケットが正常に処理されたい, so that 接続の安定性が維持される

#### Acceptance Criteria

1. If ハンドラが例外を発生させた場合, the Bancho server shall 例外をログに記録し、残りのパケットの処理を継続する
2. If ハンドラが例外を発生させた場合, the Bancho server shall パケット ID とペイロードサイズを含むエラーログを出力する
3. While 複数の C2S パケットを順次処理中, the Bancho server shall 各パケットの処理を独立して実行する

### Requirement 9: テスト要件

**Objective:** As a 開発者, I want ハンドラインフラとハンドラ実装に対する包括的なテストが整備されていたい, so that リグレッションを防止し、安全にハンドラを追加できる

#### Acceptance Criteria

1. The Bancho server shall ハンドラグループの各メソッドを依存モックで直接呼び出すユニットテストを含む
2. The Bancho server shall ハンドラからのイベント発火 → リスナー受信 → パケットキュー投入までの統合テストを含む
3. The Bancho server shall HTTP POST リクエストから S2C レスポンスバイト列までの E2E テストを含む
