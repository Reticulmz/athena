# 実装計画

> **並列実行規則:** (P)付きtaskはspec/python-docstring-qualityからtask専用worktreeを作る。
> Task 1.*と5.*は同じtooling ownerが直列に担当する。corpus taskは共有tooling、生成hook、
> project documentation、spec fileを編集しない。

- [ ] 1. Foundation: canonical standardと非blocking toolchainを整備する
- [x] 1.1 Python docstringのcanonical standardを定義する
  - AGENTS.mdでtracked first-party Pythonの全module、class、function、methodを必須対象とし、
    private、nested、dunder、Protocol、abstract、overload、property、test、fixture、fake、helperを
    除外しない規則へ更新する
  - Args:、Returns:、Yields:、Raises:、Attributes:、Examples:、Notes:の使い分け、section内の型、
    None return、__init__だけのReturns:省略、直接送出または意図的伝播exception、class attribute、
    ASCII punctuationの規則を明文化する
  - 通常function、None return、class Attributes:、__init__、private helper、contractを説明するtestの
    compactなcanonical exampleを追加する
  - README.md、docs/architecture.md、.kiro/steering/tech.mdはAGENTS.mdを唯一の規範として参照し、
    3 toolの役割、local command、external Sphinx repository、autodoc import時の注意だけを同期する
  - 完了条件: 4つの文書surfaceが矛盾せず、Sphinx config、dependency、site、generated artifactを
    Athenaへ追加していない
  - _Requirements: 1.3, 2.1, 2.2, 2.3, 2.4, 3.3, 5.1, 5.2, 5.3, 6.1, 6.3, 6.4_
  - _Boundary: AGENTS.md, README.md, docs/architecture.md, .kiro/steering/tech.md_

- [x] 1.2 承認済みdocstring toolchainをglobal gate未有効の状態で追加する
  - Python 3.14でinterrogate 1.7.0とpydoclint 0.9.1のPoCを再実行し、Ruff Dと重複しない価値、
    Ruff DOCを採用しない理由、他の不採用候補の判断を再確認する
  - 2 toolをdev-only dependencyとして追加し、uv.lockを更新する。interrogateはsphinx styleで
    100%、pydoclintはGoogle/private/signature整合を有効化し、Raises AST比較とclass attribute比較は
    設計どおり無効化する
  - RuffへGoogle pydocstyle conventionだけを設定し、global selectへのD追加はまだ行わない
  - tests/unit/test_docstring_quality_configuration.pyを規約準拠docstring付きで作成し、version、
    設定、意図的な無効化、baseline、broad exclude、docstring noqa、per-file ignore不在を検査する
  - Python 3.14 PoCと採用根拠をresearch.mdへ記録する
  - 完了条件: uvが承認versionを解決し、両CLIがfocused fixtureで動作し、configuration testが通り、
    未整備corpusのために既存quality commandがblockingされていない
  - _Depends: 1.1_
  - _Requirements: 1.1, 1.3, 1.4, 3.3, 4.1, 4.2, 4.3, 4.4_
  - _Boundary: pyproject.toml, uv.lock, tests/unit/test_docstring_quality_configuration.py, research.md_

- [x] 1.3 First-party Python inventoryと非blocking docstring commandを実装する
  - scripts/ci.shへNUL-safeなGit index inventoryを追加し、tracked first-party .pyを所有する。
    Git repository外、empty inventory、.pyi、ignored artifact、cache、generated file、untracked
    dependencyは拒否または除外する
  - python-filesはinventoryを1 path 1行で表示し、docstringsは同一inventoryへRuff D、
    interrogate、pydoclintを実行する
  - configuration testでpython-filesとGit indexを比較し、spaceを含むpathとstaged new .pyを検証する
  - quality、fix、flake.nix、pre-commitへの統合はcorpus完了まで行わない
  - 完了条件: python-filesがindexed first-party inventoryと一致し、docstringsが3 toolを起動して
    現行負債をnon-zeroで可視化し、既存quality behaviorを維持する
  - _Depends: 1.2_
  - _Requirements: 3.1, 3.2, 3.3, 4.4, 5.1_
  - _Boundary: scripts/ci.sh, tests/unit/test_docstring_quality_configuration.py_

- [x] 1.4 pydoclintをactive quality gateから撤去し、Ruffとinterrogateへ移行する
  - pydoclintのdev dependency、tool configuration、lock上の不要なpackage entry、docstrings commandの
    invocationを撤去し、Ruff Dとinterrogateだけが同一Git inventoryを検査する状態にする
  - configuration testを更新し、Ruff/Google conventionとinterrogate 100%を保護するとともに、activeな
    dependency/config/gate surfaceにpydoclintとbaselineが存在しないことを検査する
  - AGENTS.md、README.md、docs/architecture.md、.kiro/steering/tech.md、research.mdを同期し、historical
    PoC evidenceは保持したまま、現在の不採用判断と`Annotated`対応時の再評価条件を正本化する
  - uv sync、focused configuration test、docstrings commandを実行し、後者がRuff Dとinterrogateのみを
    起動して未整備corpusをnon-zeroで報告することを確認する
  - 完了条件: active gateと文書が2 tool構成に一致し、pydoclintのPoC記録と将来の再評価条件だけが
    research evidenceとして残る
  - _Depends: 1.3_
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 3.1, 3.2, 3.3, 4.1, 4.2, 4.3, 4.4, 5.1_
  - _Boundary: pyproject.toml, uv.lock, scripts/ci.sh, tests/unit/test_docstring_quality_configuration.py, AGENTS.md, README.md, docs/architecture.md, .kiro/steering/tech.md, research.md_

