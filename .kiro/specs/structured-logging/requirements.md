# Requirements Document

## Introduction
Athena osu! サーバーに構造化ログ基盤を導入する。現状は最低限のエラーログ（3箇所）しか存在せず、リクエストログ・パケット処理ログ・ビジネスロジックのログが一切出力されない。bancho プロトコルはエンドポイントが `POST /` 一つのため、HTTP レベルのログだけでは内部のパケット処理がブラックボックスになっている。

開発者がリクエストの流れとパケット処理を可視化でき、将来的にはオペレーターの運用監視や AI による自動デバッグにも活用できるログ基盤を構築する。

### Grill-me で合意した設計決定

- **ライブラリ**: structlog（標準 logging の上に構造化ログ）
- **出力**: コンソール（カラー）常時 + JSON ファイル（`logs/athena.jsonl`）は config で ON/OFF
- **設定管理**: `config.py` に設定値 + `infrastructure/logging.py` に初期化ロジック
- **初期化**: `lifespan` 内、`load_config()` 直後
- **HTTP ログ**: `BaseHTTPMiddleware` で全トランスポート共通。uvicorn アクセスログは無効化
- **C2S ログ**: `PacketDispatcher.dispatch()` にフック
- **S2C ログ**: `write_packet()` にフック（packet_id + size）
- **ユーザー情報**: structlog contextvars でリクエストスコープにバインド
- **ノイジーパケット**: 固定 `frozenset` で抑制（PING, STATS_REQUEST 等）→ DEBUG のみ
- **パケット粒度**: 意味あるパケットはペイロード付き INFO、ノイズ系は DEBUG
- **既存サービス**: auth / password / permission にビジネスロジックログ追加
- **worker プロセス**: 同じ初期化関数で統一
- **テスト**: 基盤のユニットテストのみ

## Boundary Context
- **In scope**: ログ基盤構築、HTTP リクエストログ、bancho パケットログ（C2S/S2C 双方向）、既存サービス（auth/password/permission）へのビジネスロジックログ追加、app プロセスと worker プロセスの両方
- **Out of scope**: 相関 ID によるリクエストトレーシング、セキュリティ監査ログ（ログイン試行記録・IP 追跡）、外部サービス連携（Sentry 等）、メトリクス・パフォーマンス監視、ログローテーション・永続化戦略、アラート連携
- **Adjacent expectations**: 新規機能（c2s-handlers、channel-system 等）の実装時に、本基盤を利用してサービス層のログを各 spec で順次追加していく想定

## Requirements

### Requirement 1: ログ設定
**Objective:** オペレーターとして、環境変数でログの挙動を制御したい。環境ごとに適切なログ設定で運用できるようにするため。

#### Acceptance Criteria
1. The Athena server shall ログレベル（DEBUG / INFO / WARNING / ERROR）を設定値で制御できること
2. The Athena server shall JSON ファイルログ出力の有効・無効を設定値で切り替えられること
3. The Athena server shall JSON ログファイルの出力先パスを設定値で指定できること
4. When 設定値が未指定の場合, the Athena server shall ログレベルは INFO、JSON 出力は無効をデフォルトとすること

### Requirement 2: コンソールログ出力
**Objective:** 開発者として、ターミナル上で人間が読みやすい形式のログを見たい。開発中にリクエストの流れとパケット処理をリアルタイムで追跡できるようにするため。

#### Acceptance Criteria
1. The Athena server shall すべてのログをコンソール（stdout）にカラー付きの人間可読形式で出力すること
2. The Athena server shall 各ログエントリにタイムスタンプ、ログレベル、イベント名、構造化されたキーバリューペアを含めること
3. The Athena server shall 組み込みの ASGI サーバーアクセスログを無効化し、自前のリクエストログに一本化すること

### Requirement 3: JSON ファイルログ出力
**Objective:** オペレーターおよび AI アシスタントとして、機械パース可能な形式のログを読みたい。自動解析やデバッグ支援に活用できるようにするため。

#### Acceptance Criteria
1. Where JSON ログ出力が有効の場合, the Athena server shall すべてのログを JSON Lines 形式で指定ファイルに追記出力すること
2. The Athena server shall JSON ログにタイムスタンプ、ログレベル、イベント名、すべてのコンテキスト情報をキーバリューで含めること
3. The Athena server shall コンソール出力と JSON ファイル出力を同時に行えること（相互排他でないこと）
4. If JSON ログファイルへの書き込みに失敗した場合, the Athena server shall コンソールに警告を出力し、アプリケーションの動作を継続すること

