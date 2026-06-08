# Agentic SDLC and Spec-Driven Development

Kiro-style Spec-Driven Development on an agentic SDLC

## Project Memory
Project memory keeps persistent guidance (steering, specs notes, component docs) so Codex honors your standards each run. Treat it as the long-lived source of truth for patterns, conventions, and decisions.

- Use `.kiro/steering/` for project-wide policies: architecture principles, naming schemes, security constraints, tech stack decisions, api standards, etc.
- Use local `AGENTS.md` files for feature or library context (e.g. `src/lib/payments/AGENTS.md`): describe domain assumptions, API contracts, or testing conventions specific to that folder. Codex auto-loads these when working in the matching path.
- Specs notes stay with each spec (under `.kiro/specs/`) to guide specification-level workflows.

## Project Context

### Paths
- Steering: `.kiro/steering/`
- Specs: `.kiro/specs/`

### Steering vs Specification

**Steering** (`.kiro/steering/`) - Guide AI with project-wide rules and context
**Specs** (`.kiro/specs/`) - Formalize development process for individual features

### Active Specifications
- Check `.kiro/specs/` for active specifications
- Use `$kiro-spec-status [feature-name]` to check progress

## Development Guidelines
- Think in English, generate responses in English. All Markdown content written to project files (e.g., requirements.md, design.md, tasks.md, research.md, validation reports) MUST be written in the target language configured for this specification (see spec.json.language).

## Minimal Workflow
- Phase 0 (optional): `$kiro-steering`, `$kiro-steering-custom`
- Discovery: `$kiro-discovery "idea"` — determines action path, writes brief.md + roadmap.md for multi-spec projects
- Phase 1 (Specification):
  - Single spec: `$kiro-spec-quick {feature} [--auto]` or step by step:
    - `$kiro-spec-init "description"`
    - `$kiro-spec-requirements {feature}`
    - `$kiro-validate-gap {feature}` (optional: for existing codebase)
    - `$kiro-spec-design {feature} [-y]`
    - `$kiro-validate-design {feature}` (optional: design review)
    - `$kiro-spec-tasks {feature} [-y]`
  - Multi-spec: `$kiro-spec-batch` — creates all specs from roadmap.md in parallel by dependency wave
- Phase 2 (Implementation): `$kiro-impl {feature} [tasks]`
  - Without task numbers: autonomous mode (subagent per task + independent review + final validation)
  - With task numbers: manual mode (selected tasks in main context, still reviewer-gated before completion)
  - `$kiro-validate-impl {feature}` (standalone re-validation)
- Progress check: `$kiro-spec-status {feature}` (use anytime)

## Skills Structure
Skills are located in `.agents/skills/kiro-*/SKILL.md`
- Each skill is a directory with a `SKILL.md` file
- Use `/skills` to inspect currently available skills
- Invoke a skill directly with `$kiro-<skill-name>`
- `kiro-review` — task-local adversarial review protocol used by reviewer subagents
- `kiro-debug` — root-cause-first debug protocol used by debugger subagents
- `kiro-verify-completion` — fresh-evidence gate before success or completion claims
- **If there is even a 1% chance a skill applies to the current task, invoke it.** Do not skip skills because the task seems simple.

## Collaboration Modes (Optional)
Enable collaboration modes in `~/.codex/config.toml` to let Codex choose focused execution modes for longer tasks:

```toml
[features]
collaboration_modes = true
```

## Multi-Agent (Experimental)
If multi-agent is available, use it to parallelize independent research and validation within skills. Enable in `~/.codex/config.toml`:

```toml
[features]
multi_agent = true
```

Skills with "Parallel Research" sections list independent work items that benefit from sub-agent spawning when this feature is active.

## Development Rules
- 3-phase approval workflow: Requirements → Design → Tasks → Implementation
- Human review required each phase; use `-y` only for intentional fast-track
- Keep steering current and verify alignment with `$kiro-spec-status`
- Follow the user's instructions precisely, and within that scope act autonomously: gather the necessary context and complete the requested work end-to-end in this run, asking questions only when essential information is missing or the instructions are critically ambiguous.

## Steering Configuration
- Load entire `.kiro/steering/` as project memory
- Default files: `product.md`, `tech.md`, `structure.md`
- Custom files are supported (managed via `$kiro-steering-custom`)

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

**athena** — osu! bancho 互換プライベートサーバー。stable クライアント（bancho バイナリプロトコル）と lazer クライアント（REST API v2 + SignalR）の両方をサポートする。

## 技術スタック

- **Python 3.14+** / パッケージ管理: **uv**
- **ASGI**: uvicorn + Starlette（bancho / web_legacy / signalr） + FastAPI（api）
- **バイナリプロトコル**: Caterpillar（宣言的定義、parse + build 双方向）
- **API I/O**: Pydantic v2
- **ドメインモデル**: 標準 `@dataclass(slots=True)`（Pydantic は使わない）
- **ORM**: SQLAlchemy 2.0 async + Alembic
- **キャッシュ / ステート / Pub/Sub**: Valkey（valkey-glide クライアント）
- **ジョブキュー**: taskiq + taskiq-redis（redis-py 経由で Valkey に接続、async ネイティブ）
- **DI**: 自前の軽量コンテナ（フレームワーク非依存）
- **型チェック**: basedpyright（厳格モード）
- **Lint / Format**: ruff
- **テスト**: pytest + pytest-asyncio
- **import 規則検証**: import-linter
- **環境構築**: devenv または flake.nix（Nix ベース）

## コマンド

