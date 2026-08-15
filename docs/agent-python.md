# Python Agent Policy

Read this before editing first-party Python, Python tests, local `.pyi` stubs, or Python lint/type/docstring policy.

## Code Quality

- Target Python 3.14+ for all first-party Python. Prefer modern syntax that the
  runtime and configured tools support.
- Do not write new code as if Python 3.11 or 3.12 were the style ceiling.
  Python 3.13 typing features are available; use Python 3.14 annotation behavior
  only where current tooling, imports, and runtime readers accept it.
- Use built-in generic collections and union syntax: `list[str]`, `dict[str, int]`,
  and `Path | None`; avoid legacy `typing.List`, `typing.Dict`, `typing.Tuple`,
  `typing.Optional`, and `typing.Union` in new code.
- Use modern type tools when they express the contract directly: `type` statements
  for aliases, `typing.Self` for fluent/self-returning APIs, and
  `typing.override` for overrides. Use `typing.TypeIs` for precise predicate
  narrowing and `typing.ReadOnly` for read-only `TypedDict` items.
- Prefer `match`/`case` for closed, shape-driven branching such as protocol
  variants, enum-like command kinds, and parsed tuple/dict/dataclass shapes.
  Keep `if`/`elif` for simple boolean predicates and range checks.
- Prefer unquoted annotations in new code. Avoid quoted forward references and
  routine `from __future__ import annotations` only when current tooling, imports,
  and runtime annotation readers all accept eager annotations.
- Do not add compatibility shims for Python versions below 3.14.
- Prefer established project patterns and architecture.
- Prefer idiomatic Python and async-first designs.
- Make intent explicit; avoid magic numbers and opaque conditionals.
- Diagnose root causes instead of adding workarounds.
- Do not hardcode credentials. Use config objects or environment variables.
- Use library-first judgment, but get user approval before adding dependencies.
- Avoid unnecessary abstraction.

## Dishka Dependency Injection Policy

Dishka is Athena's composition tool, not an application service locator.

- Define production providers under `apps/athena_server/src/osu_server/composition/providers/`.
  Graph assembly belongs in `providers/container.py`; framework integration belongs in
  `composition/*_integration.py` or lifespan code.
- Use `Provider` subclasses with a class-level `scope` and factory methods decorated with
  `osu_server.composition.providers._dishka.provide`. Do not use imperative `.provide(...)`
  registration in production provider modules; keep it in test override helpers such as
  `TestProviderSet`.
- Keep Dishka imports out of domain code, services, repository interfaces, and infrastructure
  adapters. Runtime adapters may use framework-specific injection only at route or job function
  boundaries. Do not pass `AsyncContainer`, `FromDishka`, `Provider`, or `Scope` into use-case
  inputs or domain objects.
- Use `Scope.APP` for process-lifetime dependencies: config, engines, clients, brokers, storage,
  state stores, stateless services, and stateless adapters. Use `Scope.REQUEST` only for
  per-request or per-job state and resources with a shorter lifetime. Use `Scope.SESSION` only
  when the integration exposes a long-lived connection/session scope. Do not put mutable
  request, user, or connection state in `Scope.APP`.
- Providers that open resources must yield them from async generator factories and release them
  after `yield`. Consumers do not close Dishka-owned objects; application and worker shutdown
  close the container.
- If a provider needs framework context such as Starlette `Request`, `WebSocket`, or Taskiq
  context, pass it through Dishka integration context data such as `from_context`, not globals or
  ad hoc attributes. Keep framework context at the adapter/composition boundary.
- Tests replace dependencies by passing override providers after the production provider set.
  Prefer `TestProviderSet`, `replace_value`, and `replace_factory`, which register
  `override=True`. Do not branch production providers on `config.environment == "test"`.
- Do not use `skip_validation=True` in app or worker container construction. If a graph change
  adds or replaces a provider, add or run a focused provider graph test that resolves the new
  dependency and closes the container.

## Python Docstring Standard

この節はAthenaのPython docstring品質に関する唯一の規範である。README、architecture
guide、steeringは実行方法とtoolの役割だけを案内し、この節の意味規則を複製しない。

### 対象範囲と言語

