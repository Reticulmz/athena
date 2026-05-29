# Requirements Document

## Introduction
stable クライアントとの通信に必要な bancho バイナリプロトコル基盤を構築する。パケットヘッダ・パケット ID 列挙型・基本ワイヤ型・シリアライゼーションユーティリティ・デコレータ駆動のディスパッチ機構を提供し、後続 spec（bancho-login 等）がハンドラを実装するための土台となる。

## Boundary Context
- **In scope**: パケットヘッダ定義、C2S/S2C パケット ID 列挙型、基本ワイヤ型（BanchoString, Message, IntList, Channel, StatusUpdate）、パケット読み書きユーティリティ、デコレータ駆動のディスパッチ機構、ログイン応答シーケンスに必要な S2C パケット型定義
- **Out of scope**: 個別パケットハンドラのビジネスロジック実装（bancho-login 等が担当）、チャット・スコア・マルチプレイ関連パケット型定義（Match, ScoreFrame, ReplayFrame 等）、ログインフロー自体の実装、HTTP リクエスト/レスポンス処理
- **Adjacent expectations**: foundation spec が提供する DI コンテナ・Starlette アプリ骨格・設定管理が利用可能であること。ディスパッチ機構は DI コンテナと連携してハンドラにサービスを提供できること

## Requirements

### Requirement 1: パケットヘッダの定義と読み書き

**Objective:** As a サーバー開発者, I want パケットヘッダを宣言的に定義し双方向に変換できること, so that 全パケットの読み書きに統一的なヘッダ処理を使える

#### Acceptance Criteria
1. The athena server shall パケットヘッダを PacketID (unsigned 16-bit)、Compression (bool, 1 byte)、ContentSize (unsigned 32-bit) の 3 フィールドで定義する
2. The athena server shall パケットヘッダの全フィールドをリトルエンディアンで読み書きする
3. When バイトストリームからヘッダを読み取る場合, the athena server shall 先頭 7 バイトから PacketID・Compression・ContentSize を復元する
4. When ヘッダからバイト列を構築する場合, the athena server shall PacketID・Compression・ContentSize から 7 バイトのバイナリ表現を生成する

### Requirement 2: パケット ID 列挙型

**Objective:** As a サーバー開発者, I want C2S と S2C のパケット ID が型安全な列挙型として定義されていること, so that パケットの方向と種類を静的に区別できる

#### Acceptance Criteria
1. The athena server shall クライアント→サーバー方向の全パケット ID を ClientPacketID 列挙型として定義する
2. The athena server shall サーバー→クライアント方向の全パケット ID を ServerPacketID 列挙型として定義する
3. The athena server shall ClientPacketID と ServerPacketID を別の列挙型として分離し、同じ数値 ID が異なる方向で独立して使用できるようにする
4. The athena server shall bancho-documentation Wiki の現行パケット ID 一覧（ID 0–109）に準拠した値を各列挙型に含める

### Requirement 3: 基本ワイヤ型の定義

**Objective:** As a サーバー開発者, I want プロトコルで使用される基本データ型が宣言的に定義されていること, so that パケットペイロードの構造を型安全に記述できる

#### Acceptance Criteria
1. The athena server shall BanchoString 型を定義する（先頭バイト 0x00 で空文字列、0x0b で ULEB128 バイト長 + UTF-8 文字列データ）
2. The athena server shall Message 型を定義する（Sender, Content, Target の 3 つの BanchoString フィールドと SenderId の signed 32-bit フィールドを含む）
3. The athena server shall IntList 型を定義する（unsigned 16-bit 長プレフィックス + その個数分の signed 32-bit 配列）
4. The athena server shall Channel 型を定義する（Name, Topic の BanchoString フィールドと UserCount の signed 16-bit フィールドを含む）
5. The athena server shall StatusUpdate 型を定義する（Status 列挙値、StatusText, BeatmapMD5 の BanchoString フィールド、Mods の signed 32-bit、PlayMode 列挙値、BeatmapId の signed 32-bit を含む）
6. The athena server shall 定義した全ワイヤ型でバイナリからの読み取り（parse）とバイナリへの書き込み（build）の双方向変換をサポートする

