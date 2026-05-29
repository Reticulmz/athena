# Requirements Document

## Introduction

osu! stable クライアントはログイン後、定期的に `POST /`（osu-token ヘッダ付き）でサーバーにポーリングし、サーバーからの通知（プレゼンス、チャット、ステータス変更等）を受信する。このリクエストは双方向であり、リクエストボディに C2S パケットを含み、レスポンスで S2C パケットを受け取る。

bancho-login によりログインフローは完成済み。bancho-protocol により S2C パケットのビルダーと C2S パケットのヘッダ解析が定義済み。本スペックでは、ログイン後のポーリングパイプライン全体（C2S 受信→ディスパッチ→ S2C drain→レスポンス返却）と、S2C パケットキューの基盤を実装する。

## Boundary Context

- **In scope**:
  - ポーリングエンドポイント（`POST /` + osu-token）のリクエスト/レスポンス処理
  - C2S パケットのバイナリストリーム解析とハンドラへの逐次ディスパッチ
  - ユーザーごとの S2C パケットキュー（投入・全件取り出し・サイズ制限・TTL）
  - セッション TTL のリフレッシュとタイムアウト短縮（300秒）
  - システムイベントから S2C パケットへの変換・配信の仕組み
- **Out of scope**:
  - 個別 C2S ハンドラの実装（チャット送信、ステータス変更等は `c2s-handlers` スペック）
  - tourney クライアントのマルチセッション対応
  - PING パケットの定期生成（バックグラウンドタスクの責務）
  - S2C パケットの個別ビルダー追加（既存の bancho-protocol スペックで定義済み）
- **Adjacent expectations**:
  - `bancho-login`: セッション作成・検証・削除の仕組みが動作すること
  - `bancho-protocol`: C2S パケットヘッダ（7バイト: PacketID u16 + Compression bool + ContentSize u32）の解析と S2C パケットのビルドが利用可能であること
  - `c2s-handlers`（後続スペック）: 本スペックが提供するディスパッチパイプラインとハンドラ登録の仕組みを利用して、個別ハンドラを実装する

## Requirements

### Requirement 1: ポーリングレスポンス

**Objective:** osu! stable クライアントとして、ログイン後にサーバーから溜まった通知パケットを受信したい。これにより、他ユーザーのプレゼンス変更やチャットメッセージ等をリアルタイムに反映できる。

#### Acceptance Criteria

1. When クライアントが有効な osu-token ヘッダ付きで `POST /` を送信した場合, the Bancho Transport shall キューに溜まった全 S2C パケットを取り出し、連結したバイナリデータをレスポンスボディとして返却する。
2. When キューが空の状態でポーリングリクエストを受信した場合, the Bancho Transport shall 空のレスポンスボディ（0バイト）を返却する。
3. When 複数のポーリングリクエストが同時に発生した場合, the Bancho Transport shall 同一パケットが複数のレスポンスに含まれないことを保証する。

### Requirement 2: C2S パケット受信と逐次ディスパッチ

**Objective:** osu! stable クライアントとして、ポーリングリクエストのボディに C2S パケット（ステータス変更、チャット送信等）を含めて送信し、サーバーに処理させたい。

#### Acceptance Criteria

1. When クライアントがポーリングリクエストのボディに1つ以上の C2S パケットを含めた場合, the Bancho Transport shall バイナリストリームを個別パケットに分割し、送信順序を保持して逐次的にハンドラへディスパッチする。
2. When リクエストボディが空の場合, the Bancho Transport shall C2S パケット処理をスキップし、S2C キューの drain のみを実行する。
3. When C2S パケットに対応するハンドラが登録されていない場合, the Bancho Transport shall そのパケットをスキップし、後続パケットの処理を継続する。
4. The Bancho Transport shall C2S パケットの処理を全て完了した後に S2C キューの drain を実行し、C2S ハンドラが生成した S2C パケットを同一レスポンスに含める。

### Requirement 3: C2S パケット解析のエラー耐性