### Requirement 4: HTTP リクエストログ
**Objective:** 開発者として、すべてのトランスポート（bancho / web_legacy / api / signalr）の HTTP リクエストを統一的にログで確認したい。リクエストの流れを一元的に追跡できるようにするため。

#### Acceptance Criteria
1. When HTTP リクエストが完了した時, the Athena server shall HTTP メソッド、リクエストパス、レスポンスステータスコード、処理時間（ミリ秒）をログに記録すること
2. The Athena server shall すべてのトランスポート（bancho / web_legacy / api / signalr）のリクエストを同一のログ形式で記録すること

### Requirement 5: Bancho C2S パケットログ
**Objective:** 開発者として、クライアントから受信した bancho パケットの種別と内容をログで確認したい。`POST /` 内部のブラックボックスを可視化するため。

#### Acceptance Criteria
1. When C2S パケットを受信した時, the Athena server shall パケット種別名とペイロードサイズをログに記録すること
2. When 意味のある C2S パケット（チャット送信、ステータス変更等）を受信した時, the Athena server shall パースされたペイロード内容を INFO レベルでログに記録すること
3. When ノイジーな C2S パケット（PING、ステータスリクエスト等）を受信した時, the Athena server shall DEBUG レベルでのみログに記録すること
4. When 未対応の C2S パケット（ハンドラ未登録）を受信した時, the Athena server shall その旨を DEBUG レベルでログに記録すること

### Requirement 6: Bancho S2C パケットログ
**Objective:** 開発者として、クライアントに送信する bancho パケットの種別をログで確認したい。サーバーからの応答内容を可視化するため。

#### Acceptance Criteria
1. When S2C パケットを構築した時, the Athena server shall パケット種別名とペイロードサイズをログに記録すること
2. When ノイジーな S2C パケットを構築した時, the Athena server shall DEBUG レベルでのみログに記録すること

### Requirement 7: リクエストコンテキスト伝播
**Objective:** 開発者として、ログエントリにユーザー情報が自動的に付与されることで、誰のリクエストか一目で判別したい。

#### Acceptance Criteria
1. While ユーザーが認証済みのリクエストを処理している間, the Athena server shall そのリクエストスコープ内の全ログにユーザー名とユーザー ID を自動付与すること
2. When リクエストの処理が完了した時, the Athena server shall バインドされたコンテキスト情報をクリアし、後続リクエストに漏洩しないこと

### Requirement 8: サービス層のビジネスロジックログ
**Objective:** 開発者として、認証・パスワード・権限の各サービスでの操作結果をログで確認したい。ビジネスロジックの成功・失敗を追跡できるようにするため。

#### Acceptance Criteria
1. When ログイン認証が成功した時, the Athena server shall ユーザー名を含む成功ログを記録すること
2. When ログイン認証が失敗した時, the Athena server shall 失敗理由（ユーザー不在、パスワード不一致等）を含むログを記録すること
3. When ユーザー登録が完了した時, the Athena server shall ユーザー名を含む成功ログを記録すること
4. When パスワード検証が失敗した時, the Athena server shall 失敗理由を含むログを記録すること
5. When 権限チェックが実行された時, the Athena server shall チェック対象と結果をログに記録すること

### Requirement 9: 機密情報の保護
**Objective:** オペレーターとして、ログに認証情報が平文で記録されないことを保証したい。ログファイルからの資格情報漏洩を防ぐため。

#### Acceptance Criteria
1. The Athena server shall パスワードおよびパスワードハッシュをログ出力時にマスキングすること
2. The Athena server shall マスキング対象以外の情報（IP アドレス、チャットメッセージ、セッショントークン等）はそのまま出力すること

### Requirement 10: プロセス間のログ統一
**Objective:** オペレーターとして、app プロセスと worker プロセスで同一のログ形式・設定を使いたい。ログの一貫性を保ち、解析を容易にするため。

#### Acceptance Criteria
1. The Athena server shall app プロセス（ASGI サーバー）と worker プロセス（ジョブキュー）で同一のログ設定を適用すること
2. The Athena server shall 両プロセスで同じ形式（コンソール出力、JSON 出力）のログを出力すること

### Requirement 11: ログ基盤の品質保証
**Objective:** 開発者として、ログ基盤の初期化やファイル出力が正しく動作することをテストで保証したい。

#### Acceptance Criteria
1. The Athena server shall ログ基盤の初期化処理（設定に応じた出力先構成）のユニットテストを持つこと
2. The Athena server shall JSON ファイル出力の動作を検証するユニットテストを持つこと
3. The Athena server shall ログレベル制御の動作を検証するユニットテストを持つこと