- [ ] 2. Productionとruntime corpusを整備する
  - 2.*の共通完了条件: implementation、call site、relevant testを読み、所有する全definitionを
    日本語Google Styleで説明する。Args:/Returns:/Yields:/Raises:/Attributes:の型と意味、class attribute、
    直接送出または意図的伝播exceptionをimplementation、call site、relevant testと手動照合する。型整合に
    必要なprecise signature annotationだけを追加し、runtime statement、control flow、decorator、constant、
    suppressionを変更しない。所有pathのRuff D、interrogate 100%、relevant testを通す
  - testを所有するtaskは、test名の言い換えではなくcontract、condition、observable outcomeを説明する

- [x] 2.1 (P) Athena CLI core sourceを整備する
  - src/athena_cli/*.py、src/athena_cli/commands/**、src/athena_cli/env/**へ共通条件を適用する
  - 新しいfunction docstringがTyper helpへ露出する箇所は、従来descriptionなしならdecoratorへ
    help=""を明示してobservable helpを維持する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびCLI command construction testが通り、help contractが不変である
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/athena_cli/*.py, src/athena_cli/commands/**, src/athena_cli/env/**_

- [x] 2.2 (P) Athena CLI core testとhelp contractを整備する
  - tests/unit/athena_cli/*.pyとtests/integration/athena_cli/*.pyへ共通条件を適用し、
    stable_verification/**とtest_cli_stable_verify.pyは除外する
  - rootとsubcommandの既存help expectationを変更せず、description contractを明示的に保護する
  - 完了条件: scoped Ruff Dとinterrogate 100%および所有するCLI unit/integration testが通り、visible helpが不変である
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: tests/unit/athena_cli/*.py, tests/integration/athena_cli/*.pyからtest_cli_stable_verify.pyを除く_

- [x] 2.3 (P) Stable verificationのgetscores source modelを整備する
  - catalog.py、getscores.py、getscores_evidence.py、models.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびfocused getscores verification testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/athena_cli/stable_verification/{catalog,getscores,getscores_evidence,models}.py_

- [x] 2.4 (P) Stable verificationのreplayとscore submission sourceを整備する
  - client.py、parsers.py、replay_download.py、score_submit.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびfocused replay/score-submit verification testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/athena_cli/stable_verification/{client,parsers,replay_download,score_submit}.py_

- [x] 2.5 (P) Stable verificationの残りのruntime sourceとtestを整備する
  - __init__.py、osu_py_probe.py、reporting.py、runner.pyと、catalog、client、osu_py_probe、parsers、replay、
    reporting、runner、score_submitのunit test、test_cli_stable_verify.pyへ共通条件を適用する
  - CLI helpとreport outputを維持する
  - 完了条件: scoped Ruff Dとinterrogate 100%および所有するstable verification testが出力差分なしで通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/athena_cli/stable_verification/{__init__,osu_py_probe,reporting,runner}.pyと明記した対応test_

- [x] 2.6 (P) Stable verificationのgetscores testを整備する
  - test_getscores.py、test_getscores_completion_evidence.py、test_getscores_contract.py、
    test_models.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および所有するgetscores testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したtests/unit/athena_cli/stable_verificationの4 file_

- [x] 2.7 (P) Application entry pointとtop-level compositionを整備する
  - src/osu_server/*.pyとsrc/osu_server/composition/*.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびapplication、worker、lifecycle、composition testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/osu_server/*.py, src/osu_server/composition/*.py_

- [x] 2.8 (P) Infrastructureとrepository composition providerを整備する
  - providers配下のidentity.py、infrastructure.py、performance.py、performance_cli.py、
    repositories.py、repository_adapters.py、storage.py、worker.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびprovider graph/replacement testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したsrc/osu_server/composition/providersの8 file_

- [x] 2.9 (P) Client familyとapplication composition providerを整備する
  - src/osu_server/composition/providers配下で2.8が所有しない全fileへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびstable、chat、beatmap、score、app、test provider graph testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/osu_server/composition/providers/**から2.8の所有fileを除く_

- [x] 2.10 (P) Beatmap、chat、event、storage domain contextを整備する
  - domain/__init__.pyとdomain/{beatmaps,chat,events,storage}/**へ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびrelevant domain testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/osu_server/domain/__init__.py, domain/{beatmaps,chat,events,storage}/**_

- [x] 2.11 (P) Identityとstable compatibility domain contextを整備する
  - domain/identity/**とdomain/compatibility/**へ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびidentity/stable compatibility domain testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/osu_server/domain/{identity,compatibility}/**_

- [x] 2.12 (P) Scores domain contextを整備する
  - domain/scores/**へ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および全score domain testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/osu_server/domain/scores/**_

- [x] 2.13 (P) Shared primitiveとjob adapterを整備する
  - src/osu_server/shared/**とsrc/osu_server/jobs/**へ共通条件を適用し、task nameとobservable outcomeを
    維持する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびshared、job、worker-job、job-boundary testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/osu_server/shared/**, src/osu_server/jobs/**_

- [x] 2.14 (P) Volatile state infrastructureを整備する
  - src/osu_server/infrastructure/state/**へ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および全state-store testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/osu_server/infrastructure/state/**_

- [x] 2.15 (P) Beatmap、storage、cache infrastructureを整備する
  - infrastructure/{beatmaps,storage,cache}/**へ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびbeatmap provider/blob-storage testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/osu_server/infrastructure/{beatmaps,storage,cache}/**_

- [x] 2.16 (P) Messaging、job、performance、HTTP infrastructure contractを整備する
  - infrastructure/{messaging,jobs,performance,http}/**とtests/unit/infrastructure/messaging/**へ
    共通条件を適用する
  - LocalEventBusとDistributedEventEnvelopeの既存英語contract phraseを日本語docstring内に保持する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびmessaging、performance、HTTP testが通り、phrase assertionが不変である
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/osu_server/infrastructure/{messaging,jobs,performance,http}/**, tests/unit/infrastructure/messaging/**_

- [x] 2.17 (P) 残りのinfrastructure adapterを整備する
  - infrastructure/*.pyとinfrastructure/{country,crypto,database,parsers,security}/**へ共通条件を
    適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびdatabase、crypto、parser、security、logging、country testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/osu_server/infrastructure/*.py, infrastructure/{country,crypto,database,parsers,security}/**_

- [x] 2.18 (P) Command repository interfaceを整備する
  - repositories/interfaces/commands/**へ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびcommand repository contract testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/osu_server/repositories/interfaces/commands/**_

- [x] 2.19 (P) Queryとtransaction repository interfaceを整備する
  - repositories/__init__.py、repositories/interfaces/*.py、interfaces/queries/**へ共通条件を
    適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびquery、session-store、Unit of Work contract testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/osu_server/repositories/__init__.py, interfaces/*.py, interfaces/queries/**_

- [x] 2.20 (P) In-memory command repositoryを整備する
  - repositories/memory/commands/**へ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびin-memory command repository testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/osu_server/repositories/memory/commands/**_

- [x] 2.21 (P) In-memory queryとUnit of Work repositoryを整備する
  - repositories/memory/*.pyとrepositories/memory/queries/**へ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびin-memory query、session-store、Unit of Work testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/osu_server/repositories/memory/*.py, memory/queries/**_
  - _Approved exception: 2026-07-22に利用者承認。`InMemoryUnitOfWorkFactory.commit_state` からreplay stateの連続3操作を `_commit_replay_state()` へ抽出する振る舞い保存refactorを許可する。操作順、container identity、UoW observable behaviorを維持し、suppression、per-file ignore、lint上限緩和は追加しない。_

- [x] 2.22 (P) SQLAlchemyのbeatmap/performance command repositoryを整備する
  - commands配下のbeatmap_leaderboards.py、beatmap_performance_bests.py、beatmaps.py、
    score_performance.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびfocused SQLAlchemy command repository testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したsrc/osu_server/repositories/sqlalchemy/commandsの4 file_

- [x] 2.23 (P) 残りのSQLAlchemy command repositoryを整備する
  - repositories/sqlalchemy/commands配下で2.22が所有しない全fileへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびfocused SQLAlchemy command repository testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/osu_server/repositories/sqlalchemy/commands/**から2.22の所有fileを除く_

- [x] 2.24 (P) SQLAlchemy query repositoryを整備する
  - repositories/sqlalchemy/queries/**へ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および全SQLAlchemy query repository testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/osu_server/repositories/sqlalchemy/queries/**_

- [x] 2.25 (P) Persistence model、SQLAlchemy Unit of Work、Valkey repositoryを整備する
  - repositories/sqlalchemy/*.py、repositories/sqlalchemy/models/**、repositories/valkey/**へ
    共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびmodel、enum、Unit of Work、Valkey session repository testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/osu_server/repositories/sqlalchemy/*.py, sqlalchemy/models/**, valkey/**_

- [x] 2.26 (P) Beatmapとchat command use-caseを整備する
  - services/commands/*.pyとservices/commands/{beatmaps,chat}/**へ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびrelevant beatmap/chat command testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/osu_server/services/commands/*.py, commands/{beatmaps,chat}/**_

- [x] 2.27 (P) Identityとstorage command use-caseを整備する
  - services/commands/{identity,storage}/**へ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびidentity/blob-storage command testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/osu_server/services/commands/{identity,storage}/**_

- [x] 2.28 (P) Score performance command use-caseを整備する
  - services/commands/scores/performance/**へ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および全score performance command testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/osu_server/services/commands/scores/performance/**_

- [x] 2.29 (P) Score submission processingとauthorizationを整備する
  - services/commands/scores/process_submission.pyとauthorization.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびscore submission/authorization testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/osu_server/services/commands/scores/{process_submission,authorization}.py_

- [x] 2.30 (P) 残りのscore command use-caseを整備する
  - services/commands/scores配下からperformance/**、process_submission.py、authorization.pyを
    除いた全fileへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびleaderboard、replay accounting、submission、stats projection testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/osu_server/services/commands/scores/**から2.28と2.29の所有pathを除く_

- [x] 2.31 (P) Beatmap、chat、storage query use-caseを整備する
  - services/queries/{beatmaps,chat,storage}/**へ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびrelevant query testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/osu_server/services/queries/{beatmaps,chat,storage}/**_

- [x] 2.32 (P) Identity query use-caseを整備する
  - services/queries/identity/**へ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびidentity query testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/osu_server/services/queries/identity/**_

- [x] 2.33 (P) Score query use-caseとservice package moduleを整備する
  - services/__init__.py、services/queries/*.py、services/queries/scores/**へ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびscore query testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/osu_server/services/__init__.py, queries/*.py, queries/scores/**_

- [x] 2.34 (P) Caterpillar-backed Bancho protocol definitionを整備する
  - transports/stable/bancho/protocol/**へ共通条件を適用し、wire nameとprotocol valueを維持する
  - 完了条件: scoped Ruff Dとinterrogate 100%および全Bancho protocol fixture/codec testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/osu_server/transports/stable/bancho/protocol/**_

- [x] 2.35 (P) Bancho handlerとlistenerを整備する
  - transports/stable/bancho/{handlers,listeners}/**へ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびfocused handler/listener testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/osu_server/transports/stable/bancho/{handlers,listeners}/**_

- [x] 2.36 (P) Bancho dispatch、mapping、parsing、workflowを整備する
  - transports/stable/bancho/*.pyとbancho/{mappers,parsers,workflows}/**へ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびdispatch、endpoint、login、polling、workflow testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/osu_server/transports/stable/bancho/*.py, bancho/{mappers,parsers,workflows}/**_

- [x] 2.37 (P) Legacy web mapperを整備する
  - transports/stable/web_legacy/mappers/**へ共通条件を適用し、legacy field nameとresponse semanticsを
    維持する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびmapper/fixture testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/osu_server/transports/stable/web_legacy/mappers/**_

- [x] 2.38 (P) Legacy endpointと残りのtransport moduleを整備する
  - transports/*.py、transports/{api,lazer}/**、transports/stable/*.py、
    transports/stable/web_legacy/*.pyへ共通条件を適用する
  - Signature annotation追加時もFastAPI、Pydantic、Starlette、legacy endpoint metadataを維持する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびrelevant transport/endpoint testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: src/osu_server/transports/*.py, transports/{api,lazer}/**, stable/*.py, web_legacy/*.py_

- [ ] 3. Test corpusを整備する
  - 3.*の共通完了条件: 全module、test、fixture、fake、helper、nested definition、dunder、propertyへ
    日本語Google Style docstringを記述する。各testはcontract、condition、observable outcomeを説明する。
    Args:、Noneを含むReturns:、Yields:、Raises:、Attributes:、Notes:の型と意味をimplementation、
    fixture、assertionと手動照合する。既存assertionとtest behaviorを変更せず、scoped Ruff D、
    interrogate 100%、所有testを通す

- [x] 3.1 (P) Shared test supportを整備する
  - tests/support/**へ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびsupport依存のfocused testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: tests/support/**_

- [x] 3.2 (P) Root fixture、factory、end-to-end testを整備する
  - tests/*.py、tests/factories/**、tests/fixtures/**、tests/e2e/**へ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびfactory/end-to-end testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: tests/*.py, tests/factories/**, tests/fixtures/**, tests/e2e/**_

- [x] 3.3 (P) Compositionとfactory unit testを整備する
  - tests/unit/composition/**とtests/unit/factories/**へ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および所有unit testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: tests/unit/{composition,factories}/**_

- [x] 3.4 (P) Domain context package testを整備する
  - tests/unit/domain/{compatibility,identity,scores}/**へ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および所有domain testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: tests/unit/domain/{compatibility,identity,scores}/**_

- [x] 3.5 (P) Core authentication、chat、beatmap domain testを整備する
  - tests/unit/domain配下のtest_auth.py、test_bancho_bot.py、test_beatmap.py、test_blob.py、
    test_bounded_context_rehomes.py、test_channel.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および6 fileのtestが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したtests/unit/domainの6 file_

- [ ] 3.6 (P) 残りのroot domain testを整備する
  - tests/unit/domain/*.pyから3.5の所有fileを除いた全fileへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および所有domain testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: tests/unit/domain/*.pyから3.5の所有fileを除く_

- [x] 3.7 (P) Architectureとdependency boundary unit testを整備する
  - tests/unit/__init__.py、test_architecture_*.py、test_blob_config.py、test_di_integration.py、
    test_event_boundaries.py、test_forbidden_words.py、test_job_boundaries.pyへ共通条件を適用する
  - tooling ownerのtests/unit/test_docstring_quality_configuration.pyは編集しない
  - 完了条件: scoped Ruff Dとinterrogate 100%および所有architecture/boundary testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したtests/unit root fileでtooling ownerのconfiguration testを除く_

- [x] 3.8 (P) Handler、lifecycle handler、routing unit testを整備する
  - test_handler_group.py、test_lifecycle_handlers.py、test_routing.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および3 fileのtestが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: tests/unit/{test_handler_group,test_lifecycle_handlers,test_routing}.py_

- [ ] 3.9 (P) Listener、worker、logging、entry-point unit testを整備する
  - test_listener_group.py、test_lifecycle_listeners.py、test_log_rotation.py、
    test_osu_server_main.py、test_worker.py、test_worker_jobs.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および6 fileのtestが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したtests/unit rootの6 file_

- [ ] 3.10 (P) State infrastructure unit testを整備する
  - tests/unit/infrastructure/state/**へ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および全state infrastructure testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: tests/unit/infrastructure/state/**_

- [ ] 3.11 (P) Beatmap file/provider infrastructure testを整備する
  - test_beatmap_file_providers.pyとtest_beatmap_providers.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および2 fileのtestが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したtests/unit/infrastructureの2 file_

- [ ] 3.12 (P) Beatmap metadata/country infrastructure testを整備する
  - test_beatmap_metadata_providers.py、test_osu_api_metadata_provider.py、
    test_country_resolver.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および3 fileのtestが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したtests/unit/infrastructureの3 file_

- [ ] 3.13 (P) Configuration/blob-storage infrastructure testを整備する
  - test_config.py、test_blob_storage_backend_selection.py、test_blob_storage_contracts.py、
    test_local_blob_storage.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および4 fileのtestが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したtests/unit/infrastructureの4 file_

- [ ] 3.14 (P) 残りのnon-messaging infrastructure unit testを整備する
  - tests/unit/infrastructure/*.py、crypto/**、performance/**から3.11-3.13の所有fileを除き、
    messaging/**とstate/**も除外した全fileへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびdatabase、crypto、HTTP、logging、parser、performance、query、
    Valkey testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: tests/unit/infrastructureからstate、messaging、3.11-3.13の所有fileを除く_

- [ ] 3.15 (P) Jobとshared unit testを整備する
  - tests/unit/jobs/**とtests/unit/shared/**へ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および所有testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: tests/unit/{jobs,shared}/**_

- [ ] 3.16 (P) Memoryとidentity-oriented SQLAlchemy repository testを整備する
  - tests/unit/repositories/memory/**と、sqlalchemy配下のtest_chat_command_repository.py、
    test_current_user_stats_command_repository.py、test_user_command_repository.py、
    test_user_integrity_errors.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および所有repository testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: tests/unit/repositories/memory/**と明記したsqlalchemyの4 test file_

- [ ] 3.17 (P) SQLAlchemy beatmap leaderboard repository testを整備する
  - test_beatmap_leaderboard_command_repository.py、test_beatmap_leaderboard_query_repository.py、
    test_beatmap_performance_best_command_repository.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および3 fileのtestが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したtests/unit/repositories/sqlalchemyの3 file_

- [ ] 3.18 (P) SQLAlchemy replay/score command repository testを整備する
  - test_replay_download_query_repository.py、test_score_command_repository.py、
    test_score_performance_command_repository.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および3 fileのtestが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したtests/unit/repositories/sqlalchemyの3 file_

- [ ] 3.19 (P) SQLAlchemy aggregate query repository testを整備する
  - test_sqlalchemy_query_repositories.pyとtest_user_stats_query_repository.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および2 fileのtestが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したtests/unit/repositories/sqlalchemyの2 file_

- [ ] 3.20 (P) SQLAlchemy Unit of Work testを整備する
  - tests/unit/repositories/sqlalchemy/test_sqlalchemy_unit_of_work.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびUnit of Work testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: tests/unit/repositories/sqlalchemy/test_sqlalchemy_unit_of_work.py_

- [ ] 3.21 (P) Repository migration testを整備する
  - tests/unit/repositories/*migration*.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および全migration testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: tests/unit/repositories/*migration*.py_

- [ ] 3.22 (P) Root beatmap repository testを整備する
  - tests/unit/repositories/test_beatmap*.pyからmigration fileを除いた全fileへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および全beatmap repository testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: tests/unit/repositories/test_beatmap*.pyから*migration*.pyを除く_

- [ ] 3.23 (P) Root blob、channel、chat repository testを整備する
  - test_blob_model.py、test_blob_repository_contract.py、test_blob_repository_memory.py、
    test_channel_repository.py、test_chat_repository_contract.py、
    test_sqlalchemy_blob_repository.py、test_sqlalchemy_chat_repository.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および7 fileのtestが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したtests/unit/repositories rootの7 file_

- [ ] 3.24 (P) Root score、replay、personal-best repository testを整備する
  - test_current_user_stats_command_repository_contract.py、test_in_memory_score_repository.py、
    test_personal_best_command_repository_contract.py、test_personal_best_query_repository_contract.py、
    test_replay_download_query_repository_contract.py、
    test_score_performance_command_repository_contract.py、
    test_score_performance_query_repository_contract.py、test_score_repository_protocol.py、
    test_user_stats_query_repository_contract.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および9 fileのtestが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したtests/unit/repositories rootの9 file_

- [ ] 3.25 (P) 残りのroot repository contract testを整備する
  - tests/unit/repositories/__init__.py、test_friend_relationship_repository_contract.py、
    test_persistence_boundary_contracts.py、test_role_repository.py、test_user_repository.pyへ
    共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および5 fileのtestが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したtests/unit/repositories rootの5 file_

- [ ] 3.26 (P) BanchoBot command service testを整備する
  - tests/unit/services/bancho_bot/test_command_service.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびcommand service testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: tests/unit/services/bancho_bot/test_command_service.py_

- [ ] 3.27 (P) 残りのBanchoBot testを整備する
  - tests/unit/services/bancho_bot/**からtest_command_service.pyを除いた全fileへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および所有BanchoBot testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: tests/unit/services/bancho_bot/**からtest_command_service.pyを除く_

- [ ] 3.28 (P) Beatmap command use-case testを整備する
  - tests/unit/services/commands/beatmaps/**へ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および全beatmap command testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: tests/unit/services/commands/beatmaps/**_

- [ ] 3.29 (P) Score performance provider/create/execute testを整備する
  - test_beatmap_file_provider.py、test_create_recalculation_batch.py、
    test_execute_calculation.py、test_future_scope_boundaries.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および4 fileのtestが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したtests/unit/services/commands/scores/performanceの4 file_

- [ ] 3.30 (P) Score performance process/projection/request/runtime testを整備する
  - test_process_recalculation_batch.py、test_projection_refresh.py、
    test_request_calculation.py、test_runtime_settings.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および4 fileのtestが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したtests/unit/services/commands/scores/performanceの4 file_

- [ ] 3.31 (P) 残りのcommand use-case testを整備する
  - tests/unit/services/commands/*.py、commands/chat/**、commands/scores/*.pyへ共通条件を適用し、
    performance/**は除外する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびpersistence、leaderboard、replay、score、projection testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: tests/unit/services/commandsのroot、chat、performance外のscore file_

- [ ] 3.32 (P) Primary score query testを整備する
  - test_beatmap_leaderboards.py、test_current_user_stats_query.py、
    test_legacy_getscores.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および3 fileのtestが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したtests/unit/services/queries/scoresの3 file_

- [ ] 3.33 (P) 残りのquery use-case testを整備する
  - tests/unit/services/queries/beatmaps/**、queries/storage/**、queries/scores/**から3.32の所有fileを
    除いた全fileへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および所有query testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: tests/unit/services/queries/{beatmaps,storage}/**と3.32が所有しないscore file_

- [ ] 3.34 (P) Authentication service testを整備する
  - tests/unit/services/test_auth_service.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびauthentication service testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: tests/unit/services/test_auth_service.py_

- [ ] 3.35 (P) Identity mutation/relationship service testを整備する
  - test_change_user_password.py、test_change_user_role.py、
    test_friend_relationship_use_cases.py、test_identity_use_cases.py、
    test_online_sessions.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および5 fileのtestが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したtests/unit/services rootの5 file_

- [ ] 3.36 (P) Identity authorization/credential service testを整備する
  - test_password_service.py、test_permission_service.py、
    test_session_authorization_service.py、test_session_credentials_query.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および4 fileのtestが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したtests/unit/services rootの4 file_

- [ ] 3.37 (P) Chat/blob-storage service testを整備する
  - test_channel_use_cases.py、test_chat_service.py、test_private_message_service.py、
    test_blob_storage_service.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および4 fileのtestが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したtests/unit/services rootの4 file_

- [ ] 3.38 (P) Beatmap service/boundary testを整備する
  - test_beatmap_boundary_separation.py、test_beatmap_eligibility.py、
    test_beatmap_freshness_policy.py、test_beatmap_mirror_service.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および4 fileのtestが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したtests/unit/services rootの4 file_

- [ ] 3.39 (P) Score service testとservices test packageを整備する
  - tests/unit/services/__init__.pyとtests/unit/services/test_score_*.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および全score service testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: tests/unit/services/__init__.py, tests/unit/services/test_score_*.py_

- [ ] 3.40 (P) Bancho protocol C2S/core testを整備する
  - test_beatmap_info_fixtures.py、test_c2s_*.py、test_enums.py、test_header.py、
    test_reader.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および所有protocol testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したtests/unit/transports/bancho/protocol file_

- [ ] 3.41 (P) Bancho protocol S2C/fixture testを整備する
  - test_s2c_*.py、test_presence_fixtures.py、test_stats_fixtures.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および所有protocol testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: tests/unit/transports/bancho/protocol/test_s2c_*.pyと明記した2 fixture file_

- [ ] 3.42 (P) Bancho protocol type/writer testを整備する
  - protocol/__init__.py、test_types.py、test_writer.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および所有protocol testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: tests/unit/transports/bancho/protocol/{__init__,test_types,test_writer}.py_

- [ ] 3.43 (P) Bancho message/presence handler testを整備する
  - test_chat_handlers.py、test_friend_handlers.py、test_presence_handlers.py、
    test_stats_request_handler.py、test_status_handlers.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および5 fileのhandler testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したtests/unit/transports/banchoの5 file_

- [ ] 3.44 (P) Bancho dispatch/endpoint testを整備する
  - test_di_registration.py、test_dispatch.py、test_e2e_flow.py、test_endpoint.py、
    test_errors.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および5 fileのtestが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したtests/unit/transports/banchoの5 file_

- [ ] 3.45 (P) Bancho workflow/listener testを整備する
  - bancho test package module、listeners/**、test_chat_listeners.py、
    test_login_response_builder.py、test_login_workflow.py、test_polling_workflow.py、
    test_workflow_contracts.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および所有workflow/listener testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したtests/unit/transports/banchoのworkflow/listener file_

- [ ] 3.46 (P) Transport root/stable mapper unit testを整備する
  - tests/unit/transports/*.pyとtests/unit/transports/stable/**へ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および所有transport testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: tests/unit/transports/*.py, tests/unit/transports/stable/**_

- [ ] 3.47 (P) Legacy getscores endpoint unit testを整備する
  - tests/unit/transports/web_legacy/test_getscores_*.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および全getscores testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: tests/unit/transports/web_legacy/test_getscores_*.py_

- [ ] 3.48 (P) Legacy replay/score-submit unit testを整備する
  - web_legacy test package module、test_replay_download_*.py、test_score_*.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および所有replay/score-submit testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: tests/unit/transports/web_legacy/{__init__,test_replay_download_*,test_score_*}.py_

- [ ] 3.49 (P) Database、migration、SQLAlchemy integration testを整備する
  - test_database.py、test_enum_scope_migration_postgresql.py、test_sqlalchemy_*.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および所有integration testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したtests/integration root file_

- [ ] 3.50 (P) Application、authorization、Valkey integration testを整備する
  - tests/integration/__init__.py、test_app_startup.py、test_authorization_refresh.py、
    test_valkey*.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および所有integration testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したtests/integration file_

- [ ] 3.51 (P) Beatmap、blob、score、score-submit integration testを整備する
  - tests/integration/services/**、test_beatmap_leaderboard_reconciliation.py、
    test_blob_storage_sqlalchemy.py、test_score_submission_integration.py、
    test_user_stats_game_flow.py、transports/web_legacy/__init__.py、
    transports/web_legacy/test_score_submit*.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および所有integration testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したtests/integrationのservice、root、web_legacy file_

- [ ] 3.52 (P) Legacy getscores integration testを整備する
  - tests/integration/test_getscores_*.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および全getscores integration testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: tests/integration/test_getscores_*.py_

- [ ] 3.53 (P) Chat、C2S、friend、replay-download integration testを整備する
  - test_c2s_pipeline.py、test_chat_e2e.py、test_chat_pipeline.py、
    test_friend_relationship_pipeline.py、transports/web_legacy/test_replay_download_endpoint.pyへ
    共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および5 fileのintegration testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したtests/integrationの5 file_

- [ ] 3.54 (P) Login、registration、polling integration testを整備する
  - test_login_flow.py、test_registration_flow.py、test_polling_e2e.pyへ共通条件を適用する
  - 完了条件: scoped Ruff Dとinterrogate 100%および3 fileのintegration testが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: 明記したtests/integrationの3 file_

- [ ] 4. Ancillary first-party Python corpusを整備する
  - 4.*の共通完了条件: production/testの該当する共通条件を適用し、Google Style sectionの型と意味を
    implementationとrelevant testまたはexecution probeに照らして手動確認する。Ruff D、interrogate
    100%、focused validation以外のruntime behaviorは変更しない
- [ ] 4.1 (P) Alembic Python moduleを整備する
  - alembic/env.pyとalembic/versions/**へproduction共通条件を適用し、migration identifier、
    schema operation、upgrade/downgrade behavior、textual DDL justificationを維持する
  - 完了条件: scoped Ruff Dとinterrogate 100%およびmigration testがschema operation差分なしで通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: alembic/env.py, alembic/versions/**_

- [ ] 4.2 (P) 残りのtracked first-party Python assetを整備する
  - gitlint_rules/**、athena-crypto/tests/**、tracked .agents/**/*.pyへproductionまたはtest共通条件を
    適用し、skill example behaviorとgitlint rule semanticsを維持する
  - 完了条件: scoped Ruff Dとinterrogate 100%および各assetのfocused testまたはexecution probeが通る
  - _Depends: 1.4_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_
  - _Boundary: gitlint_rules/**/*.py, athena-crypto/tests/**/*.py, tracked .agents/**/*.py_

