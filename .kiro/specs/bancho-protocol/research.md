# Research & Design Decisions

## Summary
- **Feature**: `bancho-protocol`
- **Discovery Scope**: New Feature (greenfield)
- **Key Findings**:
  - Caterpillar v2.8.1 は Python 3.14 互換だが `with If()` 構文は使用不可（`Conditional`/`Switch` で代替）
  - BanchoString は Caterpillar の組み込み型では表現できず、Custom FieldStruct が必要
  - 既存 bancho サーバー実装はデコレータ + dict パターンで統一されている

## Research Log

### Caterpillar ライブラリ互換性
- **Context**: Python 3.14 での動作確認が必要
- **Sources Consulted**: PyPI (caterpillar-py)、GitHub MatrixEditor/caterpillar、Issue #27
- **Findings**:
  - パッケージ名: `caterpillar-py`（`caterpillar` は別パッケージ）
  - 最新: v2.8.1 (2026-02-08)
  - Python 3.14: `@struct`, `pack`/`unpack`, `this`, `Enum`, `VarInt` は全て動作
  - `If`/`ElseIf` の `with` 文構文は Python 3.14 の `__annotations__` 変更で破壊 → v2.6.0+ の `Conditional`/`Switch` を使用
  - ULEB128 は `VarInt` で対応可能
- **Implications**: BanchoString は Custom FieldStruct として実装。条件付きフィールドは `Conditional`/`Switch` を使用

