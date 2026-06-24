# Requirements Document

## Introduction

Services 層と Transports 層が `infrastructure/` パッケージ内の Protocol/interface を直接参照している現状を整理し、AI エージェントと人間のメンテナがファイルパスから各 Protocol の層帰属を即座に判断できる構造にする。現在の import-linter 13 契約はすべてパスしており、アーキテクチャ上の違反はない。本仕様は既存の疎結合を壊さず、Protocol 配置の可読性と機械的検証を強化することを目的とする。

## Boundary Context

- **In scope**: infrastructure/ 内に散在する Protocol/interface の配置整理、import-linter 契約の追加、leaderboard_rebuild_wake の配置見直し
- **Out of scope**: ドメイン層 (domain/) の構造変更、Services 間のクロスドメイン依存解消、パッケージ名変更 (osu_server → athena_server)、Clean-room 再構築、Repository interface (repositories/interfaces/) の移動
- **Adjacent expectations**: 既存の import-linter 13 契約が引き続きパスすること。既存の Dishka provider 構成が動作し続けること。既存テストが修正なしまたは import path 変更のみで通ること

## Requirements

### Requirement 1: Protocol 配置の層帰属明確化

**Objective:** As an AI エージェントまたは人間のメンテナ, I want 各 Protocol/interface のファイルパスから「どの層の責務か」を即座に判断できること, so that コードナビゲーション時に依存グラフの意図を推測する必要がなくなる

#### Acceptance Criteria

1. When AI エージェントまたは人間のメンテナが Protocol ファイルのパスを確認したとき, the athena codebase shall パスの構造だけで「この Protocol はどの層 (shared / domain / infrastructure) に属するか」を判断できる命名規則に従っていること
2. The athena codebase shall 全ての Protocol/interface 定義を、具象実装ファイルとは別のディレクトリまたはモジュールに配置すること
3. The athena codebase shall Protocol と同一ファイルに具象実装クラスを混在させないこと (ただし Noop/Stub 等のデフォルト実装で Protocol と密接に対になるものは同居を許容する)

### Requirement 2: Services 層から具象 infrastructure への依存遮断

**Objective:** As a メンテナ, I want Services 層が infrastructure の具象実装ではなく Protocol/interface のみに依存すること, so that infrastructure 実装の差し替え (テスト用 in-memory、将来の外部サービス移行等) が Services 側の変更なしに行える

#### Acceptance Criteria

1. The athena codebase shall Services 層 (services/commands/, services/queries/) のファイルが infrastructure の具象実装モジュールを直接 import しないこと
2. When Services 層のファイルが infrastructure の機能を必要とするとき, the athena codebase shall Protocol/interface 経由でのみ依存を表現すること
3. If Services 層のファイルが infrastructure 具象実装を直接 import した場合, the import-linter shall 契約違反として検出し Exit Code を非ゼロで返すこと

### Requirement 3: Transports 層から具象 infrastructure への依存整理

**Objective:** As a メンテナ, I want Transports 層が infrastructure の具象実装への依存を最小化すること, so that transport adapter の可読性が向上し、依存グラフが明確になる

#### Acceptance Criteria

1. When Transports 層のファイルが infrastructure の機能を必要とするとき, the athena codebase shall Protocol/interface 経由での依存を優先すること
2. If Transports 層が infrastructure の具象ユーティリティ (parser, country codes 等) を使用する場合, the athena codebase shall その依存を import-linter 契約で明示的に許可対象として宣言すること
3. The athena codebase shall Transports 層から infrastructure への依存を import-linter 契約で監視し、許可リスト外の新規依存追加を検出すること

### Requirement 4: ドメイン横断 Protocol の配置明確化

**Objective:** As a メンテナ, I want 複数ドメインから参照される共有 Protocol (leaderboard_rebuild_wake 等) の配置場所が自明であること, so that 新しいドメイン横断 Protocol を追加する際に配置先で迷わない

#### Acceptance Criteria

1. The athena codebase shall 複数ドメインの services から参照される Protocol を、特定ドメインの services ディレクトリではなく共有的な場所に配置すること
2. When 新しいドメイン横断 Protocol を追加するとき, the athena codebase shall 既存のドメイン横断 Protocol と同じ配置規則に従えること
3. The athena codebase shall ドメイン横断 Protocol の配置場所を import-linter 契約で保護し、特定ドメインの services 内に新規のドメイン横断 Protocol が配置されることを検出すること

### Requirement 5: import-linter 契約による機械的検証

**Objective:** As a CI パイプラインの運用者, I want 上記の配置規則が import-linter 契約として定義されていること, so that 人間の注意力に依存せず配置規則違反を自動検出できる

#### Acceptance Criteria

1. The import-linter shall 既存の 13 契約に加えて、本仕様で追加された配置規則を検証する契約を含むこと
2. When 全ての配置規則が守られているとき, the import-linter shall Exit Code 0 を返すこと
3. If いずれかの配置規則に違反する import が追加されたとき, the import-linter shall 違反内容を報告し Exit Code を非ゼロで返すこと
4. The import-linter shall 既存の 13 契約を引き続きパスすること

### Requirement 6: 既存動作の互換性維持

**Objective:** As a 開発者, I want Protocol 配置の変更後も既存の全機能が同一の動作を維持すること, so that リファクタリングによる機能的回帰が発生しない

#### Acceptance Criteria

1. When Protocol の配置を変更したとき, the athena codebase shall 既存の全自動テスト (pytest) がパスすること
2. When Protocol の配置を変更したとき, the athena codebase shall 既存の全静的解析 (basedpyright, ruff check, ruff format --check) がパスすること
3. When Protocol の配置を変更したとき, the Dishka provider 構成 shall 変更前と同一の依存解決グラフを構築すること
4. The athena codebase shall Protocol の配置変更に伴い、消費側ファイルの import path のみを更新し、ビジネスロジックの変更を行わないこと
