"""StableProbeClientが送るlegacy HTTP requestを検証する."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

import httpx

from athena_cli.stable_verification.client import StableProbeClient
from athena_cli.stable_verification.models import StableTarget, VerificationStatus

if TYPE_CHECKING:
    from collections.abc import Mapping


class CapturedRequest(Protocol):
    """Mock transportで観測するHTTP requestの必要最小限のviewを定義する."""

    @property
    def url(self) -> object:
        """Request URLを返す.

        Returns:
            object: 文字列化してtarget URLを検証できるURL object.
        """
        ...

    @property
    def headers(self) -> Mapping[str, str]:
        """Request header mappingを返す.

        Returns:
            Mapping[str, str]: HostとContent-Typeを検証するheader mapping.
        """
        ...

    @property
    def content(self) -> bytes:
        """送信したrequest bodyを返す.

        Returns:
            bytes: POST payloadと一致するraw body.
        """
        ...


def test_get_web_legacy_uses_target_url_and_stable_host_identity() -> None:
    """GET legacy requestがtarget URLとosu. Host headerを使うことを検証する.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: URL, Host, response診断, またはbody contractが変化した場合.
    """
    captured_requests: list[CapturedRequest] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Mock transport requestを捕捉してranked responseを返す.

        Args:
            request (httpx.Request): StableProbeClientが送信したGET request.

        Returns:
            httpx.Response: ranked bodyを含む成功response.
        """
        captured_requests.append(cast("CapturedRequest", cast("object", request)))
        return httpx.Response(200, content=b"ranked-body", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = StableProbeClient(
            target=StableTarget(
                base_url="http://127.0.0.1:8000",
                host_identity="athena.localhost",
                timeout_seconds=1.0,
            ),
            http_client=http_client,
        )

        response = client.get_web_legacy(
            "/web/osu-osz2-bmsubmit-getid.php",
            query={"c": "checksum"},
        )

    assert len(captured_requests) == 1
    assert str(captured_requests[0].url) == (
        "http://127.0.0.1:8000/web/osu-osz2-bmsubmit-getid.php?c=checksum"
    )
    assert captured_requests[0].headers["host"] == "osu.athena.localhost"
    assert response.status is VerificationStatus.PASS
    assert response.body == b"ranked-body"
    assert response.diagnostic_summary.method == "GET"
    assert response.diagnostic_summary.path == "/web/osu-osz2-bmsubmit-getid.php"
    assert response.diagnostic_summary.status_code == 200
    assert response.diagnostic_summary.response_byte_size == len(b"ranked-body")


def test_post_web_legacy_sends_body_content_type_and_stable_host_identity() -> None:
    """POST legacy requestがbody, Content-Type, osu. Hostを維持することを検証する.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: request header, body, またはsuccess statusが変化した場合.
    """
    captured_requests: list[CapturedRequest] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Mock transport requestを捕捉して成功responseを返す.

        Args:
            request (httpx.Request): StableProbeClientが送信したPOST request.

        Returns:
            httpx.Response: `ok` bodyを含む成功response.
        """
        captured_requests.append(cast("CapturedRequest", cast("object", request)))
        return httpx.Response(200, content=b"ok", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = StableProbeClient(
            target=StableTarget(
                base_url="http://127.0.0.1:8000",
                host_identity="athena.localhost",
                timeout_seconds=1.0,
            ),
            http_client=http_client,
        )

        response = client.post_web_legacy(
            "/web/osu-submit-modular-selector.php",
            body=b"payload",
            content_type="multipart/form-data; boundary=example",
        )

    assert captured_requests[0].headers["host"] == "osu.athena.localhost"
    assert captured_requests[0].headers["content-type"] == "multipart/form-data; boundary=example"
    assert captured_requests[0].content == b"payload"
    assert response.status is VerificationStatus.PASS


def test_connection_failure_becomes_unavailable_probe_response() -> None:
    """接続不能が安全なUNAVAILABLE probe結果へ変換されることを検証する.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: 通信errorのstatus, empty body, またはsanitized diagnosticが変化した場合.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        """接続不能を表すhttpx errorを送出する.

        Args:
            request (httpx.Request): Mock transportへ渡されたGET request.

        Raises:
            httpx.ConnectError: local targetへの接続拒否を再現するため常に送出する.
        """
        raise httpx.ConnectError("connection refused", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = StableProbeClient(
            target=StableTarget(
                base_url="http://127.0.0.1:8000",
                host_identity="athena.localhost",
                timeout_seconds=1.0,
            ),
            http_client=http_client,
        )

        response = client.get_web_legacy(
            "/web/osu-osz2-bmsubmit-getid.php",
            query={},
        )

    assert response.status is VerificationStatus.UNAVAILABLE
    assert response.body == b""
    assert response.diagnostic_summary.method == "GET"
    assert response.diagnostic_summary.path == "/web/osu-osz2-bmsubmit-getid.php"
    assert response.diagnostic_summary.status_code is None
    assert response.diagnostic_summary.response_byte_size is None
    assert response.diagnostic_summary.sanitized_error == "ConnectError: connection refused"