### Caterpillar 配列構文と Switch 機能
- **Context**: パケット一括読み取りと条件付きフィールドに Caterpillar ネイティブ機能を活用できるか調査
- **Sources Consulted**: [配列ドキュメント](https://matrixeditor.github.io/caterpillar/tutorial/basics/stdlist.html)、[Switch ドキュメント](https://matrixeditor.github.io/caterpillar/tutorial/advanced/op-switch.html)、[Operators リファレンス](https://matrixeditor.github.io/caterpillar/reference/operators.html)
- **Findings**:
  - **配列構文**: 4 種類をサポート
    - 固定長: `uint8[100]`
    - 動的長: `int32[this.count]`（他フィールド参照）
    - Greedy: `Type[...]`（EOF または例外まで読み取り）
    - プレフィックス付き: `CString[uint8::]`
  - **Greedy 配列**: `_GreedyType` を使用。`unpack(RawPacket[...], data)` で HTTP body から全パケットを一括パース可能。カスタム PacketReader クラスが不要になる
  - **Switch**: `F(this.field) >> { value: Type, DEFAULT_OPTION: FallbackType }` 構文。`with If()` の Python 3.14 互換代替。v2.8.0+ では `f[TypeHint, F(...) >> {...}]` 拡張構文もあり
  - **Switch の用途**: Match の `freemod` フラグ → `slot_mods` 配列の有無、ScoreFrame の `scorev2_enabled` → combo/bonus フィールドの有無など、条件付きフィールドに最適
- **Implications**:
  - PacketReader をカスタムイテレータクラスから `RawPacket` struct + `read_packets()` ラッパー関数に簡素化
  - 本 spec スコープ内に Switch が必要なパケット型はない（BanchoString は FieldStruct の方が適切）
  - 後続 spec（Match, ScoreFrame 等）で Switch を積極的に使用する方針を Out of Boundary に記載

### BanchoString ワイヤフォーマット
- **Context**: osu! 独自の文字列エンコーディング
- **Sources Consulted**: bancho-documentation Wiki Types ページ、bancho.py/gulag/anchor のソースコード
- **Findings**:
  - フォーマット: `0x00` = 空文字列、`0x0b` + ULEB128 長 + UTF-8 バイト列
  - 全既存実装が同一パターン（read_u8 → ULEB128 → decode）
  - Caterpillar の `Prefixed` や `CString` では表現不可（presence byte + ULEB128 の組み合わせが独自）
- **Implications**: `_struct_.FieldStruct` を継承して `BanchoString` を実装。`VarInt` を内部で使用

### 既存 bancho サーバーのディスパッチパターン
- **Context**: ハンドラ登録・呼び出し機構の設計参考
- **Sources Consulted**: bancho.py (Akatsuki)、kawata.py、circles、anchor、osu.py (Lekuruu)
- **Findings**:
  - 2 パターン: クラスベース (bancho.py) vs 関数ベース (anchor)
  - クラスベースはコンストラクタでパース + handle() でロジック → パース責務が不明確
  - 関数ベースはシンプルだがパース責務がハンドラに混入
  - 全実装で `memoryview` によるゼロコピーバッファ管理
  - パケットレジストリは global dict が主流だが DI フレンドリーではない
- **Implications**: Athena は Caterpillar でパケット定義を分離し、関数ベースハンドラを採用。DI コンテナ経由でレジストリ管理

### Foundation Spec 統合ポイント
- **Context**: bancho-protocol が foundation の上に構築される
- **Sources Consulted**: foundation design.md、container.py、providers.py、app.py、pyproject.toml
- **Findings**:
  - Container: `register_singleton(type, factory)` / `resolve(type)` パターン
  - App: Starlette lifespan、`app.state.container` 経由でアクセス
  - 現在 `POST /` にプレースホルダールートあり → バイナリプロトコルハンドラで置換予定
  - import-linter: transports → services → domain → repositories → infrastructure → shared（厳密な一方向）
- **Implications**: PacketDispatcher を `build_container` でシングルトン登録。ハンドラから services を container.resolve() で取得

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Caterpillar 宣言的定義 + 関数ベースハンドラ | struct でパケット定義、デコレータで関数ハンドラ登録 | パース/ロジック分離、型安全、テスト容易 | BanchoString に Custom FieldStruct 必要 | 採用 |
| クラスベースハンドラ (bancho.py 方式) | BasePacket ABC + __init__(reader) + handle() | 既存実績あり | パース責務が不明確、テスト困難 | 不採用 |
| 手動 struct.unpack (Caterpillar 不使用) | Python 標準 struct モジュールで直接パース | 依存なし | 宣言的でない、双方向変換が冗長 | 不採用 |

## Design Decisions

### Decision: BanchoString の実装方式
- **Context**: osu! 独自の文字列フォーマットを Caterpillar で表現する必要がある
- **Alternatives Considered**:
  1. Caterpillar 組み込み型の組み合わせ（Prefixed + conditional）
  2. Custom FieldStruct サブクラス
  3. 手動 read/write 関数（Caterpillar 外）
- **Selected Approach**: Custom FieldStruct サブクラス
- **Rationale**: Caterpillar のエコシステム内で統一的に使用可能。他の struct にフィールドとしてネスト可能。VarInt を内部利用して ULEB128 を処理
- **Trade-offs**: 実装コストは若干高いが、全パケット定義で一貫して使用できる
- **Follow-up**: Python 3.14 での FieldStruct 動作確認

### Decision: ハンドラの関数ベース採用
- **Context**: C2S パケットハンドラの登録・呼び出しパターン
- **Alternatives Considered**:
  1. クラスベース（BasePacket ABC + handle メソッド）
  2. 関数ベース（デコレータ登録 + async 関数）
- **Selected Approach**: 関数ベース
- **Rationale**: シンプル、テスト容易、Caterpillar でパケット定義が分離されているためクラスでの二重定義が不要
- **Trade-offs**: ハンドラ間の共通処理は別途ミドルウェアパターンが必要（将来必要時）
- **Follow-up**: ハンドラ関数のシグネチャは bancho-login spec で具体化

### Decision: PacketDispatcher の DI 登録
- **Context**: ディスパッチャのライフサイクル管理と依存注入
- **Alternatives Considered**:
  1. グローバル変数（既存サーバー方式）
  2. DI コンテナ経由シングルトン
- **Selected Approach**: DI コンテナ経由シングルトン
- **Rationale**: テスト時に差し替え可能、グローバル状態を回避、foundation の DI パターンに準拠
- **Trade-offs**: デコレータ登録時にインスタンスが必要 → モジュールレベルのレジストリ + コンテナ登録の 2 段階
- **Follow-up**: providers.py への登録コード追加

## Risks & Mitigations
- **Caterpillar の Custom FieldStruct API が Python 3.14 で破壊されるリスク** — v2.8.1 で事前検証。Issue #27 は解決済み
- **BanchoString のエッジケース（不正な presence byte）** — parse 時に明示的なバリデーション + カスタム例外
- **パケット定義の網羅性** — bancho-documentation Wiki をソースオブトゥルースとし、enum 値を全件定義

## References
- [caterpillar-py PyPI](https://pypi.org/project/caterpillar-py/) — v2.8.1、Python 3.12+
- [MatrixEditor/caterpillar GitHub](https://github.com/MatrixEditor/caterpillar) — ソースコード・ドキュメント
- [Python 3.14 互換性 Issue #27](https://github.com/MatrixEditor/caterpillar/issues/27) — 解決済み
- [Lekuruu/bancho-documentation Wiki](https://github.com/Lekuruu/bancho-documentation/wiki) — プロトコル仕様
- [bancho.py (Akatsuki)](https://github.com/osuAkatsuki/bancho.py) — 参考実装

---

# Gap Analysis: bancho-protocol

## Summary
- **Feature**: `bancho-protocol`
- **Analysis Type**: Greenfield（プロトコル関連コードは一切存在しない）
- **Key Findings**:
  - caterpillar-py 依存が未追加。全プロトコルコードは新規作成
  - Foundation（DI, config, app lifespan, layer enforcement）は完備しており統合基盤は整っている
  - import-linter のレイヤー規則により providers.py からの transports インポートは禁止 → app.py lifespan での登録が必要（設計修正済み）

## Requirement-to-Asset Map

| Requirement | 必要な資産 | 既存コード | Gap |
|-------------|-----------|-----------|-----|
| 1.1–1.4 | PacketHeader struct | なし | Missing |
| 2.1–2.4 | ClientPacketID / ServerPacketID enum | なし | Missing |
| 3.1, 3.6 | BanchoString FieldStruct | なし | Missing |
| 3.2–3.5 | Message, IntList, Channel, StatusUpdate | なし | Missing |
| 4.1, 4.2, 4.4, 4.5 | RawPacket + read_packets() | `bancho_placeholder` in app.py（スタブのみ） | Missing |
| 4.3 | write_packet() | なし | Missing |
| 5.1–5.5 | PacketDispatcher | なし | Missing |
| 6.1–6.12 | 12 S2C login packet types | なし | Missing |

## Existing Assets（活用可能な基盤）

### DI Container (`infrastructure/di/container.py`)
- `register_singleton(Type, factory)` / `resolve(Type)` パターン確立
- `asyncio.Lock` による二重チェックロッキング
- シャットダウンフック機構あり
- **活用**: PacketDispatcher をシングルトン登録

### App Lifespan (`app.py`)
- `build_container(config)` → `container.initialize()` → yield → `container.shutdown()` フロー
- `POST /` に `bancho_placeholder` スタブあり → プロトコルハンドラで置換予定
- **活用**: lifespan 内で PacketDispatcher を登録、composition root として transports のインポートが許容される場所

### Shared Types (`shared/types.py`, `shared/errors.py`)
- `UserId = NewType("UserId", int)` / `Token = NewType("Token", str)`
- `AppError` 基底例外クラス
- **活用**: PacketError を AppError とは独立に定義（プロトコル層は shared.errors に依存しない設計）

### Import-Linter (`pyproject.toml`)
- レイヤー: `transports → services → domain|repositories → infrastructure → shared`
- **制約**: infrastructure から transports をインポート不可 → providers.py での PacketDispatcher 登録は禁止

### テスト基盤 (`tests/`)
- `unit/infrastructure/` と `integration/` にパターン確立
- conftest.py は未作成（テストディレクトリは空 `__init__.py` のみ）
- **活用**: 既存パターンに従い `tests/unit/transports/bancho/` を新規作成

## Implementation Approach

### Option B: 全コンポーネント新規作成（推奨）

**Rationale**: プロトコル関連コードが一切存在しないため、既存コンポーネントの拡張ではなく新規作成が唯一の選択肢。

**Integration Points**:
1. `pyproject.toml` — caterpillar-py 依存追加
2. `app.py` lifespan — PacketDispatcher の DI 登録
3. `app.py` routes — `bancho_placeholder` の置換（bancho-login spec が担当）

**Trade-offs**:
- ✅ 既存コードとの衝突リスクゼロ
- ✅ import-linter 準拠のクリーンなレイヤー構造で構築可能
- ✅ TDD で段階的に構築可能（各コンポーネントが独立テスト可能）
- ❌ ファイル数が多い（14 ソース + 8 テスト）が、責務分離のため妥当

## Effort & Risk

- **Effort**: M（3–7 日）— 新規コンポーネント群だが、各コンポーネントは単純。BanchoString の FieldStruct 実装が最も技術的に挑戦的
- **Risk**: Low-Medium
  - **Low**: 既存コードとの衝突なし、パターン確立済み、外部依存は caterpillar-py のみ
  - **Medium**: Caterpillar FieldStruct API と Greedy 配列の Python 3.14 実環境での動作検証が必要

## Research Needed（実装フェーズで検証）

1. **Caterpillar FieldStruct API**: BanchoString の `pack()`/`unpack()` シグネチャと Context オブジェクトの使い方
2. **Greedy 配列のエラーセマンティクス**: 不完全データ時に例外伝播するか黙って停止するか（Task 3.2 の PoC で検証）
3. **basedpyright との互換性**: Caterpillar の `this` プロキシや `@struct` デコレータが strict モードで型エラーを出さないか
