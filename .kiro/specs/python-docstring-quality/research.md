# Python docstring 品質ツール調査

調査日時: 2026-07-19 JST

対象は公式ドキュメント、公式GitHubリポジトリ、PyPIの公式プロジェクトページに限定した。依存関係や設定はまだ変更していない。

## 結論

1. 第一段階は、既存のRuffに `D` を追加し、`[tool.ruff.lint.pydocstyle] convention = "google"` を設定するのが妥当である。追加依存なしで、Google Styleに反する形式と公開定義のdocstring欠落を継続的に検出できる。
2. Ruff単体は数値のdocstring coverageを計測したり、coverage閾値で失敗させたりする機能を提供していない。全定義を対象にした数値目標が必要なら、coverage専用ツールを別途導入する必要がある。
3. 数値coverageが必要な場合の第一候補は `interrogate` である。ただし最新リリースは2024-04-07で、PyPIのPython classifierは3.12までである。AthenaのPython 3.14環境でのPoCを通過するまで採用を決定しない。
4. Google StyleのArgs/Returns/Raisesなどと実装の整合性を深く検証する候補は `pydoclint` である。2026-07-03に0.9.1が公開され、現行PyPI metadataの `Requires-Python >=3.10` は3.14を許容する。ただし3.14 classifierはないため、実行PoCを前提にする。docstring自体の存在は検査しないため、Ruff `D` と組み合わせる。
5. Ruffの `DOC` 規則は `pydoclint` 由来だが、Athenaが固定しているRuff 0.15.13ではpreview扱いである。今回の必須gateにはせず、stable化後に再評価する。

## Ruff pydocstyle (`D`) の確認結果

Astral公式FAQでは、Google Styleを使うには `D` を明示的に有効化し、`lint.pydocstyle.convention` を `google` に設定するよう案内している。既存の `select` を置き換えず、そこへ `"D"` を追加する構成が必要である。

```toml
[tool.ruff.lint]
select = [
    # 既存の規則群
    "D",
]

[tool.ruff.lint.pydocstyle]
convention = "google"
```

Google conventionを設定すると、当該規約に含まれない `D` 規則は無効化される。規約を超えて有効にしたい規則は完全な規則コードで追加し、緩和したい規則は明示的にignoreする。特に `D417` は引数ごとの記載を要求するため、AthenaのGoogle Style要件と照らして採否を設計時に決める。

`D100` から `D107` はdocstringの有無を検出する規則群である。公開module/class/method/function/package、public nested class、magic method、`__init__` を対象にする。一方で、通常のprivate function/class/methodを網羅する欠落規則は `D` にはない。したがって、AGENTS.mdが求めるprivate定義を含む整備完了は、`D` だけでは機械的に保証できない。

Ruffの公式settings/rulesリファレンスと、ロック済みRuff 0.15.13のCLIを確認した範囲では、docstring coverageの百分率、集計、`fail-under`に相当する設定はない。`D` は違反を個別に報告するlint規則であり、coverage計測器ではない。

Ruffには `DOC` 規則群もあり、たとえば `DOC201` は値を返す関数に `Returns` sectionがないことを検出する。しかしローカルのRuff 0.15.13ではpreview規則で、`--preview` が必須である。安定したCI契約にpreview規則を入れることは今回推奨しない。

## 専用ツール候補

| ツール | 用途 | Python 3.14との関係 | 保守性と注意点 | 判断 |
| --- | --- | --- | --- | --- |
| Ruff `D` | 存在・形式・Google conventionのlint | 現行Ruff公式settingsとAthenaのlock済み0.15.13 CLIはいずれも `py314` をtarget-versionとして受け付ける | 追加依存なし。private通常定義の欠落と数値coverageは扱えない | 採用する |
| Ruff `DOC` | Returns/Yields等と実装の一部整合性 | Ruff内蔵 | 0.15.13ではpreview | 今回は見送る |
| `interrogate` 1.7.0 | module/class/function/methodのcoverage率、詳細一覧、`fail-under` | docsはPython 3.8以上を掲げる一方、現行PyPI classifierは3.12まで。3.14の公式実行確認は未確認 | 最新releaseは2024-04-07だが、公式repoはarchivedではなく2026-06-01にもpushされている。Google style設定、privateを除外しない既定値、`pyproject.toml`設定を持つ | 数値KPIが必要ならPoC候補 |
| `pydoclint` 0.9.1 | Google Styleの引数・戻り値・yield・raise・属性と実装の整合性、baseline | 現行PyPI metadataは `Requires-Python >=3.10` で3.14を許容するが、3.14 classifierはない。実行確認は未確認 | 最新releaseは2026-07-03。docstringがない定義は検査しないため、Ruff `D` 又はcoverageツールを併用する | 内容検証を追加する次段階のPoC候補 |
| `docstr-coverage` 2.3.2 | coverage率、`fail-under`、privateやmagic methodの対象制御 | 公式PyPIページでPython 3.14を明示的には確認できなかった | 最新releaseは2024-05-07。YAML専用設定を主とするため、`interrogate`よりAthenaの現行設定方式との親和性が低い | 採用しない |
| `darglint` | 引数・戻り値の検査 | 未確認 | 公式GitHubリポジトリがarchivedで、最終pushは2022-12-08 | 採用しない |