### Requirement 4: パケット読み書きユーティリティ

**Objective:** As a サーバー開発者, I want バイトストリームから C2S パケットを読み取り、S2C パケットをバイト列に構築するユーティリティがあること, so that トランスポート層がワイヤフォーマットの詳細を意識せずにパケットを処理できる

#### Acceptance Criteria
1. When バイトストリームを受信した場合, the athena server shall ヘッダを読み取り、ContentSize 分のペイロードを切り出し、対応する ClientPacketID とペイロードバイト列の組を返す
2. When バイトストリームに複数パケットが連結されている場合, the athena server shall 全パケットを先頭から順番に読み取り、それぞれを個別のパケットとして返す
3. When S2C パケットを構築する場合, the athena server shall ServerPacketID とペイロードからヘッダ付きの完全なバイト列を生成する
4. If ヘッダの読み取りに必要な 7 バイトが不足している場合, the athena server shall データ不足を示すエラーを返す
5. If ContentSize が示すペイロード長分のデータがストリームに不足している場合, the athena server shall データ不足を示すエラーを返す

### Requirement 5: デコレータ駆動のディスパッチ機構

**Objective:** As a サーバー開発者, I want パケットハンドラをデコレータで登録し、受信パケットに応じて自動的に呼び出されること, so that 新しいハンドラの追加が宣言的かつ低コストで行える

#### Acceptance Criteria
1. The athena server shall パケットハンドラを ClientPacketID に紐づけて登録するデコレータを提供する
2. When C2S パケットを受信した場合, the athena server shall ClientPacketID に対応する登録済みハンドラを検索し呼び出す
3. If 受信した ClientPacketID に対応するハンドラが登録されていない場合, the athena server shall そのパケットを無視し、エラーを発生させずに処理を継続する
4. The athena server shall 登録された全ハンドラと対応する ClientPacketID の一覧を取得できる機能を提供する
5. If 同一の ClientPacketID に対して複数のハンドラが登録された場合, the athena server shall 重複登録をエラーとして報告する

### Requirement 6: ログイン関連 S2C パケット型の定義

**Objective:** As a サーバー開発者, I want ログイン応答シーケンスで必要な S2C パケット型が定義されていること, so that bancho-login spec がこれらの型を使用してログイン応答を構築できる

#### Acceptance Criteria
1. The athena server shall LoginReply パケット型を定義する（signed 32-bit ペイロード: 正値 = ユーザー ID、負値 = エラーコード）
2. The athena server shall ProtocolVersion パケット型を定義する（signed 32-bit ペイロード）
3. The athena server shall LoginPermissions パケット型を定義する（signed 32-bit ペイロード: 権限ビットマスク）
4. The athena server shall Notification パケット型を定義する（BanchoString ペイロード）
5. The athena server shall UserPresence パケット型を定義する（UserId, Username, Timezone, CountryId, Permissions と Mode の packed フィールド, Longitude, Latitude, Rank の各フィールド）
6. The athena server shall UserStats パケット型を定義する（UserId, StatusUpdate, RankedScore, Accuracy, PlayCount, TotalScore, Rank, PP の各フィールド）
7. The athena server shall FriendsList パケット型を定義する（IntList ペイロード）
8. The athena server shall ChannelAvailable および ChannelAvailableAutojoin パケット型を定義する（Channel 型ペイロード）
9. The athena server shall ChannelInfoComplete パケット型を定義する（ペイロードなし）
10. The athena server shall SilenceInfo パケット型を定義する（signed 32-bit ペイロード: サイレンス残り秒数）
11. The athena server shall UserPresenceBundle パケット型を定義する（IntList ペイロード: オンラインユーザー ID 一覧）
12. The athena server shall 定義した全 S2C パケット型で対応する ServerPacketID との紐づけを明示する
