# bancho 互換サーバー設計仕様書

## ドキュメント概要

本ドキュメントは、osu! の bancho 互換 private server を新規に設計・実装する際の指針を定めるものである。既存実装(bancho.py, Ripple 系)の構造的問題を踏まえ、以下を実現する設計を提示する。

- **stable クライアントと lazer クライアントの両方をサポート**する統合的なサーバー
- **モジュラモノリス**として構築し、将来的な分散化(プロセス分離、マイクロサービス化)への段階的な進化パスを残す
- **トランスポート層の明確な分離**と**ドメインロジックの一元化**を両立
- **FastAPI 的な開発体験**(型駆動、宣言的、依存性注入)を bancho プロトコルにも持ち込む
- **Valkey を揮発的ステートの中央ストア**として活用し、トランスポートの水平スケールとプロトコル横断的なステート整合性を実現
- **コードベースの可読性と保守性**を、bancho.py を上回る水準で達成する

本書は実装着手前の設計合意ドキュメントとして、また実装中の参照資料として使用することを想定する。後半のセクション 12 と付録 D で、規模拡大時の進化パスや代替実装(Cloudflare ベース)についても触れる。

---

## 1. 背景と問題意識

### 1.1 本家 osu! インフラの実態

osu! の公式インフラは、概ね以下の責務分離で構成されている。

| コンポーネント | 役割 | 公開状況 |
|---|---|---|
| bancho | リアルタイム通信(チャット、マルチ、spectator、プレゼンス)の stable 用サーバー | 非公開(クローズドソース) |
| osu-web | ウェブサイト + REST API v2、Laravel 製 | 公開(`ppy/osu-web`) |
| osu-server-spectator | lazer 用 SignalR ハブ(spectator/multiplayer/metadata) | 公開(`ppy/osu-server-spectator`) |
| Legacy `/web/*.php` ハンドラ | stable のスコア送信、リプレイ送信、updates チェック等 | 非公開 |

stable クライアントは bancho バイナリプロトコル + legacy `/web/*.php` を使い、lazer クライアントは osu-server-spectator の SignalR + osu-web の REST API v2 を使う。両クライアントは異なる経路で通信しながら、`/_lio/*` という内部 API を通じてチャット等のデータを共有している。

### 1.2 既存実装の構造的問題

bancho.py は最も普及している private server 実装だが、以下の構造的課題を持つ。

- **単一プロセスへの過度な集約**: bancho バイナリ、`/web/*` レガシー、`/api/v2/*`、ビートマップミラー、アバター配信が同一プロセスに同居し、責務分離が崩壊している
- **グローバル状態への密結合**: `app.state.sessions.*` を介したグローバル状態が全レイヤーから直接参照され、テスト容易性が低い
- **巨大ファイル**: `app/api/domains/cho.py`, `app/api/domains/osu.py` などが数千行規模で、可読性が低い
- **パケットハンドリングの集中**: `match` 文による単一巨大ディスパッチで、ハンドラ追加が既存コード編集を要求する
- **C2S / S2C パケット ID の混在**: 方向別の名前空間が分離されておらず、型レベルでの取り違え検出が効かない
- **手書きのバイナリパース**: パケット定義が `read_int32`, `read_string` の手仕事で、宣言的記述になっていない

Ripple のスタック(pep.py, LETS, Hanayo)は、責務分離はより綺麗に実現されているが、Python 2 系のレガシー、グローバル状態への依存、循環参照気味の設計など別の課題を抱えている。

### 1.3 本設計が目指すもの

本設計は、bancho.py の「動くが汚い」という現状と Ripple の「綺麗だが古い」という現状の両方を超えることを目指す。具体的には以下を達成する。

1. 新しいパケット / エンドポイント追加時の編集箇所が3点セット程度に収まる
2. 「特定の挙動を変えたい」時、該当コードに最短でたどり着ける
3. トランスポート層とビジネスロジックが独立してテストできる
4. bancho と lazer の両対応で、ドメインロジックの重複が発生しない
5. import 規則を機械的に検証でき、密結合化を防止できる
6. 新規貢献者が30分以内にコードベースの全体像を把握できる
7. 揮発的ステート(セッション、プレゼンス、チャンネル状態)を Valkey に集約し、プロセス再起動でセッションが消失しない構造とする
8. 規模拡大時に、コードを大幅変更することなくプロセス分離・サービス分離・パッケージ分割へと段階的に進化できる

---

## 2. アーキテクチャ概観

### 2.1 設計思想

本設計は以下の3つの原則に基づく。

**原則1: モジュラモノリス**

単一プロセスで運用する一方、内部のモジュール境界を明示し、モジュール間通信は公開インターフェース経由のみに制限する。マイクロサービスの運用負荷を負わずに、責務分離の利点を享受する。

**原則2: ハイブリッド構造(外側トランスポート、内側ドメイン)**

トップレベルのディレクトリ構造は通信プロトコル別(bancho / web_legacy / api / signalr)に分割し、その内部でドメイン別の機能サービス層を共有する。これにより以下を両立する。

- 新規貢献者にとっての「とっつきやすさ」: 外部仕様(URL、パケット ID)からコードへの直接的なマッピング
- 長期保守性のための「美しさ」: ビジネスロジックの一元化、ドメイン語彙によるコード表現

**原則3: 型駆動開発**

各レイヤーに最適なツールを選定し、型システムを最大限活用する。

- バイナリプロトコル → Caterpillar による宣言的定義
- REST API I/O → Pydantic v2 による自動バリデーション
- ドメインモデル → 標準 dataclass による軽量な値表現
- ハンドラディスパッチ → デコレータ + Annotated 型ヒントによる依存性注入

### 2.2 レイヤー構造

依存方向は上から下のみ。逆方向の依存は禁止する。

```
┌────────────────────────────────────────────────────┐
│ Transports                                         │
│ ├─ bancho (Starlette + 自前ディスパッチ)            │
│ ├─ web_legacy (Starlette)                          │
│ ├─ api (FastAPI)                                   │
│ └─ signalr (Starlette + 自前 SignalR 互換層)        │
├────────────────────────────────────────────────────┤
│ Services (ビジネスロジック)                         │
│ ├─ chat                                            │
│ ├─ scoring                                         │
│ ├─ multiplayer                                     │
│ ├─ spectator                                       │
│ ├─ presence                                        │
│ ├─ user                                            │
│ ├─ beatmap                                         │
│ └─ auth                                            │
├────────────────────────────────────────────────────┤
│ Domain (純粋なドメインモデル)                       │
│ ├─ Player, User, Score, Beatmap                    │
│ ├─ Channel, Message, Match, Room                   │
│ └─ 値オブジェクト、enum、型エイリアス                │
├────────────────────────────────────────────────────┤
│ Repositories (永続化抽象)                           │
│ ├─ interfaces (Protocol)                           │
│ ├─ sqlalchemy (本番実装)                            │
│ └─ memory (テスト実装)                              │
├────────────────────────────────────────────────────┤
│ Infrastructure                                     │
│ ├─ database (永続データの SQL アクセス)              │
│ ├─ cache (キャッシュ用途の Valkey ラッパー)            │
│ ├─ state (揮発的ステートの Valkey ストア)             │
│ │   ├─ SessionStore                                │
│ │   ├─ PresenceStore                               │
│ │   ├─ ChannelStateStore                           │
│ │   ├─ MatchStateStore                             │
│ │   └─ PacketQueue                                 │
│ ├─ messaging (EventBus: fire-and-forget な配信)    │
│ ├─ jobs (JobQueue: 配信保証ありのワーカー処理)       │
│ ├─ DI コンテナ                                      │
│ ├─ HTTP クライアント、ストレージ                     │
│ └─ ロギング                                         │
├────────────────────────────────────────────────────┤
│ Shared (横断的最小要素)                             │
│ └─ errors, types, constants                        │
└────────────────────────────────────────────────────┘
```

実行プロセスは以下の2つに分かれる。Services 以下のレイヤーは両プロセスで共有される。揮発的ステート(セッション、プレゼンス等)は Valkey に集約され、永続データは PostgreSQL に格納される。

```
┌─────────────────────────┐    ┌──────────────────────────┐
│ osu-server-app          │    │ osu-server-worker        │
│ (uvicorn, ASGI)         │    │ (arq worker)             │
│                         │    │                          │
│ Transports + Services + │    │ Job handlers + Services +│
│ Domain + Repositories + │    │ Domain + Repositories +  │
│ Infrastructure          │    │ Infrastructure           │
└──────────┬──────────────┘    └────────────┬─────────────┘
           │                                │
           └─────────────┬──────────────────┘
                         │
            ┌────────────┴────────────────────────────┐
            │ Valkey                                  │
            │ ├─ 揮発的ステート(session, presence,   │
            │ │   channel members, match state)      │
            │ ├─ パケットキュー(pending S2C packets) │
            │ ├─ Pub/Sub(EventBus)                  │
            │ ├─ Streams(JobQueue via taskiq)       │
            │ ├─ キャッシュ                            │
            │ └─ レート制限カウンター                   │
            └────────────┬────────────────────────────┘
                         │
                         ▼
            ┌─────────────────────────┐
            │ PostgreSQL              │
            │ (永続データ:            │
            │  users, scores, beatmaps,│
            │  replays, achievements) │
            └─────────────────────────┘
```

app プロセスは即時応答が必要な処理(認証、チャット配信、スコア受付)を担い、重い処理(PP 計算、リーダーボード更新、メダル付与、通知配信)は worker プロセスに委譲する。これによりリクエストのレイテンシが安定する。

Valkey を **揮発的ステートの中央ストア** として位置づけることで、app プロセスを水平スケールしてもセッション情報が分散せず、プロセス再起動でも接続中ユーザーのセッションが消失しない構造になる。これは bancho.py の「メモリ上のグローバルステート」設計に対する本質的な改善点である。詳細はセクション 8.5 を参照。

### 2.3 通信フローの全体像

本設計が扱う通信経路を整理する。

```
stable クライアント
  ├─ POST /                                  → bancho (バイナリ)
  └─ POST /web/osu-submit-modular-selector.php → web_legacy
     GET  /web/osu-osz2-getscores.php         → web_legacy
     GET  /web/check-updates.php              → web_legacy
     その他 /web/*.php                         → web_legacy

lazer クライアント
  ├─ POST /api/v2/oauth/token              → api (OAuth2)
  ├─ GET  /api/v2/me                       → api
  ├─ POST /api/v2/beatmaps/{id}/solo/scores → api (lazer スコア送信)
  ├─ POST /api/v2/chat/...                 → api (チャット)
  ├─ WebSocket /signalr/spectator          → signalr
  ├─ WebSocket /signalr/multiplayer        → signalr
  └─ WebSocket /signalr/metadata           → signalr

外部開発者(bot 等)
  └─ GET /api/v2/users/{id} 等             → api (osu! API v2 互換)

内部 callback (将来的に複数プロセス化した場合)
  └─ /_lio/*                               → api (interop)
```

---

## 3. 技術スタック

### 3.1 採用するライブラリと選定理由

| 領域 | 採用 | 理由 |
|---|---|---|
| ASGI サーバー | uvicorn | デファクト標準、Starlette / FastAPI と一体運用 |
| HTTP フレームワーク(bancho, web_legacy, signalr) | Starlette | 薄いミドルウェア層、不要な機能がない、WebSocket 対応 |
| HTTP フレームワーク(api) | FastAPI | OpenAPI 自動生成、Pydantic 統合、外部開発者向け API として必須 |
| バイナリプロトコル定義 | Caterpillar | Python 3.12+ の型アノテーションをそのままレイアウト DSL として使える、双方向(parse + build)対応、bitfield / 動的長サポート |
| API I/O バリデーション | Pydantic v2 | FastAPI 統合、Rust 製 core で高速、エコシステムが厚い |
| ドメインモデル | 標準 `@dataclass(slots=True)` | ゼロ依存、軽量、型チェッカーとの統合、不変条件をメソッドで表現できる柔軟性 |
| 設定管理 | pydantic-settings | 環境変数の型安全な読み込み |
| ORM | SQLAlchemy 2.0 (async) | `Mapped[...]` 型ヒント、async サポート、マイグレーション(Alembic)との統合 |
| マイグレーション | Alembic | SQLAlchemy 標準 |
| 依存性注入 | 自前の軽量コンテナ | フレームワーク非依存、テスト容易、外部ライブラリの学習コスト回避 |
| キャッシュ / ブローカー | Valkey | セッション、レート制限、キャッシュ、Pub/Sub、Streams を1つの基盤に集約（Redis プロトコル互換） |
| イベントバス(fire-and-forget) | 自前 EventBus 抽象 + 実装(in-memory / Valkey Pub/Sub) | チャット配信・プレゼンス更新等のロス許容な配信 |
| ジョブキュー(配信保証あり) | taskiq + taskiq-redis | async first、Valkey ベース、軽量、型ヒント親和性。スコア後処理・通知・メダル付与等の重い処理をワーカーに委譲 |
| import 規則検証 | import-linter | レイヤー違反、循環参照を CI で機械的に検出 |
| テスト | pytest + pytest-asyncio | デファクト標準 |
| 型チェック | mypy または pyright | 厳格モードで運用 |
| Lint / Format | ruff | 高速、設定統合 |

### 3.2 メッセージング基盤の選定背景

メッセージング(Pub/Sub・ジョブキュー)は規模に応じて段階的に強化できる構造とする。本設計では以下を採用する。

**Redis Pub/Sub(EventBus 実装の本番版)**

チャット配信、プレゼンス更新、spectator フレーム配信などの fire-and-forget 配信に使用する。配信保証は不要、レイテンシ重視。すでに Valkey を他の用途(キャッシュ、セッション)で使うため、追加インフラは発生しない。

**taskiq + taskiq-redis（JobQueue 実装）**

スコア処理パイプライン(PP 計算、リーダーボード更新、ユーザー統計更新)、通知配信、メダル付与判定など、配信保証と再試行が必要な処理に使用する。bancho サーバー本体(app プロセス)とは別の worker プロセスで実行する。

taskiq を選定する理由は以下:

1. **async ネイティブ**: サーバー本体と同じ async エコシステムで統一できる
2. **軽量**: Celery のような大型フレームワークを避け、private server 規模に見合う
3. **Valkey 基盤の共有**: 追加インフラが発生しない
4. **型ヒント親和性**: 設計書の他部分(Pydantic、dataclass、型駆動)との一貫性
5. **本家 osu! も Redis プロトコル中心の構成**: `ppy/osu-queue-score-statistics` が Redis プロトコルベースのキューシステムを採用しており、参考になる

Streams を直接扱うのではなく、taskiq のような上位ライブラリに任せることで、ジョブの登録・実行・再試行・ack を抽象化された API で扱える。Streams を生で扱うのは bancho サーバーの抽象化レベルとしては低すぎる。

### 3.3 採用しないライブラリと理由

以下は明示的に採用しない。意思決定の記録として残す。

- **Pydantic をドメイン層に使うこと**: バリデーションオーバーヘッドが過剰、ドメインの不変条件はメソッドで表現すべき、JSON シリアライズ可能性の制約がドメインを歪める
- **Construct(バイナリパース)**: Caterpillar より古い API、型ヒント統合が弱い、ただし Caterpillar が Python 3.12+ 必須で困る場合は代替候補
- **Kaitai Struct**: 読み取り専用でシリアライズができない、bancho サーバー用途では片手落ち
- **ctypes / 標準 `struct` モジュール(単体使用)**: 可変長フィールドや条件付きフィールドの表現が弱く、bancho プロトコル全体には不向き
- **aiohttp**: ASGI エコシステムから外れる、Starlette / FastAPI のミドルウェア群が使えない
- **Litestar**: 機能としては良いが、コミュニティ規模が FastAPI に及ばず、外部開発者向け osu! API v2 互換ドキュメントの観点で FastAPI を優先
- **dependency-injector / punq 等の DI フレームワーク**: 自前実装で十分、外部ライブラリの学習コストを避ける(将来的に必要なら導入を再検討)
- **Celery**: 重量級、async ネイティブではない、設定の罠が多い、bancho サーバー規模ではオーバーキル
- **RQ**: 同期コード前提、async サーバー本体との統合が悪い
- **ARQ**: メンテナンスが停滞しており、taskiq に移行
- **RabbitMQ**: 複雑な routing が不要な現状ではオーバーキル、Valkey スタックに集約する方が運用が単純
- **Kafka**: スループットが過剰、運用コストが高すぎる、private server 規模では完全に不要
- **Pyventus / blinker / pymitter / PyDispatcher 等のイベント駆動ライブラリ**: クラスレベル状態(Pyventus の EventLinker 等)が本設計のインスタンスベース DI と矛盾する、単一プロセス前提なので結局 Valkey Pub/Sub を別実装する必要がある、自前 InMemoryEventBus は40行程度で済むため依存追加のメリットが薄い、リアクティブ機能(Pyventus の Observable 等)は bancho サーバーで使う場面がない。ただし dataclass ベースのイベント定義、デコレータベースの購読、同期/非同期の両対応といった設計思想は本設計でも採用している

---

## 4. ディレクトリ構造

### 4.1 トップレベル

```
osu-server/
├── pyproject.toml
├── .env.example
├── docker-compose.yml
├── alembic.ini
├── README.md
│
├── src/
│   └── osu_server/
│       ├── __init__.py
│       ├── __main__.py            # python -m osu_server で app 起動
│       ├── app.py                 # Starlette ルートアプリの組み立て(app プロセス)
│       ├── worker.py              # ARQ ワーカー起動エントリ(worker プロセス)
│       ├── config.py              # Pydantic Settings
│       │
│       ├── transports/            # プロトコル別の入口(app プロセスのみ使用)
│       ├── services/              # ビジネスロジック(両プロセスで共有)
│       ├── domain/                # ドメインモデル(I/O 非依存)
│       ├── repositories/          # 永続化抽象と実装
│       ├── infrastructure/        # DB、キャッシュ、messaging、jobs、DI
│       └── shared/                # クロスカッティング(型、エラー、定数)
│
├── migrations/                    # alembic マイグレーション
├── tests/
│   ├── unit/
│   ├── integration/
│   └── conftest.py
└── scripts/                       # 運用ツール、データ移行など
```

実行プロセスは2つに分かれる。

- **app プロセス**: `uvicorn osu_server.app:app` で起動。HTTP / WebSocket リクエストを処理する
- **worker プロセス**: `arq osu_server.worker.WorkerSettings` で起動。ジョブキューからジョブを取り出して実行する

両プロセスは同じコードベースを共有するが、エントリポイントが異なる。`transports/` は app プロセスのみが使用し、`infrastructure/jobs/definitions/` の関数は worker プロセスから呼ばれる。`services/`, `domain/`, `repositories/` は両プロセスで共有される。

### 4.2 transports/

```
transports/
├── __init__.py
│
├── bancho/                        # bancho バイナリプロトコル(stable 用)
│   ├── __init__.py
│   ├── server.py                  # BanchoServer クラス(レジストリ + ディスパッチ)
│   ├── context.py                 # RequestContext, current_player など DI 用
│   ├── middleware.py              # 認証、レート制限、ロギング
│   ├── routes.py                  # Starlette Route 定義(POST / が bancho)
│   ├── broadcast.py               # services からのイベントを S2C で配信
│   │
│   ├── protocol/                  # ワイヤフォーマット定義
│   │   ├── __init__.py
│   │   ├── primitives.py          # BanchoString, ULEB128 等の基本型
│   │   ├── client_packet_id.py    # ClientPacketID enum (C2S)
│   │   ├── server_packet_id.py    # ServerPacketID enum (S2C)
│   │   ├── markers.py             # ClientPacket, ServerPacket Protocol
│   │   ├── encoder.py             # S2C の bytes 変換ヘルパー
│   │   ├── decoder.py             # C2S の bytes 復元ヘルパー
│   │   ├── c2s/                   # クライアント → サーバー パケット定義
│   │   │   ├── __init__.py
│   │   │   ├── auth.py            # LoginRequest 等
│   │   │   ├── chat.py            # SendPublicMessageC2S 等
│   │   │   ├── multiplayer.py
│   │   │   ├── spectator.py
│   │   │   └── status.py          # ChangeAction 等
│   │   └── s2c/                   # サーバー → クライアント パケット定義
│   │       ├── __init__.py
│   │       ├── auth.py            # LoginResponse 等
│   │       ├── chat.py            # SendMessageS2C 等
│   │       ├── multiplayer.py
│   │       ├── spectator.py
│   │       ├── notifications.py   # Announce, Notification
│   │       └── presence.py        # UserStats, UserPresence
│   │
│   └── handlers/                  # C2S パケットハンドラ
│       ├── __init__.py            # 全ハンドラを import(自動登録のため)
│       ├── auth.py                # ログイン処理
│       ├── chat.py                # チャット送受信
│       ├── multiplayer.py
│       ├── spectator.py
│       ├── status.py
│       └── presence.py
│
├── web_legacy/                    # /web/* レガシー HTTP エンドポイント
│   ├── __init__.py
│   ├── routes.py                  # Starlette Route 定義
│   ├── handlers/
│   │   ├── __init__.py
│   │   ├── score_submission.py    # osu-submit-modular-selector.php
│   │   ├── get_scores.py          # osu-osz2-getscores.php
│   │   ├── get_replay.py          # osu-getreplay.php
│   │   ├── check_updates.py       # check-updates.php
│   │   ├── seasonal.py            # osu-getseasonal.php
│   │   ├── lastfm.py              # lastfm.php
│   │   └── ...
│   └── utils/
│       ├── score_decryption.py    # AES Rijndael-256 復号
│       ├── client_hash.py         # クライアント整合性検証
│       └── replay_format.py       # .osr ファイル形式
│
├── api/                           # /api/v2/* モダン REST API
│   ├── __init__.py
│   ├── app.py                     # FastAPI インスタンス
│   ├── dependencies.py            # FastAPI Depends 共通定義
│   ├── auth/                      # OAuth2 / JWT 認証
│   │   ├── __init__.py
│   │   ├── oauth2.py
│   │   ├── jwt.py
│   │   └── scopes.py
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── users.py
│   │   ├── beatmaps.py
│   │   ├── beatmapsets.py
│   │   ├── scores.py
│   │   ├── chat.py
│   │   ├── friends.py
│   │   ├── rankings.py
│   │   ├── me.py
│   │   ├── notifications.py
│   │   ├── solo_scores.py         # /api/v2/beatmaps/{id}/solo/scores (lazer)
│   │   └── rooms.py               # マルチプレイ
│   ├── schemas/                   # Pydantic リクエスト/レスポンス
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── beatmap.py
│   │   ├── score.py
│   │   ├── chat.py
│   │   └── ...
│   └── interop/                   # /_lio/* 内部 API
│       ├── __init__.py
│       ├── routes.py
│       ├── auth.py                # 内部認証(共有秘密鍵 or IP 制限)
│       └── handlers.py
│
└── signalr/                       # SignalR ハブ(lazer 用)
    ├── __init__.py
    ├── server.py                  # SignalR サーバー実装(自前)
    ├── auth.py                    # JWT 検証(osu-web 発行のトークン)
    ├── protocol/                  # SignalR プロトコル(MessagePack ベース)
    │   ├── __init__.py
    │   ├── handshake.py
    │   ├── messages.py
    │   └── codec.py
    └── hubs/
        ├── __init__.py
        ├── spectator.py           # /spectator hub
        ├── multiplayer.py         # /multiplayer hub
        └── metadata.py            # /metadata hub
```

### 4.3 services/

```
services/
├── __init__.py
│
├── auth/
│   ├── __init__.py
│   ├── service.py                 # 認証ロジック(stable / lazer 両対応)
│   ├── stable_auth.py             # bancho バイナリプロトコルの認証フロー
│   ├── lazer_auth.py              # OAuth2 password grant フロー
│   ├── session.py                 # セッショントークン発行・検証
│   └── password.py                # パスワードハッシュ
│
├── chat/
│   ├── __init__.py
│   ├── service.py                 # メイン API: send_message, join_channel 等
│   ├── channel_registry.py        # チャンネル一覧・メンバーシップ管理
│   ├── moderation.py              # サイレンス、ミュート判定
│   └── filters.py                 # NG ワード、スパム検出
│
├── scoring/
│   ├── __init__.py
│   ├── service.py                 # submit_stable_score, submit_lazer_score
│   ├── stable_score_processor.py  # stable 形式 → 内部表現
│   ├── lazer_score_processor.py   # lazer 形式 → 内部表現
│   ├── leaderboard.py             # リーダーボード計算
│   ├── pp_calculator.py           # PP 計算(外部ライブラリラッパー)
│   ├── replay_storage.py          # リプレイファイル永続化
│   └── statistics_updater.py      # ユーザー統計更新
│
├── multiplayer/
│   ├── __init__.py
│   ├── service.py
│   ├── room.py                    # ルーム管理
│   ├── matchmaking.py             # ルーム検索・参加
│   └── score_aggregator.py        # マッチ内スコア集計
│
├── spectator/
│   ├── __init__.py
│   ├── service.py
│   └── frame_buffer.py            # フレームデータの一時保持
│
├── presence/
│   ├── __init__.py
│   ├── service.py                 # オンライン状態管理(bancho/lazer 統合)
│   ├── stable_presence.py         # bancho 接続中ユーザー
│   ├── lazer_presence.py          # metadata hub 接続中ユーザー
│   └── status.py                  # PlayerStatus(プレイ中、休止中など)
│
├── user/
│   ├── __init__.py
│   ├── service.py                 # プロフィール、設定管理
│   ├── friends.py                 # フレンドリスト
│   ├── blocks.py                  # ブロックリスト
│   └── achievements.py            # メダル
│
├── beatmap/
│   ├── __init__.py
│   ├── service.py
│   ├── lookup.py                  # MD5 / ID からの検索
│   ├── metadata_fetcher.py        # 外部 osu! API からの取得
│   └── difficulty_calculator.py   # 難易度計算ラッパー
│
└── events/                        # ドメインイベント定義
    ├── __init__.py
    ├── chat_events.py             # MessageSentEvent, ChannelJoinedEvent
    ├── score_events.py            # ScoreSubmittedEvent, NewBestEvent
    ├── presence_events.py         # PlayerOnlineEvent, PlayerOfflineEvent
    └── multiplayer_events.py      # MatchStartedEvent, RoomCreatedEvent
```

### 4.4 domain/

```
domain/
├── __init__.py
├── ids.py                         # UserId, BeatmapId 等の NewType
├── enums.py                       # Privileges, GameMode, RankedStatus, etc.
│
├── player.py                      # Player(オンライン状態を持つエンティティ)
├── user.py                        # User(永続的なアカウント情報)
├── score.py                       # Score(送信済みスコア)
├── beatmap.py                     # Beatmap, Beatmapset
├── channel.py                     # Channel(チャットチャンネル)
├── message.py                     # Message
├── match.py                       # Match(マルチプレイマッチ)
├── room.py                        # Room(マルチプレイルーム)
├── replay.py                      # Replay
├── mods.py                        # Mods, ModSettings(lazer 対応)
└── statistics.py                  # UserStatistics(各ゲームモード別)
```

### 4.5 repositories/

```
repositories/
├── __init__.py
│
├── interfaces/                    # 抽象インターフェース(Protocol)
│   ├── __init__.py
│   ├── user_repository.py
│   ├── score_repository.py
│   ├── beatmap_repository.py
│   ├── replay_repository.py
│   ├── message_repository.py
│   └── channel_repository.py
│
├── sqlalchemy/                    # SQLAlchemy 実装
│   ├── __init__.py
│   ├── models/                    # ORM モデル(SQLAlchemy 2.0 Mapped)
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── score.py
│   │   ├── beatmap.py
│   │   └── ...
│   ├── user_repository.py
│   ├── score_repository.py
│   └── ...
│
└── memory/                        # in-memory 実装(テスト用)
    ├── __init__.py
    ├── user_repository.py
    └── ...
```

### 4.6 infrastructure/

