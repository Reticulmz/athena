from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

import httpx

from athena_cli.stable_verification.client import StableProbeClient
from athena_cli.stable_verification.models import StableTarget, VerificationStatus

if TYPE_CHECKING:
    from collections.abc import Mapping


class CapturedRequest(Protocol):
    @property
    def url(self) -> object: ...

    @property
    def headers(self) -> Mapping[str, str]: ...

    @property
    def content(self) -> bytes: ...


def test_get_web_legacy_uses_target_url_and_stable_host_identity() -> None:
    captured_requests: list[CapturedRequest] = []

    def handler(request: httpx.Request) -> httpx.Response:
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
    captured_requests: list[CapturedRequest] = []

    def handler(request: httpx.Request) -> httpx.Response:
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
    def handler(request: httpx.Request) -> httpx.Response:
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
