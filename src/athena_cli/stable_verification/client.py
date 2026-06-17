from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from athena_cli.stable_verification.models import (
    DiagnosticSummary,
    StableTarget,
    VerificationStatus,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class ProbeResponse:
    status: VerificationStatus
    body: bytes
    diagnostic_summary: DiagnosticSummary


class StableProbeClient:
    def __init__(
        self,
        *,
        target: StableTarget,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._target: StableTarget = target
        self._http_client: httpx.Client = http_client or httpx.Client(
            timeout=target.timeout_seconds
        )

    def get_web_legacy(
        self,
        path: str,
        *,
        query: Mapping[str, str],
        host_prefix: str = "osu",
    ) -> ProbeResponse:
        return self._request_web_legacy(
            "GET",
            path,
            query=query,
            host_prefix=host_prefix,
        )

    def post_web_legacy(
        self,
        path: str,
        *,
        body: bytes,
        content_type: str,
        host_prefix: str = "osu",
    ) -> ProbeResponse:
        return self._request_web_legacy(
            "POST",
            path,
            body=body,
            content_type=content_type,
            host_prefix=host_prefix,
        )

    def _request_web_legacy(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        body: bytes | None = None,
        content_type: str | None = None,
        host_prefix: str,
    ) -> ProbeResponse:
        request_path = _normalize_path(path)
        headers = {"Host": f"{host_prefix}.{self._target.host_identity}"}
        if content_type is not None:
            headers["Content-Type"] = content_type

        try:
            response = self._http_client.request(
                method,
                _target_url(self._target, request_path),
                params=dict(query or {}),
                content=body,
                headers=headers,
                timeout=self._target.timeout_seconds,
            )
        except httpx.RequestError as exc:
            return ProbeResponse(
                status=VerificationStatus.UNAVAILABLE,
                body=b"",
                diagnostic_summary=DiagnosticSummary(
                    message=f"{method} {request_path} unavailable",
                    method=method,
                    path=request_path,
                    sanitized_error=_sanitize_request_error(self._target, exc),
                ),
            )

        response_body = response.content
        return ProbeResponse(
            status=VerificationStatus.PASS,
            body=response_body,
            diagnostic_summary=DiagnosticSummary(
                message=(
                    f"{method} {request_path} "
                    f"status={response.status_code} bytes={len(response_body)}"
                ),
                method=method,
                path=request_path,
                status_code=response.status_code,
                response_byte_size=len(response_body),
            ),
        )


def _normalize_path(path: str) -> str:
    return f"/{path.lstrip('/')}"


def _target_url(target: StableTarget, path: str) -> str:
    return f"{target.base_url.rstrip('/')}{path}"


def _sanitize_request_error(target: StableTarget, exc: httpx.RequestError) -> str:
    raw_message = str(exc).replace(target.base_url, "<target>")
    raw_message = raw_message.replace(target.host_identity, "<host>")
    if not raw_message:
        raw_message = "request failed"

    return f"{exc.__class__.__name__}: {raw_message}"


__all__ = [
    "ProbeResponse",
    "StableProbeClient",
]