```
infrastructure/
├── __init__.py
│
├── database/
│   ├── __init__.py
│   ├── engine.py                  # SQLAlchemy エンジン作成
│   ├── session.py                 # セッション管理、UoW
│   └── transactions.py            # トランザクション境界
│
├── cache/
│   ├── __init__.py
│   ├── redis_client.py            # Valkey 接続(全用途で共有する基盤クライアント)
│   └── decorators.py              # @cached() デコレータ等
│
├── state/                         # 揮発的ステートの中央ストア(セクション 8.5)
│   ├── __init__.py
│   ├── interfaces/                # Protocol 定義(他レイヤーはここに依存)
│   │   ├── __init__.py
│   │   ├── session_store.py       # SessionStore: ログインセッション
│   │   ├── presence_store.py      # PresenceStore: オンライン状態、現在のステータス
│   │   ├── channel_state_store.py # ChannelStateStore: チャンネルメンバー
│   │   ├── match_state_store.py   # MatchStateStore: マルチプレイルーム状態
│   │   ├── packet_queue.py        # PacketQueue: stable 用保留 S2C パケット
│   │   ├── spectator_state_store.py # SpectatorStateStore: 観戦関係
│   │   ├── ratelimit_store.py     # RateLimitStore: レート制限カウンター
│   │   └── lock_store.py          # LockStore: 分散ロック
│   ├── redis/                     # Valkey 実装(本番用、Redis プロトコル互換)
│   │   ├── __init__.py
│   │   ├── session_store.py
│   │   ├── presence_store.py
│   │   ├── channel_state_store.py
│   │   ├── match_state_store.py
│   │   ├── packet_queue.py
│   │   ├── spectator_state_store.py
│   │   ├── ratelimit_store.py
│   │   ├── lock_store.py
│   │   └── keys.py                # Valkey キー命名規約の集約
│   └── memory/                    # in-memory 実装(テスト・単一プロセス開発用)
│       ├── __init__.py
│       ├── session_store.py
│       └── ...
│
├── messaging/                     # fire-and-forget な配信(EventBus)
│   ├── __init__.py
│   ├── interface.py               # EventBus Protocol
│   ├── in_memory.py               # in-process 実装(開発・テスト用)
│   └── redis_pubsub.py            # Valkey Pub/Sub 実装(本番用)
│
├── jobs/                          # 配信保証ありのジョブ実行(JobQueue)
│   ├── __init__.py
│   ├── interface.py               # JobQueue Protocol
│   ├── arq_adapter.py             # ARQ アダプタ実装
│   ├── in_memory.py               # in-process 実装(テスト用)
│   ├── worker_settings.py         # ARQ WorkerSettings(ワーカープロセス起動用)
│   └── definitions/               # ジョブハンドラ定義
│       ├── __init__.py            # 全ジョブを集約 import(登録のため)
│       ├── score_processing.py    # PP 計算、リーダーボード更新、統計更新
│       ├── notification_delivery.py
│       ├── achievement_check.py
│       ├── statistics_recalculation.py
│       └── scheduled.py           # 定期実行ジョブ(ランキング再計算等)
│
├── di/
│   ├── __init__.py
│   ├── container.py               # DI コンテナ
│   └── providers.py               # 各依存の生成方法定義
│
├── http_clients/
│   ├── __init__.py
│   ├── osu_api.py                 # 公式 osu! API v1/v2 クライアント
│   └── beatmap_mirror.py          # ビートマップミラー
│
├── storage/
│   ├── __init__.py
│   ├── interface.py               # Storage Protocol
│   ├── local.py                   # ローカルファイルシステム
│   └── s3.py                      # S3 互換オブジェクトストレージ
│
└── logging/
    ├── __init__.py
    ├── config.py                  # ロガー設定
    └── middleware.py              # リクエストロギング
```

`infrastructure/` 配下の3つのサブディレクトリ(`state/`, `messaging/`, `jobs/`)は、それぞれ責務が異なるため明確に分離する。混同すると設計が崩れる。

| ディレクトリ | 役割 | 想定遅延 | 永続化 | 用途例 |
|---|---|---|---|---|
| `state/` | 揮発的ステートの読み書き(同期的) | 1 ms 未満 | Valkey のメモリ上(任意で AOF) | セッション参照、プレゼンス更新、チャンネルメンバー取得 |
| `messaging/` | fire-and-forget な配信(非同期) | 数 ms 〜 数十 ms | なし | チャット配信、プレゼンス通知、フレーム配信 |
| `jobs/` | 配信保証ありのジョブ実行(非同期、ワーカー処理) | 数秒 〜 数分 | あり | スコア後処理、通知配信、メダル付与、定期実行 |

`state/` と `messaging/` の違いは「同期的にデータを読み書きするか、非同期にイベントを送るか」である。同じ Valkey 基盤を使うが、API も用途も異なる。具体的な使い分けはセクション 8.5 と 8.8 を参照。

### 4.7 shared/

```
shared/
├── __init__.py
├── errors.py                      # 共通例外(DomainError 等)
├── result.py                      # Result/Either 型(オプション)
├── types.py                       # 共通型エイリアス
├── constants.py                   # bancho プロトコル定数等
└── utils/
    ├── __init__.py
    ├── time.py                    # タイムゾーン処理
    ├── strings.py                 # 文字列ユーティリティ
    └── crypto.py                  # 共通暗号処理
```

---

## 5. プロトコル仕様の取り扱い

### 5.1 bancho パケット(C2S / S2C 分離)

bancho プロトコルでは、パケット ID が方向(C2S / S2C)ごとに独立した名前空間を持つ。同じ ID が方向によって異なるパケットを表すことがあるため、必ず別 enum として定義する。

```python
# transports/bancho/protocol/client_packet_id.py
from enum import IntEnum

class ClientPacketID(IntEnum):
    """クライアント → サーバー(C2S)パケット ID"""
    CHANGE_ACTION = 0
    SEND_PUBLIC_MESSAGE = 1
    EXIT = 2
    REQUEST_STATUS_UPDATE = 3
    PING = 4
    START_SPECTATING = 16
    # ...

# transports/bancho/protocol/server_packet_id.py
class ServerPacketID(IntEnum):
    """サーバー → クライアント(S2C)パケット ID"""
    USER_ID = 5
    SEND_MESSAGE = 7
    PONG = 8
    USER_STATS = 11
    USER_LOGOUT = 12
    SPECTATOR_JOINED = 13
    # ...
```

### 5.2 パケット定義(Caterpillar)

各パケットは Caterpillar の `@struct` を用いて宣言的に定義する。バイトレベルの読み書きを手書きしない。

```python
# transports/bancho/protocol/primitives.py
from caterpillar.py import struct, LittleEndian, uint8

@struct(order=LittleEndian)
class BanchoString:
    """bancho プロトコル独自の文字列型(present marker + ULEB128 length + UTF-8)"""
    present: uint8
    length: ULEB128(if_=this.present == 0x0b)
    value: String(this.length, encoding="utf-8", if_=this.present == 0x0b)

# transports/bancho/protocol/c2s/chat.py
from caterpillar.py import struct, LittleEndian, int32
from transports.bancho.protocol.primitives import BanchoString
from transports.bancho.protocol.markers import ClientPacket

@struct(order=LittleEndian)
class SendPublicMessageC2S(ClientPacket):
    """クライアントが送信するチャットメッセージ。
    sender と sender_id は無視される(サーバーが認証情報から決定)。"""
    sender: BanchoString  # 通常は空文字列
    message: BanchoString
    target: BanchoString
    sender_id: int32  # 通常は 0

# transports/bancho/protocol/s2c/chat.py
@struct(order=LittleEndian)
class SendMessageS2C(ServerPacket):
    """サーバーがクライアントに配信するチャットメッセージ"""
    sender: BanchoString
    message: BanchoString
    target: BanchoString
    sender_id: int32
```

### 5.3 マーカー Protocol による方向制約

C2S と S2C を型レベルで区別するため、マーカー Protocol を導入する。

```python
# transports/bancho/protocol/markers.py
from typing import Protocol, runtime_checkable

@runtime_checkable
class ClientPacket(Protocol):
    """C2S パケットのマーカー。受信処理のみで扱われる。"""
    pass

@runtime_checkable
class ServerPacket(Protocol):
    """S2C パケットのマーカー。送信処理のみで扱われる。"""
    pass
```

ハンドラ登録、ブロードキャスト関数のシグネチャでこの Protocol を要求し、方向の取り違えを型チェッカーで検出する。

### 5.4 REST API スキーマ(Pydantic)

`/api/v2/*` のリクエスト / レスポンスは Pydantic モデルで定義する。

```python
# transports/api/schemas/user.py
from pydantic import BaseModel, Field
from datetime import datetime

class UserResponse(BaseModel):
    id: int
    username: str = Field(min_length=2, max_length=15)
    country_code: str
    pp: float
    accuracy: float
    play_count: int
    join_date: datetime
```

ドメインモデル(`domain/user.py` の `User`)とは別物として扱う。リポジトリやサービスからドメインモデルを受け取り、トランスポート層で DTO に変換する。

### 5.5 SignalR メッセージ

SignalR over WebSocket は MessagePack ベースの単純な RPC プロトコル。osu-server-spectator のメッセージ形式を観察し、自前で互換実装する。メッセージペイロードは `msgspec.Struct` または Pydantic で型定義する。

---

## 6. ディスパッチ機構

### 6.1 デコレータ駆動の登録

bancho パケットハンドラはデコレータで宣言的に登録する。`match` 文による集中ディスパッチは採用しない。

```python
# transports/bancho/server.py
from dataclasses import dataclass
from typing import Awaitable, Callable

@dataclass
class HandlerSpec:
    func: Callable[..., Awaitable[None]]
    requires_auth: bool
    rate_limit: RateLimit | None

class BanchoServer:
    def __init__(self):
        self._handlers: dict[ClientPacketID, HandlerSpec] = {}

    def handler(
        self,
        packet_id: ClientPacketID,
        *,
        requires_auth: bool = True,
        rate_limit: RateLimit | None = None,
    ):
        """C2S パケットのハンドラを登録するデコレータ"""
        def decorator(func):
            if packet_id in self._handlers:
                raise ValueError(f"Duplicate handler for {packet_id}")
            self._handlers[packet_id] = HandlerSpec(
                func=func,
                requires_auth=requires_auth,
                rate_limit=rate_limit,
            )
            return func
        return decorator

    async def dispatch(self, raw: bytes, ctx: RequestContext) -> bytes:
        """C2S パケットを受信、処理、S2C パケットを返す"""
        ...

# グローバル(モジュール内)シングルトンとして公開
bancho = BanchoServer()
```

### 6.2 ハンドラ実装

ハンドラは1ファイル1機能の粒度で配置し、Annotated 型ヒントによる依存性注入を活用する。

```python
# transports/bancho/handlers/chat.py
from typing import Annotated
from transports.bancho.server import bancho
from transports.bancho.protocol.client_packet_id import ClientPacketID
from transports.bancho.protocol.c2s.chat import SendPublicMessageC2S
from transports.bancho.context import current_player, RateLimit
from services.chat import service as chat_service
from domain.player import Player

@bancho.handler(
    ClientPacketID.SEND_PUBLIC_MESSAGE,
    rate_limit=RateLimit(messages=10, per_seconds=5),
)
async def handle_send_public_message(
    packet: SendPublicMessageC2S,
    player: Annotated[Player, Depends(current_player)],
):
    await chat_service.send_message(
        sender_id=player.id,
        channel_name=packet.target,
        content=packet.message,
    )
```

### 6.3 自動登録のメカニズム

ハンドラの登録は **モジュールが import された時点** で発生する。エントリポイントで明示的に副作用 import を行う。

```python
# transports/bancho/handlers/__init__.py
"""このパッケージを import すると全ハンドラがレジストリに登録される"""
from . import auth        # noqa: F401
from . import chat        # noqa: F401
from . import multiplayer # noqa: F401
from . import spectator   # noqa: F401
from . import status      # noqa: F401
from . import presence    # noqa: F401
```

`pkgutil.iter_modules` による動的 discovery は採用しない。明示的列挙の方が「何が登録されているか」の可視性が高く、エラー発生時の追跡が容易なため。

### 6.4 横断的関心事の処理

認証、レート制限、ロギング、メトリクスなどはディスパッチャ側で一元的に処理する。各ハンドラは純粋なビジネスロジックに集中する。

```python
# BanchoServer.dispatch の概略
async def dispatch(self, raw, ctx):
    packet_id, payload = parse_header(raw)
    spec = self._handlers.get(packet_id)
    if spec is None:
        return

    # 認証チェック
    if spec.requires_auth and ctx.player is None:
        raise AuthenticationError()

    # レート制限
    if spec.rate_limit:
        await self._rate_limiter.check(ctx.player, spec.rate_limit)

    # パケットパース
    packet = decode_packet(packet_id, payload)

    # ハンドラ呼び出し(DI 解決を含む)
    await self._call_with_di(spec.func, packet, ctx)
```

---

## 7. データモデル戦略

### 7.1 レイヤーごとの使い分け

| レイヤー | ライブラリ | 用途 |
|---|---|---|
| API I/O(REST) | Pydantic v2 | リクエスト / レスポンス DTO、自動バリデーション、OpenAPI 生成 |
| バイナリプロトコル(bancho) | Caterpillar | パケットレイアウトの宣言的定義、双方向シリアライズ |
| SignalR メッセージ | msgspec.Struct または Pydantic | MessagePack シリアライズ |
| ドメインモデル | `@dataclass(slots=True)` | エンティティ、不変条件をメソッドで表現 |
| 値オブジェクト・イベント | `@dataclass(frozen=True, slots=True)` | 不変性、等価性 |
| ORM モデル | SQLAlchemy 2.0 `Mapped[...]` | DB スキーマ表現 |
| 設定 | pydantic-settings | 環境変数の型安全な読み込み |

### 7.2 ドメインモデルの設計原則

ドメインモデルは I/O 依存を持たず、純粋なドメインロジックの表現に徹する。

```python
# domain/player.py
from dataclasses import dataclass, field
from domain.ids import UserId, MatchId
from domain.enums import Privileges, PlayerStatus
from shared.errors import InvalidStateError

@dataclass(slots=True)
class Player:
    """オンライン中のプレイヤーセッション"""
    id: UserId
    username: str
    country_code: str
    privileges: Privileges

    status: PlayerStatus = PlayerStatus.IDLE
    current_beatmap_id: int | None = None
    current_match: MatchId | None = None

    def can_chat_in(self, channel: "Channel") -> bool:
        """ドメインルール: チャット可否判定"""
        if self.privileges & Privileges.SILENCED:
            return False
        if channel.requires_privilege:
            return bool(self.privileges & channel.required_privilege)
        return True

    def join_match(self, match_id: MatchId) -> None:
        """ドメインルール: マッチ参加時の状態遷移"""
        if self.current_match is not None:
            raise InvalidStateError("Already in a match")
        self.status = PlayerStatus.MULTIPLAYING
        self.current_match = match_id
```

### 7.3 ID の型安全

すべての ID は `NewType` で型を区別し、誤って異なる種類の ID を渡すことを静的に防ぐ。

```python
# domain/ids.py
from typing import NewType

UserId = NewType("UserId", int)
BeatmapId = NewType("BeatmapId", int)
BeatmapsetId = NewType("BeatmapsetId", int)
ScoreId = NewType("ScoreId", int)
MatchId = NewType("MatchId", int)
RoomId = NewType("RoomId", int)
MessageId = NewType("MessageId", int)
ChannelName = NewType("ChannelName", str)
```

### 7.4 ORM モデルとドメインモデルの分離

リポジトリ実装は ORM モデルとドメインモデルの双方向変換を担当する。ORM モデルが外部レイヤーに漏れることを禁止する。

```python
# repositories/sqlalchemy/user_repository.py
from sqlalchemy.ext.asyncio import AsyncSession
from domain.user import User
from domain.ids import UserId
from repositories.sqlalchemy.models.user import UserModel

class SqlAlchemyUserRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def find_by_id(self, user_id: UserId) -> User | None:
        record = await self._session.get(UserModel, int(user_id))
        if record is None:
            return None
        return self._to_domain(record)

    def _to_domain(self, model: UserModel) -> User:
        return User(
            id=UserId(model.id),
            username=model.username,
            country_code=model.country_code,
            privileges=Privileges(model.privileges),
            ...
        )
```

---

## 8. 依存性注入とインフラ抽象

本章では、サービス間の疎結合を実現する仕組みとして、依存性注入(DI)、メッセージング(EventBus)、ジョブ実行(JobQueue)、ステート管理(StateStore)の4つを定義する。これらは異なる責務を持ち、適切に使い分ける。

| 機構 | 責務 | 同期/非同期 | 永続化 | 配信保証 | クリティカル処理に使えるか |
|---|---|---|---|---|---|
| DI コンテナ | 依存解決 | 同期 | - | - | - |
| StateStore | 揮発的ステート管理 | 同期(read/write) | Valkey メモリ | - | △(明示的に書き込めば残る) |
| EventBus | fire-and-forget 通知 | 非同期 | なし | なし | ✗(消失の可能性) |
| JobQueue | 配信保証ありの仕事依頼 | 非同期 | あり | あり | ◎(必ず実行される) |

特に重要な原則: **データ整合性に影響する処理(スコア後処理、PP 計算、リーダーボード更新、メダル付与等)は、消失すると復旧困難になるため必ず JobQueue 経由で実行する**。詳細はセクション 8.9 を参照。

### 8.1 DI コンテナ

依存性注入は自前の軽量コンテナで実装する。Protocol(抽象インターフェース)に対する具象実装を登録し、サービス層やハンドラ層が Protocol に依存する形を維持する。

```python
# infrastructure/di/container.py
from typing import TypeVar, Type, Callable

T = TypeVar("T")

class Container:
    def __init__(self):
        self._providers: dict[type, Callable] = {}
        self._singletons: dict[type, object] = {}

    def register(self, interface: Type[T], factory: Callable[[], T]) -> None:
        self._providers[interface] = factory

    def register_singleton(self, interface: Type[T], factory: Callable[[], T]) -> None:
        self._providers[interface] = factory
        self._singletons[interface] = None  # 遅延生成

    async def resolve(self, interface: Type[T]) -> T:
        if interface in self._singletons:
            if self._singletons[interface] is None:
                self._singletons[interface] = await self._call(self._providers[interface])
            return self._singletons[interface]
        return await self._call(self._providers[interface])
```

### 8.2 アプリケーション全体の組み立て

DI コンテナの設定は `infrastructure/di/providers.py` に集約する。これがアプリケーション全体の組み立て図となる。app プロセスと worker プロセスで同じコンテナビルダーを共有し、環境変数で実装を切り替える。

```python
# infrastructure/di/providers.py
def build_container(config: AppConfig) -> Container:
    container = Container()

    # Infrastructure: 共通(Valkey 接続、DB エンジン)
    container.register_singleton(AsyncEngine, lambda: create_async_engine(config.database_url))
    container.register_singleton(Redis, lambda: Redis.from_url(config.redis_url))

    # State stores: 環境別に実装を切替
    if config.environment in ("test", "development_solo"):
        container.register_singleton(SessionStore, InMemorySessionStore)
        container.register_singleton(PresenceStore, InMemoryPresenceStore)
        container.register_singleton(ChannelStateStore, InMemoryChannelStateStore)
        container.register_singleton(MatchStateStore, InMemoryMatchStateStore)
        container.register_singleton(PacketQueue, InMemoryPacketQueue)
        container.register_singleton(SpectatorStateStore, InMemorySpectatorStateStore)
        container.register_singleton(RateLimitStore, InMemoryRateLimitStore)
        container.register_singleton(LockStore, InMemoryLockStore)
    else:
        redis = Redis.from_url(config.redis_url)
        container.register_singleton(SessionStore, lambda: RedisSessionStore(redis))
        container.register_singleton(PresenceStore, lambda: RedisPresenceStore(redis))
        container.register_singleton(ChannelStateStore, lambda: RedisChannelStateStore(redis))
        container.register_singleton(MatchStateStore, lambda: RedisMatchStateStore(redis))
        container.register_singleton(PacketQueue, lambda: RedisPacketQueue(redis))
        container.register_singleton(SpectatorStateStore, lambda: RedisSpectatorStateStore(redis))
        container.register_singleton(RateLimitStore, lambda: RedisRateLimitStore(redis))
        container.register_singleton(LockStore, lambda: RedisLockStore(redis))

    # Messaging: 環境別に実装を切替
    if config.environment == "test":
        container.register_singleton(EventBus, InMemoryEventBus)
        container.register_singleton(JobQueue, InMemoryJobQueue)
    else:
        container.register_singleton(EventBus, lambda: RedisPubSubEventBus(redis=...))
        container.register_singleton(JobQueue, lambda: ArqJobQueueAdapter(redis=...))

    # Repositories
    container.register(UserRepository, lambda: SqlAlchemyUserRepository(...))
    container.register(ScoreRepository, lambda: SqlAlchemyScoreRepository(...))

    # Services
    container.register_singleton(AuthService, lambda: AuthService(...))
    container.register_singleton(ChatService, lambda: ChatService(...))
    container.register_singleton(ScoringService, lambda: ScoringService(...))

    return container
```

### 8.3 EventBus(Fire-and-Forget な配信)

チャット配信、プレゼンス更新、spectator フレーム配信などの **配信ロスを許容する低レイテンシ通知** に使用する。`infrastructure/messaging/` 配下に Protocol と実装を配置する。

```python
# infrastructure/messaging/interface.py
from typing import Protocol, Type, Callable, Awaitable, TypeVar

E = TypeVar("E")

class EventBus(Protocol):
    """Fire-and-forget な配信。配信保証なし。

    用途:
      - チャットメッセージの配信
      - オンライン状態(プレゼンス)の更新
      - spectator フレーム配信
      - その他、ロスしても再取得 / 再同期で復旧可能なイベント
    """
    async def publish(self, event: object) -> None: ...
    def subscribe(
        self,
        event_type: Type[E],
        handler: Callable[[E], Awaitable[None]],
    ) -> None: ...
```

実装は2種類用意する。

```python
# infrastructure/messaging/in_memory.py
class InMemoryEventBus:
    """単一プロセス用。開発・テスト・小規模運用で使用。"""
    def __init__(self):
        self._handlers: dict[type, list[Callable]] = defaultdict(list)

    async def publish(self, event):
        for handler in self._handlers[type(event)]:
            asyncio.create_task(handler(event))

    def subscribe(self, event_type, handler):
        self._handlers[event_type].append(handler)


# infrastructure/messaging/redis_pubsub.py
class RedisPubSubEventBus:
    """Redis Pub/Sub による分散実装。本番運用で使用。"""
    async def publish(self, event):
        channel = type(event).__name__
        payload = msgpack.packb(self._event_to_dict(event))
        await self._redis.publish(channel, payload)

    # subscribe は別タスクで pubsub.listen() を回す
```

使用例として、チャットサービスからの配信を示す。

```python
# services/chat/service.py
class ChatService:
    def __init__(self, event_bus: EventBus, message_repo: MessageRepository):
        self._event_bus = event_bus
        self._message_repo = message_repo

    async def send_message(self, sender_id, channel, content):
        message = await self._message_repo.save(...)
        # 配信ロス許容(オフラインユーザーは DB から後で取得可能)
        await self._event_bus.publish(MessageSentEvent(
            message_id=message.id,
            channel_name=channel,
            sender_id=sender_id,
            content=content,
        ))


# transports/bancho/broadcast.py
@event_bus.subscribe(MessageSentEvent)
async def broadcast_message_to_bancho_clients(event: MessageSentEvent):
    """EventBus を購読し、bancho 接続中の stable ユーザーへ S2C パケットで配信"""
    channel = bancho_state.get_channel(event.channel_name)
    if channel is None:
        return
    packet = SendMessageS2C(...)
    for player in channel.bancho_players:
        await player.send_packet(packet)
```

### 8.4 JobQueue(配信保証ありのジョブ実行)

スコア後処理、通知配信、メダル付与判定など、 **失敗時に再試行が必要な処理** に使用する。`infrastructure/jobs/` 配下に Protocol と ARQ 実装を配置する。

```python
# infrastructure/jobs/interface.py
from typing import Protocol
from datetime import datetime

class JobQueue(Protocol):
    """配信保証ありのジョブ実行。

    用途:
      - スコア後処理(PP 計算、リーダーボード更新、統計更新)
      - 通知配信
      - メダル / 実績判定
      - 定期実行(ランキング再計算、セッション期限切れ清掃)
      - その他、失敗時に再試行すべき処理
    """
    async def enqueue(self, job_name: str, **kwargs) -> str:
        """ジョブを即時実行用にエンキュー。job_id を返す。"""
        ...

    async def enqueue_in(self, delay_seconds: int, job_name: str, **kwargs) -> str:
        """指定秒数後に実行するジョブをエンキュー。"""
        ...

    async def schedule_at(self, run_at: datetime, job_name: str, **kwargs) -> str:
        """指定日時に実行するジョブをエンキュー。"""
        ...
```

ARQ アダプタ実装は以下のように記述する。

```python
# infrastructure/jobs/arq_adapter.py
from arq.connections import ArqRedis
from datetime import datetime, timedelta

class ArqJobQueueAdapter:
    def __init__(self, redis: ArqRedis):
        self._redis = redis

    async def enqueue(self, job_name: str, **kwargs) -> str:
        job = await self._redis.enqueue_job(job_name, **kwargs)
        return job.job_id

    async def enqueue_in(self, delay_seconds: int, job_name: str, **kwargs) -> str:
        job = await self._redis.enqueue_job(
            job_name,
            _defer_by=timedelta(seconds=delay_seconds),
            **kwargs,
        )
        return job.job_id

    async def schedule_at(self, run_at: datetime, job_name: str, **kwargs) -> str:
        job = await self._redis.enqueue_job(
            job_name,
            _defer_until=run_at,
            **kwargs,
        )
        return job.job_id
```

ジョブ定義は薄い関数として記述し、 **実際のロジックは services 層に委譲** する。これによりジョブ経由でも同期 API 経由でも同じコードパスを通る。

```python
# infrastructure/jobs/definitions/score_processing.py

async def process_score(ctx, score_id: int):
    """スコア送信後の後処理パイプライン。

    PP 計算 → リーダーボード更新 → ユーザー統計更新 を順次実行する。
    冪等性を保ち、リトライされても結果が変わらないこと。
    """
    container = ctx["container"]
    scoring_service = await container.resolve(ScoringService)

    if await scoring_service.is_score_processed(score_id):
        return  # 冪等性保証

    await scoring_service.calculate_and_persist_pp(score_id)
    await scoring_service.update_leaderboards(score_id)
    await scoring_service.update_user_statistics(score_id)
    await scoring_service.mark_score_processed(score_id)


async def recalculate_user_pp(ctx, user_id: int):
    """ユーザーの全スコア PP 再計算。マップ仕様変更時などに発火。"""
    container = ctx["container"]
    scoring_service = await container.resolve(ScoringService)
    await scoring_service.recalculate_user_pp(user_id)
```

サービス層からのジョブ投入例。

```python
# services/scoring/service.py
class ScoringService:
    def __init__(
        self,
        score_repo: ScoreRepository,
        job_queue: JobQueue,
        event_bus: EventBus,
    ):
        self._score_repo = score_repo
        self._job_queue = job_queue
        self._event_bus = event_bus

    async def submit_lazer_score(self, score_data) -> Score:
        # 同期処理:即座にスコアを保存(クライアントへの応答に必要)
        score = await self._score_repo.save(...)

        # 配信保証必要な処理 → JobQueue
        await self._job_queue.enqueue("process_score", score_id=int(score.id))
        await self._job_queue.enqueue("check_achievements", user_id=int(score.user_id), score_id=int(score.id))

        # ロス許容なリアルタイム通知 → EventBus
        await self._event_bus.publish(ScoreSubmittedEvent(
            score_id=score.id,
            user_id=score.user_id,
        ))

        return score
```