- リポジトリで追跡するfirst-party Python moduleと、その全class / function / methodには
  docstringを必須とする。packageの`__init__.py`、private、nested、dunder、decorator付き定義、
  `Protocol`、abstract method、`@overload`、propertyも例外にしない。
- module docstringはmoduleの責務と適用範囲を説明する。class / function / methodのdocstringは、
  挙動、呼び出し側の前提条件、制約を説明する。
- test function / method、fixture、fake、stub、helperも同じ対象である。testは検証する契約、
  入力条件、期待するobservable outcomeを説明し、test名の言い換えだけで終わらせない。fixture、
  fake、stub、helperは利用目的、提供する状態、利用上の制約を説明する。
- docstringは日本語で書く。外部仕様名、wire field名、error code、protocol value、既存の
  contract phraseは原文のまま使ってよいが、その意味とAthena側の判断は日本語で補足する。
- 追跡対象外のthird-party source、generated artifact、`.pyi`はこの規範の対象外であり、
  それぞれの所有者が定める規則に従う。

### Google Style Sections

Google Styleを使い、必須情報をcustom sectionへ置かない。Napoleonが解釈する次のsectionだけを
使う。

- `Args:`は、呼び出し側から渡す各引数を`name (type): 意味`で記載する。型は実際のannotationと
  矛盾させない。`self`と`cls`は呼び出し入力ではないため記載しない。
- `Returns:`は、通常のreturn valueを持つcallableで`type: 意味`を記載する。`None`を返す
  callableでは`None: 呼び出し側へ値を返さずに完了する意味`を記載する。`__init__`だけは
  `Returns:`を置かない。
- `Yields:`はgenerator / async generatorが順に生成する値を`type: 意味`で記載する。値をyieldする
  callableの主たる出力は`Yields:`で説明する。
- `Raises:`は、呼び出し側が扱うべき直接送出exceptionまたは意図的に伝播するexceptionだけを
  `ExceptionType: 発生条件`で記載する。発生しない場合やcaller contractではない内部exceptionの
  ためにsectionを追加しない。
- `Attributes:`はclass bodyのattributeとdataclass fieldをpublic / privateを問わず
  `name (type): 意味`で記載する。propertyはattribute欄へ読み替えず、getter / setterの
  docstringで挙動、引数、戻り値、例外を記載する。
- `Examples:`は、利用方法、wire contract、前提が短い説明だけでは伝わらない場合に、再現可能な
  usage exampleを記載する。
- `Notes:`は、呼び出し側が知るべき前提条件、制約、non-obvious invariantを記載する。
  `Constraints:`などのcustom sectionは使わない。

要約行はASCIIの`.`, `?`, `!`のいずれかで終える。日本語docstring内の`()`, `:`, `/`, `-`には
ASCII文字を使い、見分けにくいfullwidth punctuationを使わない。

### Canonical Examples

通常のfunctionは引数、return value、callerが扱うexception、制約を一致させる。

```python
def normalize_username(raw_name: str, *, allow_empty: bool = False) -> str:
    """ログイン用のユーザー名を正規化して返す.

    Args:
        raw_name (str): 正規化対象の入力値.
        allow_empty (bool): 正規化後の空文字列を許可するか.

    Returns:
        str: 前後空白を除去して小文字化したユーザー名.

    Raises:
        ValueError: allow_emptyがFalseで正規化後の値が空の場合.

    Notes:
        Unicode正規化は呼び出し側のtransport boundaryで完了していること.
    """
```

`None`を返すcallableにも、値を返さずに完了する意味を記載する。

```python
async def publish_session_revocation(session_id: str) -> None:
    """指定したsessionの失効通知を発行する.

    Args:
        session_id (str): 失効したsessionの識別子.

    Returns:
        None: 通知を発行し、呼び出し側へ値を返さずに完了する.

    Raises:
        EventBusUnavailableError: 通知基盤へ接続できない場合.
    """
```

class bodyのattributeとdataclass fieldはclass docstringで説明する。

```python
@dataclass(slots=True)
class SessionWindow:
    """sessionが有効な時間範囲を表す.

    Attributes:
        started_at (datetime): sessionが有効になった時刻.
        expires_at (datetime): sessionを拒否する時刻.
    """

    started_at: datetime
    expires_at: datetime
```

