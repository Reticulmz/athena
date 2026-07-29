"""interactive CLI promptを型付きのadapterとして提供する."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol, cast

from athena_cli.env.dsn import DatabaseConnectionParts, ValkeyConnectionParts
from athena_cli.errors import CliUserError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


InitSection = Literal["database", "valkey", "osu_api"]
_INIT_SECTIONS: frozenset[InitSection] = frozenset({"database", "valkey", "osu_api"})


@dataclass(frozen=True, slots=True)
class PromptChoice:
    """checkbox promptで選択可能な表示名と値を表す.

    Attributes:
        name (str): userへ表示する選択肢名.
        value (str): 選択時にproviderから返る内部値.
    """

    name: str
    value: str


class PromptProvider(Protocol):
    """CLI prompt libraryを呼び出すための抽象boundaryを定義する."""

    def checkbox(self, *, message: str, choices: Sequence[PromptChoice]) -> object:
        """複数選択promptを表示してprovider固有の結果を返す.

        Args:
            message (str): userへ表示するprompt message.
            choices (Sequence[PromptChoice]): 選択可能な表示名と内部値.

        Returns:
            object: providerが返した未検証の選択結果.
        """
        ...

    def text(self, *, message: str, default: str | None = None) -> object:
        """text入力promptを表示してprovider固有の結果を返す.

        Args:
            message (str): userへ表示するprompt message.
            default (str | None): userが未入力時に表示するoptionalな既定値.

        Returns:
            object: providerが返した未検証のtext結果.
        """
        ...

    def secret(self, *, message: str) -> object:
        """secret入力promptを表示してprovider固有の結果を返す.

        Args:
            message (str): userへ表示するprompt message.

        Returns:
            object: providerが返した未検証のsecret結果.
        """
        ...

    def confirm(self, *, message: str, default: bool = False) -> object:
        """Boolean confirmation promptを表示してprovider固有の結果を返す.

        Args:
            message (str): userへ表示するprompt message.
            default (bool): userが未入力時に使う既定の確認結果.

        Returns:
            object: providerが返した未検証のconfirmation結果.
        """
        ...


class ExecutablePrompt(Protocol):
    """InquirerPyが返す実行可能promptの最小interfaceを定義する."""

    def execute(self) -> object:
        """promptを実行してprovider固有の結果を返す.

        Returns:
            object: prompt libraryが返した未検証の結果.
        """
        ...


class InquirerPyPromptProvider:
    """InquirerPyをPromptProvider boundaryへ適合させるadapterを提供する."""

    def checkbox(self, *, message: str, choices: Sequence[PromptChoice]) -> object:
        """InquirerPyのcheckbox promptを実行する.

        Args:
            message (str): userへ表示するprompt message.
            choices (Sequence[PromptChoice]): 表示名と内部値を持つ選択肢.

        Returns:
            object: InquirerPyが返した選択結果.

        Raises:
            CliUserError: InquirerPy factoryがcallableでない場合.
            ModuleNotFoundError: InquirerPyをimportできない場合.
        """
        prompt_choices = [{"name": choice.name, "value": choice.value} for choice in choices]
        prompt = _get_prompt_factory("checkbox")(message=message, choices=prompt_choices)
        return _execute_prompt(prompt)

    def text(self, *, message: str, default: str | None = None) -> object:
        """InquirerPyのtext promptを実行する.

        Args:
            message (str): userへ表示するprompt message.
            default (str | None): 未入力時に表示するoptionalな既定値.

        Returns:
            object: InquirerPyが返したtext結果.

        Raises:
            CliUserError: InquirerPy factoryがcallableでない場合.
            ModuleNotFoundError: InquirerPyをimportできない場合.
        """
        prompt = _get_prompt_factory("text")(message=message, default=default or "")
        return _execute_prompt(prompt)

    def secret(self, *, message: str) -> object:
        """InquirerPyのsecret promptを実行する.

        Args:
            message (str): userへ表示するprompt message.

        Returns:
            object: InquirerPyが返したsecret結果.

        Raises:
            CliUserError: InquirerPy factoryがcallableでない場合.
            ModuleNotFoundError: InquirerPyをimportできない場合.
        """
        prompt = _get_prompt_factory("secret")(message=message)
        return _execute_prompt(prompt)

    def confirm(self, *, message: str, default: bool = False) -> object:
        """InquirerPyのconfirmation promptを実行する.

        Args:
            message (str): userへ表示するprompt message.
            default (bool): userが未入力時に使う既定の確認結果.

        Returns:
            object: InquirerPyが返したconfirmation結果.

        Raises:
            CliUserError: InquirerPy factoryがcallableでない場合.
            ModuleNotFoundError: InquirerPyをimportできない場合.
        """
        prompt = _get_prompt_factory("confirm")(message=message, default=default)
        return _execute_prompt(prompt)


@dataclass(frozen=True, slots=True)
class OsuApiPromptResult:
    """official osu! API設定promptから収集した結果を表す.

    Attributes:
        enabled (bool): official osu! API sourceを有効にする場合はTrue.
        client_id (str | None): 有効時に入力したoptionalなclient ID.
        client_secret (str | None): 有効時に入力したoptionalなclient secret.
    """

    enabled: bool
    client_id: str | None
    client_secret: str | None


@dataclass(frozen=True, slots=True)
class PromptAdapter:
    """prompt providerの未検証結果をCLI用の型付き値へ変換する.

    Attributes:
        provider (PromptProvider): promptを表示して結果を取得するadapter.
    """

    provider: PromptProvider = field(default_factory=InquirerPyPromptProvider)

    def select_sections(self) -> tuple[InitSection, ...]:
        """Environment file初期化で収集する設定sectionを選択する.

        Returns:
            tuple[InitSection, ...]: userが選択したdatabaseとValkeyとosu APIのsection.

        Raises:
            CliUserError: provider結果が文字列sectionのsequenceでない場合.
        """
        raw_result = self.provider.checkbox(
            message="Select configuration sections",
            choices=(
                PromptChoice(name="Database", value="database"),
                PromptChoice(name="Valkey", value="valkey"),
                PromptChoice(name="osu! API", value="osu_api"),
            ),
        )
        return tuple(_coerce_section(value) for value in _coerce_string_sequence(raw_result))

    def collect_database_parts(self) -> DatabaseConnectionParts:
        """Database DSNを構築するためのprompt入力を収集する.

        Returns:
            DatabaseConnectionParts: hostとportとdatabaseと認証情報を含む接続情報.

        Raises:
            CliUserError: providerが期待する文字列値を返さない場合.
        """
        return DatabaseConnectionParts(
            host=_coerce_string(self.provider.text(message="Database host", default="localhost")),
            port=_coerce_int(self.provider.text(message="Database port", default="5432")),
            database=_coerce_string(self.provider.text(message="Database name")),
            username=_coerce_string(self.provider.text(message="Database username")),
            password=_coerce_string(self.provider.secret(message="Database password")),
        )

    def collect_valkey_parts(self) -> ValkeyConnectionParts:
        """Valkey DSNを構築するためのprompt入力を収集する.

        Returns:
            ValkeyConnectionParts: hostとportとdatabaseとoptionalな認証情報を含む接続情報.

        Raises:
            CliUserError: providerが期待する文字列値を返さない場合.
        """
        return ValkeyConnectionParts(
            host=_coerce_string(self.provider.text(message="Valkey host", default="localhost")),
            port=_coerce_int(self.provider.text(message="Valkey port", default="6379")),
            database=_coerce_int(self.provider.text(message="Valkey database", default="0")),
            username=_coerce_optional_string(self.provider.text(message="Valkey username")),
            password=_coerce_optional_string(self.provider.secret(message="Valkey password")),
        )

    def collect_osu_api_config(self) -> OsuApiPromptResult:
        """Official osu! API sourceの有効化と認証情報を収集する.

        Returns:
            OsuApiPromptResult: 有効化状態と有効時のclient credentials.

        Raises:
            CliUserError: providerがexpectedなconfirmationまたは文字列値を返さない場合.
        """
        enabled = self.confirm("Enable official osu! API sources?")
        if not enabled:
            return OsuApiPromptResult(enabled=False, client_id=None, client_secret=None)
        return OsuApiPromptResult(
            enabled=True,
            client_id=_coerce_string(self.provider.text(message="osu! API client ID")),
            client_secret=_coerce_string(self.provider.secret(message="osu! API client secret")),
        )

    def confirm(self, message: str, *, default: bool = False) -> bool:
        """providerのconfirmation結果をboolとしてvalidationする.

        Args:
            message (str): userへ表示するconfirmation message.
            default (bool): userが未入力時に使う既定値.

        Returns:
            bool: providerが返したvalidation済みconfirmation結果.

        Raises:
            CliUserError: provider結果がboolでない場合.
        """
        raw_result = self.provider.confirm(message=message, default=default)
        if not isinstance(raw_result, bool):
            raise CliUserError("Confirmation prompt returned a non-boolean value.")
        return raw_result

    def collect_confirmed_secret(
        self,
        *,
        message: str,
        confirmation_message: str,
    ) -> str:
        """secretを2回入力させ一致することを確認して返す.

        Args:
            message (str): 最初のsecret入力で表示するmessage.
            confirmation_message (str): 再入力で表示するconfirmation message.

        Returns:
            str: 2回一致したsecret値.

        Raises:
            CliUserError: provider結果が文字列でないか2回の入力が一致しない場合.
        """
        secret = _coerce_string(self.provider.secret(message=message))
        confirmation = _coerce_string(self.provider.secret(message=confirmation_message))
        if secret != confirmation:
            raise CliUserError("Secret confirmation did not match.")
        return secret


def _coerce_section(value: str) -> InitSection:
    """文字列のsection値をsupport対象のInitSectionへvalidationする.

    Args:
        value (str): providerが返したsection値.

    Returns:
        InitSection: support対象としてvalidation済みのsection値.

    Raises:
        CliUserError: valueがsupport対象のsectionでない場合.
    """
    if value not in _INIT_SECTIONS:
        raise CliUserError(f"Unsupported section selected: {value}")
    return value


def _coerce_string_sequence(value: object) -> tuple[str, ...]:
    """provider結果を文字列だけからなるtupleへvalidationする.

    Args:
        value (object): providerが返した未検証の複数選択結果.

    Returns:
        tuple[str, ...]: 文字列だけからなるsection値のtuple.

    Raises:
        CliUserError: valueがlistまたはtupleでないか文字列以外を含む場合.
    """
    if not isinstance(value, list | tuple):
        raise CliUserError("Section prompt returned an invalid value.")
    raw_items = cast("Sequence[object]", value)
    if not all(isinstance(item, str) for item in raw_items):
        raise CliUserError("Section prompt returned non-string values.")
    return tuple(cast("Sequence[str]", raw_items))


def _coerce_string(value: object) -> str:
    """provider結果を文字列としてvalidationする.

    Args:
        value (object): providerが返した未検証の結果.

    Returns:
        str: validation済みの文字列値.

    Raises:
        CliUserError: valueが文字列でない場合.
    """
    if not isinstance(value, str):
        raise CliUserError("Text prompt returned a non-string value.")
    return value


def _coerce_optional_string(value: object) -> str | None:
    """provider結果を空文字をNoneへ置換したoptional文字列へ変換する.

    Args:
        value (object): providerが返した未検証の結果.

    Returns:
        str | None: 空文字でないvalidation済み文字列またはNone.

    Raises:
        CliUserError: valueが文字列でない場合.
    """
    coerced = _coerce_string(value)
    return coerced or None


def _coerce_int(value: object) -> int:
    """provider結果を10進整数としてvalidationする.

    Args:
        value (object): providerが返した未検証の結果.

    Returns:
        int: validation済みの整数値.

    Raises:
        CliUserError: valueが文字列でないか整数として変換できない場合.
    """
    raw_value = _coerce_string(value)
    try:
        return int(raw_value)
    except ValueError as exc:
        raise CliUserError(f"Expected an integer prompt value, got {raw_value!r}.") from exc


def _get_prompt_factory(name: str) -> Callable[..., object]:
    """InquirerPy moduleから名前に対応するcallable prompt factoryを取得する.

    Args:
        name (str): InquirerPy.inquirerにあるprompt factory名.

    Returns:
        Callable[..., object]: dynamic importしたcallable prompt factory.

    Raises:
        AttributeError: nameに対応するInquirerPy.inquirer attributeが存在しない場合.
        CliUserError: 指定名のattributeがcallableでない場合.
        ModuleNotFoundError: InquirerPyをimportできない場合.
    """
    inquirer_module = importlib.import_module("InquirerPy.inquirer")
    factory = cast("object", getattr(inquirer_module, name))
    if not callable(factory):
        raise CliUserError(f"InquirerPy prompt factory is not callable: {name}")
    return factory


def _execute_prompt(prompt: object) -> object:
    """実行可能promptをProtocol boundary経由で実行する.

    Args:
        prompt (object): execute methodを持つことを期待するInquirerPy prompt.

    Returns:
        object: prompt libraryが返した未検証の結果.

    Raises:
        AttributeError: promptがexecute methodを提供しない場合.
    """
    return cast("ExecutablePrompt", prompt).execute()