### 8.5 ステート管理戦略(Valkey 中央集約)

bancho サーバーが扱うデータは、永続化が必要なもの(ユーザー、スコア、ビートマップ等)と、揮発的だが複数プロセス・複数リクエストにまたがって共有されるもの(セッション、プレゼンス、チャンネル参加状況等)に分けられる。本設計では **後者を Valkey に集約** する。

bancho.py や Ripple では、これらの揮発的ステートをアプリケーションプロセスのメモリ(Python のグローバル変数や `app.state.*`)に保持していた。これは以下の問題を引き起こす。

- **プロセス再起動でセッション全消失**: 接続中ユーザー全員が強制ログアウトされる
- **トランスポートの水平スケール不能**: 複数 bancho プロセスを立てると、ロードバランサーが分散した先でセッションが見つからない
- **プロトコル間のステート分断**: stable と lazer で同じユーザーが別々に管理される
- **メモリ消費の制約**: プロセスメモリが上限となり、同時接続数がスケールしない

Valkey 集約はこれらをすべて解決する。

#### 8.5.1 揮発的ステートの分類

bancho サーバーが保持する揮発的データを以下に分類する。すべて Valkey に置く。

| カテゴリ | 内容 | 永続化 | TTL | アクセス頻度 |
|---|---|---|---|---|
| セッション | ログイントークン、認証情報、接続中ユーザーの ID | 不要 | 長め(分〜時間) | 高 |
| プレゼンス | オンライン状態、現在のステータス、プレイ中のマップ、mods | 不要 | ハートビート間隔 | 高 |
| チャンネル状態 | 各チャンネルのメンバー一覧 | 不要 | セッション連動 | 中 |
| マッチ状態 | マルチプレイルームの状態、参加者、設定 | マッチ終了時に履歴のみ DB | 不要(明示的削除) | 中 |
| パケットキュー | 各ユーザー宛の保留中 S2C パケット | 不要 | 短め(数十秒) | 高 |
| spectator 状態 | 誰が誰を観戦中か | 不要 | セッション連動 | 中 |
| レート制限カウンター | パケット送信頻度、API コール頻度 | 不要 | 短(秒〜分) | 高 |
| 分散ロック | 同時実行制御(ルーム編集排他等) | 不要 | 短(数秒) | 低 |

#### 8.5.2 Protocol 抽象化

各ステートは `infrastructure/state/interfaces/` 配下で Protocol として抽象化する。サービス層・トランスポート層は Protocol に依存し、具体実装(Valkey / in-memory)を知らない。

```python
# infrastructure/state/interfaces/session_store.py
from typing import Protocol
from domain.ids import UserId
from domain.session import Session, Token

class SessionStore(Protocol):
    async def create(self, user_id: UserId, client_type: str) -> Token: ...
    async def get(self, token: Token) -> Session | None: ...
    async def get_by_user(self, user_id: UserId) -> Session | None: ...
    async def touch(self, token: Token) -> None: ...   # last_seen を更新
    async def delete(self, token: Token) -> None: ...
    async def list_online_user_ids(self) -> list[UserId]: ...


# infrastructure/state/interfaces/presence_store.py
class PresenceStore(Protocol):
    async def update(self, user_id: UserId, presence: Presence) -> None: ...
    async def get(self, user_id: UserId) -> Presence | None: ...
    async def get_many(self, user_ids: list[UserId]) -> dict[UserId, Presence]: ...
    async def delete(self, user_id: UserId) -> None: ...


# infrastructure/state/interfaces/channel_state_store.py
class ChannelStateStore(Protocol):
    async def add_member(self, channel: ChannelName, user_id: UserId) -> None: ...
    async def remove_member(self, channel: ChannelName, user_id: UserId) -> None: ...
    async def get_members(self, channel: ChannelName) -> set[UserId]: ...
    async def is_member(self, channel: ChannelName, user_id: UserId) -> bool: ...
    async def get_channels_of_user(self, user_id: UserId) -> set[ChannelName]: ...


# infrastructure/state/interfaces/packet_queue.py
class PacketQueue(Protocol):
    async def enqueue(self, user_id: UserId, packet: bytes) -> None: ...
    async def dequeue_all(self, user_id: UserId) -> list[bytes]: ...
    async def clear(self, user_id: UserId) -> None: ...
```

#### 8.5.3 Valkey キー設計

`infrastructure/state/redis/keys.py` に Valkey のキー命名規約を集約する。これにより、複数のストア実装間でキー名の衝突や暗黙の依存を防ぐ。

```python
# infrastructure/state/redis/keys.py
"""Valkey キー命名規約。すべてのキーは小文字、コロン区切り、英数字のみを使う。"""

# セッション
def session_key(token: str) -> str: return f"session:{token}"
def user_session_key(user_id: int) -> str: return f"user_session:{user_id}"
ONLINE_USERS_ZSET = "online_users"  # member: user_id, score: last_seen timestamp

# プレゼンス
def presence_key(user_id: int) -> str: return f"presence:{user_id}"

# チャンネル
def channel_members_key(channel: str) -> str: return f"channel_members:{channel}"
def user_channels_key(user_id: int) -> str: return f"user_channels:{user_id}"

# パケットキュー
def packet_queue_key(user_id: int) -> str: return f"packet_queue:{user_id}"

# マッチ
def match_key(match_id: int) -> str: return f"match:{match_id}"
def match_members_key(match_id: int) -> str: return f"match_members:{match_id}"

# spectator
def spectators_of_key(target_id: int) -> str: return f"spectators_of:{target_id}"
def spectating_key(spectator_id: int) -> str: return f"spectating:{spectator_id}"

# レート制限
def ratelimit_key(category: str, user_id: int) -> str:
    return f"ratelimit:{category}:{user_id}"

# ロック
def lock_key(resource: str, resource_id: str | int) -> str:
    return f"lock:{resource}:{resource_id}"
```

将来 Valkey Cluster へ移行する可能性を考慮し、 **複数キーを atomic に操作する場合は hash tag** を使う。例えば、ユーザー単位で複数のキーを同一トランザクションで触る場合:

```
session:{user:12345}
presence:{user:12345}
user_channels:{user:12345}
```

`{user:12345}` の部分が同じスロットに配置されるため、Valkey Cluster 化後も MULTI/EXEC が機能する。

#### 8.5.4 アクセス権限のルール

「Valkey 上の揮発的ステートに、どのレイヤーがアクセスして良いか」を明確化する。原則として **すべてのレイヤーが state Protocol を介して Valkey にアクセスして良い** が、永続データ(DB)へのアクセスはサービス層に限定する。

| レイヤー | state にアクセス可能 | repositories にアクセス可能 |
|---|---|---|
| transports/ | Yes(Protocol 経由) | No |
| services/ | Yes | Yes |
| repositories/ | No | 自身のみ |
| infrastructure/jobs/definitions/ | Yes | Yes(サービス経由) |

特に `transports/bancho/` は **パケットキューを直接ポーリング** する必要がある(stable クライアントが頻繁に POST で取りに来るため)。これをすべてサービス経由にすると遅すぎるため、PacketQueue Protocol を直接使うことを許容する。一方で「スコア送信」「メダル付与」等のビジネスロジックを伴う処理は必ずサービス層を経由させる。

#### 8.5.5 サービス層からの利用例

セッション管理はサービス層で完結する例を示す。

```python
# services/auth/service.py
class AuthService:
    def __init__(
        self,
        user_repo: UserRepository,
        session_store: SessionStore,
        presence_store: PresenceStore,
        event_bus: EventBus,
    ):
        self._user_repo = user_repo
        self._session_store = session_store
        self._presence_store = presence_store
        self._event_bus = event_bus

    async def login_stable(
        self,
        username: str,
        password_md5: str,
        client_hashes: ClientHashes,
    ) -> Session:
        user = await self._user_repo.find_by_username(username)
        if user is None or not verify_password(password_md5, user.password_hash):
            raise InvalidCredentialsError()

        # セッション発行(Valkey に保存)
        token = await self._session_store.create(user.id, client_type="stable")

        # プレゼンス初期化(Valkey に保存)
        await self._presence_store.update(
            user.id,
            Presence(status=PlayerStatus.IDLE, mode=GameMode.STD),
        )

        # 配信(EventBus 経由)
        await self._event_bus.publish(PlayerOnlineEvent(user_id=user.id))

        return Session(token=token, user_id=user.id, client_type="stable")

    async def logout(self, token: Token) -> None:
        session = await self._session_store.get(token)
        if session is None:
            return

        await self._session_store.delete(token)
        await self._presence_store.delete(session.user_id)

        # チャンネルからも退出
        channels = await self._channel_state_store.get_channels_of_user(session.user_id)
        for channel in channels:
            await self._channel_state_store.remove_member(channel, session.user_id)

        await self._event_bus.publish(PlayerOfflineEvent(user_id=session.user_id))
```

#### 8.5.6 トランスポート層からの利用例

bancho プロセスがパケットキューを直接ポーリングする例を示す。これは `state/` の Protocol を直接使う数少ないトランスポート層のユースケースである。

```python
# transports/bancho/server.py(抜粋)
async def handle_request(self, request, ctx):
    # 受信したパケット群を処理
    incoming = parse_incoming_packets(request.body)
    for packet in incoming:
        await self.dispatch_packet(packet, ctx)

    # ユーザー宛の保留パケットを取り出して返す
    pending = await self._packet_queue.dequeue_all(ctx.player.id)

    # session の last_seen を更新
    await self._session_store.touch(ctx.token)

    return concat_packets(pending)
```

#### 8.5.7 「state」と「messaging」の使い分け

`state/` と `messaging/` は同じ Valkey 基盤を使うが、責務が異なる。混同しないこと。

- **state/**: 「今の状態を読み書きする」。同期的、CRUD 風 API、最新値を返す。例: 「ユーザー X のプレゼンスを取得する」「チャンネル Y のメンバーリストを取得する」
- **messaging/**: 「状態が変化したことを通知する」。非同期的、Pub/Sub、配信ロス許容。例: 「ユーザー X がログインした」「チャンネル Y にメッセージが送信された」

両方を組み合わせて使う典型パターン:

1. サービス層が `state/` を更新する(プレゼンスを更新)
2. サービス層が `messaging/` でイベントを発火する(プレゼンス変更通知)
3. 各トランスポート層がイベントを購読し、自プロトコルのクライアントに通知する(bancho パケット送信、SignalR 配信等)

これにより「状態の正本は Valkey 上の state」「変更通知は EventBus」という二段構えの整合性モデルが成立する。クライアント側は通知を取りこぼしても、明示的に state を問い合わせれば最新状態を取得できる。

#### 8.5.8 in-memory 実装の活用

`state/memory/` 以下に各 Protocol の in-memory 実装を提供する。これは:

- **テスト**: Valkey なしでサービス層のテストを書ける
- **超軽量開発**: ローカルで素早く立ち上げて挙動確認できる
- **教育・デモ**: 依存サービスを最小化して動かせる

```python
# infrastructure/state/memory/session_store.py
class InMemorySessionStore:
    def __init__(self):
        self._sessions: dict[Token, Session] = {}
        self._user_sessions: dict[UserId, Token] = {}

    async def create(self, user_id, client_type):
        token = generate_token()
        self._sessions[token] = Session(...)
        self._user_sessions[user_id] = token
        return token

    async def get(self, token):
        return self._sessions.get(token)
    # ...
```

DI コンテナで環境別に切り替える。

```python
# infrastructure/di/providers.py
if config.environment == "test":
    container.register_singleton(SessionStore, InMemorySessionStore)
else:
    container.register_singleton(
        SessionStore,
        lambda: RedisSessionStore(redis=container.resolve(Redis)),
    )
```

### 8.6 Worker プロセスの起動

taskiq ワーカーは `osu_server.worker` モジュールから起動する。app プロセスと同じ DI コンテナを構築し、ジョブ実行時に依存を解決する。

```python
# src/osu_server/worker.py
from arq.connections import RedisSettings
from arq.cron import cron
from osu_server.config import load_config
from osu_server.infrastructure.di.providers import build_container
from osu_server.infrastructure.jobs.definitions import score_processing
from osu_server.infrastructure.jobs.definitions import notification_delivery
from osu_server.infrastructure.jobs.definitions import achievement_check
from osu_server.infrastructure.jobs.definitions import scheduled


async def startup(ctx):
    """ワーカー起動時に DI コンテナを構築"""
    config = load_config()
    container = build_container(config)
    await container.initialize()
    ctx["container"] = container
    ctx["config"] = config


async def shutdown(ctx):
    await ctx["container"].shutdown()


class WorkerSettings:
    """ARQ ワーカー設定。`arq osu_server.worker.WorkerSettings` で起動する。"""
    redis_settings = RedisSettings.from_dsn(load_config().redis_url)
    on_startup = startup
    on_shutdown = shutdown

    # 各ジョブ定義モジュールから関数を集約
    functions = [
        score_processing.process_score,
        score_processing.recalculate_user_pp,
        notification_delivery.send_notification,
        achievement_check.check_achievements,
        scheduled.recalculate_global_rankings,
        scheduled.cleanup_expired_sessions,
    ]

    max_jobs = 20
    keep_result = 3600
    job_timeout = 300  # 5 分
    max_tries = 3      # 失敗時の再試行回数

    # 定期実行(ランキング更新、セッション清掃等)
    cron_jobs = [
        cron(scheduled.recalculate_global_rankings, hour={0, 6, 12, 18}, minute=0),
        cron(scheduled.cleanup_expired_sessions, minute=0),
    ]
```

### 8.7 ジョブ設計のガイドライン

ジョブを設計する際は以下のルールを守る。なお、 **「そもそもどの処理をジョブにすべきか」というクリティカル処理判別の原則はセクション 8.9 を参照** すること。

**1. 引数はシリアライズ可能なプリミティブのみ**

`Player` や `Score` のようなドメインオブジェクトを引数にしない。msgpack でシリアライズできず失敗する。代わりに ID を渡し、ワーカー内で再取得する。

```python
# ✗ NG
await job_queue.enqueue("process_score", score=score_object)

# ✓ OK
await job_queue.enqueue("process_score", score_id=int(score.id))
```

**2. 冪等性を保つ**

ARQ は失敗時に再試行する。同じジョブが2回実行されても結果が変わらないように設計する。「処理済みフラグ」のチェックや UPSERT を使用する。

**3. 長時間ジョブを避ける**

1ジョブが数分以上かかると、ワーカーがブロックされて他のジョブが滞留する。長い処理は分割し、 **ジョブから子ジョブを発行する** パターンを使う。

```python
async def schedule_pp_recalculation_for_all(ctx):
    """全ユーザー PP 再計算を、ユーザー単位の子ジョブに分割"""
    user_ids = await get_all_user_ids()
    for user_id in user_ids:
        await ctx["redis"].enqueue_job("recalculate_user_pp", user_id=user_id)


async def recalculate_user_pp(ctx, user_id: int):
    """1ユーザー分のみ処理(数秒で完了)"""
    ...
```

**4. エラー追跡を統合する**

Sentry などのエラートラッキングをミドルウェアレベルで統合し、ジョブ失敗を見落とさない仕組みを作る。

```python
async def process_score(ctx, score_id: int):
    try:
        ...
    except Exception:
        sentry_sdk.capture_exception()
        raise  # ARQ の再試行機構に乗せる
```

### 8.8 EventBus、JobQueue、StateStore の使い分け基準

3つのインフラ機構の使い分けを以下にまとめる。

| 判断項目 | StateStore | EventBus | JobQueue |
|---|---|---|---|
| 何を表現するか | 「今の状態」 | 「状態が変化したという通知」 | 「実行すべき仕事の依頼」 |
| 同期 / 非同期 | 同期(read/write) | 非同期(publish-subscribe) | 非同期(producer-consumer) |
| 配信ロス | 関係なし(値を読み書き) | 許容(後で state を読めば最新がわかる) | 許容しない(必ず実行) |
| 処理の重さ | 軽量(<1 ms) | 軽量(数 ms) | 重い(数秒〜数分) |
| 永続化 | Valkey メモリ(任意で AOF) | なし | あり(Valkey Streams) |
| 失敗時の再試行 | 関係なし | なし | あり |
| データ消失時の影響 | 接続再開時に再構築可 | ユーザーは少し古い表示で済む | **整合性が壊れる、復旧困難** |
| 想定用途 | セッション、プレゼンス、チャンネル参加 | チャット配信、ステータス変化通知 | スコア後処理、メダル付与、定期実行 |

判断に迷ったら以下の質問を順に検討する。

1. 「この操作は値を読む / 書くだけか?」 → Yes なら **StateStore**
2. 「**この処理が消失したらデータ整合性が壊れるか?**」 → Yes なら必ず **JobQueue**(セクション 8.9 を参照)
3. 「この処理が失敗して通知が消えても、ユーザー体験は壊れないか?」 → Yes なら **EventBus**
4. 「この処理は app プロセス内で完結すべきか、それとも別プロセスで非同期実行すべきか?」 → 後者なら **JobQueue**

質問 2 が最重要であり、これを最優先で判断する。整合性が壊れる処理を EventBus に流すのは設計事故である。

典型的な複合パターンとして、 **「StateStore で状態を更新 → EventBus で変化を通知」** がある。例えば「ユーザーがプレイ中になった」場合:

```python
# 1. StateStore で状態更新
await self._presence_store.update(
    user_id,
    Presence(status=PlayerStatus.PLAYING, beatmap_id=beatmap_id),
)

# 2. EventBus で配信(各トランスポートが購読して、自分のクライアントに通知)
await self._event_bus.publish(PresenceChangedEvent(
    user_id=user_id,
    new_status=PlayerStatus.PLAYING,
))
```

これにより「state は最新値の正本」「EventBus は変化の通知」という二段構成で整合性を取る。

さらに「重い処理が必要」な場合は JobQueue が加わる。例えば「スコアが送信された」場合:

```python
# 1. リポジトリ経由で永続化(DB)— 同期処理として完結させる
score = await self._score_repo.save(...)

# 2. JobQueue で重い処理を委譲(PP 計算、リーダーボード更新等)
#    ── 失敗が許されないので必ず JobQueue で配信保証する
await self._job_queue.enqueue("process_score", score_id=int(score.id))

# 3. EventBus でリアルタイム通知(画面のリーダーボード即時更新表示など)
#    ── 失敗してもユーザーは画面を再読み込みすれば回復するので EventBus で OK
await self._event_bus.publish(ScoreSubmittedNotice(
    score_id=score.id,
    user_id=score.user_id,
))
```

ここで重要なのは、 **同じ「スコア送信後の処理」でも、データ整合性に影響するもの(PP 計算、リーダーボード更新)は JobQueue、UI のリアルタイム更新通知のような失っても良いものは EventBus** という分離である。

### 8.9 クリティカル処理の判別と JobQueue 化原則

データ整合性に影響を与える処理(以下「クリティカル処理」と呼ぶ)は、 **必ず JobQueue 経由で実行する** ことを本設計の原則とする。これは bancho.py や Ripple で頻繁に発生していた「処理途中でクラッシュしてデータが半端な状態になる」「リトライ機構がなく失敗が黙って消える」といった問題を構造的に防ぐためのルールである。

#### 8.9.1 クリティカル処理の定義

以下のいずれかに該当する処理はクリティカル処理である。

1. **失敗するとユーザーの保有データが正しく反映されない**(スコア、PP、メダル、統計)
2. **失敗するとリーダーボード等の集計値がズレる**(整合性の崩壊)
3. **失敗を検知できないまま黙って消えると業務的に致命的**(課金、購入、報酬付与)
4. **後から手動復旧することが困難または不可能**

逆に、以下はクリティカル処理ではない。

- ユーザー画面の即時更新通知(失敗しても画面再読み込みで回復する)
- 「現在オンライン」表示の更新(次のハートビートで自然に再同期される)
- チャットメッセージのリアルタイム配信(DB に永続化済み、再ログインで履歴取得可能)
- spectator のフレーム配信(古いフレームは捨てて構わない)

#### 8.9.2 bancho サーバーにおけるクリティカル処理の例

本設計のスコープ内で、必ず JobQueue 経由とすべき処理を以下に列挙する。

| カテゴリ | 処理内容 | 失敗時の影響 |
|---|---|---|
| スコア後処理 | PP 計算とユーザーランクへの反映 | ユーザーの PP が正しく上がらない、ランキングが狂う |
| | リーダーボードキャッシュの更新 | リーダーボードが古い情報のまま表示され続ける |
| | ユーザー統計更新(play_count, total_score 等) | 統計値が実態と乖離する |
| | リプレイファイルの永続ストレージ保存(R2/S3) | リプレイがダウンロードできなくなる |
| メダル / 実績 | メダル付与判定 | メダルが付与されない、ユーザーから抗議が来る |
| | 実績解除イベントの記録 | 実績履歴が欠ける |
| 通知 | 通知の永続化と配信 | 重要な通知が届かない(フレンド申請、報酬通知等) |
| マッチ後処理 | マッチ結果の集計と DB 保存 | マッチ履歴が残らない |
| | マルチプレイのレート計算 | レーティングが正しく反映されない |
| 定期処理 | グローバルランキング再計算 | ランキングが古いまま固定化される |
| | 期限切れセッション清掃 | 不要データが Valkey に蓄積し続ける |
| | 統計のバッチ集計 | 集計値が古いままになる |
| 外部連携 | Discord ボット等への通知 | 連携サービスとの整合性が崩れる |
| | 外部 API への状態同期 | サードパーティとの整合性が崩れる |

#### 8.9.3 同期処理と JobQueue の境界

スコア送信のように **「即時に応答する必要がある部分」** と **「失敗が許されないが時間をかけて処理して良い部分」** が混在するケースは多い。この場合、両者の境界を明確に分けて設計する。

```python
# services/scoring/service.py
class ScoringService:
    async def submit_lazer_score(self, score_data: ScoreSubmission) -> Score:
        # ─────────────────────────────────────────────
        # 同期処理(クライアントへの応答前に完了させる必要がある)
        # ─────────────────────────────────────────────

        # 1. スコアの妥当性検証
        await self._validate_score(score_data)

        # 2. スコアを DB に永続化(これが完了すればユーザーには「保存された」と返せる)
        score = await self._score_repo.save(...)

        # ─────────────────────────────────────────────
        # 非同期処理(クリティカル処理 → JobQueue 経由で配信保証)
        # ─────────────────────────────────────────────

        # 3. PP 計算とリーダーボード更新(失敗したら整合性が壊れる)
        await self._job_queue.enqueue("process_score", score_id=int(score.id))

        # 4. メダル付与判定(失敗したら付与漏れ)
        await self._job_queue.enqueue("check_achievements",
            user_id=int(score.user_id), score_id=int(score.id))

        # 5. リプレイの永続ストレージ転送(失敗したらリプレイ喪失)
        if score_data.replay_data:
            await self._job_queue.enqueue("store_replay",
                score_id=int(score.id), replay_blob_key=temporary_key)

        # ─────────────────────────────────────────────
        # ロス許容な通知(EventBus 経由)
        # ─────────────────────────────────────────────

        # 6. リアルタイム表示更新通知(失敗しても画面再読み込みで回復)
        await self._event_bus.publish(ScoreSubmittedNotice(
            score_id=score.id, user_id=score.user_id,
        ))

        return score  # クライアントへの即時応答
```

このパターンの利点:

- **同期処理が短時間で済む**(DB への単純な INSERT のみ)→ クライアントのレイテンシが安定
- **重い処理は worker に分散**(PP 計算は数百 ms かかることもある)→ app プロセスがブロックされない
- **失敗時の再試行が自動**(ARQ が指数バックオフで再試行)→ 一時的な障害で消失しない
- **app プロセスがクラッシュしても影響最小**(DB 保存後にクラッシュしても、ジョブは Valkey 上に残っており worker が拾う)

#### 8.9.4 JobQueue 化を「忘れずに」適用するための実装規律

「失敗が許されない処理を EventBus に流してしまう」事故を防ぐため、以下の実装規律を採用する。

**1. クリティカル処理は events ディレクトリに置かない**

```
services/events/         ← FireAndForgetEvent 専用(EventBus で配信される)
infrastructure/jobs/definitions/  ← クリティカル処理(JobQueue で実行される)
```

物理的にディレクトリを分けることで、 「これは EventBus か JobQueue か」が一目で分かる。

**2. 命名規則で意図を明示する**

- `*Event`(`MessageSentEvent`, `PresenceChangedEvent` 等): EventBus 用、ロス許容
- `*Notice`(`ScoreSubmittedNotice` 等): EventBus 用、リアルタイム通知
- `process_*`、`check_*`、`recalculate_*` 等の動詞関数(`process_score`, `check_achievements`): JobQueue 用、クリティカル処理

**3. コードレビューチェックリスト**

新しい処理を追加する際、以下を必ず確認する。

- 「この処理が消失したら、復旧手段はあるか?」
- 「この処理は冪等か?(複数回実行しても結果が変わらないか)」
- 「この処理は何秒以内に完了する想定か?(秒オーダーなら同期、それ以上なら JobQueue を検討)」
- 「失敗時の挙動は明示的に定義されているか?」

**4. Sentry / ログでのジョブ失敗追跡**

ジョブの失敗は黙って消えやすい(ユーザーから見えない場所で起きる)。 **必ずエラートラッキングを統合し、失敗ジョブを可視化する** 仕組みを整える。

```python
# infrastructure/jobs/middleware.py
async def with_error_tracking(ctx, func, *args, **kwargs):
    try:
        return await func(ctx, *args, **kwargs)
    except Exception as exc:
        sentry_sdk.capture_exception(exc, extras={
            "job_name": func.__name__,
            "job_args": args,
            "job_kwargs": kwargs,
            "job_id": ctx.get("job_id"),
            "try_count": ctx.get("job_try"),
        })
        raise  # ARQ の再試行機構に乗せる
```

#### 8.9.5 JobQueue 化のアンチパターン

クリティカル処理を JobQueue に回す際、以下のアンチパターンを避ける。

**アンチパターン 1: ジョブから fire-and-forget で別の重い処理を呼ぶ**

```python
# ✗ NG
async def process_score(ctx, score_id):
    await calculate_pp(score_id)
    asyncio.create_task(update_global_rankings())  # fire-and-forget でロス可能性
```

`asyncio.create_task` で起動した処理は、ワーカーがクラッシュすると消失する。子ジョブが必要なら、 **明示的に enqueue_job する**。

```python
# ✓ OK
async def process_score(ctx, score_id):
    await calculate_pp(score_id)
    await ctx["redis"].enqueue_job("update_global_rankings")
```

**アンチパターン 2: ジョブ内で例外を握りつぶす**

```python
# ✗ NG
async def process_score(ctx, score_id):
    try:
        await calculate_pp(score_id)
    except Exception:
        pass  # 失敗を黙殺、リトライもされない
```

例外を握りつぶすと、ARQ の再試行機構が機能しない。 **再試行可能なエラーは re-raise する**。

```python
# ✓ OK
async def process_score(ctx, score_id):
    try:
        await calculate_pp(score_id)
    except TransientError:
        raise  # ARQ が指数バックオフで再試行する
    except PermanentError as exc:
        # 永続的なエラーは Dead Letter Queue 相当の処理に回す
        await mark_score_as_failed(score_id, reason=str(exc))
        sentry_sdk.capture_exception(exc)
        # raise しない(再試行しても無意味)
```

**アンチパターン 3: ジョブ内で同期的に DB トランザクションを長時間保持**

ジョブが長時間 DB トランザクションを保持すると、他のジョブや app プロセスのクエリがブロックされる。 **トランザクション境界を最小化** し、複数のフェーズに分割する。

**アンチパターン 4: クリティカル処理を EventBus に投げる**

これが本セクションの主旨。 「リアルタイム性が欲しいから EventBus で良いだろう」と判断してクリティカル処理を EventBus に流すと、サブスクライバが居なかった場合や処理失敗時にデータが消失する。クリティカル処理は **必ず JobQueue を経由する**。

### 8.10 イベント定義のマーカー

イベントクラスに用途のマーカーを付けて、誤った使用を型レベルで防止する。

```python
# services/events/markers.py
class FireAndForgetEvent:
    """EventBus.publish に渡すべきイベントのマーカー"""
    pass

class ReliableJob:
    """JobQueue.enqueue に渡すべきジョブペイロードのマーカー"""
    pass


# services/events/chat_events.py
@dataclass(frozen=True)
class MessageSentEvent(FireAndForgetEvent):
    """チャットメッセージ配信。EventBus 経由。"""
    message_id: int
    channel_name: str
    sender_id: int
    content: str


# services/events/score_events.py
@dataclass(frozen=True)
class ScoreSubmittedNotice(FireAndForgetEvent):
    """スコア送信のリアルタイム通知(リーダーボード即時更新表示用)。配信ロス許容。"""
    score_id: int
    user_id: int

# JobQueue 経由の重い処理は、ジョブ関数の引数で表現するため
# マーカークラスは必須ではない。ただし型ヒントで明示することは推奨。
```

---

## 9. アプリケーション起動

本サーバーは2つの実行プロセスから構成される。

- **app プロセス**: HTTP / WebSocket リクエストを処理する ASGI サーバー
- **worker プロセス**: ジョブキューからジョブを取り出して実行する ARQ ワーカー

両プロセスは同じ DI コンテナビルダー(`build_container`)を共有するが、エントリポイントが異なる。

### 9.1 app プロセスのエントリポイント

`app.py` で Starlette アプリケーションを組み立てる。各トランスポートを Mount で統合する。

```python
# src/osu_server/app.py
from contextlib import asynccontextmanager
from starlette.applications import Starlette
from starlette.routing import Mount

from osu_server.config import load_config
from osu_server.infrastructure.di.providers import build_container
from osu_server.transports.bancho.routes import bancho_routes
from osu_server.transports.bancho import handlers as _bancho_handlers  # noqa: F401
from osu_server.transports.web_legacy.routes import legacy_routes
from osu_server.transports.api.app import create_api_app
from osu_server.transports.signalr.server import create_signalr_app


@asynccontextmanager
async def lifespan(app: Starlette):
    config = load_config()
    container = build_container(config)
    app.state.container = container
    app.state.config = config
    await container.initialize()
    try:
        yield
    finally:
        await container.shutdown()


def create_app() -> Starlette:
    api_app = create_api_app()
    signalr_app = create_signalr_app()
    return Starlette(
        routes=[
            *bancho_routes,                      # POST / → bancho dispatch
            Mount("/web", routes=legacy_routes), # /web/* → レガシー
            Mount("/api/v2", app=api_app),       # /api/v2/* → FastAPI
            Mount("/signalr", app=signalr_app),  # SignalR hubs
        ],
        lifespan=lifespan,
    )


app = create_app()
```

起動コマンド:

```bash
uvicorn osu_server.app:app --host 0.0.0.0 --port 8000
```

### 9.2 worker プロセスのエントリポイント

`worker.py` で ARQ の WorkerSettings を定義する(セクション 8.5 を参照)。起動コマンド:

```bash
arq osu_server.worker.WorkerSettings
```

ワーカープロセスは複数立ち上げて水平スケール可能(同じ Valkey ブローカーを共有する複数のワーカーがジョブを分担する)。

### 9.3 Docker Compose による統合起動

開発環境および小〜中規模本番運用では、Docker Compose で全プロセスを統合管理する。

```yaml
# docker-compose.yml
services:
  app:
    build: .
    command: uvicorn osu_server.app:app --host 0.0.0.0 --port 8000
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql+asyncpg://...
      - VALKEY_URL=valkey://valkey:6379/0
    depends_on:
      - postgres
      - valkey

  worker:
    build: .
    command: taskiq worker osu_server.worker:broker
    environment:
      - DATABASE_URL=postgresql+asyncpg://...
      - VALKEY_URL=valkey://valkey:6379/0
    depends_on:
      - postgres
      - valkey
    deploy:
      replicas: 2  # 必要に応じて水平スケール

  valkey:
    image: valkey/valkey:8-alpine
    volumes:
      - valkey_data:/data

  postgres:
    image: postgres:16
    environment:
      - POSTGRES_USER=osu
      - POSTGRES_PASSWORD=...
      - POSTGRES_DB=osu_server
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  valkey_data:
  postgres_data:
```

app プロセスがダウンしてもワーカーは独立して動作し続け、ジョブの処理は継続される。逆にワーカーがダウンしても app プロセスのリクエスト処理に影響しない(ジョブは Valkey に蓄積され、ワーカー復旧後に処理される)。

---

## 10. 設計上のルールと制約

### 10.1 import 規則

import-linter で以下のルールを CI に組み込み、機械的に違反を検出する。

```toml
# pyproject.toml
[tool.importlinter]
root_package = "osu_server"

[[tool.importlinter.contracts]]
name = "Layered architecture"
type = "layers"
layers = [
    "osu_server.transports",
    "osu_server.services",
    "osu_server.domain | osu_server.repositories",
    "osu_server.infrastructure",
    "osu_server.shared",
]

[[tool.importlinter.contracts]]
name = "Services don't depend on transports"
type = "forbidden"
source_modules = ["osu_server.services"]
forbidden_modules = ["osu_server.transports"]

[[tool.importlinter.contracts]]
name = "Domain has no I/O dependencies"
type = "forbidden"
source_modules = ["osu_server.domain"]
forbidden_modules = [
    "osu_server.repositories",
    "osu_server.infrastructure",
    "osu_server.transports",
]

[[tool.importlinter.contracts]]
name = "Inter-service communication via api.py only"
type = "forbidden"
source_modules = ["osu_server.transports"]
forbidden_modules = [
    "osu_server.services.chat.channel_registry",
    "osu_server.services.scoring.pp_calculator",
    # 各サービスの内部実装ファイルを列挙
]
```

### 10.2 命名規則

- パケットクラス: 方向サフィックスを必須とする(`SendPublicMessageC2S`, `SendMessageS2C`)
- ハンドラ関数: `handle_<動詞>_<対象>` 形式(`handle_send_public_message`)
- サービス公開関数: 動詞始まりの命令形(`send_message`, `submit_score`)
- リポジトリメソッド: `find_by_*`, `save`, `delete`, `exists` を基本動詞とする
- イベント: `<対象><動詞過去形>Event` 形式(`MessageSentEvent`, `ScoreSubmittedEvent`)

### 10.3 ファイル粒度

- 1ファイルが300行を超えたら分割を検討する
- パケットハンドラは1ファイル1機能(`chat.py`, `multiplayer.py` 等)を基本とし、機能内の各ハンドラは同一ファイル内に配置する
- ドメインエンティティは1エンティティ1ファイルを基本とする

### 10.4 公開 API の境界

各サブパッケージの `__init__.py` で公開シンボルを明示する。

```python
# services/chat/__init__.py
from services.chat.service import (
    send_message,
    join_channel,
    leave_channel,
    get_channel_members,
)

__all__ = [
    "send_message",
    "join_channel",
    "leave_channel",
    "get_channel_members",
]
```

これにより、外部から `from services.chat.channel_registry import ChannelRegistry` のような内部実装への直接アクセスが文化的に抑制される。import-linter で機械的にも禁止する。

### 10.5 例外設計

ドメイン層は固有の例外を定義し、トランスポート層がプロトコル固有のエラー応答に変換する。

```python
# shared/errors.py
class DomainError(Exception):
    """ドメイン層から発生するエラーの基底"""

class NotFoundError(DomainError): pass
class ValidationError(DomainError): pass
class AuthorizationError(DomainError): pass
class ConflictError(DomainError): pass
class InvalidStateError(DomainError): pass

# 具体的なドメイン例外
class UserNotFoundError(NotFoundError): pass
class ChannelNotFoundError(NotFoundError): pass
class AlreadyInMatchError(InvalidStateError): pass
class MessageTooLongError(ValidationError): pass
```

トランスポート層では、これらをプロトコル固有のエラーに変換する。`HTTPException` を services 層から投げることは禁止する。

---

## 11. テスト戦略

### 11.1 テスト構造

```
tests/
├── conftest.py                    # pytest fixture
├── unit/
│   ├── domain/                    # ドメインモデルのユニットテスト
│   ├── services/                  # サービスのユニットテスト(リポジトリは mock)
│   └── transports/
│       ├── bancho/
│       │   ├── protocol/          # パケットパース/シリアライズのテスト
│       │   └── handlers/          # ハンドラのテスト(サービスは mock)
│       ├── web_legacy/
│       └── api/
├── integration/
│   ├── repositories/              # 実 DB を使うテスト
│   ├── services/                  # サービス + リポジトリの結合テスト
│   └── transports/
│       ├── bancho/                # 実 bancho パケットを送受信
│       ├── api/                   # FastAPI TestClient
│       └── web_legacy/
└── fixtures/                      # テストデータ
    ├── beatmaps/
    ├── replays/
    └── packets/                   # 既知のパケットバイナリサンプル
```

### 11.2 テストの粒度別方針

**ユニットテスト**: ドメインモデルとサービスのビジネスロジックを検証。リポジトリは Protocol に対する in-memory 実装を使い、I/O を排除する。

**結合テスト**: サービス + 実リポジトリ + 実 DB(testcontainers 等)で結合動作を検証。マイグレーションが正しく適用されることも確認する。

**E2E テスト**: 実際のプロトコル(bancho バイナリ、HTTP リクエスト)を投げて、end-to-end の振る舞いを検証。最も少なくする(典型的シナリオのみ)。

### 11.3 テスト用ユーティリティ

```python
# tests/conftest.py
import pytest
from osu_server.transports.bancho.server import BanchoServer
from osu_server.repositories.memory import MemoryUserRepository

@pytest.fixture
def bancho_server():
    """テスト用のクリーンな BanchoServer を返す"""
    return BanchoServer()

@pytest.fixture
def memory_user_repo():
    """in-memory リポジトリ"""
    return MemoryUserRepository()

# tests/unit/transports/bancho/handlers/test_chat.py
async def test_send_public_message_broadcasts(bancho_server, memory_user_repo):
    response = await send_test_packet(
        bancho_server,
        ClientPacketID.SEND_PUBLIC_MESSAGE,
        SendPublicMessageC2S(
            sender="",
            message="hello",
            target="#osu",
            sender_id=0,
        ),
    )
    assert any(
        isinstance(p, SendMessageS2C) and p.message == "hello"
        for p in response
    )
```

---

## 12. 既知の制約と将来の拡張ポイント

### 12.1 現時点で意図的に対応しない範囲

以下は本設計の初期スコープから外す。必要に応じて将来導入する。

- **lazer のフル機能対応**: 初期は OAuth2 認証 + lazer スコア送信までを目標とし、SignalR ハブの完全実装は段階的に進める
- **SignalR の自前実装の完成度**: 必要最低限のメッセージタイプから着手し、エッジケース対応は後から追加する
- **アンチチート機構**: 本家の閉じたロジックは再現不能なため、最小限の整合性チェックに留める
- **lazer ↔ stable のクロスクライアント機能の完全互換**: チャットの相互配信は実装するが、プレゼンス統合は後回しにする(本家でも完全には統合されていないため、許容できる)
- **RabbitMQ / Kafka の導入**: 現状の Valkey(Pub/Sub + Streams via taskiq)で必要十分。複雑な routing が要求されるか、桁違いのスループットが必要になった時点で再検討
- **マルチリージョン展開**: 単一リージョンでスケールできる範囲で運用する。global なプレイヤーベースを抱える本家とは要件が異なる
- **イベントソーシング / CQRS**: 状態の正本は RDB に置き、必要に応じて派生ビューをキャッシュする伝統的な構成を採る

### 12.2 設計上の妥協点

以下の妥協点を認識した上で進める。

- **services/ の境界の引き直し**: 運用していくと、当初の境界が現実と合わなくなる場合がある。リファクタリングを定期的に許容する文化が必要
- **凝集度の部分的妥協**: ハイブリッド構造の代償として、機能関連コードがディレクトリをまたいで配置される。IDE の Find Usages で対応する
- **認証ロジックの分散**: stable バイナリ認証、OAuth2、SignalR JWT 検証が別物のため、`services/auth/` だけで完結させるのは無理がある。各トランスポートが認証アダプタを持ち、共通の認可ロジックのみ services/auth/ に集約する形で妥協する
- **トランザクション境界**: モジュールをまたぐ atomic 操作は Unit of Work パターンで対応するが、複雑なケースでは Saga パターン(結果整合性)に倒す
- **EventBus と JobQueue の使い分け判断**: 開発者がイベントごとにどちらを使うか判断する必要がある。ガイドライン(セクション 8.8)を整備するが、判断ミスは発生しうる。コードレビューで補正する

### 12.3 段階的進化パス(モジュラモノリスからの成長)

本設計のモジュラモノリスは、規模拡大時に以下の段階で進化させることを想定している。各段階は前段階を基盤にして、コードの大幅変更を伴わずに移行できる。

#### Stage 1: モジュラモノリス(初期実装)

- 単一プロセス(app + worker の2プロセス)
- 単一 DB、単一 Valkey
- すべてのコードが `osu_server` という単一 Python パッケージ
- in-process 関数呼び出しでサービスを呼ぶ

```python
# transports/bancho/handlers/chat.py
from services.chat import api as chat_api
await chat_api.send_message(...)
```

これが本設計のメイン構成。同時接続 〜 数百のレベルで運用可能。

#### Stage 2: スキーマ分離

DB の物理構造はそのまま単一インスタンスだが、スキーマ単位でサービスごとに分離する。

```
共有 PostgreSQL クラスタ
├── identity スキーマ        ← Identity Service / User Service のみが書き込み可
├── scoring スキーマ         ← Scoring Service のみが書き込み可
├── chat スキーマ            ← Chat Service のみが書き込み可
└── multiplayer スキーマ     ← Multiplayer Service のみが書き込み可
```

各サービスは自分のスキーマにしか書き込まない、というルールを徹底する。他スキーマへの参照は、サービス層の `api.py` 経由か、データの非正規化(イベント駆動同期)で対応する。これは将来の DB 物理分離への準備として効く。

#### Stage 3: サービス間通信の Protocol 抽象化

`services/*/api.py` を Protocol として定義し、in-process 実装と remote 実装を切り替えられるようにする。

```python
# services/chat/api.py
class ChatAPI(Protocol):
    async def send_message(self, ...) -> MessageId: ...