## Ruffとの役割分担

```text
Ruff D       = docstringの有無とGoogle Styleの基本形式
interrogate  = 全対象のcoverage率と閾値
pydoclint   = 書かれたArgs/Returns/Raises等と実装の整合性
```

この3つは重複ではなく、検査対象が異なる。今回の最小構成はRuff `D` のみとし、coverageの数値目標が要件として必要なら `interrogate` のPoCを追加する。`pydoclint` はdocstringが一通り揃った後に導入すると、初期の違反量と設定判断を分離できる。

## 導入前に決める事項

1. coverageの対象を `src/` のみとするか、`tests/` も含めるか。
2. private定義も100%対象にするか。Ruff `D` だけではこの方針を強制できない。
3. coverageを初回から100%とするか、現状値をbaselineとして段階的に引き上げるか。
4. `D417` の引数記載要求を必須とするか。AthenaのGoogle Style規約は型・意味の明記を要求しているため、原則は有効を推奨する。

## 根拠

- [Ruff FAQ: Google/NumPy Style docstring設定](https://docs.astral.sh/ruff/faq/#does-ruff-support-numpy-or-google-style-docstrings) (2026-07-19確認)
- [Ruff settings: `lint.pydocstyle.convention`](https://docs.astral.sh/ruff/settings/#lint-pydocstyle-convention) (2026-07-19確認)
- [Ruff rules: pydocstyle (`D`)](https://docs.astral.sh/ruff/rules/#pydocstyle-d) (2026-07-19確認)
- [Ruff rule: `DOC201`](https://docs.astral.sh/ruff/rules/docstring-missing-returns/) (2026-07-19確認)。Athenaのlock済み0.15.13でも `nix develop --command uv run ruff rule DOC201` でpreview要件を確認した。
- [Ruff FAQ: 置換できるツール一覧](https://docs.astral.sh/ruff/faq/#which-tools-does-ruff-replace) (2026-07-19確認)。`pydocstyle` と `flake8-docstrings` をRuffで置換可能と記載している。
- [`interrogate` 公式ドキュメント](https://interrogate.readthedocs.io/en/latest/) (2026-07-19確認)
- [`interrogate` 公式PyPIページ](https://pypi.org/project/interrogate/) (2026-07-19確認)
- [`interrogate` 1.7.0 release](https://github.com/econchick/interrogate/releases/tag/1.7.0) (2026-07-19確認)
- [`pydoclint` 公式README](https://github.com/jsh9/pydoclint) (2026-07-19確認)
- [`pydoclint` 公式PyPIページ](https://pypi.org/project/pydoclint/) (2026-07-19確認)
- [`pydoclint` 0.9.1 release](https://github.com/jsh9/pydoclint/releases/tag/0.9.1) (2026-07-19確認)
- [`docstr-coverage` 公式PyPIページ](https://pypi.org/project/docstr-coverage/) (2026-07-19確認)
- [`docstr-coverage` v2.3.2 release](https://github.com/HunterMcGushion/docstr_coverage/releases/tag/v2.3.2) (2026-07-19確認)
- [`darglint` 公式GitHubリポジトリ](https://github.com/terrencepreilly/darglint) (2026-07-19確認)

---

# Implementation Gap Analysis

分析日時: 2026-07-19 JST

## Analysis Summary

- 現行品質基盤はRuff、Nix生成pre-commit、`scripts/ci.sh quality`を既に持つため、Google
  Styleの基本lintは既存構成の拡張で実現できる。ただし`D`とpydocstyle conventionは未設定である。
- core first-party候補837ファイルにGoogle conventionのRuff `D`違反が5,313件ある。
  `.agents/`のPython asset 2件を含めると5,345件であり、変更範囲はリポジトリ全体に及ぶ。
- Ruffの欠落検査は通常のprivate/nested定義を保護しない。独立AST監査ではcore定義10,578件の
  うち6,635件にdocstringがなく、private名の欠落だけで1,872件あった。
- CIは`src/ tests/`だけを検査する一方、pre-commit Ruffは変更された全Pythonへ作用する。
  さらにCI/uvはRuff 0.15.13、Nix生成hookは0.15.17で、ローカルとCIの一致要件に既存gapがある。
- 追加docstringは`__doc__`を変える。Typer command helpやdocstring内容を直接検査する既存testへの
  影響を確認しないと、実行時挙動不変の要件を保証できない。

## Analysis Preconditions

- `spec.json`の`approvals.requirements.approved`は`false`である。skill規定に従ってgap分析は
  実施したが、設計へ進む前に要件の承認または改訂が必要である。
- core steeringは`.kiro/steering/tech.md`だけが存在し、標準の`product.md`と`structure.md`は
  存在しない。技術制約は`tech.md`、`AGENTS.md`、実際の品質gateから補完した。
- 分析は現行コード調査、ローカルRuff 0.15.13による実測、一次情報による依存候補調査、
  要件の独立レビューを並行実施して統合した。

## Current State Investigation

### Python Scope Inventory

| Root | Python files | Current gate relationship |
| --- | ---: | --- |
| `src/` | 457 | CI、local quality、pre-commitの対象 |
| `tests/` | 352 | CI、local quality、pre-commitの対象 |
| `alembic/` | 25 | pre-commitは対象、CIの明示path外 |
| `gitlint_rules/` | 2 | pre-commitは対象、CIの明示path外 |
| `athena-crypto/tests/` | 1 | pre-commitは対象、root CIの明示path外 |
| `.agents/` Python assets | 2 | hidden asset。対象に含めるか未確定 |
| `typings/` `.pyi` | 117 | third-party stub。要件のout-of-scope候補 |

`src/`から`athena-crypto/tests/`までをcore first-party候補とすると837ファイルである。
`.agents/`のtemplate/scriptを含めると839ファイルになる。`ruff check .`は`typings/`にも作用するため、
単純なrepository root指定ではthird-party stubの2,554件をdocstring対象へ混入させる。

### Existing Assets and Integration Points

| Asset | Existing capability | Extension point |
| --- | --- | --- |
| `pyproject.toml` | Ruffの既存select/ignore、`src = ["src", "tests"]` | `D`とGoogle conventionの追加、必要なら専用tool設定 |
| `scripts/ci.sh` | format、lint、type、importの統合quality command | 対象rootとdocstring完全性checkの追加 |
| `.github/workflows/ci.yml` | `./scripts/ci.sh quality`を実行 | `scripts/ci.sh`の変更がCIへ伝播 |
| `flake.nix` | Ruff/pre-commit hookの生成元 | 専用hookまたはversion整合が必要な場合の変更元 |
| `.pre-commit-config.yaml` | Nixから生成されたhook結果 | `DO NOT MODIFY`であり直接編集不可 |
| `AGENTS.md` | 日本語Google Style、型・意味・例外・制約、ASCII記号の規約 | private存在要件と終端記号などの明文化 |
| `tests/unit/athena_cli/test_packaging.py` | `pyproject.toml`を`tomllib`で検査 | `D`とconventionの設定回帰testを追加可能 |
| `tests/unit/test_architecture_package_skeletons.py` | module docstringを許容するAST判定 | package rootへのdocstring追加と共存可能 |

### Measured Baseline

Ruff 0.15.13で`D`と`convention = "google"`を一時指定した実測値:

| Scope | Ruff D violations |
| --- | ---: |
| `src/` | 1,555 |
| `tests/` | 3,703 |
| `alembic/`、`gitlint_rules/`、`athena-crypto/tests/` | 55 |
| core合計 | 5,313 |
| `.agents/` assetを含む追加分 | 32 |

core 5,313件のうち4,171件はmissing-docstring規則、1,142件は形式規則である。Ruffが安全に
自動修正可能と報告するのは279件であり、大半は定義の責務を読んで記述する必要がある。

独立AST存在監査ではcoreのmodule/class/function/method/nested定義10,578件中、docstringあり
3,943件、欠落6,635件だった。これはRuffや`interrogate`の公式coverage値ではなく、Ruffが
検査しないprivate/nested領域の規模を把握するための調査値である。

主なhotspot:

- `tests/unit/`: Ruff違反3,175件
- `src/osu_server/repositories/`: 419件
- `tests/integration/`: 341件
- `src/osu_server/services/`: 316件
- `src/athena_cli/`: 221件

## Requirement-to-Asset Map

| Requirement | Existing assets | Gap classification and details |
| --- | --- | --- |
| R1 Google Style gate | Ruff、`pyproject.toml`、quality script、CI、pre-commit | **Missing**: `D`とpydocstyle convention。**Constraint**: 既存select/ignoreを維持する。**Constraint**: Ruff 0.15.13/0.15.17のversion drift |
| R2 first-party完全性 | `AGENTS.md`規約、詳細な日本語docstringの既存例 | **Missing**: 6,635件のAST欠落候補。**Missing**: private/nestedの自動gate。**Unknown**: 対象rootと定義種別。**Constraint**: 日本語内容はRuffだけで保証できない |
| R3 違反0と将来保護 | CI、pre-commit、抑制禁止方針 | **Missing**: 全rootを同じ対象にするcommand。**Missing**: private完全性check。**Constraint**: `D`を先にglobal enableするとcleanup完了までhookが全変更を阻害する |
| R4 追加tool評価 | 既存`research.md`、Python 3.14.4環境 | **Missing**: `interrogate`/`pydoclint`の3.14 PoC、誤検知、runtime、対象判定。**Constraint**: dependencyとlock変更には明示承認が必要 |
| R5 規約と実行方法 | `AGENTS.md`、README群、quality script、Nix hook | **Missing**: 対象scope・完全性定義・具体例の単一参照元。**Constraint**: 現在のCIとpre-commitの対象が一致しない |

## Explicit Gaps and Constraints

### 1. Target Scope Is Not Closed

「追跡されるfirst-party Python」は`src/ tests/`より広いが、次の扱いが未確定である。

- Alembic revisionの`upgrade`/`downgrade`
- `gitlint_rules/`
- `athena-crypto/tests/`
- `.agents/`内のexecutable scriptとtemplate asset
- `typings/`のthird-party stubを明示除外する方法

CI path、pre-commit path、coverage tool pathが同じ集合を指すよう、設計でscope manifestを固定する
必要がある。

### 2. Requirements Are Stronger Than Current Policy

`AGENTS.md`は新規または変更するpublic定義にdocstringを要求し、private定義は「書く場合」の内容規則を
定めている。Requirements 2/3は、既存を含むすべてのprivate定義へ存在まで要求している。この強化を
意図した方針として`AGENTS.md`へ反映するか、要件側の対象を調整しなければR5と矛盾する。

### 3. Ruff D Does Not Prove Content Completeness

- `D417`は既に`Args:` sectionがあるdocstring内の引数漏れだけを検査し、section自体を要求しない。
- Ruff `D`は通常のprivate定義を欠落検査しない。
- 日本語であること、型と意味が正しいこと、制約が実装と一致することは検査しない。
- `D415`は日本語の`。`を終端記号として認めないため、要約行の終端をASCII `.`, `?`, `!`の
  いずれにするか規約同期が必要である。
- 既存の`Constraints:` custom sectionは129件ある。Google Styleの`Notes:`へ統合するか、
  Athena extensionとして維持するかを決める必要がある。

### 4. Definition Semantics Are Underspecified

完全性checkの対象として次を確定する必要がある。

- nested callback/function
- dunder method
- override/Protocol/abstract method
- property、setter、classmethod、staticmethod
- dataclass field、private field、継承attribute
- pytest test function/method、fixture、typed fake/stub
- `Raises:`に記録する例外の範囲
- `None`を返す全callableで`Returns:`を要求するか

特に「発生し得る全例外」は静的に閉じられないため、意図的に送出または公開contractとして伝播する例外
など、検証可能な定義へ狭める必要がある。

### 5. Quality Gates Differ Today

- GitHub CIと`./scripts/ci.sh quality`は`src/ tests/`だけをRuffへ渡す。
- Nix生成pre-commit Ruffは`types = ["python"]`へ`ruff check --fix`を実行し、変更されたmigration、
  asset、stubにも作用し得る。
- uv lockのRuffは0.15.13だが、生成済みpre-commit hookのNix Ruffは0.15.17である。
- `.pre-commit-config.yaml`は生成物なので、修正元は`flake.nix`または実行command側である。

同一configでもversionとinput pathが異なるため、R5の「ローカル確認とCIの結果一致」は現状満たされない。

### 6. Docstrings Can Be Runtime-Observable

- Typer command functionにdocstringを追加すると、command help説明として表示される可能性がある。
  現在の`athena dev change-password --help`にはcommand descriptionがない。
- `LocalEventBus.__doc__`の`cross-replica`、`DistributedEventEnvelope.__doc__`の
  `not a durable source of truth`と`no replay guarantee`をtestが直接検査している。
- module docstringを無視してpackage inertnessを調べる既存AST testは追加と共存できる。

R3.4を満たすには、CLI help snapshot、docstring contract assertions、公開OpenAPI等のintrospection consumerを
変更前後で確認し、意図しないuser-observable差分を検出する必要がある。

## External Dependency Feasibility

### Ruff `D`

- 現行0.15.13で利用可能であり、追加依存は不要。
- Google conventionは複数の`D`規則を除外するため、実際の有効規則集合を設計に記録する必要がある。
- `DOC201`等の`DOC`規則は現行公式資料でもPreviewで、必須gateには適さない。

### `interrogate` 1.7.0

- coverage、`fail-under`、`pyproject.toml`設定があり、Ruffと異なる品質信号を提供する。
- `Requires-Python >=3.8`だがclassifierは3.12までで、AthenaのPython 3.14実行は未確認。
- private/nested/test/overload等の実測対象と終了codeを一時環境PoCで確認する必要がある。

### `pydoclint` 0.9.1

- Args/Returns/Yields/Raises等と実装の整合性を検査し、Ruff `D`と異なる役割を持つ。
- `Requires-Python >=3.10`だが3.14 classifierと公式CI確認はない。
- 日本語Google Style、decorator、overload、Caterpillar生成定義への誤検知をPoCする必要がある。

## Implementation Approach Options

### Option A: Extend Existing Gates With Ruff and a Repository-Owned AST Audit

既存`pyproject.toml`、quality script、CI、Nix hookを拡張し、private/nested完全性だけを小さな
repository-owned AST checkerまたはcontract testで補う。

**Changes and integration**:

- Ruff `D`とGoogle conventionを既存configへ追加する。
- 全対象rootを共有するdocstring check commandをquality scriptから呼ぶ。
- AST checkerで対象定義と除外理由をAthena側のcontractとして固定する。
- `tests/unit/athena_cli/test_packaging.py`等でconfigとscopeを回帰検査する。

**Trade-offs**:

- 追加dependencyがなく、Python 3.14とAthena固有の定義分類を制御しやすい。
- checkerの仕様、例外、testをAthenaが継続保守する必要がある。
- Args/Returns/Raisesの意味整合性は人間reviewまたは別checkが必要である。

### Option B: Create a Dedicated Docstring Quality Toolchain

Ruff `D`に加え、PoCを通過した`interrogate`をcoverage gate、必要なら`pydoclint`を内容整合gateとして
独立commandへまとめる。

**Changes and integration**:

- Python 3.14一時環境で候補versionを固定してPoCする。
- 採用時はdev dependency、lock、tool設定、Nix/CI実行を追加する。
- scope、100% threshold、誤検知時の扱いを一つのcommandへ集約する。

**Trade-offs**:

- coverageと内容整合性を既製toolで測定でき、独自AST logicを減らせる。
- compatibility、保守性、誤検知、複数toolの実行時間に依存する。
- toolの対象modelがAthenaのprivate/Protocol/Caterpillar/test構造に合わない場合、除外が増える。

### Option C: Hybrid, Evidence-Gated Rollout

Ruffの形式lintを既存gateへ統合しつつ、完全性は`interrogate` PoC結果に応じて外部toolまたはAST auditを
選び、内容整合性はdocstring整備後に`pydoclint` PoCで追加判断する。

**Phases**:

1. scope、定義分類、終端記号、例外/attribute、runtime-observable contractを固定する。
2. `interrogate`と`pydoclint`をproject dependencyへ追加せずPython 3.14でPoCする。
3. package/domain単位でdocstringを整備し、CLI helpとdocstring contract testを維持する。
4. 全対象がcleanになったintegration pointで`D`と完全性gateを有効化する。
5. `pydoclint`は誤検知と追加価値が許容できる場合だけ後続gateへ加える。

**Trade-offs**:

- PoC結果に応じて外部toolとlocal checkerを選べ、要件coverageと導入riskの均衡を取りやすい。
- phase間の暫定状態と統合作業を明確に管理しないと、scopeや規約が分岐する。
- 大規模なparallel editはfile ownershipとintegration branchを厳密に分ける必要がある。

## Complexity and Risk

- **Effort: XL**: 837以上のPython file、Ruff違反5,313件、AST欠落候補6,635件、複数のquality
  integration pointを横断する。実装logic自体より、対象定義ごとの正確な説明とレビュー量が支配的である。
- **Risk: High**: scopeと定義意味が未確定で、tool互換性、Ruff version drift、Typer help、既存docstring
  contract、merge conflict、誤った説明の大量生成が主要riskである。

## Design Phase Recommendations

現時点で最も情報損失が少ない設計候補はOption Cである。ただし実装方式はPoC結果後に確定する。
設計では次をdecision gateとして扱う。

1. core scopeを`src/`, `tests/`, `alembic/`, `gitlint_rules/`, `athena-crypto/tests/`とするか、
   `.agents/` assetも含めるか。`typings/`はthird-party stubとして除外するか。
2. private/nested/dunder/override/Protocol/property/test/fixtureの対象規則を定義する。
3. summary終端をASCII punctuationへ統一し、`Constraints:` sectionの扱いを決める。
4. `Raises:`、`Attributes:`、`None` returnの記述範囲を検証可能なcontractへ狭める。
5. Ruff 0.15.13/0.15.17を統一するか、両versionで同じ規則結果を保証する。
6. `interrogate`/`pydoclint`のPython 3.14 PoCを実施し、外部toolかAST auditかを選ぶ。
7. CLI helpと直接`__doc__`を検査するtestをruntime-observable regression gateとして固定する。
8. package/domain単位のfile ownership、integration順序、最終gate有効化pointを設計する。

## Research Needed

- `interrogate` 1.7.0のPython 3.14起動、設定読込、private/nested/testのcoverage、終了code、実行時間。
- `pydoclint` 0.9.1のPython 3.14起動、日本語section、decorator/overload/Protocol/Caterpillarでの誤検知。
- Typerが各command docstringをhelpへ反映する条件と、既存help contractを維持する方法。
- Nix Ruff 0.15.17とuv Ruff 0.15.13で有効なGoogle convention規則集合と結果が一致するか。
- `.agents/` Python assetのownershipと、template codeをfirst-party品質対象に含めるべきか。

---

# Design Discovery

調査日時: 2026-07-19 JST

## 確定した品質境界

- `AGENTS.md`をPython docstring品質基準の正本とする。
- 対象は、追跡されるfirst-party `.py`である`src/`、`tests/`、`alembic/`、
  `gitlint_rules/`、`athena-crypto/tests/`、および`.agents/`内の2件のPython assetとする。
- `typings/`の117件の`.pyi`はthird-party stubなので除外する。`alembic/script.py.mako`など
  Pythonを生成する非`.py` templateも今回の完全性対象には含めない。
- moduleと、public/privateを問わないclass、function、methodを対象とする。nested定義、dunder、
  `__init__`、property getter/setter、Protocol/abstract method、overload、pytest test/fixtureも
  例外なく含める。lambdaやruntime生成callableはdocstringを保持できないため対象外とする。
- test function/method、fixture、fake、helperは、名前の言い換えではなく検証対象contract、条件、
  期待するobservable outcome、利用上の制約を説明する。
- class bodyで宣言するpublic/private attributeとdataclass fieldは`Attributes:`で説明する。
  propertyは各methodのdocstringで説明し、class attributeへ読み替えない。

## Python 3.14 Tool PoC

PoCはproject dependencyを変更せず、`nix develop`内のPython 3.14.4と一時`uvx`環境で行った。

| Tool | Result | Full-scope signal | Design implication |
| --- | --- | --- | --- |
| `interrogate 1.7.0` | 起動・走査成功 | 10,617定義中3,975 documented、6,642 missing、37.4%。full scan約4.9秒 | private、nested、magic、property、overloadを含む100% completeness gateとして採用可能 |
| `pydoclint 0.9.1` | 起動・全839 file走査成功 | 最終候補設定では現状7,011 output linesの違反報告。full scan約5.4秒 | Args/Returns/Yieldsと型注釈の整合gateとして採用可能 |
| Ruff 0.15.13 / 0.15.17 | 両versionで走査成功 | 両方とも同じ5,345件のGoogle `D`違反 | 現状結果は一致するが、将来差分を避けるためuv lock版へ実行元を統一する |

日本語Google Style、private Protocol、dataclass、`__init__`、property、nested function、
`None` return、Raises、overloadを含む12定義のfixtureでは、`interrogate` 100%と
`pydoclint` 0件を同時に達成した。これにより日本語そのもの、Python 3.14 syntax、
decorator、private/nested分類にはblocking compatibility issueがないことを確認した。

`interrogate --style google`はclassまたは`__init__`の片方だけで両方をcoveredとして扱う。
Athenaは両定義へdocstringを要求するため、coverage styleは`sphinx`を使う。この設定は
docstring記法をSphinx Styleへ変えるものではなく、class/constructorのcoverage集計だけを
分離する。Google Styleの形式はRuffと`pydoclint`が検査する。

追加のrepresentative PoCでは、`check-class-attributes = true`がtype annotationを持たない
`StrEnum` memberと`__slots__`をclass attributeとして扱った。`Attributes:`へAthena規約どおり
型を記載するとDOC605になり、解消にはruntime `__annotations__`の追加または個別除外が必要になる。
これはruntime不変と抑制禁止に反するため、pydoclintのclass attribute照合は無効化する。
`Attributes:`の型と意味は`AGENTS.md`、directory review、final diff reviewで保証する。

Signature auditでは7,997 callableのうち、型なしargumentを持つcallableが4件、return annotationが
ないcallableが41件だった。`pydoclint`のargument/return型整合を全scopeで有効にするには、これらへ
precise annotationを追加する必要がある。docstring type contractとSphinx signature品質へ直接必要な
範囲なので本featureへ含めるが、logicや既存pyright suppressionは変更しない。Typer/FastAPIなど
annotationをruntime利用するsurfaceは既存observable behaviorをtestで保護する。

`pydoclint`のRaises検査はfunction body内の直接`raise`を基準にするため、collaboratorから
意図的に伝播するcontract exceptionを正しく扱えない。Athenaの`Raises:`はcallerが扱うべき
直接送出または意図的伝播exceptionを記録し、pydoclintのRaises整合検査だけは無効化する。
Args、Returns、Yields、Attributes、型整合、private、constructorの検査は有効にする。

## Runtime-observable Docstring Investigation

Typer PoCでは、command functionへdocstringを追加すると`--help`のdescriptionが追加された。
decoratorへ`help=""`を明示すると、docstringが存在しても従来のdescriptionなし表示を維持できた。
したがって、CLI commandのdocstring整備前に現行helpをexplicit decorator metadataへ固定し、
integration testで主要help outputを保護する。

現行コードにFastAPI routeはなく、OpenAPI descriptionへdocstringが流れる経路は見つからなかった。
一方、次の既存testは`__doc__`自体をruntime contractとして検査している。

- `LocalEventBus.__doc__`の`cross-replica`
- `DistributedEventEnvelope.__doc__`の`not a durable source of truth`
- `DistributedEventEnvelope.__doc__`の`no replay guarantee`

これらの英語contract phraseは日本語docstring内に原文のまま残す。docstringをAST bodyから除外して
構造を検査する既存testは、docstring追加後も成立する。

## Sphinx Readiness Investigation

Sphinx公式Napoleon documentationは、Google Style docstringをreStructuredTextへ前処理し、
module、class、attribute、method、function、variableのdocstringをautodocへ渡せると説明している。
Athenaが採用する`Args:`、`Attributes:`、`Returns:`、`Yields:`、`Raises:`、`Examples:`、
`Notes:`はすべてNapoleonのsupported sectionである。

公式設定では`napoleon_include_private_with_doc`と`napoleon_include_init_with_doc`のdefaultは
`False`、`napoleon_include_special_with_doc`は`True`である。別documentation repositoryが
private、`__init__`、dunderを生成したい場合は前2項を明示的に`True`にする。

Sphinx autodocはdocument対象moduleをimportし、import side effectも実行する。外部docs repositoryは
Athenaを依存込みでinstallし、必要なtest environmentを設定したうえでmodule selectionを所有する。
Athena側はSphinx config、theme、HTML、deploymentを所有しない。

PyPIの現行Sphinxは9.1.0で、`Requires-Python >=3.12`とPython 3.14 classifierを持つ。
Python 3.14.4の一時`uvx`環境で、`sphinx.ext.autodoc`と`sphinx.ext.napoleon`、private、
`__init__`、special memberを有効化したfixtureを`-W`でHTML buildし、warning 0で成功した。
Sphinxは恒久dependencyへ追加せず、最終validation時のreadiness PoCだけに使う。

Sources:

- [Sphinx Napoleon official documentation](https://www.sphinx-doc.org/en/master/usage/extensions/napoleon.html)
- [Sphinx autodoc official documentation](https://www.sphinx-doc.org/en/master/usage/extensions/autodoc.html)
- [sphinx-build official manual](https://www.sphinx-doc.org/en/master/man/sphinx-build.html)
- [Sphinx PyPI](https://pypi.org/project/Sphinx/)

## Adjacent BasedPyright Suppression Audit

現行first-party Pythonには`# pyright: ignore[...]`が194件、`# type: ignore`が2件ある。
内訳は`src/` 61件、`tests/` 130件、`gitlint_rules/` 3件である。`# noqa` 59件はRuff側の
別contractなのでこの数へ含めない。

抑制にはthird-party typing boundary、negative test、decoratorにcaptureされるnested function、
runtime mutation rejection testなど異なる原因が混在する。除去はstub追加、typed fake、test構造、
protocol、runtime codeの変更を伴い、docstringだけを変える本featureのreview/rollback contractと
一致しない。新しい抑制は本featureでも追加禁止とし、既存抑制の全件auditと削減は直後の独立specへ
分離する。

## Design Decisions

### Decision 1: Ruff + interrogate + pydoclintを採用する

- Ruff `D`とGoogle conventionが存在と基本形式を検査する。
- `interrogate`がRuff対象外のprivate/nested定義を含む100% completenessを検査する。
- `pydoclint`が書かれたArgs/Returns/Yieldsとsignature/type annotationの整合を検査する。
- Ruff `DOC`はpreviewなので採用しない。repository-owned AST checkerは、`interrogate`が必要な
  定義分類をPython 3.14で満たしたため新設しない。

### Decision 2: `AGENTS.md`を機械gateと同じcontractへ明確化する

- 全module/class/function/methodへ日本語Google Style docstringを必須化する。
- `Args:`は`name (type): meaning`、`Returns:`/`Yields:`は`type: meaning`を使う。
- 戻り値がないcallableは`Returns:`で`None`の意味を記す。ただし`__init__`はGoogle Style上
  return valueを持たないconstructorなので`Returns:`を置かない。
- exceptionがない場合は`Raises: なし`と書かずsectionを省略する。
- custom `Constraints:`は使わず、制約・前提条件はGoogle Styleの`Notes:`へ記録する。
- 要約行はASCIIの`.`, `?`, `!`で終える。既存のASCII punctuation規則も維持する。

### Decision 3: Baselineなしの最終一括有効化を行う

global gateを先に有効化すると、未整備領域の5,345件以上の違反が各task commitを阻害する。
各package taskは同じtool設定を対象pathへ明示実行し、全task統合後にRuff `D`、100% coverage、
pydoclint、CI/pre-commit連携を有効化する。baseline、per-file ignore、広範な`noqa`は使わない。

### Decision 4: Python quality実行元をuv lockへ統一する

Nix生成Ruff hookの実行entryを`uv run ruff`へ切り替え、CI、manual command、pre-commitが
同じlock済みversionと`pyproject.toml`を使う。`.pre-commit-config.yaml`は直接編集せず、
`flake.nix`から再生成する。

### Decision 5: Scopeと実行順序を`./scripts/ci.sh`へ集約する

`git ls-files --cached -- '*.py'`を使い、Git index上のtracked first-party `.py`を動的に収集する。
これにより新しいrootやtest fileをscope manifestへ手動追加し忘れる問題を避け、`.pyi`は
拡張子contractで除外する。新規fileはstaging後に通常のtracked scopeへ入る。個別file arrayでの
`interrogate` PoCも37.4%を再現した。

`quality`は収集した全fileのRuff format/lint、`interrogate`、`pydoclint`に加えて既存
basedpyright/import-linterを実行する。`docstrings` subcommandはRuff `D`、`interrogate`、
`pydoclint`だけを再現可能に実行する。CIは既存`quality`呼出しのまま新gateを継承し、
pre-commitはfirst-party Python変更時に`docstrings`を実行する。

### Decision 6: Sphinx生成surfaceは別repositoryへ分離する

AthenaはSphinx/Napoleon-compatibleなsource docstringと一時readiness PoC evidenceだけを所有する。
Sphinx config、API page selection、theme、generated artifact、deploymentは別documentation repositoryが
所有する。これによりruntime repositoryへdocumentation site lifecycleを混在させず、sourceと公開
referenceの二重記述も避ける。

### Decision 7: BasedPyright抑制cleanupは独立specへ分離する

docstring cleanupはbehavior-neutralなdocumentation diffとしてreviewする。194件のpyright suppressionと
2件のtype ignoreは型境界別に原因分析し、structural alternativeへ置き換える独立specで扱う。
本featureは既存抑制を増やさず、docstring変更のついでに無関係な型修正を混在させない。

## Build vs Adopt

private completeness checkerは自作せず`interrogate`を採用する。PoCで必要な定義分類と
Python 3.14互換性を確認でき、独自AST仕様の保守を避けられるためである。callable内容整合も
自作せず`pydoclint`を採用し、Athena固有のRaises contractとruntime annotationを要求する
class attribute照合だけ設定で境界を切る。

## Risks and Mitigations

- **誤った大量説明**: package単位のownership、focused test、reviewを行い、機械的なsummary生成だけで
  完了扱いにしない。
- **CLI help差分**: Typer decoratorへ現行help metadataを固定し、help integration testを追加する。
- **`__doc__` contract破損**: 既存phrase assertionを維持し、対象testを各taskで実行する。
- **merge conflict**: directory ownershipを分割し、`pyproject.toml`、`uv.lock`、`flake.nix`、
  `scripts/ci.sh`、`AGENTS.md`はtooling taskの単一ownerに限定する。
- **quality gate実行時間**: PoCのfull scanは2 tool合計約15秒であり、pre-commitではPython変更時だけ
  実行する。大幅な増加が生じた場合もscopeやthresholdを緩和せず、tool profilingを行う。

## Task 1.2実装時のPython 3.14再検証

実施日時: 2026-07-19 JST

`nix develop`内のPython 3.14.4で、承認済みの`interrogate 1.7.0`と`pydoclint 0.9.1`を
dev dependencyとしてlockした。`nix develop --command uv sync`は88 packageを解決して成功した。

次のfocused fixtureを`/tmp`に作成し、repositoryへfixture artifactを残さずに検証した。
fixtureは日本語Google Styleのmodule、class、`__init__`、private method、dunder、property、
nested function、overload、`None` return、yield、`Raises:`を含む。

| Command | Result | 確認したsignal |
| --- | --- | --- |
| `uv run interrogate --config pyproject.toml /tmp/athena_docstring_quality_probe.py` | `RESULT: PASSED (minimum: 100.0%, actual: 100.0%)` | `sphinx` coverage semanticsがclassと`__init__`を別definitionとして数え、private/nested/dunder/property/overloadを除外しないこと |
| `uv run pydoclint --config pyproject.toml /tmp/athena_docstring_quality_probe.py` | `No violations` | Google StyleのArgs/Returns/Yields、signature type、private definition、constructor、None return、star argument、style mismatch設定がPython 3.14.4で読まれること |

`interrogate`はRuff `D`がcoverage数値と通常のprivate/nested definitionを完全には扱わない部分を
100% thresholdで補う。`pydoclint`はRuff `D`が検査しないArgs/Returns/Yieldsとsignature typeの
整合を補う。このため両toolはRuffと役割が重複しない。

Ruffには`[tool.ruff.lint.pydocstyle] convention = "google"`だけを先に追加した。未整備corpusを
既存quality commandでblockしないため、migration step 1ではglobal `select`または`extend-select`へ
`D`/`D417`を追加していない。最終gate activation taskで`D`を追加するとGoogle conventionにより
`D417`も有効になる。Ruff `DOC`はRuff 0.15.13ではpreviewであり、stableな必須gateへ採用しない。

`pydoclint`はdirect ASTの`raise`だけでは意図的に伝播するcaller-visible exceptionを判定できないため
`skip-checking-raises = true`とした。unannotated `StrEnum` memberと`__slots__`へruntime annotationを
要求するclass attribute照合も、runtime不変と個別ignore禁止に反するため
`check-class-attributes = false`とした。それ以外のcontent checksは有効である。

baseline、baseline生成、tool設定上のbroad exclude、docstring ruleの`noqa`、Ruffのper-file
docstring ignoreは追加していない。`pydoclint`の既定値が表示する`.git|.tox`はtool内部の既定path
filterであり、後続taskがGit indexから渡すfirst-party Python inventoryを隠す設定ではない。

不採用候補の判断は維持する。repository-owned AST checkerは`interrogate`が必要なdefinition分類を
Python 3.14で満たしたため不要であり、`darglint`など保守状況またはPython 3.14互換性を確認できない
候補は必須gateへ入れない。Sphinxはexternal documentation repositoryの責務であり、Athenaのdev
dependencyには追加しない。