- [ ] 5. Gate activation、Sphinx readiness、final validationを行う
- [ ] 5.1 Repository-wide docstring gateを有効化する
  - 既存のnon-docstring ruleを維持したままRuff global selectへDを追加し、Google conventionの
    documented exclusion以外のdocstring ignoreを追加しない
  - Configuration testを完成させ、global D、D417、interrogate 100%、pydoclint dependency/configの不在、
    baseline/suppression escape hatch不在を検査する
  - docstringsをqualityへ統合し、Ruff format/lint/fixを同じfirst-party .py inventoryへ統一する。
    BasedPyrightとimport-linterの既存scopeは維持する
  - Direct gate invocationでもtypings/**/*.pyiや他のnon-first-party fileをRuff Dへ渡さない
  - 完了条件: python-filesがGit inventoryと一致し、docstringsがRuff D 0件とinterrogate 100%を返し、
    qualityが通り、pydoclintとtypingsがdocstring scope外である
  - _Depends: 2.1-2.38, 3.1-3.54, 4.1, 4.2_
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 3.1, 3.2, 3.3, 4.4, 5.1_
  - _Boundary: pyproject.toml, scripts/ci.sh, tests/unit/test_docstring_quality_configuration.py_

- [ ] 5.2 Generated pre-commit hookとdeveloper documentationを同期する
  - flake.nixでRuff format/lint hookをuv lock済みRuffへ統一し、.pyだけにmatchさせて.pyiを除外する
  - First-party .py変更時にfull docstring hookを起動し、pass_filenamesを無効化してscripts/ci.shを
    inventoryの唯一のownerにする。.pre-commit-config.yamlはflake.nixから再生成し、直接編集しない
  - README.md、docs/architecture.md、.kiro/steering/tech.mdをfinal command/hook behaviorへ同期し、
    .github/workflows/ci.ymlは変更しない
  - 完了条件: generated hookがuv toolchainを使い、typings変更ではRuff Dを起動せず、Python source
    変更ではfull gateを起動し、local/CI entryの文書が一致する
  - _Depends: 5.1_
  - _Requirements: 1.1, 1.2, 3.2, 3.3, 5.1, 5.2_
  - _Boundary: flake.nix, generated .pre-commit-config.yaml, README.md, docs/architecture.md, .kiro/steering/tech.md_