# services/chat/local_api.py(現状の in-process 実装)
class LocalChatAPI:
    async def send_message(self, ...):
        return await self._service.send_message(...)
```

呼び出し側のコードは Protocol に依存し、具象実装を知らない。

```python
# transports/bancho/handlers/chat.py
async def handle_send_message(packet, player, chat_api: ChatAPI = Depends(...)):
    await chat_api.send_message(...)
```

この時点ではまだ in-process なのでオーバーヘッドはほぼゼロ。次の Stage への準備段階として機能する。

#### Stage 4: トランスポート層と Service 層のプロセス分離

トランスポートプロセス(bancho、api、web_legacy、signalr)と Service プロセスを物理的に分離する。これは「Service 中央プロセス案」とも呼ばれる構成で、 **「コードベースとしてはモノリス、デプロイ単位としては分散」** という独特の位置づけになる。

```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ Bancho       │  │ Web Legacy   │  │ API          │
│ Process      │  │ Process      │  │ Process      │
│ (薄いだけ)    │  │ (薄いだけ)    │  │ (薄いだけ)    │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       │                 │                 │
       │ RPC / 内部 HTTP  │                 │
       └─────────────────┼─────────────────┘
                         ▼
              ┌──────────────────────┐
              │ Service Process      │
              │ (ビジネスロジック)    │
              └──────┬───────────────┘
                     │
       ┌─────────────┼─────────────┐
       ▼                           ▼
┌──────────────┐            ┌──────────────┐
│ Valkey       │            │ PostgreSQL   │
│ (揮発的状態)  │            │ (永続データ)  │
└──────────────┘            └──────────────┘
```

このアーキテクチャの利点:

- **トランスポート層の独立スケール**: 各トランスポートを別マシンで動かせる
- **トランスポート言語の自由度**: 例えば bancho プロセスだけ Rust や Go で実装し直せる
- **障害隔離**: bancho プロセスがクラッシュしても API は生きている
- **DB アクセスの集中**: コネクションプールやスロークエリ監視が一箇所
- **Ripple の「形だけマイクロサービス」を超える**: ビジネスロジックの一元化を保ちつつ、物理プロセス分離の利点を得る

実現のために前提となる条件:

- Stage 3 で Protocol 抽象化が完了している
- Stage 1 から Valkey ステート集約を採用している(セッション、プレゼンスがプロセス共有可能)
- 通信は gRPC または内部 HTTP API(まずは内部 HTTP、性能ネックになったら gRPC へ)

このアーキテクチャは **真のマイクロサービスとモジュラモノリスの中間** に位置し、以下の伝統的なパターンに対応する。

- N-Tier Architecture(Web Tier + Application Tier + Data Tier)
- Backend For Frontend(各クライアント種別ごとのゲートウェイ + 共通サービス層)
- Cell-Based Architecture(Edge を Cell が囲む構成)

#### Stage 5: モノレポ化 + 共通パッケージ分離

コードベースを単一 Python パッケージから、複数の独立した Python パッケージに分割する。これによりビルド・テスト・デプロイの粒度が向上する。詳細はセクション 12.4 を参照。

#### Stage 6: 一部サービスの DB 物理分離

特定の重いサービス(例: スコアリング)のスキーマを別 DB クラスタに切り出す。Stage 2 でスキーマ分離が済んでいれば、テーブルを別 DB にコピーするだけで完結する。サービス間の参照は `api.py` 経由になっているため、呼び出し側コードは無変更。

#### Stage 7: 真のマイクロサービス

各サービスが独立した DB、独立したコードベース(別リポジトリ)、独立したリリースサイクルを持つ。イベントバスは Valkey Pub/Sub から RabbitMQ / Kafka 等に拡張される可能性がある。

ただしこの段階に至る private server はほぼ存在しない。ここまで来るとチームサイズも数十人規模が必要で、private server コミュニティの現実とは乖離する。

#### 進化の指針

「いつ次の Stage に進むか」の判断基準:

| 移行 | 判断基準 |
|---|---|
| Stage 1 → 2 | 「特定のテーブルへのアクセスが特定サービスからのみ」が明確になったとき |
| Stage 2 → 3 | サービス間のインターフェースが安定し、サービス境界が動かなくなったとき |
| Stage 3 → 4 | 単一プロセスのリソースが上限に達した、またはトランスポートの言語を変えたい要求が出たとき |
| Stage 4 → 5 | チームが複数人になり、コンポーネント単位の独立開発が必要になったとき |
| Stage 5 → 6 | 特定サービスの DB 負荷が支配的になり、他サービスに影響を与えるようになったとき |
| Stage 6 → 7 | チームが数十人規模になり、組織的にサービスごとの所有が必要になったとき |

**重要なのは、各 Stage の移行が「小さな変更」で済むこと**。これがモジュラモノリスから始める最大の理由である。bancho.py や Ripple の構造では、Stage 4 への移行は事実上の全面書き直しになる。本設計では各 Stage の境界が API 抽象とプロトコル境界で守られているため、段階的な進化が可能である。

### 12.4 モノレポ化 + 共通パッケージ分離(Stage 5 の詳細)

Stage 5 として、コードベースを複数の Python パッケージに分割する。これは `osu-server` という1つのモノレポ内に複数の独立したパッケージを配置する形を取る。

#### 12.4.1 パッケージ分割の方針

`packages/` 配下に共通パッケージ群、 `apps/` 配下に実行プロセスを配置する。

```
osu-server/                          # モノレポルート
├── pyproject.toml                   # ワークスペース定義(uv workspace)
├── packages/                        # 共通パッケージ群
│   ├── osu-domain/                  # ドメインモデル(I/O 非依存)
│   ├── osu-shared/                  # 横断的最小要素
│   ├── osu-protocol/                # bancho プロトコル定義
│   ├── osu-repositories/            # 永続化層
│   ├── osu-state/                   # Valkey ステートストア
│   ├── osu-services/                # ビジネスロジック
│   ├── osu-infrastructure/          # DB、キャッシュ、DI、ジョブ等
│   └── osu-service-client/          # サービス間 RPC クライアント(Stage 4 以降で使用)
│
└── apps/                            # 実行プロセス(エントリポイント)
    ├── bancho-app/                  # bancho プロセス
    ├── web-legacy-app/              # web_legacy プロセス
    ├── api-app/                     # api プロセス
    ├── signalr-app/                 # signalr プロセス
    ├── worker-app/                  # ARQ ワーカー
    └── service-app/                 # Service 中央プロセス(Stage 4 以降)
```

#### 12.4.2 各パッケージの依存関係

```
osu-domain ─┬───────────────────────────────┐
            │                               │
osu-shared ─┴┐                              │
             │                              │
osu-protocol ┤                              │
             │                              │
osu-repositories ──┐                        │
                   ├─ osu-services ─────────┤
osu-state ─────────┘                        │
                                            │