**Objective:** サーバー運用者として、不正な C2S パケットがサーバーの安定性を損なわないようにしたい。

#### Acceptance Criteria

1. If C2S パケットのヘッダが不正（バイト不足、不正なパケットID等）である場合, the Bancho Transport shall 当該パケット以降の解析を中止し、処理済みパケットの結果と S2C キューの内容をレスポンスとして返却する。
2. If C2S ハンドラの実行中に例外が発生した場合, the Bancho Transport shall 例外をログに記録し、後続パケットの処理を継続する。
3. If C2S パケットのペイロードサイズがヘッダに記載されたサイズと一致しない場合, the Bancho Transport shall 当該パケット以降の解析を中止する。
4. If リクエストボディのサイズが上限を超えている場合, the Bancho Transport shall リクエストを拒否し、パケット処理を行わない。

### Requirement 4: S2C パケットキュー

**Objective:** サーバーの各コンポーネントとして、特定ユーザーに S2C パケットを配信するために、ユーザーごとのパケットキューにパケットを投入したい。

#### Acceptance Criteria

1. The Bancho Transport shall ユーザーごとに独立した S2C パケットキューを提供し、ビルド済みの S2C パケット（バイト列）を1つまたは複数同時に投入できること。
2. When パケットキューのサイズが上限（4096パケット）を超えた場合, the Bancho Transport shall 最も古いパケットから切り捨て、新しいパケットを優先して保持する。
3. When 対象ユーザーのセッションが存在しない場合にパケットが投入された場合, the Bancho Transport shall そのパケットを破棄する。

### Requirement 5: セッションライフサイクルとタイムアウト

**Objective:** osu! stable クライアントとして、ポーリングを継続している間はセッションが維持され、切断後は適切にクリーンアップされるようにしたい。

#### Acceptance Criteria

1. When クライアントがポーリングに成功した場合, the Bancho Transport shall セッションの有効期限を300秒にリフレッシュする。
2. When セッションの有効期限が切れた場合, the Bancho Transport shall セッションと関連するパケットキューの両方をクリーンアップする。
3. When パケットキューの有効期限は, the Bancho Transport shall セッションの有効期限と連動し、セッションのリフレッシュ時にキューの有効期限も同時にリフレッシュする。

### Requirement 6: セッション検証の失敗

**Objective:** サーバーとして、無効なセッションからのポーリングリクエストを適切に拒否したい。

#### Acceptance Criteria

1. If osu-token ヘッダの値に対応するセッションが存在しない場合, the Bancho Transport shall 認証失敗を示すレスポンスを返却する（ログインフロー既存の `LoginResult.AUTHENTICATION_FAILED` と同一形式）。
2. If osu-token ヘッダが存在しない `POST /` リクエストの場合, the Bancho Transport shall ログインフローとして処理する（既存動作、変更なし）。

### Requirement 7: イベント駆動の S2C パケット配信

**Objective:** サーバーの各サービス（チャット、プレゼンス等）として、プロトコル固有の実装詳細を知ることなく、ユーザーへの通知を発行したい。

#### Acceptance Criteria

1. When システムイベント（チャットメッセージ送信、ユーザーステータス変更等）が発生した場合, the Bancho Transport shall 対象ユーザーのキューに適切な S2C パケットを投入する。

### Requirement 8: 観測可能性

**Objective:** サーバー運用者として、ポーリングパイプラインの動作状況を監視・デバッグしたい。

#### Acceptance Criteria

1. When ポーリングリクエストを処理した場合, the Bancho Transport shall C2S パケット数、S2C パケット数、処理時間を構造化ログに記録する。
2. When C2S パケットのヘッダ解析エラーまたはハンドラ例外が発生した場合, the Bancho Transport shall エラー詳細（パケット種別、ペイロードサイズ、例外情報）を構造化ログに記録する。
3. When 未登録の C2S パケットを受信した場合, the Bancho Transport shall パケット種別とサイズをデバッグレベルでログに記録する。
