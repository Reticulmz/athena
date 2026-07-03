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
        r"password(?:_hash)?"
        r"|session_token"
        r"|raw_credential"
        r"|raw_replay"
        r"|complete_osr_bytes"
        r"|credential"
        r"|token"
        r")=([^,\s]+)"
    ),
    flags=re.IGNORECASE,
)


class StableVerificationReporter:
    def render_text(self, result: VerificationRunResult) -> str:
        lines: list[str] = []
        if result.target is None:
            lines.append("Target: fixture-only")
        else:
            lines.extend(_target_text_lines(result.target))

        lines.append(f"Failed: {str(result.failed).lower()}")
        lines.extend(_surface_result_text(surface_result) for surface_result in result.results)

        return "\n".join(lines)

    def render_json(self, result: VerificationRunResult) -> str:
        payload: dict[str, object] = {
            "target": _target_payload(result.target),
            "failed": result.failed,
            "results": [
                _surface_result_payload(surface_result) for surface_result in result.results
            ],
        }
        return json.dumps(payload, ensure_ascii=False)


def redact_text(value: str) -> str:
    return _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=<redacted>", value)


def _target_text_lines(target: StableTarget) -> list[str]:
    return [
        f"Target: {target.base_url}",
        f"Stable Host: osu.{target.host_identity}",
        f"Target/Host mismatch: {_target_host_mismatch(target)}",
    ]


def _target_host_mismatch(target: StableTarget) -> str:
    if target.host_identity in target.base_url:
        return "no"

    return "yes"


def _target_payload(target: StableTarget | None) -> dict[str, str] | None:
    if target is None:
        return None

    return {
        "base_url": target.base_url,
        "host_identity": target.host_identity,
    }


def _surface_result_text(result: SurfaceResult) -> str:
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