osu-infrastructure ─────────────────────────┤
                                            │
                                ┌───────────┴───────────┐
                                ▼                       ▼
                          各 apps/* (実行プロセス)
```

各パッケージ:

- **osu-domain**: 他に依存しない最下層。Pure Python のデータクラスのみ
- **osu-shared**: errors, types, constants 等の最小要素
- **osu-protocol**: bancho プロトコル定義(Caterpillar による C2S/S2C パケット)。 `osu-domain` と `osu-shared` のみに依存
- **osu-repositories**: 永続化抽象とその実装。 `osu-domain` に依存
- **osu-state**: Valkey ステートストア。 `osu-domain` に依存
- **osu-services**: ビジネスロジック。 `osu-domain`, `osu-repositories`, `osu-state` に依存
- **osu-infrastructure**: DB、DI、ジョブ、メッセージング等の基盤
- **osu-service-client**: Stage 4 以降に追加、Service プロセスへの RPC クライアント

各 `apps/*` は必要な共通パッケージのみを依存に持つ。たとえば `bancho-app` は `osu-protocol` と `osu-services` に依存するが、 `signalr-app` は別のサブセットに依存する。

#### 12.4.3 ツールチェーン

uv workspace を採用する。uv (Astral 社) が提供する高速な Python パッケージマネージャで、モノレポを単一の `pyproject.toml` で管理できる。

```toml
# ルートの pyproject.toml
[tool.uv.workspace]
members = ["packages/*", "apps/*"]
```

各パッケージの `pyproject.toml` で内部依存を表現する。

```toml
# apps/bancho-app/pyproject.toml
[project]
name = "bancho-app"
dependencies = [
    "starlette>=0.36",
    "uvicorn>=0.27",
    "caterpillar-py>=2.0",
    "osu-domain",
    "osu-shared",
    "osu-protocol",
    "osu-services",
    "osu-state",
    "osu-infrastructure",
]

[tool.uv.sources]
osu-domain = { workspace = true }
osu-shared = { workspace = true }
osu-protocol = { workspace = true }
osu-services = { workspace = true }
osu-state = { workspace = true }
osu-infrastructure = { workspace = true }
```

#### 12.4.4 モノレポ化の利点

- **依存方向の物理的強制**: ディレクトリ単位ではなくパッケージ単位の境界となり、import-linter のような事後検出ではなくインストール時点で破綻する強い制約
- **ビルドとテストの粒度向上**: 変更があったパッケージとその依存先のみテストすれば良い。CI 時間が大幅短縮される
- **Docker イメージサイズの最小化**: 各 `apps/*` のイメージに不要なコードが入らない
- **再利用性**: `osu-protocol` を別プロジェクト(bot、解析ツール、リプレイビューワー)で利用できる
- **PyPI 公開の選択肢**: 特定パッケージ(例: `osu-protocol`)を単体で PyPI 公開し、他の private server 開発者と共有できる

#### 12.4.5 移行のタイミング

最初から完全分割する必要はない。Stage 1 では単一パッケージ `osu_server` で開始し、以下の兆候が出たときに分割を検討する。

- パッケージ内のディレクトリ間で依存方向の混乱が頻発する
- CI のテスト実行時間が10分を超え始める
- 別プロジェクトでドメインモデルを再利用したい要求が出る
- Stage 4(Service プロセス分離)に進む準備として、明確な境界が必要になる

設計書の現在のディレクトリ構造(`transports/`, `services/`, `domain/` 等)は、 **このモノレポ化を念頭に命名されている**。後から各サブディレクトリを `packages/osu-*/` に移動するのが容易な形を保っている。

#### 12.4.6 落とし穴

- **パッケージ粒度の判断ミス**: 細かく分けすぎるとオーバーヘッド、大きすぎると意味がない。 「**別プロジェクトで再利用したいか**」と「**依存方向の境界を引きたいか**」で判断する
- **循環依存**: A → B → C → A のような循環は致命的。 `pydeps` 等で定期的にチェックする
- **バージョン管理の複雑化**: モノレポ内ではすべてのパッケージを同じバージョンで進めるのを基本とする(lerna の "fixed mode" 相当)
- **`py.typed` マーカー**: 各パッケージに `py.typed` を置かないと、mypy が型情報を読まない

---

## 13. 用語集

| 用語 | 説明 |
|---|---|
| bancho | osu! の stable クライアント用リアルタイム通信サーバーのコードネーム。バイナリプロトコルを使用 |
| osu-web | osu! 公式のウェブサイト + REST API サーバー(Laravel 製、オープンソース) |
| osu-server-spectator | lazer 用の SignalR ハブサーバー(C# / ASP.NET Core 製、オープンソース) |
| stable | osu! の旧来のクライアント。bancho と legacy `/web/*` を使う |
| lazer | osu! の新世代クライアント。osu-server-spectator と osu-web の REST API を使う |
| C2S | Client to Server。クライアントからサーバーへ送られるパケット |
| S2C | Server to Client。サーバーからクライアントへ送られるパケット |
| `_lio` | Legacy InterOp。osu-web が提供する、bancho からの内部 callback 用 API |
| SignalR | Microsoft 製のリアルタイム通信フレームワーク。WebSocket + MessagePack ベース |
| ULEB128 | Unsigned Little-Endian Base 128。可変長整数エンコーディング。bancho プロトコルで文字列長に使用 |
| Caterpillar | Python 3.12+ 向けの宣言的バイナリパーサー / ビルダーライブラリ |
| ARQ | Async first な Python 向けジョブキューライブラリ。Redis プロトコルベース。Sidekiq の Python 版に相当。本プロジェクトでは taskiq に移行済み |
| taskiq | Async first な Python 向けジョブキューライブラリ。taskiq-redis ブローカーで Valkey を使用。ARQ の後継として採用 |
| StateStore | 揮発的ステート(セッション、プレゼンス等)を Valkey に保管するための Protocol 群 |
| EventBus | 配信ロスを許容する fire-and-forget な通知機構。本設計では Valkey Pub/Sub をバックエンドに使用 |
| JobQueue | 配信保証ありのジョブ実行機構。失敗時に再試行される。本設計では taskiq + Valkey Streams を使用 |
| Redis Pub/Sub | Redis のメッセージング機能。購読者にメッセージを fan-out するが永続化や ack はない |
| Redis Streams | Redis のログ風データ構造。永続化、コンシューマーグループ、ack をサポート |
| Hash Tag(Redis) | Redis Cluster で複数キーを同一スロットに配置するための記法。 `{...}` 部分が同じキーは同じスロットに入る |
| Sidekiq | Ruby 界のデファクトジョブキュー。本設計では参考とし、Python 版相当として taskiq を採用 |
| app プロセス | uvicorn で起動する ASGI サーバープロセス。HTTP / WebSocket リクエストを処理 |
| worker プロセス | taskiq で起動するジョブ実行プロセス。app プロセスとは独立して水平スケール可能 |
| Service プロセス | Stage 4 で導入される中央プロセス。ビジネスロジックを集約し、トランスポートプロセスから RPC で呼ばれる |
| 冪等性 | 同じ操作を複数回実行しても結果が変わらない性質。ジョブ設計の必須要件 |
| モジュラモノリス | 単一プロセスで動作するが、内部のモジュール境界を明示的に管理するアーキテクチャパターン |
| モノレポ | 複数のパッケージを単一のリポジトリで管理する手法。本設計では Stage 5 で採用 |
| uv workspace | Python の高速パッケージマネージャ uv が提供するモノレポ管理機能 |
| BFF (Backend For Frontend) | クライアント種別ごとに専用 API ゲートウェイを置く設計パターン。本設計の Stage 4 はこれに近い |
| Hexagonal Architecture | ビジネスロジックを I/O から分離する設計手法。Ports & Adapters とも呼ばれる |
| Unit of Work | DB トランザクション境界を抽象化する設計パターン |
| Saga パターン | 分散トランザクションを補償処理(compensating action)で実現する設計パターン |
| Durable Objects | Cloudflare のステートフルワーカー。特定 ID にバインドされたインスタンスがメモリと WebSocket 接続を保持できる(付録 D で詳述) |
| axum | Tokio チーム公式の Rust 製 Web フレームワーク。Tower エコシステムの中核(付録 E で詳述) |
| binrw | Rust の宣言的バイナリパーサー。derive macro でバイナリレイアウトを定義できる、Caterpillar の Rust 版 |
| apalis | Rust 製のジョブキューライブラリ。Redis / RabbitMQ をブローカーとして使える、ARQ の Rust 版 |
| sqlx | Rust 製の async SQL ライブラリ。コンパイル時にクエリを型チェックできる |
| fred | Rust 製の Redis クライアント。クラスタ・パイプライン・Pub/Sub などフル機能 |
| Tower | Rust の汎用「サービス抽象化」レイヤー。HTTP / gRPC / Redis 等を共通の Service trait で扱う |
| proc-macro | Rust の手続きマクロ。コンパイル時にコードを生成し、Python のデコレーター相当の機能を実現できる |
| inventory crate | Rust のコンパイル時分散登録ライブラリ。複数のファイルから登録された情報を起動時に集約する |
| rosu-pp | Rust 製の osu! PP 計算ライブラリ。本家との数値一致が高く、Rust 版実装ではネイティブ統合可能 |
| cargo workspace | Cargo のモノレポ管理機能。複数の crate を1つのプロジェクトで管理する |
| .NET | Microsoft 主導のオープンソース開発プラットフォーム。C# / F# / VB.NET の実行基盤(付録 F で詳述) |
| ASP.NET Core | .NET 上の async ファースト Web フレームワーク。Kestrel サーバー + middleware パイプライン + 組み込み DI で構成される、FastAPI に相当する立ち位置 |
| EF Core | Entity Framework Core。.NET 公式の async ORM、SQLAlchemy 2.0 に相当 |
| Native AOT | .NET 8+ の Ahead-of-Time コンパイル機能。シングルバイナリ・高速起動・低メモリを実現するが、リフレクションに制約がある |
| Hangfire | C# 製のジョブキューライブラリ。Redis / SQL バックエンド対応、Web 管理 UI 内蔵、ARQ の C# 版に相当 |
| Coravel | C# 製の軽量タスクスケジューラ。in-process 中心、シンプルな API |
| StackExchange.Redis | .NET の主要な Redis クライアントライブラリ |
| NuGet | .NET のパッケージマネージャ・パッケージレジストリ。pip / npm の .NET 版 |
| source generator | C# のコンパイル時コード生成機能。Roslyn ベースで動作し、Python のデコレーターや Rust の proc-macro に相当する役割を果たす |
| Roslyn | C# / VB.NET のコンパイラ基盤。アナライザーや source generator を実装する API を提供 |
| osu-tools | osu! 公式の PP 計算ツール(C# 製)。C# 版実装ではライブラリとして直接統合可能(本家との数値一致が保証される) |
| osu-framework | osu! 公式のゲームフレームワーク(C# 製)。クライアント本体と osu-server-spectator が依存している基盤ライブラリ |
| Kestrel | ASP.NET Core の HTTP サーバー実装。uvicorn の .NET 版に相当する立ち位置 |
| BanchoNET | C# / .NET で書かれた bancho 互換 private server の参考実装プロジェクト |
| Deku | Rust のバイナリパースライブラリ。bit-level の表現力に特化、symmetric serialization(付録 G で binrw との比較を詳述) |
| Hachoir | Python のバイナリパースライブラリ。多数のファイル形式パーサー内蔵、リバースエンジニアリング向け |
| Mr. Crowbar | Python のバイナリパースライブラリ。Django 的な model framework、CLI 可視化ツール付き |
| dissect.cstruct | Python のバイナリパースライブラリ。C 言語風の構造定義、Fox-IT 製、フォレンジック向け |
| restructure | TypeScript / JavaScript のバイナリパースライブラリ。npm ダウンロード数最大(付録 D で採用、付録 G で詳述) |
| Binary-parser | TypeScript / JavaScript のバイナリパースライブラリ。GitHub スター数最大、declarative API(付録 G で詳述) |
| scroll | Rust の軽量バイナリ読み書きクレート。Pread/Pwrite trait、低レベル |
| winnow | Rust のパーサーコンビネータライブラリ。Nom のフォーク、改善版 |
| Kaitai Struct | 言語非依存のバイナリフォーマット記述 DSL。read-only(serializer なし)のため bancho サーバー用途には不適合 |
| dloss/binary-parsing | 「Awesome Binary Parsing」、言語横断的なバイナリパースライブラリのカタログ(付録 G の主要情報源) |

---

## 付録 A: 参考プロジェクト

本設計の参照元、または対比対象として以下を挙げる。

- **osuAkatsuki/bancho.py**: 最も普及している private server。本設計が改善を試みる対象
- **osuripple/ripple** (pep.py, LETS, Hanayo): 古典的だが責務分離が比較的綺麗な実装
- **Pure-Peace/peace**: Rust 製、マイクロサービス指向の新世代実装
- **NovemoG/BanchoNET**: C# (.NET 8) 製の実装、osu! 本体と同言語
- **osuAkatsuki/akatsuki-lazer**: lazer 互換サーバーの Python 実装(進行中)
- **ppy/osu-web**: 公式の Web バックエンド(REST API のリファレンス)
- **ppy/osu-server-spectator**: 公式の SignalR ハブ実装(lazer リアルタイム通信のリファレンス)
- **ppy/osu-infrastructure**: スコア送信パイプラインなどの公式設計ドキュメント

---

## 付録 B: 主要な意思決定の記録

以下は、設計過程で議論した中で特に意思決定として明示しておくべき項目。

| 決定事項 | 採用 | 却下 | 理由 |
|---|---|---|---|
| ディレクトリトップレベルの分け方 | トランスポート別 | 機能別(モジュラモノリス純粋形) | 新規貢献者のとっつきやすさ、外部仕様との対応の良さを優先。機能の分離は services/ 配下で実現 |
| バイナリパース | Caterpillar | Construct, Kaitai Struct, 手書き | 型ヒント統合、双方向対応、可読性のバランス |
| ドメインモデル | dataclass | Pydantic, attrs | バリデーションオーバーヘッド回避、I/O 非依存の純粋なドメイン表現 |
| HTTP フレームワーク | Starlette + FastAPI 混在 | 全部 FastAPI、全部 Starlette | プロトコル特性に応じた最適化。bancho/web_legacy は Starlette、API は FastAPI |
| パケット ID 名前空間 | C2S/S2C で完全分離 | 単一 enum | 方向取り違えを型レベルで検出 |
| ハンドラ登録 | デコレータ + 明示的 import | match 文集中ディスパッチ、自動 discovery | 宣言的、ファイル単位の責務分離、追跡可能性 |
| メッセージング基盤の二分化 | EventBus と JobQueue を別 Protocol として分離 | 単一の Pub/Sub で全部扱う | 配信保証要件が異なる用途を混同せず、実装の使い分けを可能にする |
| EventBus 実装 | Valkey Pub/Sub | Valkey Streams、自前実装一択 | チャット配信などロス許容な用途には Pub/Sub の単純さで十分 |
| EventBus ライブラリ | 自前 InMemoryEventBus(40 行程度) | Pyventus, blinker, pymitter, PyDispatcher 等 | クラスレベル状態(EventLinker)が DI 設計と矛盾、結局 Valkey Pub/Sub を別実装する必要があり依存追加のメリットが薄い、コアな抽象化レイヤーは自前実装する原則。ただし dataclass ベースのイベント定義など思想は参考にする |
| JobQueue 実装 | taskiq + taskiq-redis | Celery, RQ, Dramatiq, ARQ, Valkey Streams 直叩き | async first、軽量、Valkey 基盤共有、型ヒント親和性 |
| メッセージング基盤 | Valkey(Pub/Sub + taskiq via Streams) | RabbitMQ, Kafka | private server 規模では Valkey で必要十分、運用基盤を増やさない |
| クリティカル処理の扱い | 必ず JobQueue 経由(配信保証あり) | EventBus で fire-and-forget、同期処理で待機 | データ整合性に影響する処理(PP 計算、リーダーボード更新、メダル付与等)が消失すると復旧困難、再試行・永続化が必要 |
| クリティカル処理の境界 | 同期処理(DB 保存まで)+ JobQueue(後処理)+ EventBus(リアルタイム通知)の3層分割 | 全部同期、全部非同期、全部同じ機構 | クライアントレイテンシ最小化、整合性保証、リアルタイム性のバランス |
| 揮発的ステートの保管場所 | Valkey に集約(StateStore Protocol 経由) | プロセスメモリ(bancho.py 方式)、DB 直接 | プロセス再起動でセッション消失を防ぐ、トランスポート水平スケール対応、プロトコル間ステート整合性 |
| StateStore の API スタイル | Protocol(具象 in-memory / Valkey 切替可能) | グローバル関数、Valkey 直接呼び出し | テスト容易性、in-memory 実装での単一プロセス開発、将来的な実装差し替え |
| プロセス分離(初期) | app プロセス + worker プロセスの2分離 | 単一プロセス全部入り(bancho.py 方式) | 重い処理の影響をリクエストレイテンシから隔離、独立スケール可能 |
| 分散化への進化 | 7 段階の段階的進化(Stage 1〜7) | 一度に全部マイクロサービス化、永遠にモノリス | 規模に応じた成長を許容、各段階の移行コストを最小化 |
| Stage 4 のアーキテクチャ | Service 中央プロセス + 薄いトランスポート | Ripple 型(各プロセスが直接 DB 操作) | ビジネスロジックの一元化、共有 DB アンチパターンの回避、トランスポート言語の自由度 |
| パッケージ構造(Stage 5) | モノレポ + 共通パッケージ分離(packages/, apps/) | 単一巨大パッケージのまま、別リポジトリ分割 | 依存方向の物理強制、ビルド粒度向上、再利用性、PyPI 公開可能性 |
| モノレポツール | uv workspace | Poetry workspace, pip path deps, Pants/Bazel | 高速、モダン、Python 標準 pyproject.toml ベース、private server 規模に適合 |
| DI | 自前軽量コンテナ | dependency-injector, punq | 学習コスト最小化、必要十分な機能 |
| 代替実装言語の正式採用 | Python(本流)、Rust(性能重視)、C#(本家互換性重視)、TypeScript / Cloudflare(サーバーレス実験) | Go、Kotlin、Java の付録化 | それぞれが固有の戦略的価値を持つ。Go はデコレーター文化と合わず、Kotlin / Java は C# に対する明確な優位性が薄い(性能・互換性・書き心地のいずれでも他言語に劣後する) |
| C# / .NET 版の位置づけ | 「本家互換性最大化」用途の代替実装(付録 F) | Rust 版や Python 版に統合、付録化しない | osu! 本家(クライアント・osu-server-spectator・osu-tools)が C# 製である戦略的価値。SignalR ネイティブ、osu-tools 直接統合、PP 計算の数値完全一致は他言語では再現不能 |
| C# 版のジョブキュー | Hangfire | Coravel、自前 Redis Streams 直叩き | 機能豊富、Web 管理 UI 内蔵、Redis バックエンド対応、ARQ と同等の運用体験 |
| C# 版のシングルバイナリ戦略 | Native AOT(.NET 8+) | JIT 配布、PublishSingleFile のみ | Rust 版と同等のシングルバイナリ運用、起動高速化、メモリ削減、Docker イメージ最小化を実現 |
| Kotlin / Java の不採用 | C# が同等以上の能力を持つため付録化しない | Kotlin の Ktor 構成を独立した付録化 | SignalR / osu-tools の互換性で C# に劣り、書き心地で Python に劣り、性能で Rust に劣る。「JVM である」こと自体が決定的な利点とならない。ただし既存 JVM インフラを流用する必要がある場合は、付録 F の C# 実装を Kotlin に翻訳する形で対応可能 |

---

## 付録 C: 実装着手のロードマップ(参考)

以下は実装順序の参考。厳密に従う必要はなく、プロジェクト固有の事情で調整する。

**Phase 1: 基盤構築(2〜4週間)**
- ディレクトリスケルトン作成
- DI コンテナ、設定、ロギング、DB 接続
- import-linter 設定、CI 整備
- domain/ の主要エンティティと ids.py
- **StateStore Protocol の定義と in-memory 実装**(セッション、プレゼンス、チャンネル状態など)

**Phase 2: bancho プロトコル基盤(3〜5週間)**
- Caterpillar によるパケット定義(C2S / S2C 両方の主要パケット)
- BanchoServer ディスパッチ機構、デコレータ、ミドルウェア
- 認証ハンドラ(LOGIN)、ping/pong、status update
- **StateStore の Valkey 実装に切替**(SessionStore, PresenceStore, PacketQueue を Valkey ベースに)
- 最小限の動作確認(stable クライアントでログインして接続維持できるところまで)

**Phase 3: チャット機能(2〜3週間)**
- services/chat/ の実装
- ChannelStateStore の活用(チャンネルメンバー管理)
- bancho の C2S/S2C チャット系パケット
- EventBus 基盤(InMemoryEventBus 実装、Valkey Pub/Sub 実装)、broadcast 機構

**Phase 4: スコア機能(stable)+ Worker プロセス導入(4〜6週間)**
- web_legacy/ の score_submission 実装
- AES 復号、クライアントハッシュ検証
- services/scoring/ の実装、リーダーボード
- **JobQueue 基盤の構築**: taskiq アダプタ、worker.py、定期実行ジョブの土台
- **スコア後処理を Worker に分離**: PP 計算、リーダーボード更新、統計更新を非同期化
- Docker Compose による app + worker + Valkey + DB の統合起動

**Phase 5: REST API 基盤(2〜3週間)**
- FastAPI セットアップ、OAuth2 認証
- 主要エンドポイント(`/api/v2/me`, `/api/v2/users/{id}` 等)
- Swagger UI で外部開発者向けドキュメント公開

**Phase 6: 通知 / メダル / 定期処理(2〜3週間)**
- メダル付与判定の Worker ジョブ化
- 通知配信機能(JobQueue 経由で配信保証)
- ランキング再計算等の cron ジョブ整備

**Phase 7: マルチプレイ・spectator (stable)(4〜6週間)**
- services/multiplayer/, services/spectator/ の実装
- MatchStateStore, SpectatorStateStore の活用
- bancho の関連 C2S/S2C パケット
- spectator フレーム配信を EventBus(Valkey Pub/Sub)で実装

**Phase 8: lazer 対応(段階的、6〜12週間以上)**
- /api/v2/beatmaps/{id}/solo/scores の lazer スコア送信
- SignalR 互換層の自前実装
- spectator hub、metadata hub、multiplayer hub の段階的実装

**Phase 9 以降(オプション、規模拡大時):**
- Stage 2(DB スキーマ分離)への移行
- Stage 3(サービス間通信の Protocol 抽象化)への移行
- Stage 4(Service 中央プロセス分離)への移行
- Stage 5(モノレポ + 共通パッケージ分離、uv workspace 導入)への移行

各 Phase は独立して動作確認できる単位とし、毎回 stable または lazer クライアントでの実動作テストを通過させる。Phase 1 で StateStore Protocol を導入する時点で、Valkey 集約への準備が整い、Phase 4 でワーカープロセスを導入する時点で、本設計の二プロセス構成が完成する重要な節目となる。Phase 9 以降の進化(Stage 2〜5)は、規模と必要性に応じて選択的に実施する。

---

## 付録 D: Cloudflare ベースの代替実装(実験的)

本設計の主推奨は VPS / クラウド VM 上での Python 実装(uvicorn + arq)であるが、 **コンセプト実証や別軸での挑戦** として、Cloudflare Workers をベースとした代替アーキテクチャも検討に値する。本付録ではその概要を示す。これは公式推奨構成ではなく、 **「もし Cloudflare で構築するならこうなる」** という参考情報である。

### D.1 採用するスタック

| 領域 | 採用 |
|---|---|
| HTTP フレームワーク | Hono(Cloudflare Workers 第一級サポート) |
| 言語 | TypeScript |
| 揮発的ステート | Durable Objects（Valkey StateStore の代替） |
| 永続データ | Hyperdrive 経由の外部 PostgreSQL(Neon, Supabase 等)、または D1 |
| ジョブキュー | Cloudflare Queues(ARQ の代替) |
| 静的コンテンツ | R2(アバター、リプレイファイル、ビートマップ画像) |
| Pub/Sub | Durable Object 内の WebSocket fan-out、または Workers 間 Service Bindings |
| バイナリパース | TypeScript 自前実装 or `restructure` ライブラリ |

### D.2 アーキテクチャ概要

```
┌─────────────────────────────────────────────────────┐
│ Cloudflare Workers (Hono)                           │
│ ├─ /api/v2/* (REST API、ステートレス)                 │
│ ├─ /web/* (レガシーエンドポイント、ステートレス)        │
│ └─ / (bancho プロトコル受け口、Durable Object に転送)  │
└──────────────┬──────────────────────────────────────┘
               │
               ├─ ChannelDO (チャンネルごと)
               │  - メンバー管理 + メッセージブロードキャスト
               ├─ MatchDO (マッチごと)
               │  - ルーム状態 + プレイヤー管理
               ├─ UserSessionDO (ユーザーごと)
               │  - セッション情報 + 保留中パケット
               │  - HTTP ロングポーリング / WebSocket 接続
               └─ SpectatorDO (スペクテイト対象ごと)
                  - フレームバッファ + 観戦者一覧

┌─────────────────────────────────────────────────────┐
│ Cloudflare Queues (ARQ の代替)                       │
│ - スコア処理、PP 計算、リーダーボード更新                │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│ Cloudflare R2(オブジェクトストレージ)                │
│ - リプレイファイル(.osr)、アバター、ビートマップ画像   │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│ External PostgreSQL (Neon/Supabase) via Hyperdrive  │
│ - users, scores, beatmaps の永続化                    │
└─────────────────────────────────────────────────────┘
```

### D.3 メイン設計との対応

| メイン設計の概念 | Cloudflare 版での対応 |
|---|---|
| StateStore (Valkey) | Durable Objects（チャンネル / マッチ / ユーザー / 観戦単位でインスタンス） |
| EventBus (Valkey Pub/Sub) | Durable Object 内の WebSocket fan-out + Workers 間 Service Bindings |
| JobQueue (ARQ) | Cloudflare Queues |
| 永続 DB (PostgreSQL) | Hyperdrive 経由の外部 PostgreSQL、または D1(SQLite ベース、軽量用途のみ) |
| キャッシュ (Valkey) | Workers KV（結果整合性、グローバル分散） |
| ファイルストレージ | R2 |
| app プロセス | Workers + Durable Objects |
| worker プロセス | Queue Consumer Workers |

### D.4 実現可能性のスペクトル

各コンポーネントの実装難易度と推奨度を示す。

| コンポーネント | 実現可能性 | 推奨度 |
|---|---|---|
| `/api/v2/*` REST API | 完全に可能、むしろ向いている | 強く推奨 |
| 静的コンテンツ配信(R2) | 完全に可能 | 強く推奨 |
| スコア処理パイプライン(Queues) | 可能 | 推奨 |
| `/web/*` レガシー(ステートレス部分) | 概ね可能 | 条件付き推奨 |
| bancho バイナリプロトコル(stable) | Durable Objects で可能だが複雑 | 非推奨 |
| SignalR spectator hub(lazer) | DO で可能、相性が良い | 検討の価値あり |
| マルチプレイ状態管理 | DO で可能だが複雑 | 非推奨 |

### D.5 制約とトレードオフ

このアーキテクチャを採用する場合の主な制約:

- **コスト構造**: stable クライアントの定期 HTTP ポーリング(数秒に1回)はリクエスト数で課金されるため、ユーザー数 × ポーリング頻度でコストが線形に増える。VPS 一台で動かす場合と比べて、規模次第ではコスト劣位になる
- **レイテンシ**: グローバルに分散したユーザーが特定の Durable Object にアクセスする場合、地理的距離によるペナルティが発生する。bancho のリアルタイム性に影響しうる
- **Caterpillar 相当の TypeScript ライブラリの欠如**: Python の Caterpillar ほど洗練された宣言的バイナリパーサーは TypeScript エコシステムには現状ない。`restructure`(npm ダウンロード数最大)、`Binary-parser`(GitHub スター数最大)、`Binpat` 等の選択肢で構築可能だが、いずれも Caterpillar の現代的な体験には及ばない。詳細は付録 G を参照
- **ローカル開発の難しさ**: Cloudflare Workers のローカル実行(`wrangler dev`)は強力だが、Durable Objects の挙動再現には若干の制約がある
- **外部開発者向けドキュメント**: OpenAPI 自動生成は Hono にも対応ライブラリがあるが、FastAPI のエコシステムには及ばない

### D.6 推奨される現実的な使い方

Cloudflare スタックを **全面採用するのではなく、メイン構成と組み合わせるハイブリッド** が現実的である。

```
[stable client] → c.bancho.example.com → VPS(従来構成、Python)
[stable client] → osu.bancho.example.com/web/* → VPS

[lazer client]  → osu.bancho.example.com/api/v2/* → Cloudflare Workers (Hono)
[external bot]  → osu.bancho.example.com/api/v2/* → Cloudflare Workers (Hono)

各種静的ファイル → R2(リプレイ、アバター、ビートマップ画像)
```

この構成だと:

- bancho 本体は実績ある Python 実装で安定運用
- REST API は Cloudflare のグローバル CDN に乗せて、外部 bot 開発者向けのレイテンシを最適化
- 静的コンテンツは R2 でコスト最安、グローバル配信
- VPS は最小スペックで済む

### D.7 完全 Cloudflare 化が向くケース

以下の特殊な状況であれば、フル Cloudflare 化を検討する価値がある。

- **lazer 専用の private server**: WebSocket 中心のため Hibernation で経済的に成立しやすい
- **インフラ管理を極限まで減らしたい**: VPS の保守を一切したくないケース
- **グローバル展開が前提**: 世界中のユーザーが同程度に分散しているケース
- **学習・実験目的**: サーバーレスでの bancho サーバー実装がそれ自体の目的

逆に「日本人プレイヤー中心で運用」「コストを最小化したい」「貢献者は Python 開発者が多い」というケースでは、メイン構成(Python + VPS)を選ぶべきである。

### D.8 設計書本体との関係

本付録の代替実装は、メインの設計書を否定するものではなく、 **同じドメインモデル・同じプロトコル知識を別実装で再現したらこうなる** という対応関係を示すものである。 `osu-domain` や `osu-protocol` のような共通パッケージを言語非依存の概念として捉えれば、Python 版でも TypeScript 版でも同じ設計思想に従う実装が可能である。

実装プロジェクトとしては **Python 版を本流** とし、TypeScript / Cloudflare 版は実験的な別ブランチまたは別リポジトリとして並走させるのが現実的だろう。

---

## 付録 E: Rust ベースの代替実装(性能 + 書き心地の両立を目指す)

メインの推奨は Python であるが、 **性能と書き心地の両立を最優先する場合の代替実装** として、Rust ベースの構成も検討に値する。本付録は、Rust 版を実装する際の指針をまとめる。

Cloudflare 版(付録 D)が「サーバーレス前提のラディカルな代替」だったのに対し、本付録は **「同じアーキテクチャを別言語で再実装する」** 方向性となる。設計書本体のドメインモデル、トランスポート分離、StateStore / EventBus / JobQueue の設計思想はそのまま流用する。

### E.1 採用するスタック

| 領域 | 採用クレート | 対応する Python ライブラリ |
|---|---|---|
| HTTP ランタイム | tokio + hyper | uvicorn |
| HTTP ルーティング(REST) | axum | FastAPI |
| HTTP ルーティング(レガシー、bancho) | axum + hyper 直接 | Starlette |
| WebSocket(SignalR 互換) | axum::extract::ws | starlette WebSocket |
| バイナリパース(bancho パケット) | binrw | Caterpillar |
| API バリデーション | serde + validator | Pydantic |
| 設定管理 | figment + serde | pydantic-settings |
| ORM | sqlx(async, type-checked queries) | SQLAlchemy 2.0 |
| マイグレーション | sqlx::migrate | Alembic |
| Redis プロトコルクライアント | fred(高機能)または deadpool-redis | valkey-glide |
| ジョブキュー | apalis | taskiq + taskiq-redis |
| ロギング | tracing + tracing-subscriber | logging |
| エラー追跡 | sentry crate | sentry-sdk |
| OAuth2 | oauth2 crate | authlib |
| JWT | jsonwebtoken | python-jose |
| PP 計算 | rosu-pp(ネイティブ統合) | rosu-pp-py(の元) |
| エラーハンドリング | thiserror + anyhow | 標準 Exception |
| シリアライズ | serde, serde_json, rmp-serde | json, msgpack |
| 自動 OpenAPI 生成 | utoipa または aide | FastAPI 内蔵 |
| テスト | tokio::test + axum-test | pytest + httpx |
| Lint / Format | clippy + rustfmt | ruff |
| 並行処理基盤 | Arc + tokio::sync(RwLock, Mutex, mpsc) | asyncio |
| ビルドツール | cargo workspace | uv workspace |
| 自作 proc-macro | bancho-handler-macro(自前) | Python のデコレーター(言語標準) |

### E.2 アーキテクチャ概要

設計書のレイヤー構造をそのまま Rust の crate workspace で表現する。 `cargo workspace` の機能でモノレポを構築する。

```
osu-server/                          # workspace root
├── Cargo.toml                       # workspace 定義
├── packages/                        # 共通 crate 群(Python 版 packages/ と対応)
│   ├── osu-domain/                  # ドメインモデル(I/O 非依存)
│   ├── osu-shared/                  # 横断的最小要素
│   ├── osu-protocol/                # bancho プロトコル定義(binrw ベース)
│   ├── osu-repositories/            # 永続化層(sqlx ベース)
│   ├── osu-state/                   # Redis StateStore 群
│   ├── osu-services/                # ビジネスロジック
│   ├── osu-infrastructure/          # DB、キャッシュ、DI、ジョブ等
│   ├── osu-service-client/          # サービス間 RPC クライアント(Stage 4 用)
│   └── bancho-handler-macro/        # 自作 proc-macro(後述 E.4)
│
└── apps/                            # 実行プロセス(各バイナリ)
    ├── bancho-app/                  # bancho プロセス
    ├── web-legacy-app/              # web_legacy プロセス
    ├── api-app/                     # api プロセス
    ├── signalr-app/                 # signalr プロセス
    └── worker-app/                  # apalis ワーカー
```

`Cargo.toml`(workspace root)では以下のように定義する。

```toml
[workspace]
members = ["packages/*", "apps/*"]
resolver = "2"

[workspace.package]
edition = "2021"
rust-version = "1.75"

[workspace.dependencies]
tokio = { version = "1", features = ["full"] }
axum = "0.7"
hyper = "1"
sqlx = { version = "0.7", features = ["postgres", "runtime-tokio"] }
fred = "9"
binrw = "0.13"
serde = { version = "1", features = ["derive"] }
tracing = "0.1"
thiserror = "1"
anyhow = "1"

osu-domain = { path = "packages/osu-domain" }
osu-protocol = { path = "packages/osu-protocol" }
osu-services = { path = "packages/osu-services" }
osu-state = { path = "packages/osu-state" }
osu-infrastructure = { path = "packages/osu-infrastructure" }
bancho-handler-macro = { path = "packages/bancho-handler-macro" }
```

各 app crate は必要なものだけを依存に持つ。例えば `apps/bancho-app/Cargo.toml`:

```toml
[package]
name = "bancho-app"
version = "0.1.0"
edition.workspace = true

[dependencies]
tokio.workspace = true
axum.workspace = true
hyper.workspace = true
binrw.workspace = true
serde.workspace = true
tracing.workspace = true

osu-domain.workspace = true
osu-protocol.workspace = true
osu-services.workspace = true
osu-state.workspace = true
osu-infrastructure.workspace = true
bancho-handler-macro.workspace = true
```

`api-app` は `osu-protocol`(bancho バイナリ定義)に依存する必要がない、というように、 **app ごとに必要な crate だけを依存に含める** ことができる。これは Python の `osu-protocol` を不要なプロセスで import しない、という方針と完全に一致する。

### E.3 Web フレームワークの選定: axum

Rust の Web フレームワークは複数選択肢がある(axum, actix-web, rocket, poem 等)が、本実装では **axum を採用する**。理由は以下の通り。

| 項目 | axum | actix-web | rocket | poem |
|---|---|---|---|---|
| Tokio 公式 | ✓ | ✗ | ✗ | ✗ |
| Tower エコシステム統合 | ◎ | ✗ | ✗ | ◎ |
| tonic(gRPC)との同居 | ◎ | △ | △ | ◯ |
| WebSocket サポート | ◎ | ◎ | △ | ◎ |
| エコシステム成熟度 | ◎ | ◎ | ◯ | ◯ |
| 長期メンテナンス安定性 | ◎ | ◯ | ◯ | △ |
| マクロ駆動の書き心地 | △(関数ベース) | ◎ | ◎ | ◎ |

axum を採用する決定的な理由:

1. **Tower エコシステムの中核**: `tower-http` の認証、CORS、トレーシング、レート制限が直接使える
2. **gRPC との同居**: 設計書 Stage 4(Service プロセス分離)で内部通信に gRPC を採用する場合、axum と tonic は同じ Tower ベースで同居可能
3. **長期サポートの安全性**: Tokio チーム公式で、メンテナンス体制が最も安定
4. **bancho プロトコルへの柔軟性**: hyper の薄い殻として、HTTP の枠を出る用途にも対応できる
5. **エコシステムの成長性**: sqlx, redis-rs, tonic, tracing すべてが axum 前提で進化中

書き心地の観点で actix-web や rocket のマクロ駆動が魅力的だが、 **axum + 自作 proc-macro(後述 E.4)** で同等以上の体験を構築できる。Tower エコシステムの戦略的価値は他のフレームワークでは得られない。

### E.4 bancho ハンドラ用 proc-macro の設計

axum の標準 API は関数ベースで明示的だが、 **bancho パケットハンドラには Python のデコレーター相当の体験が欲しい**。これを自作 proc-macro `bancho-handler-macro` で実現する。

#### E.4.1 目指す書き心地

```rust
// transports/bancho/handlers/chat.rs
use bancho_handler_macro::bancho_handler;
use osu_protocol::client_packet_id::ClientPacketId;
use osu_protocol::c2s::chat::SendPublicMessageC2S;

#[bancho_handler(
    packet_id = ClientPacketId::SendPublicMessage,
    rate_limit = "10/5s",
)]
async fn handle_send_public_message(
    packet: SendPublicMessageC2S,
    Player(player): Player,
    Service(chat): Service<ChatService>,
) -> Result<(), HandlerError> {
    chat.send_message(player.id, packet.target, packet.message).await?;
    Ok(())
}
```

これは Python のデコレーター版とほぼ等価:

```python
@bancho.handler(
    ClientPacketID.SEND_PUBLIC_MESSAGE,
    rate_limit=RateLimit(messages=10, per_seconds=5),
)
async def handle_send_public_message(
    packet: SendPublicMessageC2S,
    player: Annotated[Player, Depends(current_player)],
    chat: Annotated[ChatService, Depends(get_chat_service)],
):
    await chat.send_message(player.id, packet.target, packet.message)
```

#### E.4.2 proc-macro が生成するコード

`#[bancho_handler]` 属性は内部的に以下を行う。

1. **元の関数をそのまま残す**: テスタブル性のため、関数自体は通常通り呼べる
2. **`inventory` クレートで自動登録**: 副次的に登録用の構造体を生成し、起動時に集約される
3. **extractor の解決**: `Player(player)` のような引数を `FromBanchoContext` trait で抽出するコードを生成
4. **横断的関心事の wrap**: `rate_limit` 等の属性に応じて、レート制限・認証チェックの wrap コードを生成

具体的な展開イメージ:

```rust
// 元のコード
#[bancho_handler(packet_id = ClientPacketId::SendPublicMessage)]
async fn handle_send_public_message(
    packet: SendPublicMessageC2S,
    Player(player): Player,
    Service(chat): Service<ChatService>,
) -> Result<(), HandlerError> { /* ... */ }