```bash
# 環境
devenv shell                              # Nix 開発環境に入る
uv sync                                   # 依存インストール

# 実行
uvicorn osu_server.app:app --reload       # app プロセス（HTTP/WS）
taskiq worker osu_server.worker:broker      # worker プロセス（ジョブ実行）
python -m osu_server                      # __main__.py 経由の起動

# 品質
ruff check src/                           # lint
ruff format src/                          # format
basedpyright src/                         # 型チェック
pytest tests/                             # 全テスト
pytest tests/unit/                        # ユニットテストのみ
pytest tests/unit/test_chat.py::test_send # 単一テスト
import-linter                             # レイヤー依存違反チェック

# マイグレーション
alembic upgrade head                      # DB マイグレーション適用
alembic revision --autogenerate -m "..."  # 新規マイグレーション生成
```

## アーキテクチャ

### モジュラモノリス + ハイブリッド構造

外側はプロトコル別（bancho / web_legacy / api / signalr）、内側はドメイン別（services 層で共有）。

### レイヤー（依存方向: 上→下のみ、逆方向禁止）

```
Transports → Services → Domain → Repositories → Infrastructure → Shared
```

- **Transports**: プロトコル別の入口。app プロセスのみ使用
- **Services**: ビジネスロジック。両プロセス（app / worker）で共有
- **Domain**: 純粋なドメインモデル（I/O 非依存）
- **Repositories**: 永続化抽象（Protocol） + 実装（SQLAlchemy / memory）
- **Infrastructure**: DB, Valkey, EventBus, JobQueue, DI コンテナ
- **Shared**: errors, types, constants

### 2プロセス構成

- **app プロセス**（uvicorn）: 即時応答 — 認証、チャット配信、スコア受付
- **worker プロセス**（taskiq）: 重い処理 — PP 計算、リーダーボード更新、メダル付与

### 揮発的ステート

セッション・プレゼンス・チャンネル状態・マッチ状態・パケットキューは全て Valkey に集約。プロセス再起動でもセッション消失しない。

### ディレクトリ構造（src/osu_server/）

```
src/osu_server/
├── app.py              # Starlette ルートアプリ組み立て
├── worker.py           # taskiq ワーカーエントリ
├── config.py           # pydantic-settings
├── transports/
│   ├── bancho/         # stable 用 bancho バイナリプロトコル
│   │   ├── protocol/   # パケット定義（c2s/ s2c/ 方向別）
│   │   └── handlers/   # C2S パケットハンドラ
│   ├── web_legacy/     # /web/*.php 互換エンドポイント
│   ├── api/            # FastAPI /api/v2/*
│   └── signalr/        # lazer 用 SignalR ハブ
├── services/           # ドメイン別ビジネスロジック
├── domain/             # dataclass ベースのドメインモデル
├── repositories/       # interfaces/ + sqlalchemy/ + memory/
├── infrastructure/     # DB, cache, state, messaging, jobs, DI
└── shared/             # errors, types, constants
```

## 設計上の重要な規約

- **C2S / S2C パケット ID は方向別に名前空間を分離** — `ClientPacketID` と `ServerPacketID` は別 enum
- **パケットハンドラ追加は3点セット**: パケット定義 + ハンドラ関数 + デコレータ登録
- **ドメイン層に Pydantic を使わない** — バリデーションオーバーヘッド回避、不変条件はメソッドで表現
- **Service の public use-case method は入力モデルを優先**。sender / destination / authorization / payload など複数概念を受け取る場合や primitive 引数が増える場合は、`domain` 層の `@dataclass(slots=True, frozen=True)` input/value object にまとめる。`ChannelService.get_delivery_targets()` のような collaborator query や小さく凝集した内部境界 method は無理に dataclass 化しない
- **DB アクセスは SQLAlchemy 2.0 async + Repository パターンに統一** — Protocol は `repositories/interfaces`、SQLAlchemy 実装は `repositories/sqlalchemy` に置く
- **services / transports / jobs は SQLAlchemy model、DB session、raw SQL を直接扱わない** — 永続化は Repository に委譲する
- **現行 production target は PostgreSQL + asyncpg** — MySQL 等の別 dialect は spec で明示し、driver / migration / model compatibility を検証して導入する
- **unit test のためだけに SQLite / aiosqlite 等の別 DB driver を暗黙導入しない** — DB 不要な範囲は typed fake / stub / in-memory 実装で検証する
- **EventBus**（fire-and-forget）と **JobQueue**（配信保証あり）を使い分ける
- **import-linter でレイヤー違反を CI で機械的に検出**する

## プロトコル仕様リファレンス

bancho バイナリプロトコルの仕様は **[Lekuruu/bancho-documentation Wiki](https://github.com/Lekuruu/bancho-documentation/wiki)** を参照。主要な内容:

- **Protocol**: パケット構造（ヘッダ: PacketID u16 + Compression bool + ContentSize u32 + Content）、リトルエンディアン
- **Login**: ログインフロー（HTTP POST `/` でクレデンシャル送信 → レスポンスでパケットストリーム返却）
- **PacketEnums**: 全パケット ID 一覧（C2S / S2C 共通番号、方向はコンテキストで区別）
- **Types**: BanchoString, Message, Match, Status, UserPresence, UserStats, ReplayFrameBundle, ScoreFrame 等のワイヤフォーマット定義
- **Packets**: 各パケット ID ごとの詳細仕様（Client/ Server/ サブディレクトリ）

## 詳細設計

`bancho_server_design.md` に全セクションの詳細仕様あり（Valkey ステート設計、SignalR 互換層、スコアパイプライン等）。

## rules
@.claude/rules/*.md
.claude/rules/*.mdを必ず読んでください
