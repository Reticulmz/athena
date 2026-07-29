# Requirements Document

## Introduction

Athena は Python の型安全性とlintを品質ゲートとして運用しているが、docstring の
存在とGoogle Styleへの準拠はまだ自動検証されていない。`AGENTS.md` は日本語の
Google Style、型と意味、戻り値、例外、制約の説明を定めるdocstring品質基準の正本である。
本featureは、その規約をRuffのdocstring lintで継続的に検証し、first-party Pythonコード
全体の既存docstringを整備する。整備後のdocstringは、別repositoryがSphinxとNapoleonで
API documentを生成できる互換性を持つ。専用のdocstring品質ツールは、Ruffと重複しない価値と
Python 3.14互換性を実証できる場合だけ導入対象とする。

## Boundary Context

- **In scope**: `src/`、`tests/`、migration、運用scriptを含む、リポジトリで追跡される
  first-party Pythonのdocstring整備、Google StyleのRuff検証、追加品質ツールの互換性PoC、
  docstring型整合に必要なsignature annotation補完、Sphinx/Napoleon readiness PoC、品質ゲートと
  開発者向け説明の同期。
- **Out of scope**: third-party依存、生成物、Python以外の文書形式、実行時の振る舞い変更、
  PoCを通さない新規依存の恒久導入、Sphinx site/config/theme/deploymentの恒久所有、既存の
  BasedPyright抑制を一括解消する型品質refactor。
- **Adjacent expectations**: `AGENTS.md` をdocstring品質基準の正本として、日本語Google Style
  規約と既存のRuff品質ゲートを矛盾なく維持する。現行のprivate定義に対する曖昧な文面は、
  public/privateを問わずdocstringを必須とする規約へ同期する。追加ツールはRuffの存在・形式検査を
  置き換えるのではなく、coverageまたは内容整合性などの不足する検査だけを補う。

## Requirements

### Requirement 1: Google Style Docstring品質ゲート

**Objective:** As a maintainer, I want Google Styleに準拠するdocstring lintを品質ゲートで
継続実行したい, so that 新旧コードで形式規約が一貫して守られる。

#### Acceptance Criteria

1. When Python品質ゲートを実行する, the Docstring Quality Gate shall Ruffの`D`規則群と
   Google Style conventionを適用する。
2. The Docstring Quality Gate shall 既存の非docstring lint規則を維持する。
3. If Google Style conventionが特定のdocstring規則を除外または競合させる, the Docstring
   Quality Gate shall その採否を明示し、意図しない規則緩和を発生させない。
4. The Docstring Quality Gate shall 引数記載を検証するGoogle Style対応規則を有効にする。

### Requirement 2: First-party Python Docstring完全性

**Objective:** As a contributor, I want first-party Pythonの定義が一貫して説明されている状態に
したい, so that 実装の責務と利用上の制約をコード上で理解できる。

#### Acceptance Criteria

1. When first-party Pythonのmodule、またはpublic/privateを問わないclass、function、methodが
   対象範囲に存在する, the Documentation Standard shall 各定義に日本語のGoogle Style
   docstringを必須とし、挙動、前提、制約を説明する。testsのtest function/method、fixture、
   fake、helperも同じ対象とし、検証する契約、条件、意図を説明する。
2. When 対象定義が引数、戻り値、yield値、例外、属性を持つ, the Documentation Standard shall
   該当するGoogle Style sectionで型と意味を説明する。
3. Where 対象callableが`None`を返す、または呼出側に重要な制約を持つ, the Documentation
   Standard shall その意味と制約を明記する。
4. The Documentation Standard shall 日本語docstring内でASCIIの`()`, `:`, `/`, `-`を使い、
   曖昧な全角記号を使わず、要約行をASCIIの`.`, `?`, `!`のいずれかで終える。

### Requirement 3: 全対象の違反解消と将来保護

**Objective:** As a maintainer, I want 既存のdocstring負債を可視化せず残さず解消したい, so that
品質ゲートが将来の後退だけでなく現在のコード品質も保証できる。

#### Acceptance Criteria

1. When このfeatureの整備を完了する, the Docstring Quality Gate shall 対象範囲全体でRuffの
   有効なdocstring規則違反を0件と報告し、private定義を含む対象定義すべてにdocstringがあることを
   完全性監査で示す。
2. When contributorが対象範囲のPythonコードを追加または変更する, the Docstring Quality Gate
   shall 新しいdocstring規則違反を拒否する。
3. The Docstring Quality Gate shall per-file ignore、広範な`noqa`、またはbaseline固定によって
   既存のdocstring違反を隠蔽しない。
4. When docstring整備を行う, the Documentation Standard shall Pythonコードの実行時振る舞いを
   変更しない。

### Requirement 4: 追加Docstring品質ツールの採用判定

**Objective:** As a maintainer, I want Ruffで検査できないcoverageまたは内容整合性を根拠を
持って補完したい, so that 依存を増やさずに有用な品質信号だけを導入できる。

#### Acceptance Criteria

1. When 追加のdocstring品質ツールを採用候補として評価する, the Tool Evaluation shall Python
   3.14およびAthenaの開発環境での実行PoCを示す。
2. When 候補ツールがcoverage、引数・戻り値・例外の内容整合性、または別の品質信号を提供する,
   the Tool Evaluation shall Ruff `D` と重複しない役割を明示する。
3. If 候補ツールがpreview機能、保守終了、または確認できないPython 3.14互換性に依存する,
   the Tool Evaluation shall そのツールを必須品質ゲートへ採用しない。
4. Where coverage計測ツールを採用する, the Tool Evaluation shall 対象範囲、測定値、閾値、
   失敗時の扱いを再現可能な形で定義する。

### Requirement 5: 開発者向け規約と実行方法の同期

**Objective:** As a contributor, I want docstring品質の期待値と検証方法を一箇所から理解したい,
so that ローカル確認とCIの結果が一致する。

#### Acceptance Criteria

1. When docstring品質規約または品質ゲートを変更する, the Project Documentation shall 対象範囲、
   Google Styleの期待値、実行方法、追加ツールの役割を同期する。
2. The Project Documentation shall `AGENTS.md` をdocstring品質基準の正本として扱い、
   日本語Google Style規約と品質ゲートの契約を一致させる。
3. When contributorが定義のdocstringを作成または更新する, the Project Documentation shall
   既存の良い実装例または具体的な記述基準を参照できるようにする。

### Requirement 6: Sphinx生成互換性

**Objective:** As a documentation maintainer, I want Athenaのdocstringを別repositoryからSphinxで
生成可能な品質に保ちたい, so that sourceと公開documentationを二重管理せずAPI referenceを
構築できる。

#### Acceptance Criteria

1. The Documentation Standard shall Sphinx Napoleonが解釈するGoogle Style sectionだけを使い、
   custom sectionへ必須情報を置かない。
2. When completed docstring examplesをSphinx autodocとNapoleonで処理する, the Sphinx Readiness
   Validation shall docstring parse warningなしでdocumentを生成する。
3. The Project Boundary shall Sphinxの恒久config、theme、生成物、公開workflowをAthena repositoryへ
   所有させず、別documentation repositoryの責務とする。
4. The Project Documentation shall external documentation repositoryがprivate、`__init__`、dunderを
   必要に応じて生成できるNapoleon/autodoc前提と、module import時の注意点を記録する。

## Supporting Evidence

- `.kiro/specs/python-docstring-quality/research.md` はRuff `D`、Google convention、候補ツールの
  一次情報調査を記録する。