// 展開後(マクロが生成するコード、概念的なもの)
async fn handle_send_public_message(
    packet: SendPublicMessageC2S,
    Player(player): Player,
    Service(chat): Service<ChatService>,
) -> Result<(), HandlerError> { /* 元のロジックそのまま */ }

inventory::submit! {
    BanchoHandlerRegistration {
        packet_id: ClientPacketId::SendPublicMessage,
        handler: |raw_payload: Vec<u8>, ctx: BanchoContext| -> BoxFuture<'static, Result<(), HandlerError>> {
            Box::pin(async move {
                let packet = SendPublicMessageC2S::read_le(&mut Cursor::new(&raw_payload))?;
                let player = Player::from_bancho_context(&ctx).await?;
                let chat = Service::<ChatService>::from_bancho_context(&ctx).await?;
                handle_send_public_message(packet, player, chat).await
            })
        },
        rate_limit: Some(RateLimit::parse("10/5s").unwrap()),
        requires_auth: true,
    }
}
```

#### E.4.3 起動時の登録収集

`inventory` クレートを使うと、 **コンパイル時に分散登録された情報を起動時に1箇所に集約** できる。これは Python の「副作用 import で登録」より構造的に堅牢。

```rust
// transports/bancho/server.rs
pub fn build_bancho_server() -> BanchoServer {
    let mut server = BanchoServer::new();

    // inventory が収集した全ハンドラを登録
    for registration in inventory::iter::<BanchoHandlerRegistration> {
        server.register(registration);
    }

    server
}
```

「ファイルを置けば自動登録される」が **コンパイル時の保証付きで実現** される。Python の `from . import handler_module  # noqa: F401` のような副作用 import が不要。

#### E.4.4 proc-macro クレートの構造

`packages/bancho-handler-macro/` の構造は以下のようになる。

```
packages/bancho-handler-macro/
├── Cargo.toml
└── src/
    ├── lib.rs                    # proc-macro のエントリポイント
    ├── attribute.rs              # 属性パース(packet_id, rate_limit 等)
    └── codegen.rs                # コード生成ロジック
```

`Cargo.toml`:

```toml
[package]
name = "bancho-handler-macro"
version = "0.1.0"

[lib]
proc-macro = true

[dependencies]
syn = { version = "2", features = ["full"] }
quote = "1"
proc-macro2 = "1"
```

実装は概ね 200〜300 行程度になる見込み。 **proc-macro 自作は学習コストがあるが、一度作れば bancho サーバー全体の書き心地が劇的に改善する** ため、投資価値が高い。

### E.5 各レイヤーの実装方針

設計書セクション 8 の各機構を Rust で実装する場合の方針を示す。

#### E.5.1 StateStore（Valkey 集約）

trait による抽象化と、`fred` クレートによる Valkey 実装（Redis プロトコル互換）。

```rust
// packages/osu-state/src/interfaces/session_store.rs
use async_trait::async_trait;
use osu_domain::ids::UserId;
use osu_domain::session::{Session, Token};

#[async_trait]
pub trait SessionStore: Send + Sync {
    async fn create(&self, user_id: UserId, client_type: ClientType) -> Result<Token, StateError>;
    async fn get(&self, token: &Token) -> Result<Option<Session>, StateError>;
    async fn touch(&self, token: &Token) -> Result<(), StateError>;
    async fn delete(&self, token: &Token) -> Result<(), StateError>;
    async fn list_online_user_ids(&self) -> Result<Vec<UserId>, StateError>;
}

// packages/osu-state/src/redis/session_store.rs
use fred::prelude::*;

pub struct RedisSessionStore {
    client: RedisPool,
}

#[async_trait]
impl SessionStore for RedisSessionStore {
    async fn create(&self, user_id: UserId, client_type: ClientType) -> Result<Token, StateError> {
        let token = Token::generate();
        let key = format!("session:{}", token.as_str());
        let user_session_key = format!("user_session:{}", user_id.0);

        let pipeline = self.client.pipeline();
        pipeline.hset(&key, &[
            ("user_id", user_id.0.to_string()),
            ("client_type", client_type.to_string()),
            ("created_at", chrono::Utc::now().timestamp().to_string()),
        ]).await?;
        pipeline.expire(&key, SESSION_TTL_SECONDS).await?;
        pipeline.set(&user_session_key, token.as_str(),
            Some(Expiration::EX(SESSION_TTL_SECONDS)), None, false).await?;
        pipeline.zadd("online_users", None, None, false, false,
            vec![(chrono::Utc::now().timestamp() as f64, user_id.0)]).await?;
        pipeline.all().await?;

        Ok(token)
    }

    // 他のメソッドも同様
}
```

trait による抽象化は Python の Protocol と等価で、テスト時は `MemorySessionStore` に差し替え可能。

#### E.5.2 EventBus

```rust
// packages/osu-infrastructure/src/messaging/interface.rs
#[async_trait]
pub trait EventBus: Send + Sync {
    async fn publish<E: Event + Send + Sync + 'static>(&self, event: E) -> Result<(), MessagingError>;
    fn subscribe<E: Event + Send + Sync + 'static, F, Fut>(&self, handler: F)
    where
        F: Fn(E) -> Fut + Send + Sync + 'static,
        Fut: Future<Output = ()> + Send + 'static;
}

pub trait Event: Serialize + DeserializeOwned + 'static {
    const EVENT_TYPE: &'static str;
}

// 実装(Valkey Pub/Sub、Redis プロトコル互換)
pub struct RedisPubSubEventBus {
    client: RedisPool,
    handlers: Arc<RwLock<HashMap<&'static str, Vec<HandlerFn>>>>,
}

// イベント定義
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MessageSentEvent {
    pub message_id: i64,
    pub channel_name: String,
    pub sender_id: i64,
    pub content: String,
}

impl Event for MessageSentEvent {
    const EVENT_TYPE: &'static str = "chat.message_sent";
}
```

#### E.5.3 JobQueue: apalis

ARQ の Rust 相当として `apalis` を採用する。Redis Streams または RabbitMQ をブローカーとして使え、tokio + Tower エコシステムに統合されている。

```rust
// apps/worker-app/src/main.rs
use apalis::prelude::*;
use apalis::redis::RedisStorage;

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct ProcessScoreJob {
    pub score_id: i64,
}

impl Job for ProcessScoreJob {
    const NAME: &'static str = "process_score";
}

async fn process_score(job: ProcessScoreJob, ctx: WorkerContext) -> Result<(), JobError> {
    let scoring = ctx.data::<ScoringService>()?;

    if scoring.is_score_processed(job.score_id).await? {
        return Ok(());  // 冪等性保証
    }

    scoring.calculate_and_persist_pp(job.score_id).await?;
    scoring.update_leaderboards(job.score_id).await?;
    scoring.update_user_statistics(job.score_id).await?;
    scoring.mark_score_processed(job.score_id).await?;

    Ok(())
}

#[tokio::main]
async fn main() -> Result<()> {
    let config = load_config()?;
    let container = build_container(&config).await?;

    let storage: RedisStorage<ProcessScoreJob> =
        RedisStorage::connect(&config.redis_url).await?;

    Monitor::new()
        .register({
            WorkerBuilder::new("score-processor")
                .data(container.resolve::<ScoringService>())
                .source(storage.clone())
                .build_fn(process_score)
        })
        .register({
            WorkerBuilder::new("achievement-checker")
                .data(container.resolve::<AchievementService>())
                .source(achievement_storage)
                .build_fn(check_achievements)
        })
        .run()
        .await?;

    Ok(())
}
```

設計書のセクション 8.5(worker.py)に対応する Rust 版。WorkerBuilder で各ジョブハンドラを登録し、Monitor で全体を起動する。

#### E.5.4 サービス層

サービスは trait + struct + Arc で Python の class 相当を表現する。

```rust
// packages/osu-services/src/scoring/service.rs
use std::sync::Arc;

#[async_trait]
pub trait ScoringApi: Send + Sync {
    async fn submit_lazer_score(&self, score: ScoreSubmission, user_id: UserId) -> Result<Score, AppError>;
    async fn calculate_and_persist_pp(&self, score_id: i64) -> Result<(), AppError>;
    async fn update_leaderboards(&self, score_id: i64) -> Result<(), AppError>;
    // ...
}

pub struct ScoringService {
    score_repo: Arc<dyn ScoreRepository>,
    job_queue: Arc<dyn JobQueue>,
    event_bus: Arc<dyn EventBus>,
    pp_calculator: Arc<PpCalculator>,
}

#[async_trait]
impl ScoringApi for ScoringService {
    async fn submit_lazer_score(&self, score: ScoreSubmission, user_id: UserId)
        -> Result<Score, AppError>
    {
        // 同期処理: DB 永続化
        let saved = self.score_repo.save(&score, user_id).await?;

        // クリティカル処理は JobQueue 経由
        self.job_queue.enqueue(ProcessScoreJob { score_id: saved.id.0 }).await?;
        self.job_queue.enqueue(CheckAchievementsJob {
            user_id: user_id.0,
            score_id: saved.id.0,
        }).await?;

        // ロス許容な通知は EventBus
        self.event_bus.publish(ScoreSubmittedNotice {
            score_id: saved.id.0,
            user_id: user_id.0,
        }).await?;

        Ok(saved)
    }
}
```

設計書のセクション 8.9.3 のスコア送信パターン(同期 + JobQueue + EventBus の3層)が、Rust でもそのまま再現できる。

### E.6 PP 計算のネイティブ統合

Rust 版の最大の強みの一つが、 **PP 計算ライブラリ rosu-pp をネイティブに統合できる** こと。Python 版では rosu-pp-py 経由(FFI)で呼ぶが、Rust 版では直接依存できる。

```rust
// packages/osu-services/src/scoring/pp_calculator.rs
use rosu_pp::{Beatmap, GameMods, Performance};

pub struct PpCalculator {
    beatmap_storage: Arc<dyn BeatmapStorage>,
}

impl PpCalculator {
    pub async fn calculate(&self, score: &Score) -> Result<f64, AppError> {
        let beatmap_data = self.beatmap_storage.fetch(&score.beatmap_md5).await?;
        let map = Beatmap::from_bytes(&beatmap_data)?;

        let mods = GameMods::from_bits(score.mods);
        let perf = Performance::new(&map)
            .mods(mods)
            .accuracy(score.accuracy)
            .combo(score.max_combo as u32)
            .calculate();

        Ok(perf.pp)
    }
}
```

これは Python 版の `rosu-pp-py` 呼び出しと等価だが、 **FFI のオーバーヘッドがなく、ネイティブ最適化が効く**。PP 計算は本家との数値一致が要求されるシビアな領域で、ネイティブ統合は信頼性面でも有利。

### E.7 axum との統合パターン

各トランスポートが axum をどう使うかの全体像。

#### E.7.1 REST API(axum 標準)

```rust
// apps/api-app/src/routers/users.rs
use axum::{Router, extract::{Path, State}, routing::get, Json};
use osu_domain::ids::UserId;
use osu_services::user::UserApi;

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/:id", get(get_user))
        .route("/me", get(get_current_user))
}

async fn get_user(
    Path(id): Path<u64>,
    State(state): State<AppState>,
) -> Result<Json<UserResponse>, ApiError> {
    let user = state.user_service.find_by_id(UserId(id as i64)).await?
        .ok_or(ApiError::NotFound)?;
    Ok(Json(UserResponse::from(user)))
}
```

#### E.7.2 bancho プロトコル(axum + 自前ディスパッチ)

```rust
// apps/bancho-app/src/main.rs
use axum::{Router, routing::post, body::Bytes, extract::State, response::Response};
use http::{StatusCode, header};
use bancho_handler_macro::collect_handlers;

#[tokio::main]
async fn main() -> Result<()> {
    let config = load_config()?;
    let container = build_container(&config).await?;

    // proc-macro が登録した全ハンドラを集約
    let bancho_server = collect_handlers!();

    let app = Router::new()
        .route("/", post(handle_bancho_request))
        .with_state(AppState {
            bancho_server: Arc::new(bancho_server),
            container,
        });

    let listener = tokio::net::TcpListener::bind(&config.bind_addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}

async fn handle_bancho_request(
    State(state): State<AppState>,
    headers: HeaderMap,
    body: Bytes,
) -> Result<Response, BanchoError> {
    let token = headers.get("osu-token").and_then(|h| h.to_str().ok()).map(String::from);
    let ctx = BanchoContext::new(&state.container, token).await?;

    let response_bytes = state.bancho_server.dispatch(&body, ctx).await?;

    Ok(Response::builder()
        .header(header::CONTENT_TYPE, "application/octet-stream")
        .header("cho-token", token_for_response)
        .body(response_bytes.into())?)
}
```

#### E.7.3 SignalR 互換層(axum WebSocket)

```rust
// apps/signalr-app/src/hubs/spectator.rs
use axum::{extract::{ws::{WebSocket, WebSocketUpgrade}, State}, response::Response};

pub async fn spectator_ws_handler(
    ws: WebSocketUpgrade,
    State(state): State<AppState>,
) -> Response {
    ws.on_upgrade(move |socket| async move {
        handle_spectator_connection(socket, state).await;
    })
}

async fn handle_spectator_connection(socket: WebSocket, state: AppState) {
    let hub = state.spectator_hub.clone();
    hub.register_connection(socket).await;
}
```

3つのトランスポートすべてが同じ axum + Tower エコシステム上で統一的に書ける。

### E.8 制約とトレードオフ

Rust 版を採用する際の制約:

#### E.8.1 開発速度の低下

正直に言って、 **Python 版より2〜3倍の開発時間** が必要になる。所有権・ライフタイム・async trait の制約に時間を取られる場面は避けられない。「動くものを早く作る」が優先なら Python 版を選ぶべき。

#### E.8.2 proc-macro の自作コスト

`bancho-handler-macro` の自作は最初の数週間〜1ヶ月の投資が必要。 `syn`, `quote` の学習、エラーメッセージのデバッグ、edge case への対応など、 **Rust の中でも特殊な領域** に踏み込む必要がある。

ただし一度作れば後はその恩恵を受け続けられるので、長期プロジェクトなら投資価値はある。

#### E.8.3 貢献者を集めにくい

osu! private server コミュニティは Python が主流で、Rust を書ける貢献者は限られる。 **「個人プロジェクトとして長く続ける覚悟」** がないと、メンテナンス負担が増えるリスクがある。

Peace というプロジェクトがこの方針で進んでいるが、知名度の割にコントリビューターは多くない。これは技術選択の影響が大きい。

#### E.8.4 Caterpillar / Pydantic ほどの宣言性は得られない

binrw は `#[binrw]` derive で宣言的にバイナリ定義できるが、 **Caterpillar の `if_=` のような条件付きフィールド** は属性マクロで表現する必要があり、書き心地は若干劣る。

```rust
// binrw での条件付きフィールド
#[derive(BinRead, BinWrite)]
#[brw(little)]
struct BanchoString {
    present: u8,

    #[br(if(present == 0x0b))]
    #[bw(if(*present == 0x0b))]
    length: Option<ULEB128>,

    #[br(if(present == 0x0b))]
    #[bw(if(*present == 0x0b))]
    #[br(count = length.unwrap_or(0))]
    value: Option<Vec<u8>>,
}
```

Caterpillar の方がやや簡潔だが、Rust 版でも宣言的な記述は維持できる。

なお、binrw 以外にも Rust のバイナリパースライブラリは複数存在し(Deku、scroll、Nom、winnow 等)、特に **Deku は bit-level の表現力に特化** している。bancho プロトコルが多数の bit-packed フィールドを含む場合、Deku の方が適合する可能性もある。詳細な比較は付録 G.2 を参照。

#### E.8.5 エラーハンドリングの記述量

`Result<T, E>` を全箇所で扱うため、 `?` 演算子があっても記述量は Python より多くなる。ただしこれは **Rust の堅牢性の代償** で、致命的なエラーの黙殺を構造的に防げる利点もある。

#### E.8.6 ビルド時間

Rust のコンパイル時間は Python の起動時間よりはるかに長い。 **incremental compilation でも数十秒、フルビルドで数分** かかる。開発サイクルが Python より遅くなる。

`cargo watch` や `bacon` で自動リビルドしつつ、 `mold` リンカーで高速化する等の工夫が必要。

### E.9 Rust 版を選ぶべきシナリオ

以下のいずれかに該当する場合、Rust 版を本気で検討する価値がある。

- **数千〜数万同時接続を想定する大規模 private server を構築したい**: Python では性能上限に達するスケール
- **PP 計算をネイティブ統合し、本家との数値一致を厳密に保証したい**: rosu-pp の Rust ネイティブ実装を活用
- **シングルバイナリデプロイの運用簡潔さを最優先する**: 1ファイル配布、軽量 Docker イメージ、低メモリ消費
- **長期メンテナンス(5〜10年)を想定し、堅牢性を最優先する**: 型システムによる安全性、async-await の確実性
- **メイン開発者が Rust に習熟している、または学ぶ覚悟がある**: 開発速度の低下を許容できる

逆に、以下の場合は Python 版を選ぶべき:

- **数ヶ月以内に動くものが必要**
- **コミュニティに開かれた貢献者ベースのプロジェクトにしたい**
- **既存の Python 製 osu! ライブラリ群を最大活用したい**
- **チームに Rust 経験者が少ない**

### E.10 Python 版からの段階的移行

すでに Python 版が稼働している状況で、性能ボトルネックを Rust に置き換える段階的移行も可能。

#### Stage A: ホットスポットだけ Rust 化

特定の重い処理(PP 計算、binary パース、ハッシュ検証)を Rust で実装し、PyO3 経由で Python から呼ぶ。

```python
# Python 側
from osu_pp_native import calculate_pp  # PyO3 で Rust から bind

result = calculate_pp(beatmap_bytes, score_data)
```

これで Python 版の利便性を保ちつつ、性能ネックを解消できる。

#### Stage B: トランスポート1つを Rust に置き換え

例えば bancho バイナリプロトコルだけ Rust に切り出し、REST API は Python のまま運用する。プロセスを分離し、それぞれ最適な言語で書く。

設計書の Stage 4(トランスポート分離)が完成していれば、この移行はトランスポート単位の切り替えで実現可能。サービス層は同じ DB / Redis を共有する。

#### Stage C: 全面 Rust 化

最終段階として、全コンポーネントを Rust に統一する。これは規模拡大が確定し、Rust の運用体制が整った場合のみ。

この段階的移行は、 **「最初は Python で動かして実用性を確保し、必要に応じて Rust 化する」** という現実的な戦略を可能にする。設計書のドメインモデルとプロトコル知識は両言語で共通なので、移行時のリスクが低減する。

### E.11 設計書本体との関係

本付録の Rust 実装は、 **同じ設計思想を別言語で再現したもの** である。以下が共通する。

- ドメインモデル(Player, Score, Channel, Match)
- bancho プロトコル仕様(C2S/S2C パケット定義)
- レイヤー構造(transports / services / domain / repositories / infrastructure)
- StateStore / EventBus / JobQueue の3軸インフラ抽象
- クリティカル処理の JobQueue 化原則
- 段階的進化パス(Stage 1〜7)

異なるのは実装言語と、それに伴う具体的なクレート選択のみ。 **設計書本体の意思決定はすべて Rust 版にも適用される**。

実装プロジェクトとしては以下の選択肢がある。

1. **Python 版を本流とし、Rust 版は別リポジトリで実験的に並走**
2. **Rust 版を本流とし、Python 版は廃止または小規模ツール用途に縮小**
3. **両方を別リポジトリで継続運用し、共通仕様(`osu-protocol` 相当)だけを共有**

現実的には選択肢 1 から始めて、実際に Rust 版が完成してから 2 への移行を検討するのが安全。

---

## 付録 F: C# / .NET ベースの代替実装(本家との互換性を最大化)

メインの推奨は Python であるが、 **本家 osu! との互換性を最大化したい場合の代替実装** として、C# / .NET ベースの構成も検討に値する。本付録は、C# 版を実装する際の指針をまとめる。

Rust 版(付録 E)が「性能と書き心地の両立」を目指したのに対し、本付録は **「本家コードベースとの戦略的な近接性」** を最重視する方向性となる。osu! クライアント本体、osu-server-spectator(lazer 用 SignalR ハブ)、osu-tools(PP 計算ツール)、osu-framework(ゲームフレームワーク)、これらすべてが C# / .NET で書かれている事実は無視できない。

### F.1 採用するスタック

| 領域 | 採用 | 対応する Python ライブラリ |
|---|---|---|
| ランタイム | .NET 8+ (LTS) | Python 3.12+ |
| HTTP / Web フレームワーク | ASP.NET Core | FastAPI + Starlette |
| 認証・ミドルウェア | ASP.NET Core Identity / Authentication | FastAPI security |
| WebSocket | ASP.NET Core SignalR | starlette WebSocket(自前 SignalR 互換層) |
| バイナリパース(bancho パケット) | 自前 source generator + `BinaryReader` / `Span<byte>` | Caterpillar |
| API バリデーション | FluentValidation または DataAnnotations | Pydantic |
| 設定管理 | `Microsoft.Extensions.Configuration` | pydantic-settings |
| ORM | EF Core (本格)または Dapper (軽量) | SQLAlchemy 2.0 |
| マイグレーション | EF Core Migrations | Alembic |
| Redis プロトコルクライアント | StackExchange.Redis | valkey-glide |
| ジョブキュー | Hangfire または Coravel | taskiq + taskiq-redis |
| ロギング | Serilog | structlog / logging |
| エラー追跡 | Sentry.NET | sentry-sdk |
| OAuth2 | OpenIddict | authlib |
| JWT | Microsoft.AspNetCore.Authentication.JwtBearer | python-jose |
| **PP 計算** | **osu-tools の直接参照(osu.Game.Rulesets.*)** | rosu-pp-py |
| エラーハンドリング | `Result<T>` パターン(`OneOf`, `LanguageExt`)or 例外 | 標準 Exception |
| シリアライズ | System.Text.Json, MessagePack-CSharp | json, msgpack |
| 自動 OpenAPI 生成 | NSwag または Swashbuckle | FastAPI 内蔵 |
| テスト | xUnit + WebApplicationFactory | pytest + httpx |
| Lint / Format | dotnet format + Roslyn analyzers | ruff |
| 並行処理基盤 | `Task` + `async/await` + `Channel<T>` | asyncio |
| 依存性注入 | Microsoft.Extensions.DependencyInjection(言語標準) | 自前 DI コンテナ |
| ビルドツール | dotnet CLI + .csproj | uv |
| シングルバイナリ化 | Native AOT または PublishSingleFile | (なし) |

