"""AppConfig schemaからenvironment fileの内容を生成する."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import TypeAdapter

from athena_cli.env.schema import get_config_env_metadata
from athena_cli.errors import CliUserError
from athena_cli.presentation import mask_secret
from osu_server.config import AppConfig

if TYPE_CHECKING:
    from collections.abc import Mapping

    from osu_server.config import EnvironmentName


_STRING_LIST_ADAPTER = TypeAdapter(list[str])


@dataclass(frozen=True, slots=True)
class EnvGenerationInput:
    """environment file生成に必要な入力を表す.

    Attributes:
        environment (EnvironmentName): 生成対象のenvironment名.
        values (Mapping[str, str]): userまたはprocessから取得した環境変数値.
    """

    environment: EnvironmentName
    values: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class EnvGenerationResult:
    """生成済みenvironment file内容とsecretの表示用summaryを表す.

    Attributes:
        content (str): fileへ書き込む末尾newline付きの環境変数内容.
        masked_summary (tuple[str, ...]): secret値をmaskした表示用の行.
    """

    content: str
    masked_summary: tuple[str, ...]


class MissingEnvValuesError(CliUserError):
    """必須のenvironment valueが不足していることを表す.

    Attributes:
        missing_values (tuple[str, ...]): 値が不足している環境変数名.
    """

    def __init__(self, missing_values: tuple[str, ...]) -> None:
        """不足している環境変数名を保持して例外を初期化する.

        Args:
            missing_values (tuple[str, ...]): 値がない必須環境変数名.
        """
        self.missing_values: tuple[str, ...] = missing_values
        joined_values = ", ".join(missing_values)
        super().__init__(f"Missing required environment values: {joined_values}")


def generate_env_content(generation_input: EnvGenerationInput) -> EnvGenerationResult:
    """schemaと入力値からvalidation済みenvironment file内容を生成する.

    Args:
        generation_input (EnvGenerationInput): target environmentと入力済み環境変数値.

    Returns:
        EnvGenerationResult: file内容とsecretをmaskしたsummary.

    Raises:
        MissingEnvValuesError: 必須環境変数の値が不足している場合.
        ValidationError: 収集済みの値がAppConfig validationを通過しない場合.
    """
    values = _collect_values(generation_input)
    _validate_app_config(values)
    lines = tuple(f"{env_var}={value}" for env_var, value in values.items())
    masked_summary = tuple(
        _format_summary_line(env_var, value)
        for env_var, value in values.items()
        if _is_secret_env_var(env_var)
    )
    return EnvGenerationResult(content="\n".join(lines) + "\n", masked_summary=masked_summary)


def _collect_values(generation_input: EnvGenerationInput) -> dict[str, str]:
    """入力値とschema defaultからenvironment fileへ出力する値を収集する.

    Args:
        generation_input (EnvGenerationInput): target environmentと入力済み環境変数値.

    Returns:
        dict[str, str]: 出力順を維持した環境変数名と値のmapping.

    Raises:
        MissingEnvValuesError: 必須環境変数の値が不足している場合.
    """
    values: dict[str, str] = {}
    missing_values: list[str] = []
    for field in get_config_env_metadata():
        value = generation_input.values.get(field.env_var)
        if field.env_var == "ENVIRONMENT":
            value = generation_input.environment
        if value is None:
            if field.empty_value_is_unset and field.default in (None, ""):
                continue
            value = field.default
        if field.empty_value_is_unset and value == "":
            continue
        if field.required and not value:
            missing_values.append(field.env_var)
            continue
        values[field.env_var] = value or ""
    if missing_values:
        raise MissingEnvValuesError(tuple(missing_values))
    return values


def _validate_app_config(values: Mapping[str, str]) -> None:
    """生成対象の環境変数値がAppConfigでvalidationできることを確認する.

    Args:
        values (Mapping[str, str]): environment fileへ出力する環境変数名と値.

    Returns:
        None: validationが成功し値を返さずに完了する.

    Raises:
        ValidationError: AppConfigが入力値を受け付けない場合.
    """
    field_values: dict[str, object] = {}
    for field in get_config_env_metadata():
        if field.env_var not in values:
            continue
        value = values[field.env_var]
        if field.empty_value_is_unset and value == "":
            continue
        field_values[field.field_name] = _parse_list_value(value) if field.list_like else value
    _ = AppConfig.model_validate(field_values)


def _parse_list_value(value: str) -> list[str]:
    """JSON arrayまたはcomma区切り環境変数値を正規化済みlistへ変換する.

    Args:
        value (str): JSON arrayまたはcomma区切りの環境変数値.

    Returns:
        list[str]: 前後空白と空要素を除去した要素のlist.

    Raises:
        ValidationError: JSON arrayとして解釈する値が不正な場合.
    """
    if value.strip().startswith("["):
        items = _STRING_LIST_ADAPTER.validate_json(value)
    else:
        items = value.split(",")
    return [item.strip() for item in items if item.strip()]


def _format_summary_line(env_var: str, value: str) -> str:
    """secret環境変数をmaskしたsummary行へ整形する.

    Args:
        env_var (str): 表示する環境変数名.
        value (str): mask対象の環境変数値.

    Returns:
        str: 値をmaskしたENV_VAR=value形式のsummary行.
    """
    return f"{env_var}={mask_secret(value)}"


def _is_secret_env_var(env_var: str) -> bool:
    """環境変数名がsecretを含む表示mask対象か判定する.

    Args:
        env_var (str): 判定する環境変数名.

    Returns:
        bool: passwordまたはsecretまたはaccess keyを示す語を含む場合はTrue.
    """
    return any(part in env_var for part in ("PASSWORD", "SECRET", "ACCESS_KEY"))
