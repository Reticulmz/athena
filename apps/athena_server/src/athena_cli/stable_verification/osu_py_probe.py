"""osu.pyを利用する任意のgetscores probeを提供する."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from athena_cli.stable_verification.models import (
    DiagnosticSummary,
    EvidenceScope,
    EvidenceType,
    StableSurface,
    SurfaceResult,
    VerificationStatus,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from athena_cli.stable_verification.models import GetscoresProbeCase


@dataclass(frozen=True, slots=True)
class OsuPyProbePrerequisites:
    """osu.py probeを実行するための前提情報を表す.

    Attributes:
        version (str | None): 検証対象のosu! client version. 未確認時はNone.
        executable_sha256 (str | None): 検証対象client executableのSHA-256値. 未確認時はNone.
        credentials_present (bool): 認証情報をlocal環境で利用できる場合はTrue.
    """

    version: str | None
    executable_sha256: str | None
    credentials_present: bool

    def missing_fields(self) -> tuple[str, ...]:
        """未設定の必須前提field名を安定した順序で返す.

        Returns:
            tuple[str, ...]: 未設定のversion, executable_sha256, credentialsのfield名.
        """
        missing: list[str] = []
        if self.version is None:
            missing.append("version")
        if self.executable_sha256 is None:
            missing.append("executable_sha256")
        if not self.credentials_present:
            missing.append("credentials")

        return tuple(missing)


class OsuPyProbe:
    """任意のosu.py getscores probeを依存注入で実行する.

    Notes:
        前提不足, osu.py未導入, またはexecutor失敗はrunを失敗させないoptional結果へ変換する.
    """

    def __init__(
        self,
        *,
        import_osu: Callable[[], object] | None = None,
        executor: Callable[[object, GetscoresProbeCase], SurfaceResult] | None = None,
    ) -> None:
        """依存を差し替え可能なprobeを初期化する.

        Args:
            import_osu (Callable[[], object] | None): osu.py moduleを読み込む関数. Noneなら
                標準のimport処理を使う.
            executor (Callable[[object, GetscoresProbeCase], SurfaceResult] | None): 読み込んだ
                moduleとprobe caseを検証する関数. Noneなら未設定結果を返す.
        """
        self._import_osu: Callable[[], object] = import_osu or _import_osu_module
        self._executor: Callable[[object, GetscoresProbeCase], SurfaceResult] = (
            executor or _missing_executor
        )

    def probe_getscores(
        self,
        case: GetscoresProbeCase,
        prerequisites: OsuPyProbePrerequisites,
    ) -> SurfaceResult:
        """指定caseをosu.py経由で検証しoptionalなsurface結果へ正規化する.

        Args:
            case (GetscoresProbeCase): osu.py executorへ渡すgetscores request case.
            prerequisites (OsuPyProbePrerequisites): probe実行に必要なclient証跡と認証情報.

        Returns:
            SurfaceResult: 実行結果, 前提不足skip, または安全に要約したunavailable結果.
        """
        missing_prerequisites = prerequisites.missing_fields()
        if missing_prerequisites:
            return _optional_result(
                VerificationStatus.SKIP,
                "osu.py probe prerequisites missing: " + ", ".join(missing_prerequisites),
            )

        try:
            osu_module = self._import_osu()
        except ModuleNotFoundError as exc:
            if exc.name == "osu":
                return _optional_result(
                    VerificationStatus.SKIP,
                    "osu.py package is not installed",
                )
            return _optional_result(
                VerificationStatus.UNAVAILABLE,
                f"osu.py import failed: {exc.__class__.__name__}",
            )

        try:
            return self._executor(osu_module, case)
        except Exception as exc:
            return _optional_result(
                VerificationStatus.UNAVAILABLE,
                f"osu.py getscores probe failed: {exc.__class__.__name__}",
            )


def _import_osu_module() -> object:
    """インストール済みのosu.py moduleを遅延importする.

    Returns:
        object: importしたosu.py module.

    Raises:
        ModuleNotFoundError: osu.py packageを利用できない場合.
    """
    return importlib.import_module("osu")


def _missing_executor(
    osu_module: object,
    case: GetscoresProbeCase,
) -> SurfaceResult:
    """executor未設定時の安全なoptional unavailable結果を返す.

    Args:
        osu_module (object): 読み込み済みのosu.py module. 未設定executorでは使用しない.
        case (GetscoresProbeCase): 検証対象のgetscores request case. 未設定executorでは使用しない.

    Returns:
        SurfaceResult: executor未設定を示すoptional unavailable結果.
    """
    _ = (osu_module, case)
    return _optional_result(
        VerificationStatus.UNAVAILABLE,
        "osu.py getscores executor is not configured",
    )


def _optional_result(status: VerificationStatus, message: str) -> SurfaceResult:
    """osu.py probe用のoptional HEADLESS_PROBE結果を組み立てる.

    Args:
        status (VerificationStatus): probeが返すskipまたはunavailable状態.
        message (str): reportへ公開してよい診断要約.

    Returns:
        SurfaceResult: getscores surfaceに紐づくoptional probe結果.
    """
    return SurfaceResult(
        surface=StableSurface.GETSCORES,
        status=status,
        evidence_type=EvidenceType.HEADLESS_PROBE,
        scope=EvidenceScope.OPTIONAL,
        diagnostic_summary=DiagnosticSummary(message=message),
        reference="optional:osu.py getscores probe",
    )


__all__ = [
    "OsuPyProbe",
    "OsuPyProbePrerequisites",
]