特筆すべきは:

- **依存性注入が .NET 標準ライブラリに組み込まれている**: 自前 DI コンテナを書く必要がない
- **SignalR がフレームワーク標準**: lazer の SignalR ハブを互換性問題ゼロで実装できる
- **osu-tools が直接依存に追加できる**: NuGet または GitHub サブモジュール経由で `osu.Game.Rulesets.*` を参照可能

### F.2 アーキテクチャ概要

設計書のレイヤー構造を C# プロジェクト構造で再現する。 **.NET の慣習に従いソリューション(`.sln`)とプロジェクト(`.csproj`)で構成** する。

```
osu-server/                          # ソリューションルート
├── osu-server.sln                   # ソリューションファイル
├── Directory.Build.props            # 共通ビルド設定
├── packages/                        # 共通プロジェクト群
│   ├── Osu.Domain/                  # ドメインモデル(I/O 非依存)
│   │   └── Osu.Domain.csproj
│   ├── Osu.Shared/                  # 横断的最小要素
│   ├── Osu.Protocol/                # bancho プロトコル定義
│   │   ├── ClientPacketId.cs
│   │   ├── ServerPacketId.cs
│   │   ├── C2S/
│   │   │   ├── Auth.cs
│   │   │   ├── Chat.cs
│   │   │   └── ...
│   │   └── S2C/
│   │       └── ...
│   ├── Osu.Protocol.Generators/     # source generator(bancho-handler-macro 相当)
│   ├── Osu.Repositories/            # 永続化層(EF Core or Dapper)
│   ├── Osu.State/                   # Redis StateStore 群
│   ├── Osu.Services/                # ビジネスロジック
│   ├── Osu.Infrastructure/          # DB、キャッシュ、DI、ジョブ等
│   └── Osu.ServiceClient/           # サービス間 RPC クライアント(Stage 4 用)
│
└── apps/                            # 実行プロセス(各ホスト)
    ├── Osu.Bancho.Host/             # bancho プロセス
    │   ├── Program.cs
    │   └── Osu.Bancho.Host.csproj
    ├── Osu.WebLegacy.Host/          # web_legacy プロセス
    ├── Osu.Api.Host/                # api プロセス
    ├── Osu.Signalr.Host/            # signalr プロセス
    └── Osu.Worker.Host/             # Hangfire / Coravel ワーカー
```

`Directory.Build.props` でプロジェクト共通設定を一元化:

```xml
<Project>
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <LangVersion>latest</LangVersion>
    <TreatWarningsAsErrors>true</TreatWarningsAsErrors>
    <AnalysisLevel>latest</AnalysisLevel>
  </PropertyGroup>
</Project>
```

各プロジェクトの `.csproj` は最小限の依存記述で済む:

```xml
<!-- apps/Osu.Bancho.Host/Osu.Bancho.Host.csproj -->
<Project Sdk="Microsoft.NET.Sdk.Web">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <PublishAot>true</PublishAot>  <!-- Native AOT 有効化 -->
  </PropertyGroup>

  <ItemGroup>
    <PackageReference Include="StackExchange.Redis" />
    <PackageReference Include="Serilog.AspNetCore" />
  </ItemGroup>

  <ItemGroup>
    <ProjectReference Include="..\..\packages\Osu.Domain\Osu.Domain.csproj" />
    <ProjectReference Include="..\..\packages\Osu.Protocol\Osu.Protocol.csproj" />
    <ProjectReference Include="..\..\packages\Osu.Services\Osu.Services.csproj" />
    <ProjectReference Include="..\..\packages\Osu.State\Osu.State.csproj" />
    <ProjectReference Include="..\..\packages\Osu.Infrastructure\Osu.Infrastructure.csproj" />
  </ItemGroup>
</Project>
```

### F.3 ASP.NET Core の採用

C# の Web フレームワーク選定は事実上 **ASP.NET Core 一択**。これは Microsoft 公式かつ業界標準で、他の選択肢(NancyFx, ServiceStack 等)は採用例が大幅に少ない。

ASP.NET Core が bancho サーバー用途に適している理由:

1. **SignalR がフレームワーク標準**: lazer の SignalR ハブを互換性問題なしに実装
2. **依存性注入が組み込み**: `Microsoft.Extensions.DependencyInjection` を全コンポーネントで統一的に使用
3. **ミドルウェアパイプライン**: Python の Starlette と同様の薄い middleware 層
4. **WebSocket サポートが組み込み**: 自前実装不要
5. **Minimal API**(.NET 6+): FastAPI ライクな宣言的 API 定義
6. **MVC / Controllers**: 大規模 API に向く、属性ベースの宣言的記述
7. **gRPC が標準サポート**: 設計書 Stage 4 のサービス間通信にそのまま使える
8. **Kestrel サーバー**: 高性能な ASGI 相当(HTTP/2, HTTP/3 対応)

#### F.3.1 Minimal API スタイル(FastAPI 風)

軽量な REST API なら Minimal API:

```csharp
// apps/Osu.Api.Host/Program.cs
var builder = WebApplication.CreateBuilder(args);

builder.Services.AddOsuServerServices(builder.Configuration);
builder.Services.AddRedis(builder.Configuration);
builder.Services.AddDbContext<OsuDbContext>(opts => opts.UseNpgsql(...));

var app = builder.Build();

app.MapGet("/api/v2/users/{id:long}", async (
    long id,
    IUserService userService,
    CancellationToken ct) =>
{
    var user = await userService.FindByIdAsync(new UserId(id), ct);
    return user is null
        ? Results.NotFound()
        : Results.Ok(UserResponse.From(user));
});

app.MapPost("/api/v2/beatmaps/{beatmapId:long}/solo/scores", async (
    long beatmapId,
    LazerScoreSubmission submission,
    [FromServices] IScoringService scoring,
    HttpContext context,
    CancellationToken ct) =>
{
    var user = context.GetCurrentUser();
    var score = await scoring.SubmitLazerScoreAsync(submission, user.Id, ct);
    return Results.Ok(score);
});

app.Run();
```

これは FastAPI の `@app.get("/users/{id}")` とほぼ同じ書き心地。

#### F.3.2 Controller スタイル(大規模 API 向け)

複雑な API は伝統的な Controller で:

```csharp
[ApiController]
[Route("api/v2/users")]
public class UsersController : ControllerBase
{
    private readonly IUserService _userService;

    public UsersController(IUserService userService)
    {
        _userService = userService;
    }

    [HttpGet("{id:long}")]
    public async Task<ActionResult<UserResponse>> GetUser(
        long id,
        CancellationToken ct)
    {
        var user = await _userService.FindByIdAsync(new UserId(id), ct);
        return user is null
            ? NotFound()
            : Ok(UserResponse.From(user));
    }

    [HttpGet("me")]
    [Authorize]
    public async Task<ActionResult<UserResponse>> GetCurrentUser(
        CancellationToken ct)
    {
        var user = await _userService.FindByIdAsync(User.GetUserId(), ct);
        return Ok(UserResponse.From(user!));
    }
}
```

#### F.3.3 OpenAPI 自動生成

NSwag または Swashbuckle で OpenAPI スキーマを自動生成:

```csharp
builder.Services.AddSwaggerGen(c =>
{
    c.SwaggerDoc("v2", new OpenApiInfo { Title = "osu! API v2 compatible" });
});

app.UseSwagger();
app.UseSwaggerUI();
```

これで `/swagger` から FastAPI と同等の対話的 API ドキュメントが提供される。

### F.4 bancho ハンドラ用 attribute と source generator の設計

C# の attribute は Python のデコレーターと意味的に同じ機能。 **源泉ジェネレーター(source generator)** と組み合わせると、コンパイル時にハンドラ登録コードを自動生成できる(Rust の proc-macro 相当)。

#### F.4.1 目指す書き心地

```csharp
// transports/bancho/Handlers/ChatHandlers.cs
public static class ChatHandlers
{
    [BanchoHandler(
        ClientPacketId.SendPublicMessage,
        RateLimit = "10/5s")]
    public static async Task HandleSendPublicMessage(
        SendPublicMessageC2S packet,
        [CurrentPlayer] Player player,
        [FromServices] IChatService chat,
        CancellationToken ct)
    {
        await chat.SendMessageAsync(player.Id, packet.Target, packet.Message, ct);
    }
}
```

これは Python のデコレーター版とほぼ等価。`[CurrentPlayer]` と `[FromServices]` は ASP.NET Core の DI と統合された属性ベースの引数解決。

#### F.4.2 source generator が生成するコード

`[BanchoHandler]` 属性を付けたメソッドに対して、コンパイル時に以下のような登録コードが自動生成される:

```csharp
// 自動生成されるコード(概念)
public static class GeneratedBanchoHandlers
{
    public static void RegisterAll(BanchoHandlerRegistry registry)
    {
        registry.Register(ClientPacketId.SendPublicMessage, new HandlerSpec
        {
            Handler = async (rawPayload, ctx, ct) =>
            {
                var packet = SendPublicMessageC2S.Parse(rawPayload);
                var player = ctx.GetCurrentPlayer();
                var chat = ctx.Services.GetRequiredService<IChatService>();
                await ChatHandlers.HandleSendPublicMessage(packet, player, chat, ct);
            },
            RateLimit = RateLimit.Parse("10/5s"),
            RequiresAuth = true,
        });

        // 他の [BanchoHandler] 付きメソッドも同様に登録
    }
}
```

起動時にこれを呼べばすべてのハンドラが登録される:

```csharp
// apps/Osu.Bancho.Host/Program.cs
var registry = new BanchoHandlerRegistry();
GeneratedBanchoHandlers.RegisterAll(registry);
builder.Services.AddSingleton(registry);
```

#### F.4.3 source generator プロジェクトの構造

```
packages/Osu.Protocol.Generators/
├── Osu.Protocol.Generators.csproj
└── BanchoHandlerGenerator.cs        # IIncrementalGenerator 実装
```

`Osu.Protocol.Generators.csproj`:

```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>netstandard2.0</TargetFramework>
    <IsRoslynComponent>true</IsRoslynComponent>
    <EnforceExtendedAnalyzerRules>true</EnforceExtendedAnalyzerRules>
  </PropertyGroup>

  <ItemGroup>
    <PackageReference Include="Microsoft.CodeAnalysis.CSharp" Version="4.8.0" />
  </ItemGroup>
</Project>
```

実装は概ね 300〜500 行程度。 **Rust の proc-macro 自作と同じくらいの労力** だが、Roslyn の API は安定しており、エコシステムも充実している(StackOverflow の質問数も Rust proc-macro より多い)。

#### F.4.4 バイナリパースも source generator で

bancho パケット定義も同様に source generator で扱える。Caterpillar の C# 版を自作するイメージ。

```csharp
[BanchoPacket]
public partial record SendPublicMessageC2S(
    BanchoString Sender,
    BanchoString Message,
    BanchoString Target,
    int SenderId);

// source generator が以下のメソッドを自動生成
public partial record SendPublicMessageC2S
{
    public static SendPublicMessageC2S Parse(ReadOnlySpan<byte> bytes) { /* ... */ }
    public byte[] Pack() { /* ... */ }
}
```

`partial record` と source generator の組み合わせで、 **Caterpillar 並みの宣言的バイナリ定義** が実現できる。これは C# 9+ の機能を活用した現代的なアプローチ。

### F.5 各レイヤーの実装方針

設計書セクション 8 の各機構を C# で実装する場合の方針を示す。

#### F.5.1 StateStore（Valkey 集約）

