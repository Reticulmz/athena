# Requirements Document

## Introduction

Athena の開発者・メンテナーは、Dishka dependency graph を管理する `CommonProviderSet` と `AppProviderSet` が肥大化し、infrastructure、repository、command/query use-case、stable transport workflow が同じ provider ファイルへ集まっているため、import の見通し低下、変更競合、責務境界の読み取りづらさに直面している。既存の app/worker/test の dependency composition と stable client / worker の外部挙動を維持しながら、provider 定義を composition root の所有権と import-linter 境界に沿った保守しやすい構成へ変更する。

## Boundary Context

- **In scope**:
  - app / worker / test の dependency graph を構成する provider 定義の責務分割
  - app/worker 共有 dependency と app-only workflow dependency の見通し改善
  - provider replacement、startup failure、shutdown finalization の既存契約維持
  - dependency boundary validation と provider 構成の整合性維持

- **Out of scope**:
  - Dishka 以外の DI framework への置き換え
  - domain、service、repository、transport、job の外部挙動変更
  - stable client endpoint、packet、legacy web response、worker task name、task payload の変更
  - provider 定義を domain package や infrastructure package の所有物へ移すこと
  - 新しい runtime dependency の追加

- **Adjacent expectations**:
  - `application-architecture-refactor` spec で確立した architecture boundary と provider replacement 方針を前提にする
  - import-linter、basedpyright、ruff、provider graph tests はこの refactor 後も同じ品質ゲートとして機能する
  - 将来の feature specs は、分割後の provider 構成に新しい dependency wiring を追加できる

## Requirements

### Requirement 1: Provider ownership boundary の維持

**Objective:** As an Athena メンテナー, I want dependency composition が composition root の所有範囲に閉じていてほしい, so that domain や service の境界が DI wiring に侵食されない

#### Acceptance Criteria

1. When dependency wiring が追加または変更された場合, the Athena system shall provider 定義を composition root の所有範囲として扱う
2. If provider 定義が domain package または infrastructure package の所有物として追加された場合, then the Athena system shall その変更を architecture boundary 違反として検出できる
3. When domain、service、repository interface が読み込まれた場合, the Athena system shall それらの module が Dishka provider 型へ依存しない状態を維持する
4. When dependency boundary validation が実行された場合, the Athena system shall provider modularization による新しい import-linter 違反を報告しない

### Requirement 2: Provider responsibility の発見しやすさ

**Objective:** As an Athena 開発者, I want dependency provider が責務ごとに整理されていてほしい, so that feature 追加時に変更すべき wiring を短時間で特定できる

#### Acceptance Criteria

1. When 開発者が特定の feature area の dependency wiring を探す場合, the Athena system shall 関連する provider 責務を他の無関係な feature area から区別できる状態にする
2. When app/worker 共有 dependency を確認する場合, the Athena system shall app-only workflow dependency と混在しない形で共有 dependency を確認できる状態にする
3. When app-only stable workflow dependency を確認する場合, the Athena system shall infrastructure や repository wiring と混在しない形で workflow dependency を確認できる状態にする
4. When 新しい dependency wiring が追加される場合, the Athena system shall 既存の巨大な all-purpose provider へ追記する必要がない構成を提供する

### Requirement 3: Runtime dependency graph の互換性

**Objective:** As an Athena operator, I want provider 分割後も app と worker が同じ依存解決契約で起動してほしい, so that refactor が runtime startup の退行を起こさない

#### Acceptance Criteria

1. When app dependency graph が構築された場合, the Athena system shall 既存の app runtime dependency をすべて解決できる
2. When worker dependency graph が構築された場合, the Athena system shall 既存の worker runtime dependency をすべて解決できる
3. If required dependency を解決できない場合, then the Athena system shall 部分的に初期化された graph で serving または task execution を開始しない
4. When test dependency graph が provider replacement を使って構築された場合, the Athena system shall production code branch を追加せずに replacement を適用できる

### Requirement 4: Managed dependency lifecycle の維持

**Objective:** As an Athena operator, I want provider 分割後も managed dependency の lifecycle が維持されてほしい, so that startup/shutdown の安全性が変わらない

#### Acceptance Criteria

1. When managed runtime dependency が作成された場合, the Athena system shall 既存と同等の lifetime で dependency を管理する
2. When app または worker が shutdown する場合, the Athena system shall managed dependency を configured lifecycle に従って finalize する
3. If managed dependency の作成または finalization が失敗した場合, then the Athena system shall failure を operator に観測可能な形で報告する
4. When app と worker が共有する dependency category を使用する場合, the Athena system shall runtime 種別ごとに一貫した lifecycle behavior を維持する

### Requirement 5: Stable client と worker の外部挙動維持

**Objective:** As an Athena 利用者, I want provider 分割後も stable client と worker の挙動が変わらないでほしい, so that 内部 refactor が互換性を壊さない

#### Acceptance Criteria

1. When stable client login flow が実行された場合, the Athena system shall provider 分割前と同じ互換 response behavior を維持する
2. When stable client polling、chat、registration、getscores、score submit flow が実行された場合, the Athena system shall provider 分割前と同じ externally observable behavior を維持する
3. When existing worker task が実行された場合, the Athena system shall task name、payload shape、success/failure outcome の互換性を維持する
4. The Athena system shall provider modularization を理由に public endpoint、stable packet contract、legacy web response、worker task contract を変更しない

### Requirement 6: Validation coverage の維持

**Objective:** As an Athena メンテナー, I want provider 分割が automated validation で検証されてほしい, so that import 整理が未検証の構造変更にならない

#### Acceptance Criteria

1. When quality validation が実行された場合, the Athena system shall formatting、linting、type checking、dependency boundary checks を通過する
2. When relevant automated tests が実行された場合, the Athena system shall provider graph、startup failure、provider replacement、app/worker integration の期待を満たす
3. If provider 分割により circular import または import-time failure が発生した場合, then the Athena system shall validation で failure を検出する
4. When refactor が完了した場合, the Athena system shall 旧 all-purpose provider へ新規 dependency wiring を集中させる必要がないことを validation または review で確認できる