- [ ] 5.3 Transient Sphinx/Napoleon readiness PoCを再実行する
  - Repository外のtemporary directoryへSphinx 9.1.0 autodoc/Napoleon projectを作り、
    Google docstringとprivate、__init__、special memberを有効にする
  - Domain、services、repositories、infrastructure、transports、CLI、testsから代表的なimport-safe
    moduleを選び、sphinx-build -W -b htmlを実行する
  - Exact environment、代表module、warning 0、external repositoryのimport/environment前提を
    research.mdへ記録する
  - Temporary source/build directoryを削除し、AthenaにSphinx dependency、config、stub、theme、
    generated outputがないことを確認する
  - 完了条件: warning-as-error buildが成功し、承認済みexternal documentation boundaryが維持される
  - _Depends: 5.2_
  - _Requirements: 6.1, 6.2, 6.3, 6.4_
  - _Boundary: .kiro/specs/python-docstring-quality/research.mdとrepository外のtemporary directory_

- [ ] 5.4 Full validationとfinal diff reviewを行う
  - nix develop経由で./scripts/ci.sh docstrings、./scripts/ci.sh quality、
    ./scripts/ci.sh test、prek run --all-filesを実行する
  - Indexed first-party .pyが全件対象で、Ruff D 0件、interrogate 100%であり、pydoclint dependency/config、
    新しいpyright ignore、type ignore、noqa、per-file ignore、baselineがないことを確認する
  - Full diffをlayer boundary、security-sensitive text、日本語Google Style品質、手動Attributes:/
    Raises: coverage、Typer/introspection compatibility、承認済みhelp metadataとprecise annotation以外の
    runtime statement差分不在の観点でreviewする
  - Review fix後にaffected focused testを再実行する
  - 完了条件: 全local gateが成功し、全requirementを満たし、implementation PR作成前に未検証項目がない
  - _Depends: 5.3_
  - _Requirements: 1.1, 1.2, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 5.1, 6.2_
  - _Boundary: validationとreviewのみで新しいfeature scopeを追加しない_

## Implementation Notes

- `__init__`は`Returns:`を記載しない例外であり、それ以外の`None` return callableは`Returns: None`を記載する.
- 全corpus taskはRuff Dとinterrogateに加え、ASTでdocstring token中のnon-ASCII punctuationが0件であることを確認する. `。`と`、`はASCII `.`と`,`へ置換し、runtime stringは変更しない.
