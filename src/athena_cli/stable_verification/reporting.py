"""Stable verification結果をreport-safeなtextとJSONへ変換する."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from athena_cli.stable_verification.models import (
        StableTarget,
        SurfaceResult,
        VerificationRunResult,
    )


_SECRET_ASSIGNMENT = re.compile(
    (
        r"\b("
        r"password(?:_(?:hash|md5))?"
        r"|session_token"
        r"|raw_credential"
        r"|raw_replay(?:_bytes)?"
        r"|complete_osr(?:_bytes)?"
        r"|credential(?:_value)?"
        r"|authorization"
        r"|cookie"
        r"|token"
        r")=([^,\s]+)"
    ),
    flags=re.IGNORECASE,
)


class StableVerificationReporter:
    """Stable verification runを安全なtextまたはJSONで表示する.

    Notes:
        診断文字列中のcredential-likeなassignmentは出力前にredactする.
    """

    def render_text(self, result: VerificationRunResult) -> str:
        """Verification runを人間向けの改行区切りtextへ変換する.

        Args:
            result (VerificationRunResult): targetとsurface結果を含むverification run.

        Returns:
            str: target, 成否, 各surface結果を含むreport-safeなtext.
        """
        lines: list[str] = []
        if result.target is None:
            lines.append("Target: fixture-only")
        else:
            lines.extend(_target_text_lines(result.target))

        lines.append(f"Failed: {str(result.failed).lower()}")
        lines.extend(_surface_result_text(surface_result) for surface_result in result.results)

        return "\n".join(lines)

    def render_json(self, result: VerificationRunResult) -> str:
        """Verification runをmachine-readable JSON textへ変換する.

        Args:
            result (VerificationRunResult): targetとsurface結果を含むverification run.

        Returns:
            str: redact済みのtargetとresult schemaを表すJSON text.
        """
        payload: dict[str, object] = {
            "target": _target_payload(result.target),
            "failed": result.failed,
            "results": [
                _surface_result_payload(surface_result) for surface_result in result.results
            ],
        }
        return json.dumps(payload, ensure_ascii=False)


def redact_text(value: str) -> str:
    """credential-likeなkey=value値をreport-safeなplaceholderへ置換する.

    Args:
        value (str): redact前の診断またはreport text.

    Returns:
        str: secret値を`<redacted>`へ置換したtext.
    """
    return _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=<redacted>", value)


def _target_text_lines(target: StableTarget) -> list[str]:
    """targetを人間向けreportの固定3行へ変換する.

    Args:
        target (StableTarget): base URLとstable host identityを持つprobe接続先.

    Returns:
        list[str]: target URL, Host header, host mismatchを示すtext行.
    """
    return [
        f"Target: {target.base_url}",
        f"Stable Host: osu.{target.host_identity}",
        f"Target/Host mismatch: {_target_host_mismatch(target)}",
    ]


def _target_host_mismatch(target: StableTarget) -> str:
    """Base URLにstable host identityが含まれるかをyes/noで表す.

    Args:
        target (StableTarget): 比較対象のprobe接続先.

    Returns:
        str: host identityを含む場合は`no`, 含まない場合は`yes`.
    """
    if target.host_identity in target.base_url:
        return "no"

    return "yes"


def _target_payload(target: StableTarget | None) -> dict[str, str] | None:
    """targetをJSON schema向けのmappingへ変換する.

    Args:
        target (StableTarget | None): verification target. fixture-only runではNone.

    Returns:
        dict[str, str] | None: base_urlとhost_identityのmapping. target未設定時はNone.
    """
    if target is None:
        return None

    return {
        "base_url": target.base_url,
        "host_identity": target.host_identity,
    }


def _surface_result_text(result: SurfaceResult) -> str:
    """1件のsurface結果をreport-safeな空白区切りtextへ変換する.

    Args:
        result (SurfaceResult): text表示するsurface検証結果.

    Returns:
        str: surface, status, evidence, scope, redact済み診断を連結したtext.
    """
    return " ".join(
        (
            result.surface.value,
            result.status.value,
            result.evidence_type.value,
            result.scope.value,
            redact_text(result.diagnostic_summary.message),
        )
    )


def _surface_result_payload(result: SurfaceResult) -> dict[str, str | None]:
    """1件のsurface結果をJSON schema向けのmappingへ変換する.

    Args:
        result (SurfaceResult): JSON表示するsurface検証結果.

    Returns:
        dict[str, str | None]: redact済みdiagnostic_summaryを含むresult mapping.
    """
    return {
        "surface": result.surface.value,
        "status": result.status.value,
        "evidence_type": result.evidence_type.value,
        "scope": result.scope.value,
        "diagnostic_summary": redact_text(result.diagnostic_summary.message),
        "reference": result.reference,
    }


__all__ = [
    "StableVerificationReporter",
    "redact_text",
]