interface(C# の慣習でプレフィックス `I`)と StackExchange.Redis による実装（Redis プロトコル互換）:

```csharp
// packages/Osu.State/Interfaces/ISessionStore.cs
public interface ISessionStore
{
    Task<Token> CreateAsync(UserId userId, ClientType clientType, CancellationToken ct = default);
    Task<Session?> GetAsync(Token token, CancellationToken ct = default);
    Task TouchAsync(Token token, CancellationToken ct = default);
    Task DeleteAsync(Token token, CancellationToken ct = default);
    Task<IReadOnlyList<UserId>> ListOnlineUserIdsAsync(CancellationToken ct = default);
}

// packages/Osu.State/Redis/RedisSessionStore.cs
public class RedisSessionStore : ISessionStore
{
    private readonly IConnectionMultiplexer _redis;

    public RedisSessionStore(IConnectionMultiplexer redis)
    {
        _redis = redis;
    }

    public async Task<Token> CreateAsync(
        UserId userId,
        ClientType clientType,
        CancellationToken ct = default)
    {
        var token = Token.Generate();
        var db = _redis.GetDatabase();
        var batch = db.CreateBatch();

        var sessionKey = $"session:{token.Value}";
        var userSessionKey = $"user_session:{userId.Value}";

        _ = batch.HashSetAsync(sessionKey, new HashEntry[]
        {
            new("user_id", userId.Value),
            new("client_type", clientType.ToString()),
            new("created_at", DateTimeOffset.UtcNow.ToUnixTimeSeconds()),
        });
        _ = batch.KeyExpireAsync(sessionKey, TimeSpan.FromHours(2));
        _ = batch.StringSetAsync(userSessionKey, token.Value, TimeSpan.FromHours(2));
        _ = batch.SortedSetAddAsync("online_users",
            userId.Value,
            DateTimeOffset.UtcNow.ToUnixTimeSeconds());

        batch.Execute();
        await Task.WhenAll(batch.WaitAll(ct));

        return token;
    }

    // 他のメソッドも同様
}
```

`Microsoft.Extensions.DependencyInjection` で登録:

```csharp
services.AddSingleton<ISessionStore, RedisSessionStore>();
services.AddSingleton<IPresenceStore, RedisPresenceStore>();
services.AddSingleton<IChannelStateStore, RedisChannelStateStore>();
// ...
```

#### F.5.2 EventBus

```csharp
// packages/Osu.Infrastructure/Messaging/IEventBus.cs
public interface IEventBus
{
    Task PublishAsync<TEvent>(TEvent @event, CancellationToken ct = default)
        where TEvent : class;

    void Subscribe<TEvent>(Func<TEvent, CancellationToken, Task> handler)
        where TEvent : class;
}

// 実装(Valkey Pub/Sub、Redis プロトコル互換)
public class RedisPubSubEventBus : IEventBus
{
    private readonly IConnectionMultiplexer _redis;
    private readonly ConcurrentDictionary<Type, List<Delegate>> _handlers = new();

    public async Task PublishAsync<TEvent>(TEvent @event, CancellationToken ct = default)
        where TEvent : class
    {
        var channel = typeof(TEvent).FullName!;
        var payload = MessagePackSerializer.Serialize(@event);
        await _redis.GetSubscriber().PublishAsync(
            RedisChannel.Literal(channel), payload);
    }

    // Subscribe は購読タスクを起動する
}

// イベント定義(record で immutable)
public record MessageSentEvent(
    long MessageId,
    string ChannelName,
    long SenderId,
    string Content);
```

C# 9+ の `record` 型は Python の `@dataclass(frozen=True)` と等価。

#### F.5.3 JobQueue: Hangfire または Coravel

C# の主要なジョブキューライブラリは Hangfire と Coravel。bancho サーバー用途では:

- **Hangfire**: 機能豊富、Web UI 付き、Redis プロトコル / SQL バックエンド対応、taskiq の C# 版に相当
- **Coravel**: 軽量、シンプル、in-process 中心

Redis Streams ベースの JobQueue が必要なら Hangfire を推奨。

```csharp
// apps/Osu.Worker.Host/Program.cs
var builder = Host.CreateApplicationBuilder(args);

builder.Services.AddHangfire(config => config
    .UseRedisStorage(builder.Configuration["Redis:ConnectionString"]));

builder.Services.AddHangfireServer(options =>
{
    options.ServerName = "score-processing-worker";
    options.Queues = ["score-processing", "achievements", "default"];
    options.WorkerCount = 20;
});

builder.Services.AddScoped<IScoringService, ScoringService>();
builder.Services.AddScoped<IPpCalculator, PpCalculator>();

var host = builder.Build();
await host.RunAsync();
```

```csharp
// packages/Osu.Infrastructure/Jobs/ScoreProcessingJob.cs
public class ScoreProcessingJob
{
    private readonly IScoringService _scoringService;

    public ScoreProcessingJob(IScoringService scoringService)
    {
        _scoringService = scoringService;
    }

    [Queue("score-processing")]
    [AutomaticRetry(Attempts = 3)]
    public async Task ProcessScore(long scoreId)
    {
        if (await _scoringService.IsScoreProcessedAsync(scoreId))
            return; // 冪等性保証

        await _scoringService.CalculateAndPersistPpAsync(scoreId);
        await _scoringService.UpdateLeaderboardsAsync(scoreId);
        await _scoringService.UpdateUserStatisticsAsync(scoreId);
        await _scoringService.MarkScoreProcessedAsync(scoreId);
    }
}
```

呼び出し側:

```csharp
// services/Scoring/ScoringService.cs
public class ScoringService : IScoringService
{
    private readonly IBackgroundJobClient _jobs;
    private readonly IScoreRepository _scoreRepo;
    private readonly IEventBus _eventBus;

    public async Task<Score> SubmitLazerScoreAsync(
        LazerScoreSubmission submission,
        UserId userId,
        CancellationToken ct)
    {
        // 同期処理: DB に永続化
        var score = await _scoreRepo.SaveAsync(submission, userId, ct);

        // クリティカル処理は JobQueue 経由
        _jobs.Enqueue<ScoreProcessingJob>(j => j.ProcessScore(score.Id.Value));
        _jobs.Enqueue<AchievementJob>(j => j.CheckAchievements(userId.Value, score.Id.Value));

        // ロス許容な通知は EventBus
        await _eventBus.PublishAsync(new ScoreSubmittedNotice(
            score.Id.Value, userId.Value), ct);

        return score;
    }
}
```

設計書セクション 8.9.3 のスコア送信3層パターン(同期 + JobQueue + EventBus)がそのまま C# で表現できる。

### F.6 SignalR ハブのネイティブ実装(C# 固有の強み)

C# 版実装の **最大の戦略的優位** は、lazer の SignalR ハブを互換性問題なしに実装できること。osu-server-spectator のコードを直接参照・派生実装できる。

#### F.6.1 osu-server-spectator のソース構造をそのまま流用

osu-server-spectator は `Microsoft.AspNetCore.SignalR.Hub<TClient>` を継承する形で実装されている。これを同じパターンで作成する:

```csharp
// apps/Osu.Signalr.Host/Hubs/SpectatorHub.cs
public class SpectatorHub : Hub<ISpectatorClient>, ISpectatorServer
{
    private readonly ISpectatorService _spectatorService;
    private readonly IUserStateService _userState;

    public SpectatorHub(
        ISpectatorService spectatorService,
        IUserStateService userState)
    {
        _spectatorService = spectatorService;
        _userState = userState;
    }

    public async Task BeginPlaySession(long scoreToken, SpectatorState state)
    {
        var userId = Context.GetUserId();
        await _spectatorService.BeginPlaySessionAsync(userId, scoreToken, state);

        // 観戦者全員に通知
        await Clients.Group(GetSpectatorGroup(userId))
            .UserBeganPlaying(userId, state);
    }

    public async Task SendFrameData(FrameDataBundle data)
    {
        var userId = Context.GetUserId();
        await Clients.Group(GetSpectatorGroup(userId))
            .UserSentFrames(userId, data);
    }

    public async Task EndPlaySession(SpectatorState state)
    {
        var userId = Context.GetUserId();
        await _spectatorService.EndPlaySessionAsync(userId);
        await Clients.Group(GetSpectatorGroup(userId))
            .UserFinishedPlaying(userId, state);
    }

    public override async Task OnConnectedAsync()
    {
        await _userState.MarkOnlineAsync(Context.GetUserId(), ClientType.Lazer);
        await base.OnConnectedAsync();
    }

    public override async Task OnDisconnectedAsync(Exception? exception)
    {
        await _userState.MarkOfflineAsync(Context.GetUserId(), ClientType.Lazer);
        await base.OnDisconnectedAsync(exception);
    }

    private static string GetSpectatorGroup(int userId) => $"spectator:{userId}";
}
```

これは osu-server-spectator の `SpectatorHub.cs` と **同じ構造、同じ API、同じシリアライゼーション形式**。lazer クライアントから見れば完全に互換。

#### F.6.2 Multiplayer Hub と Metadata Hub も同様

```csharp
public class MultiplayerHub : Hub<IMultiplayerClient>, IMultiplayerServer
{
    public async Task<MultiplayerRoom> JoinRoom(long roomId, string? password = null)
    {
        // osu-server-spectator と同じインターフェース
    }

    // ChangeSettings、StartMatch、TransferHost など
}

public class MetadataHub : Hub<IMetadataClient>, IMetadataServer
{
    public async Task<UserPresence> GetUserPresence(int userId)
    {
        // ...
    }

    public async Task UpdateActivity(UserActivity? activity)
    {
        // ...
    }
}
```

3つのハブすべて、osu-server-spectator の公開コードをリファレンスとして実装できる。 **これは他言語実装では絶対に到達できないレベルの互換性**。

#### F.6.3 Valkey backplane で水平スケール

複数の signalr-host インスタンスをロードバランスする場合、SignalR の Redis プロトコル互換 backplane を使う（Valkey に接続）:

```csharp
builder.Services.AddSignalR()
    .AddMessagePackProtocol()
    .AddStackExchangeRedis(builder.Configuration["Redis:ConnectionString"], options =>
    {
        options.Configuration.ChannelPrefix = RedisChannel.Literal("osu-signalr");
    });
```

これで複数の signalr プロセスが Valkey 経由でメッセージを共有でき、トランスポートの水平スケールが完成する。

### F.7 PP 計算(osu-tools との直接統合)

C# 版の **第二の戦略的優位** は、osu-tools(公式 PP 計算ツール)をライブラリとして直接統合できること。

#### F.7.1 osu-tools の参照方法

osu-tools は GitHub に公開されているが、NuGet パッケージとしては配布されていない。以下のいずれかで統合する:

- **Git サブモジュール**: `osu-tools` を `external/osu-tools` にサブモジュールとして配置、必要なプロジェクトを `.csproj` で参照
- **ローカルビルド + private NuGet feed**: osu-tools をビルドして社内 NuGet サーバーにアップロード
- **`osu.Game.Rulesets.*` プロジェクトを直接参照**: osu! 本家のリポジトリから必要なプロジェクトだけ参照

#### F.7.2 PP 計算の実装

```csharp
// packages/Osu.Services/Scoring/PpCalculator.cs
using osu.Game.Beatmaps;
using osu.Game.Rulesets;
using osu.Game.Rulesets.Catch;
using osu.Game.Rulesets.Mania;
using osu.Game.Rulesets.Osu;
using osu.Game.Rulesets.Taiko;
using osu.Game.Scoring;

public class PpCalculator : IPpCalculator
{
    private readonly IBeatmapStorage _beatmapStorage;

    public PpCalculator(IBeatmapStorage beatmapStorage)
    {
        _beatmapStorage = beatmapStorage;
    }

    public async Task<double> CalculateAsync(Score score, CancellationToken ct = default)
    {
        var beatmap = await _beatmapStorage.GetWorkingBeatmapAsync(score.BeatmapMd5, ct);
        var ruleset = GetRuleset(score.RulesetId);

        var scoreInfo = new ScoreInfo
        {
            BeatmapInfo = beatmap.BeatmapInfo,
            Ruleset = ruleset.RulesetInfo,
            Mods = ConvertMods(score.Mods, ruleset),
            Accuracy = score.Accuracy,
            MaxCombo = score.MaxCombo,
            Statistics = ConvertStatistics(score.Statistics),
        };

        var difficulty = ruleset
            .CreateDifficultyCalculator(beatmap)
            .Calculate(scoreInfo.Mods);

        var performance = ruleset
            .CreatePerformanceCalculator()!
            .Calculate(scoreInfo, difficulty);

        return performance.Total;
    }

    private Ruleset GetRuleset(int rulesetId) => rulesetId switch
    {
        0 => new OsuRuleset(),
        1 => new TaikoRuleset(),
        2 => new CatchRuleset(),
        3 => new ManiaRuleset(),
        _ => throw new ArgumentException($"Unknown ruleset: {rulesetId}"),
    };
}
```

これは **本家の PP 計算ロジックを直接使う** ため、 **数値一致が完全に保証される**。Rust の rosu-pp は本家との一致を再現実装で頑張っているのに対し、C# 版は **本家そのもの**。

仕様変更やアップデートに追従するときも、osu-tools のサブモジュールを更新するだけ。ライブラリ作者の独立した実装に依存しない。

#### F.7.3 ジョブからの呼び出し

```csharp
public class ScoreProcessingJob
{
    private readonly IPpCalculator _ppCalculator;
    private readonly IScoreRepository _scoreRepo;

    public async Task ProcessScore(long scoreId)
    {
        var score = await _scoreRepo.FindByIdAsync(new ScoreId(scoreId))
            ?? throw new InvalidOperationException($"Score {scoreId} not found");

        var pp = await _ppCalculator.CalculateAsync(score);
        await _scoreRepo.UpdatePpAsync(score.Id, pp);

        // リーダーボード更新、メダル付与判定など
    }
}
```

### F.8 Native AOT によるシングルバイナリ運用

.NET 8+ の Native AOT(Ahead-of-Time)コンパイルで、 **完全なシングル実行可能ファイル** を生成できる。これは Rust の `cargo build --release` と同等の体験。

#### F.8.1 Native AOT の有効化

`.csproj` で:

```xml
<PropertyGroup>
  <PublishAot>true</PublishAot>
  <StripSymbols>true</StripSymbols>
  <InvariantGlobalization>true</InvariantGlobalization>
</PropertyGroup>
```

ビルド:

```bash
dotnet publish -c Release -r linux-x64 -o ./publish/bancho
```

出力される実行ファイルは:
- **サイズ**: 10〜30 MB(ランタイム同梱)
- **起動**: 数十 ms(JIT より圧倒的に速い)
- **メモリ**: 数十 MB(JIT より大幅に少ない)
- **依存**: ゼロ(scratch ベースの Docker イメージで動く)

```dockerfile
FROM scratch
COPY ./publish/bancho /bancho
ENTRYPOINT ["/bancho"]
```

#### F.8.2 Native AOT の制約

Native AOT は強力だが、いくつかの制約がある:

- **リフレクションが制限される**: 多くのライブラリが動的型生成を使っており、AOT で動かないことがある
- **動的アセンブリロードができない**: プラグインアーキテクチャは困難
- **JIT 最適化されない**: ピーク性能は通常の JIT より若干低いことがある
- **EF Core の一部機能が AOT 非対応**: query compilation の制約

これらを回避するため、 **source generator ベースの代替が用意されている**:

- JSON: `System.Text.Json` の source generator
- DI: `[ServiceRegistration]` 属性
- EF Core: AOT 対応の compiled queries

bancho サーバー実装では **source generator ベースで全レイヤーを書く** ことで、Native AOT の利点を最大限享受できる。`Osu.Protocol.Generators` のような独自 source generator もこの方針と一致する。

#### F.8.3 段階的な AOT 対応

最初から AOT 完全対応を目指すと工数が膨らむ。 **JIT モードで動かしつつ、徐々に AOT 化を進める** のが現実的:

1. Phase 1: JIT モードで開発、機能完成を優先
2. Phase 2: `PublishReadyToRun=true` で部分的 AOT
3. Phase 3: `PublishAot=true` で完全 AOT、AOT 警告を1つずつ解消

### F.9 制約とトレードオフ

C# 版を採用する際の制約:

#### F.9.1 osu! private server コミュニティでの実績の少なさ

BanchoNET というプロジェクトが C# 実装を進めているが、bancho.py のような大規模 community 実装には至っていない。 **新しい道を切り拓く立場** になる。

ただし「本家と同言語」の戦略的価値は、コミュニティ拡大にとって追い風になる可能性もある。 **osu! クライアント開発者がそのまま貢献できる** ため、長期的には貢献者が集まる潜在性がある。

#### F.9.2 Linux 中心のコミュニティでの心理的障壁

私は前回も触れたが、 **「C# は Windows」というステレオタイプ** がまだ強い。実際は .NET Core 以降 Linux ファーストで運用可能で、Docker 統合も問題ないが、Python / Rust 文化のコミュニティでは採用を躊躇させる要素となる。

これは技術的な問題ではなく文化的な問題で、 **時間をかけて誤解を解く** 必要がある。

#### F.9.3 大規模なライブラリ依存

ASP.NET Core 一式は機能豊富だが、 **エコシステム全体のサイズが大きい**。Rust の axum + 必要なものだけ追加するミニマリスティックなアプローチとは対照的。

ただし Native AOT で不要なコードはトリミングされるため、配布サイズの問題は最終的には解消される。

#### F.9.4 Microsoft 依存への懸念

.NET 自体は MIT で完全オープン、Linux Foundation 配下の .NET Foundation で管理されているが、 **Microsoft の戦略変更でエコシステムが揺れる可能性** は残る。歴史的な信頼の問題で、特にコミュニティ寄りの開発文化では躊躇要因となる。

実際には .NET の OSS 化以降は安定しており、過度な懸念は不要。

#### F.9.5 ビルド時間とディスク容量

`dotnet restore` は npm や pip より遅く、 `.csproj` の依存解決に時間がかかる。 **CI でのフルビルドは Rust よりは速いが、Python よりは遅い**。

ディスク容量も `obj/` `bin/` が肥大化しやすい。

#### F.9.6 IDE 体験の差

Visual Studio / JetBrains Rider は世界最強の C# IDE 体験を提供するが、 **VSCode + C# Dev Kit** はまだ機能差がある。Python の VSCode 体験ほど洗練されていない。

無料の選択肢としては JetBrains Rider が 2024 年から個人利用無料化したので、これが事実上のデファクト。

### F.10 C# 版を選ぶべきシナリオ

以下のいずれかに該当する場合、C# 版を本気で検討する価値がある。

- **lazer の完全互換性を最優先したい**: SignalR ハブを本家と完全互換で実装したい
- **PP 計算の数値一致を厳密に保証したい**: osu-tools の直接統合で本家ロジックを使う
- **本家コードベースから派生実装を作りたい**: osu-server-spectator のソースを直接参照
- **C# / .NET の経験がある開発者がチームにいる**: 学習コストを抑えられる
- **シングルバイナリ運用と高性能を両立したい**: Native AOT で実現
- **エンタープライズグレードの IDE 体験を求める**: Rider / Visual Studio
- **依存性注入が組み込まれたフレームワークが欲しい**: 自前 DI コンテナ不要

逆に、以下の場合は Python 版を選ぶべき:

- **数ヶ月以内に動くものが必要**
- **既存の Python 製 osu! ライブラリを最大活用したい**
- **小規模 private server で開始したい**
- **コミュニティの主流(bancho.py 等)に合わせたい**
- **C# 文化に馴染みがないチーム**

### F.11 Rust 版との比較

C# 版と Rust 版(付録 E)は、 **どちらも「性能と書き心地の両立」を狙う代替実装** だが、最適化する側面が異なる。

| 観点 | C# 版 | Rust 版 |
|---|---|---|
| 性能 | ◎(Native AOT)、JIT モードでも十分速い | ◎(Native、最速) |
| 書き心地 | ◎(attribute、modern C#) | ◯(proc-macro 自作)|
| 本家との互換性 | **◎(SignalR ネイティブ、osu-tools 統合)** | △(rosu-pp は再実装) |
| シングルバイナリ | ◎(Native AOT) | ◎(cargo build) |
| 起動時間 | ◯(JIT)〜 ◎(AOT) | ◎ |
| メモリ消費 | ◯(GC)〜 ◎(AOT) | ◎ |
| 開発速度 | ◎(LINQ、async/await、DI 内蔵) | △(所有権) |
| エコシステム | ◎(成熟、巨大) | ◎(成長中) |
| 学習コスト | ◯ | △(難) |
| OSS コミュニティ親和性 | △(歴史的に Windows 中心の印象) | ◯ |
| osu! 採用実績 | △(BanchoNET) | △(Peace) |
| 自前ライブラリの必要性 | source generator(.NET 標準機能) | proc-macro(やや高度) |

**「lazer 完全互換性 + 本家ロジックの正確性」を最優先する場合 → C# 版**
**「シンプルなトランスポート + ピーク性能」を最優先する場合 → Rust 版**

どちらも有力で、 **C# は戦略的価値、Rust は技術的純度** の対比となる。

### F.12 設計書本体との関係

本付録の C# 実装も、 **同じ設計思想を別言語で再現したもの** である。以下が共通する。

- ドメインモデル(Player, Score, Channel, Match)
- bancho プロトコル仕様(C2S/S2C パケット定義)
- レイヤー構造(transports / services / domain / repositories / infrastructure)
- StateStore / EventBus / JobQueue の3軸インフラ抽象
- クリティカル処理の JobQueue 化原則
- 段階的進化パス(Stage 1〜7)

異なるのは実装言語と、それに伴う具体的なライブラリ・パターン選択のみ。

実装プロジェクトとしての位置づけは、本設計書では以下のように整理する。

| 実装 | 立場 | 強み |
|---|---|---|
| Python 版(本体) | **本流推奨** | バランス、開発速度、コミュニティ |
| Rust 版(付録 E) | **代替: 性能重視** | ピーク性能、シングルバイナリ純度 |
| C# 版(本付録) | **代替: 本家互換性重視** | SignalR ネイティブ、osu-tools 統合 |
| TypeScript / Cloudflare 版(付録 D) | **代替: サーバーレス前提** | グローバル分散、運用負荷ゼロ |

これらは排他的ではなく、 **目的に応じて選ぶ** か、 **複数を並行運用する** ことも可能。例えば「Python を本流とし、SignalR 部分だけ C# で別プロセス」というハイブリッド構成も成立する(Stage 4 のサービス分離と組み合わせると自然)。

### F.13 補足: なぜ Kotlin / Java を本付録の対象としないか

JVM 系言語(Kotlin、Java)は技術的には bancho サーバー実装に使えるが、 **本設計書では付録化しない** ことを決定した。理由を意思決定として記録する。

- **本家との互換性アドバンテージがない**: SignalR は ASP.NET Core 由来であり、Kotlin から完全互換実装するのは C# より困難。osu-tools の JVM 統合も JNI 経由で複雑
- **言語固有の特異な強みが薄い**: 性能は Rust に劣り、書き心地は Python に劣り、互換性は C# に劣る。「JVM である」こと自体が決定的な利点とならない
- **bancho サーバーの採用実績がない**: Kotlin / Java で書かれた bancho 互換サーバーはコミュニティに存在しない
- **GC 言語としては C# が同等以上**: GC の選択肢は C# と Kotlin で同等で、ランタイム性能も拮抗。あえて JVM を選ぶ戦略的理由が見つからない

ただし以下の特殊な状況では Kotlin / Java 採用が合理的になりうる:

- 既存の JVM ベースのインフラを流用したい(認証基盤、監視ツール等)
- チームが Kotlin / Java に強く習熟しており、C# 移行コストを避けたい
- Android クライアント開発と統合したい(Kotlin の場合)

これらの特殊条件下では、本付録 F の C# 実装ガイドを Kotlin に翻訳する形で実装することは可能。Ktor + Kotlin Coroutines + Exposed(ORM)+ Hoplite(設定)+ Lettuce(Redis)+ Quartz(JobQueue)というスタックで、設計書の構造をそのまま再現できる。

JVM 採用を検討する場合の参考として位置づける。

---

## 付録 G: 言語別バイナリパースライブラリのカタログ

本付録は、各言語におけるバイナリパースライブラリの選択肢を網羅的にカタログ化したものである。本設計書本体および付録 D / E / F では各言語の代表的なライブラリ(Caterpillar、binrw、source generator 自作、restructure)を採用しているが、 **「他にどんな選択肢があり、なぜ選ばなかったか」** を体系的に記録することで、将来の実装判断の参考となる。

参考リポジトリとして [dloss/binary-parsing](https://github.com/dloss/binary-parsing)(Awesome Binary Parsing)が、言語横断的なカタログとして優秀。本付録はこれを bancho サーバー実装の観点から整理したものである。

### G.1 Python のバイナリパースライブラリ

| ライブラリ | 採用判断 | 特徴 |
|---|---|---|
| **Caterpillar** | **採用(設計書本体)** | Python 3.12+ の型アノテーションを DSL として使用、双方向(parse + build)、動的長・bitfield・条件付きフィールド対応 |
| Construct | 不採用 | API が古め、Caterpillar の前世代相当、ただし枯れていて安定 |
| Hachoir | 不採用 | バイナリストリームをフィールド単位で view・edit、多数のフォーマット用パーサーが付属(リバースエンジニアリング向け) |
| Mr. Crowbar | 不採用 | Django 的な model framework、CLI ツール付き、ファイル形式の可視化に強い |
| dissect.cstruct | 不採用 | C 言語風の構造定義、Fox-IT 製、デジタルフォレンジック向け |
| Scapy | 不採用 | ネットワークパケット送受信に特化、bancho プロトコル全体に使うには大げさ |
| 標準 `struct` モジュール | 不採用 | 可変長フィールド・条件付きフィールドの表現が弱い |
| ctypes | 不採用 | C 構造体相互運用向けで、bancho プロトコル全体には不向き |

**Caterpillar 採用の理由(他選択肢との対比で補強)**:

- **型ヒント統合**: 他のライブラリは独自 DSL(Construct の `Struct("field" / Int32ul)` 等)を使うが、Caterpillar は Python 3.12+ の型アノテーションをそのまま使える。型チェッカーとの統合が自然
- **双方向対応**: Caterpillar、Construct、Mr. Crowbar、dissect.cstruct は parse + build の両方をサポート。Kaitai Struct は read-only なので bancho サーバー用途には不適合
- **現代的な設計**: 2023 年以降にメンテナンスされており、Python の最新機能を活用
- **依存の軽さ**: Hachoir は多数のフォーマットを内蔵していて重量級、Scapy はネットワーク全般向けで大げさ

Construct を「Caterpillar が Python 3.12+ で困った時の代替候補」として位置づけるのは妥当だが、現時点では Caterpillar の選定で問題ない。

### G.2 Rust のバイナリパースライブラリ

| ライブラリ | 採用判断 | 特徴 |
|---|---|---|
| **binrw** | **採用(付録 E)** | derive macro、ストリーム I/O ベース、双方向、エルゴノミクス重視 |
| Deku | 有力代替 | bit-level の表現力に特化、symmetric serialization、derive macro |
| scroll | 不採用 | 軽量、Pread/Pwrite trait、低レベル、derive 対応 |
| Nom | 不採用 | パーサーコンビネータ、関数ベース、テキスト/バイナリ両対応 |
| winnow | 不採用 | Nom のフォーク、改善版、エラーメッセージが優秀、アクティブメンテ |

**binrw vs Deku の比較**(Rust 採用時の主要な判断ポイント):

| 観点 | binrw | Deku |
|---|---|---|
| マクロ駆動 | derive + attribute | derive + attribute |
| ストリーム I/O | `BinRead`/`BinWrite` で Reader/Writer ベース | `Read`/`Write` ベース |
| bit-level の表現力 | ◯(`#[br(map = ...)]` 等で工夫) | ◎(`#[deku(bits = 3)]` で直接表現) |
| エラーメッセージ | 良 | 良 |
| 学習リソース | 多 | 中 |

bancho プロトコルは **byte-aligned のフィールドが大半** で、bit-level の細かい操作が必要な場面は限定的(mods bitfield 程度)。そのため binrw で十分。Deku は通信プロトコル全体が bit-packed な場合(low-level network protocol 等)に最大の威力を発揮する。

**Nom / winnow** はパーサーコンビネータ系で、 **読み取り専用** に特化。bancho サーバーは双方向(S2C パケットのシリアライズも必要)が必要なので、derive 系の binrw / Deku が適合する。

**scroll** は最軽量だが derive のエルゴノミクスは binrw / Deku に劣る。性能重視のホットパス専用クレートという位置づけ。

### G.3 TypeScript / JavaScript のバイナリパースライブラリ

| ライブラリ | 採用判断 | 特徴 |
|---|---|---|
| **restructure** | **付録 D で言及** | declarative、双方向、C-like 構造・ポインタ・配列・bitfield・カスタム型対応、fontkit / pdfkit が使用 |
| Binary-parser | 代替候補 | declarative、効率的なパーサー生成、シンプルな API |
| Binpat | 検討候補 | declarative patterns、新しめ |
| jBinary | 不採用 | 高レベル API、メンテ停滞気味 |
| DataView / Uint8Array 直接操作 | 最終手段 | 標準 API、宣言性ゼロ |

**人気度の現実**:

JavaScript 系では **「GitHub スター数」と「npm ダウンロード数」で人気ライブラリが異なる** という興味深い現象がある。

- **GitHub スター数**: Binary-parser が最も多い(declarative API のシンプルさで初学者人気)
- **npm ダウンロード数**: restructure が最大(fontkit / pdfkit といった著名なパッケージが依存しているため、実運用での採用が多い)

この乖離は「学習者の関心が向くライブラリ」と「実プロジェクトで採用されるライブラリ」のズレを示している。本設計書の付録 D で restructure を推奨したのは **実運用での採用実績** を重視したためで、この判断は npm ダウンロード数の傾向と一致する。

ただし bancho サーバーのような **新規開発で書き心地を最優先する** 場合、Binary-parser の declarative API の方が好まれる可能性もある。両方を試して比較するのが現実的。

**現実的な選定指針**:

- Cloudflare Workers / Bun + Elysia / Node.js での新規実装: restructure(実績重視)または Binary-parser(API のシンプルさ)
- 既存プロジェクトの拡張: 既に使われているライブラリに合わせる(fontkit 系なら restructure、独立プロジェクトなら自由)
- パフォーマンス最優先: 自前で DataView / Uint8Array を扱う(ただし保守性は犠牲になる)

TypeScript エコシステムでは、Caterpillar や binrw ほど洗練された宣言的体験は **現時点では存在しない**(2024 年時点)。これは設計書本体で言及した通り。ただし「全く存在しない」わけではなく、 **restructure や Binary-parser で実用的なバイナリパーサーは構築可能**。

### G.4 C# / .NET のバイナリパースライブラリ

C# / .NET エコシステムの特殊事情として、 **汎用バイナリパースライブラリが薄い** という現実がある。dloss/binary-parsing のカタログにも C# / .NET のセクションが存在しないことが、この現実を裏付けている。

| アプローチ | 評価 | 用途 |
|---|---|---|
| **自作 source generator(Roslyn)** | **採用(付録 F)** | Caterpillar や binrw 相当の宣言的体験を自前で実現 |
| 標準 `BinaryReader` / `BinaryWriter` | 低レベルだが標準 | 単発の小さなパース、付録 F でも併用 |
| `System.Buffers` / `Span<byte>` | 現代的、高性能 | ホットパスの最適化 |
| MemoryPack | 独自フォーマット用 | 高性能シリアライズだが独自バイナリフォーマット |
| MessagePack-CSharp | 標準フォーマット用 | MessagePack 用、bancho プロトコルには使えない |

**なぜ C# の汎用ライブラリは弱いか**:

- .NET エコシステムは **「フレームワーク + 独自フォーマット」の組み合わせが豊富** で、汎用パーサーへの需要が低い
- protobuf-net、System.Text.Json、MemoryPack 等の **特定フォーマットに特化したライブラリが充実** している
- バイナリプロトコルを扱うシーンは Windows API 連携などに偏り、汎用 DSL の需要が少なかった
- C# 9+ の record と source generator の組み合わせで、 **自前で十分なものが作れる** ようになった

**設計書の判断の正当性**:

付録 F で「自作 source generator で `[BanchoPacket]` を実装する」とした判断は、C# エコシステムの現実を踏まえた **唯一の合理的な選択** だった。汎用ライブラリを採用しようとすると Construct や binrw 相当のものが存在せず、結局は低レベル API でかき集めることになる。

Roslyn ベースの source generator は **エコシステムが成熟しており、StackOverflow の質問数も豊富** で、Rust の proc-macro より学習リソースが多い。これは C# 版実装の隠れた強み。

### G.5 Go のバイナリパースライブラリ

設計書の以前の評価で「Go では宣言的バイナリパースができない」と書いた箇所があったが、これは **不正確** だった。訂正する。

| ライブラリ | 採用判断 | 特徴 |
|---|---|---|
| restruct | 検討価値あり | struct タグベース、双方向、宣言的 |
| struc | 検討価値あり | struct タグベース、C-style 構造のパック/アンパック |
| 標準 `encoding/binary` | 低レベル | 標準ライブラリ、宣言性なし |
| gopacket | ネットワーク特化 | パケット処理、Google 製 |

**struct タグベースの宣言的記述例**(restruct):

```go
type SendPublicMessageC2S struct {
    Sender   BanchoString `struc:"BanchoString"`
    Message  BanchoString `struc:"BanchoString"`
    Target   BanchoString `struc:"BanchoString"`
    SenderID int32        `struc:"int32,little"`
}

var packet SendPublicMessageC2S
err := restruct.Unpack(rawBytes, binary.LittleEndian, &packet)
```

これは Caterpillar や binrw ほど洗練されていないが、 **「Go では宣言的バイナリパースが不可能」というのは過言** だった。struct タグベースの実用的なライブラリは存在する。

ただし設計書本体の Go 評価は概ね妥当で、 **「デコレーター文化との相性」「Tower 相当の抽象化レイヤー」「erorr handling の冗長性」** の問題は依然として残る。バイナリパースだけ取り上げれば Go でも書けるが、bancho サーバー全体としては Python / Rust / C# / TypeScript の方が向いている、という結論は変わらない。

### G.6 その他言語のバイナリパースライブラリ

完全性のため、他言語のオプションも整理しておく(本設計書のスコープ外だが、将来的な参考として)。

#### Java

- **Preon**: Bit syntax for Java、declarative data binding framework
- **Apache Daffodil**: DFDL (Data Format Description Language) 実装、XML Schema ベース、Scala/Java で動作

#### Ruby

- **BinData**: declarative、双方向、Ruby らしい DSL

#### Swift

- **swift-binary-parsing**: Apple 公式の最近のライブラリ、`ParserSpan` / `ParserRange` ベース、安全性重視

Swift 公式のバイナリパーサーが最近登場した事実は興味深く、 **Apple が iOS / macOS で扱うフォーマット(画像、フォント、デバイス通信等)のために整備した** ものと推測される。bancho サーバー用途では使う場面は薄いが、iOS / macOS 向けの osu! クライアント独自実装などには活きる可能性がある。

#### Clojure / Haskell / OCaml / Nim

- **Gloss** (Clojure): バイト形式と Clojure データ構造の相互変換
- **scodec** (Scala): Combinator library、関数型のアプローチ
- **attoparsec** (Haskell): 高速なパーサーコンビネータ
- **binarylang / binaryparse** (Nim): 言語内 DSL

これらはいずれも bancho サーバー用途では主流外だが、 **「同じ問題に対する各言語の哲学」** を学ぶ参考にはなる。

### G.7 言語非依存ツール

#### Kaitai Struct

- **採用判断: 不採用**
- read-only(parser のみ生成、serializer なし)
- bancho サーバーのように **双方向(S2C パケットのシリアライズ)** が必要な用途には不適合
- ただし bancho プロトコルの **解析・ドキュメント化ツール** としては優秀。`.ksy` でプロトコル定義を書けば多言語にコンパイルできる
- リバースエンジニアリングや異言語間のリファレンス共有には有用

#### ASN.1

- **採用判断: 不採用**
- 通信業界・暗号(X.509)・LDAP 等で広く使われる古典的標準
- bancho プロトコルは ASN.1 ベースではないため適合しない
- ただし lazer の証明書・JWT 等の周辺で間接的に関わる可能性

#### DFDL (Apache Daffodil)

- **採用判断: 不採用**
- XML Schema で binary format を記述する、軍事・通信業界標準
- 学習コストが高く、bancho サーバー規模ではオーバーキル

#### Spicy

- **採用判断: 不採用**
- Zeek プロジェクトのパーサジェネレータ、network protocol に特化
- 学術寄りでコミュニティが小さい

### G.8 選定指針(新規言語で実装する場合)

bancho サーバーを別の言語で実装したい場合、バイナリパースライブラリ選定の指針を以下にまとめる。

#### 必須要件

1. **双方向対応**: parse(C2S 受信)と build(S2C 送信)の両方が必要
2. **動的長フィールド対応**: BanchoString のように、フィールド内容に応じて長さが変わる構造を扱える
3. **条件付きフィールド対応**: present marker(0x0b)の有無で次のフィールドが存在するか変わるような構造
4. **エンディアン制御**: bancho プロトコルはリトルエンディアン
5. **アクティブメンテナンス**: 過去2年以内のコミットがあること

#### 強く望ましい要件

1. **宣言的記述**: 手書きで `read_int32`, `read_string` を並べるのではなく、 **構造定義として表現** できる
2. **型システム統合**: パケット型がそのままプログラミング言語の型として扱える
3. **エラーメッセージの質**: パース失敗時にどのフィールドで失敗したか分かる

#### あれば嬉しい要件

1. **bit-level の表現力**: mods bitfield 等を直接表現できる
2. **ストリーム I/O**: メモリ消費を抑えられる
3. **コード生成によるパフォーマンス**: ランタイムリフレクションではなくコンパイル時生成

#### 採用しないアンチパターン

- **read-only のみ(Kaitai Struct)**: serialize ができないため双方向通信に不適合
- **テキスト形式特化(JSON Schema 等)**: バイナリプロトコルには使えない
- **過度に重量級(Hachoir、Scapy)**: 多数のフォーマット内蔵で依存が重い

### G.9 設計書本体への影響

本付録は **既存の選定判断を補強する** ものであり、変更を要請するものではない。

| 言語 | 既存の選定(変更なし) | 補強された理由 |
|---|---|---|
| Python | Caterpillar | 他選択肢(Hachoir, Mr. Crowbar, dissect.cstruct 等)との対比で、型ヒント統合と現代性が優位 |
| Rust | binrw | Deku、scroll、Nom、winnow との対比で、ストリーム I/O とエルゴノミクスが適合 |
| TypeScript | restructure(推奨)/ Binary-parser(代替) | npm ダウンロード数(restructure)と GitHub スター数(Binary-parser)の現実差を踏まえた選択 |
| C# / .NET | 自作 source generator | エコシステムに汎用ライブラリが薄いため、source generator 自作が現実解として確立 |
| Go | (本設計の対象外、ただし評価訂正) | struct タグベースの restruct / struc は存在する。「宣言的記述が不可能」は不正確 |

### G.10 参考文献

- [dloss/binary-parsing](https://github.com/dloss/binary-parsing): 「Awesome Binary Parsing」、本付録の主要な情報源
- [Caterpillar Documentation](https://github.com/MatrixEditor/caterpillar)
- [binrw Documentation](https://binrw.rs)
- [restructure on npm](https://www.npmjs.com/package/restructure)
- [Roslyn Source Generators Cookbook](https://github.com/dotnet/roslyn/blob/main/docs/features/source-generators.cookbook.md)

これらを起点に、各言語での実装着手時にライブラリ選定を再評価できる。

---

## 改訂履歴

| 日付 | 版 | 内容 |
|---|---|---|
| 初版 | 1.0 | 設計の基本方針と全体構造を確立 |
| 第二版 | 1.1 | メッセージング基盤を EventBus(fire-and-forget)と JobQueue(配信保証あり)に二分化。ARQ をジョブキュー実装として正式採用し、worker プロセスを app プロセスから分離する2プロセス構成を確立。Redis Pub/Sub を EventBus 本番実装として明記。RabbitMQ / Kafka を初期スコープから除外することを意思決定として明示。ロードマップに Worker プロセス導入の Phase を追加 |
| 第三版 | 1.2 | Redis を揮発的ステートの中央ストアとして明示的に位置づけ、`infrastructure/state/` に StateStore Protocol 群(SessionStore、PresenceStore、ChannelStateStore 等)を新設。セクション 8.5 として「ステート管理戦略」を追加。マイクロサービス化への脱出口を、より具体的な7段階の進化パス(Stage 1〜7)として再構成し、特に Stage 4 で「Service 中央プロセス + 薄いトランスポート」アーキテクチャを Ripple 型分散モノリスの改良案として位置づけ。セクション 12.4 として「モノレポ + 共通パッケージ分離」を新設し、uv workspace を採用。付録 D として「Cloudflare ベースの代替実装」を追加し、Durable Objects を Redis StateStore の代替として扱う構成を提示 |
| 第四版 | 1.3 | セクション 8.9 として「クリティカル処理の判別と JobQueue 化原則」を新設。データ整合性に影響する処理(PP 計算、リーダーボード更新、メダル付与、ユーザー統計更新、リプレイ永続化等)は必ず JobQueue 経由で実行する原則を明文化。スコア送信処理を「同期処理(DB 保存) + JobQueue(クリティカル後処理) + EventBus(リアルタイム通知)」の3層に分割するパターンを確立。クリティカル処理判別チェックリスト、JobQueue 化のアンチパターン(fire-and-forget タスク、例外握りつぶし、長時間トランザクション、EventBus 誤用)を整理。Pyventus 等のイベント駆動ライブラリを採用しない判断を明示し、設計書本体(セクション 3.3)と付録 B に意思決定として記録 |
| 第五版 | 1.4 | 付録 E として「Rust ベースの代替実装」を追加。axum + binrw + apalis + sqlx + fred のスタックを推奨構成として整理。bancho ハンドラ用の自作 proc-macro(`bancho-handler-macro`)の設計を詳述し、Python のデコレーターパターンに相当する書き心地を Rust でも実現する方針を確立。PP 計算ライブラリ rosu-pp のネイティブ統合、apalis による JobQueue 実装、cargo workspace によるモノレポ構成、Python 版からの段階的移行パスを記載。書き心地と性能の両立を求める長期プロジェクトの選択肢として位置づけ |
| 第六版 | 1.5 | 付録 F として「C# / .NET ベースの代替実装」を追加。ASP.NET Core + SignalR + osu-tools + EF Core + Hangfire + StackExchange.Redis のスタックを推奨構成として整理。bancho ハンドラ用 attribute と source generator の設計を詳述し、Python のデコレーターパターンを C# でも実現する方針を確立。osu-server-spectator と互換な SignalR ハブのネイティブ実装、osu-tools の直接統合による PP 計算の本家完全互換、Native AOT によるシングルバイナリ運用を記載。Kotlin / Java を付録対象としない判断を意思決定として明示。Python / Rust / C# / TypeScript の4実装の位置づけを明確化し、「Python が本流、Rust は性能重視、C# は本家互換性重視、Cloudflare は実験的」という4本立て構成として整理 |
| 第七版 | 1.6 | 付録 G として「言語別バイナリパースライブラリのカタログ」を追加。dloss/binary-parsing(Awesome Binary Parsing)を起点に、Python(Caterpillar, Hachoir, Mr. Crowbar, dissect.cstruct 等)、Rust(binrw, Deku, scroll, Nom, winnow)、TypeScript(restructure, Binary-parser, Binpat)、C# / .NET(汎用ライブラリの薄さと source generator 戦略の正当化)、Go(restruct, struc 等の存在を明記し評価訂正)、その他言語(Java, Ruby, Swift 等)を整理。GitHub スター数と npm ダウンロード数で人気ライブラリが異なる JavaScript エコシステムの実情、binrw vs Deku の比較、bancho サーバー用途での選定指針(双方向対応、動的長対応、エンディアン制御等の必須要件)を体系化。既存の選定判断(Caterpillar, binrw, restructure, source generator 自作)を変更せず、補強する形で位置づけ |
