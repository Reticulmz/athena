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

詳細は `.claude/rules/architecture.md` および `docs/architecture.md` を参照。

### レイヤー構造

```
Composition → Runtime Adapters → Command/Query Use-Cases → Repositories → Infrastructure
                                  Command/Query Use-Cases → Domain → Shared
```

- **Composition**: Dishka による DI グラフ構築（`composition/providers/`）
- **Runtime Adapters**: Starlette routes / taskiq tasks（thin adapters）
- **Command Use-Cases**: 状態変更ワークフロー（`services/commands/`、UnitOfWork 経由）
- **Query Use-Cases**: 読み取り専用ワークフロー（`services/queries/`、Query Repository 経由）
- **Domain**: transport 非依存のビジネス言語（`domain/`、標準 dataclass）
- **Repositories**: Command（UoW 参加）/ Query（読み取り最適化）に分離
- **Infrastructure**: DB, Valkey, EventBus, JobQueue

### 重要な設計規約

- **Command/Query 責務分離**: 状態変更と読み取りを明確に分離
- **UnitOfWork パターン**: Command 側はトランザクション境界を UoW で管理
- **Transport は thin adapter**: use-case を呼び、SQLAlchemy / DB session を直接扱わない
- **Domain は Pydantic を使わない**: 標準 dataclass のみ（バリデーションオーバーヘッド回避）
- **import-linter で依存方向を機械的に検証**: CI で自動チェック

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


# Agentic SDLC and Spec-Driven Development

Kiro-style Spec-Driven Development on an agentic SDLC

## Commit Attribution

- When a coding agent creates a commit, include its own model identifier in the commit body or footer.
- Required footer format: `Agent-Model: <agent product> (<model name>)`
- Example: `Agent-Model: Claude Code (<model name>)`

## Project Context

### Paths
- Steering: `.kiro/steering/`
- Specs: `.kiro/specs/`

### Steering vs Specification

**Steering** (`.kiro/steering/`) - Guide AI with project-wide rules and context
**Specs** (`.kiro/specs/`) - Formalize development process for individual features

### Active Specifications
- Check `.kiro/specs/` for active specifications
- Use `/kiro-spec-status [feature-name]` to check progress

## Development Guidelines
- Think in English, generate responses in English. All Markdown content written to project files (e.g., requirements.md, design.md, tasks.md, research.md, validation reports) MUST be written in the target language configured for this specification (see spec.json.language).

## Minimal Workflow
- Phase 0 (optional): `/kiro-steering`, `/kiro-steering-custom`
- Discovery: `/kiro-discovery "idea"` — determines action path, writes brief.md + roadmap.md for multi-spec projects
- Phase 1 (Specification):
  - Single spec: `/kiro-spec-quick {feature} [--auto]` or step by step:
    - `/kiro-spec-init "description"`
    - `/kiro-spec-requirements {feature}`
    - `/kiro-validate-gap {feature}` (optional: for existing codebase)
    - `/kiro-spec-design {feature} [-y]`
    - `/kiro-validate-design {feature}` (optional: design review)
    - `/kiro-spec-tasks {feature} [-y]`
  - Multi-spec: `/kiro-spec-batch` — creates all specs from roadmap.md in parallel by dependency wave
- Phase 2 (Implementation): `/kiro-impl {feature} [tasks]`
  - Without task numbers: autonomous mode (subagent per task + independent review + final validation)
  - With task numbers: manual mode (selected tasks in main context, still reviewer-gated before completion)
  - `/kiro-validate-impl {feature}` (standalone re-validation)
- Progress check: `/kiro-spec-status {feature}` (use anytime)

## Skills Structure
Skills are located in `.claude/skills/kiro-*/SKILL.md`
- Each skill is a directory with a `SKILL.md` file
- Skills run inline with access to conversation context
- Skills may delegate parallel research to subagents for efficiency
- Additional files (templates, examples) can be added to skill directories
- `kiro-review` — task-local adversarial review protocol used by reviewer subagents
- `kiro-debug` — root-cause-first debug protocol used by debugger subagents
- `kiro-verify-completion` — fresh-evidence gate before success or completion claims
- **If there is even a 1% chance a skill applies to the current task, invoke it.** Do not skip skills because the task seems simple.

## Development Rules
- 3-phase approval workflow: Requirements → Design → Tasks → Implementation
- Human review required each phase; use `-y` only for intentional fast-track
- Keep steering current and verify alignment with `/kiro-spec-status`
- Follow the user's instructions precisely, and within that scope act autonomously: gather the necessary context and complete the requested work end-to-end in this run, asking questions only when essential information is missing or the instructions are critically ambiguous.

## Steering Configuration
- Load entire `.kiro/steering/` as project memory
- Default files: `product.md`, `tech.md`, `structure.md`
- Custom files are supported (managed via `/kiro-steering-custom`)

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **athena** (15560 symbols, 27848 relationships, 241 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/athena/context` | Codebase overview, check index freshness |
| `gitnexus://repo/athena/clusters` | All functional areas |
| `gitnexus://repo/athena/processes` | All execution flows |
| `gitnexus://repo/athena/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