`__init__`は初期化の引数と制約を記載するが、`Returns:`を持たない。

```python
class SessionCache:
    """session単位の短期cacheを提供する.

    Attributes:
        namespace (str): cache keyを分離する接頭辞.
    """

    def __init__(self, namespace: str) -> None:
        """session cacheを初期化する.

        Args:
            namespace (str): 空文字列ではないcache keyの接頭辞.

        Raises:
            ValueError: namespaceが空文字列の場合.
        """
```

private helperもpublic definitionと同じ情報量で記載する。

```python
def _parse_retry_delay(header_value: str | None) -> timedelta | None:
    """Retry-After headerを待機時間へ変換する.

    Args:
        header_value (str | None): response headerから取得した値.

    Returns:
        timedelta | None: 解釈可能な待機時間. 値がないか不正な場合はNone.
    """
```

testは契約、条件、observable outcomeを明示する。

```python
def test_expired_session_is_rejected(client: TestClient, expired_session: Session) -> None:
    """期限切れsessionを拒否する認証契約を検証する.

    期限切れsessionを含むrequestを送信し、認証済みresourceへ到達せずHTTP 401になることを確認する.

    Args:
        client (TestClient): 認証requestを送信するtest client.
        expired_session (Session): 有効期限を過ぎたsession fixture.

    Returns:
        None: 拒否responseを検証して完了し、呼び出し側へ値を返さない.
    """
```

### Quality Gate And Sphinx Handoff

- `just docstrings`はRuff `D`でGoogle Styleの存在と形式を、`interrogate`で
  対象definitionの完全性を検証する。Args:/Returns:/Yields:/Raises:/Attributes:の型と意味はこの
  規約を正本とし、implementation、call site、relevant testを照合してreviewする。各toolの設定は
  この意味規則を弱めるper-file docstring ignore、docstring `noqa`、tool-level broad exclude、
  baselineを追加してはならない。
- `pydoclint`はTyperの`Annotated` metadataを基底型として比較できないためactive gateへ含めない。
  公式対応が確認できた場合だけ、`.kiro/specs/python-docstring-quality/research.md`のfixtureで
  再評価する。
- RuffのGoogle conventionでは`D203`、`D204`、`D213`、`D215`、`D400`、`D401`、`D404`、
  `D406`、`D407`、`D408`、`D409`、`D413`をGoogle Styleの対象外として明示する。これは
  conventionとの競合を解消する選択であり、`D417`を含む他のdocstring ruleを追加ignoreで
  緩和してはならない。
- Sphinxのdependency、`conf.py`、RST stub、theme、generated artifact、公開workflowはAthenaでは
  所有せず、external documentation repositoryが所有する。そのrepositoryは`autodoc`がmoduleを
  importすることを前提に、Athenaと必要dependencyをinstallし、environmentと対象moduleを選択する。
  private、`__init__`、dunderを生成する場合はNapoleon / autodocの対応するinclude optionを設定する。

## Type Safety And Lint Policy

Resolve pyright and ruff issues structurally. Suppression is the last resort, and only after the reason is documented.

Avoid these shortcuts:

- file-level `# pyright: reportXxx=false`
- broad `# type: ignore`
- casual `# noqa`
- inline `# pyright: ignore[...]`
- using `AsyncMock` to hide `Any`
- changing linter/type-checker config to silence errors

For tests, prefer typed in-memory implementations or Protocol-compliant stubs over untyped mocks. Test code follows the same type-safety standard as production code.

### Resolution Steps

When encountering type or lint errors, resolve in this order:

1. Fix the code. If the type is wrong, fix the type.
2. Use in-memory implementations or stubs to structurally avoid `Any` from mocks.
3. Search for community type stubs such as `types-*` packages on PyPI, typeshed, or third-party GitHub stubs.
4. Generate stubs with `basedpyright --createstub <package>`.
5. Manually refine generated stubs. Server/test-only stubs live under `apps/athena_server/typings/`; public `athena_crypto` stubs live under `packages/athena_crypto/typings/`.
6. Use inline suppression only after the earlier steps have been tried, and document the reason in a comment.
