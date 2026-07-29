"""Stable web legacy endpointをreport-safeにprobeするHTTP clientを提供する."""

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
    """Stable probeの通信結果と安全な診断情報を表す.

    Attributes:
        status (VerificationStatus): Probeの成否またはtargetの可用性を表す状態.
        body (bytes): HTTP response body.通信不能時は空bytes.
        diagnostic_summary (DiagnosticSummary): Request pathとresponse metadataだけを含む診断情報.
    """

    status: VerificationStatus
    body: bytes
    diagnostic_summary: DiagnosticSummary


class StableProbeClient:
    """Stable web legacy endpointへHTTP probeを送信する.

    Attributes:
        _target (StableTarget): URL,Host identity,timeoutを持つprobe接続先.
        _http_client (httpx.Client): HTTP requestを実行するclient.
    """

    def __init__(
        self,
        *,
        target: StableTarget,
        http_client: httpx.Client | None = None,
    ) -> None:
        """Stable probeの接続先とHTTP clientを初期化する.

        Args:
            target (StableTarget): URL,Host identity,timeoutを定義する接続先.
            http_client (httpx.Client | None): 注入するHTTP client.未指定時はtargetの
                timeoutで生成する.
        """
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
        """Stable web legacy endpointへGET requestを送信する.

        Args:
            path (str): `/web/`配下のrequest path.先頭の`/`は任意.
            query (Mapping[str, str]): URL query field名と値の対応.
            host_prefix (str): Host headerの先頭へ付けるstable service prefix.

        Returns:
            ProbeResponse: HTTP responseまたは通信不能をreport-safeに表した結果.
        """
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
        """Stable web legacy endpointへPOST requestを送信する.

        Args:
            path (str): `/web/`配下のrequest path.先頭の`/`は任意.
            body (bytes): Request bodyのbytes.
            content_type (str): `Content-Type` headerへ設定するmedia type.
            host_prefix (str): Host headerの先頭へ付けるstable service prefix.

        Returns:
            ProbeResponse: HTTP responseまたは通信不能をreport-safeに表した結果.
        """
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
        """Stable web legacy requestを実行してprobe結果へ変換する.

        Args:
            method (str): HTTP method.
            path (str): 正規化前のrequest path.
            query (Mapping[str, str] | None): URL query field名と値の対応.GETで使用する.
            body (bytes | None): Request body.POSTで使用する.
            content_type (str | None): 指定時に`Content-Type` headerへ設定するmedia type.
            host_prefix (str): target host identityの前へ付けるstable service prefix.

        Returns:
            ProbeResponse: HTTP responseまたは`httpx.RequestError`を変換したprobe結果.

        Notes:
            `httpx.RequestError`はUNAVAILABLEのProbeResponseへ変換する.credentialやtarget
            identityは診断から除去する.
        """
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
    """Request pathを先頭`/`を持つ形式へ正規化する.

    Args:
        path (str): 正規化前のpath.

    Returns:
        str: 先頭に1つの`/`を持つpath.
    """
    return f"/{path.lstrip('/')}"


def _target_url(target: StableTarget, path: str) -> str:
    """Stable targetとrequest pathからrequest URLを組み立てる.

    Args:
        target (StableTarget): Base URLを持つprobe接続先.
        path (str): 先頭`/`を持つrequest path.

    Returns:
        str: Base URL末尾の`/`を重複させないrequest URL.
    """
    return f"{target.base_url.rstrip('/')}{path}"


def _sanitize_request_error(target: StableTarget, exc: httpx.RequestError) -> str:
    """HTTP request例外をtarget固有値を含まない診断文字列へ変換する.

    Args:
        target (StableTarget): 診断からbase URLとhost identityを除去する接続先.
        exc (httpx.RequestError): HTTP request中に発生した例外.

    Returns:
        str: 例外class名とsanitized messageを結合した診断文字列.

    Notes:
        Base URLは`<target>`へ,host identityは`<host>`へ置換する.
    """
    raw_message = str(exc).replace(target.base_url, "<target>")
    raw_message = raw_message.replace(target.host_identity, "<host>")
    if not raw_message:
        raw_message = "request failed"

    return f"{exc.__class__.__name__}: {raw_message}"


__all__ = [
    "ProbeResponse",
    "StableProbeClient",
]
