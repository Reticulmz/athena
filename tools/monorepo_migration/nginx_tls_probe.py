"""Nginx development ingressをhostname検証付きTLS requestでprobeするmodule."""

from __future__ import annotations

import argparse
import http.client
import signal
import socket
import ssl
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Literal, cast

SERVER_NAME = "osu.athena.localhost"
LOOPBACK_ADDRESS = "127.0.0.1"
HEALTH_PATH = "/health"
HTTP_OK = 200
HTTP_NOT_FOUND = 404


class IngressProbeError(RuntimeError):
    """Nginx ingressが期待するHTTP/TLS contractを満たさないことを表す."""


@dataclass(slots=True, frozen=True)
class ProbeResponse:
    """Ingress health requestから観測したHTTP responseを表す.

    Attributes:
        status (int): Nginxが返したHTTP status code.
        body (str): UTF-8としてdecodeしたresponse body.
    """

    status: int
    body: str


@dataclass(slots=True, frozen=True)
class ProbeCommand:
    """既に起動したNginx TLS ingressを1回検証するcommandを表す.

    Attributes:
        ca_certificate (Path): Server certificateを発行したmkcert root CA certificate.
        port (int): TLS ingressへ接続するloopback port.
    """

    ca_certificate: Path
    port: int


@dataclass(slots=True, frozen=True)
class IntegrationCommand:
    """隔離namespaceでbackendとNginxを起動して検証するcommandを表す.

    Attributes:
        repository_root (Path): `.state/nginx`と`.state/certs`を持つfixture root.
        ip_command (Path): Namespace loopbackを有効化する`ip` executable path.
        nginx_command (Path): 起動するNginx executable path.
        ca_certificate (Path): Fixture server certificateを発行したmkcert root CA certificate.
    """

    repository_root: Path
    ip_command: Path
    nginx_command: Path
    ca_certificate: Path


type Command = ProbeCommand | IntegrationCommand
type CommandName = Literal["probe", "integration"]


class HealthRequestHandler(BaseHTTPRequestHandler):
    """Nginx forwarding headerをresponse bodyへ反映するfixture HTTP handler."""

    def do_GET(self) -> None:
        """Health pathへHostとforwarded protocolを含むresponseを返す.

        Returns:
            None: HTTP responseをclientへ書き込み、呼び出し側へ値を返さずに完了する.
        """
        body = (f"{self.headers.get('Host')}|{self.headers.get('X-Forwarded-Proto')}").encode()
        self.send_response(HTTP_OK if self.path == HEALTH_PATH else HTTP_NOT_FOUND)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        _ = self.wfile.write(body)


def _build_tls_context(ca_certificate: Path) -> ssl.SSLContext:
    """Isolated mkcert CAを信頼しhostname検証を要求するclient contextを返す.

    Args:
        ca_certificate (Path): Server certificateを発行したroot CA PEM path.

    Returns:
        ssl.SSLContext: `CERT_REQUIRED`とhostname検証を有効にしたclient context.

    Raises:
        IngressProbeError: 構築されたcontextがverification contractを満たさない場合.
        OSError: CA certificateを読み込めない場合.
    """
    context = ssl.create_default_context(
        purpose=ssl.Purpose.SERVER_AUTH,
        cafile=str(ca_certificate),
    )
    if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
        raise IngressProbeError(
            "TLS client context must require certificate and hostname validation"
        )
    return context


def _read_health_response(connection: socket.socket) -> ProbeResponse:
    """接続済みsocketへnamed health requestを送りresponseを返す.

    Args:
        connection (socket.socket): HTTP bytesを送受信する接続済みsocket.

    Returns:
        ProbeResponse: Response statusとUTF-8 body.

    Raises:
        OSError: Socket送受信に失敗した場合.
        http.client.HTTPException: HTTP responseをparseできない場合.
        UnicodeError: Response bodyがUTF-8ではない場合.
    """
    request = (
        f"GET {HEALTH_PATH} HTTP/1.1\r\nHost: {SERVER_NAME}\r\nConnection: close\r\n\r\n"
    ).encode("ascii")
    connection.sendall(request)
    response = http.client.HTTPResponse(connection)
    try:
        response.begin()
        return ProbeResponse(
            status=response.status,
            body=response.read().decode("utf-8"),
        )
    finally:
        response.close()


def _request_health(
    port: int,
    *,
    use_tls: bool,
    ca_certificate: Path | None,
) -> ProbeResponse:
    """Loopback IPへ接続しnamed HTTPまたはverified TLS health requestを送る.

    Args:
        port (int): Loopback接続先port.
        use_tls (bool): TCP socketをTLSでwrapするか.
        ca_certificate (Path | None): TLS時に信頼するroot CA. Plain HTTPではNone.

    Returns:
        ProbeResponse: Nginx ingressから受け取ったstatusとbody.

    Raises:
        IngressProbeError: TLS requestでCA certificateが指定されない場合.
        OSError: Socket接続、TLS handshake、送受信に失敗した場合.
        http.client.HTTPException: HTTP responseをparseできない場合.
        UnicodeError: Response bodyがUTF-8ではない場合.
    """
    with socket.create_connection((LOOPBACK_ADDRESS, port), timeout=1) as tcp_socket:
        if not use_tls:
            return _read_health_response(tcp_socket)
        if ca_certificate is None:
            raise IngressProbeError("TLS health request requires a CA certificate")
        context = _build_tls_context(ca_certificate)
        with context.wrap_socket(tcp_socket, server_hostname=SERVER_NAME) as tls_socket:
            return _read_health_response(tls_socket)


def _wait_for_expected_health(
    nginx_process: subprocess.Popen[str],
    *,
    port: int,
    use_tls: bool,
    ca_certificate: Path | None,
    expected_body: str,
) -> None:
    """Nginx起動中に期待するhealth responseが得られるまでbounded retryする.

    Args:
        nginx_process (subprocess.Popen[str]): Early exitを監視するNginx process.
        port (int): Loopback接続先port.
        use_tls (bool): TLSとhostname verificationを使うか.
        ca_certificate (Path | None): TLS requestが信頼するroot CA certificate.
        expected_body (str): Forwarding contractを表す期待response body.

    Returns:
        None: 期待responseを観測し、呼び出し側へ値を返さずに完了する.

    Raises:
        IngressProbeError: Nginxがearly exitするかretry上限まで期待responseを得られない場合.
    """
    last_failure = "health request was not attempted"
    for _attempt in range(100):
        if nginx_process.poll() is not None:
            _, nginx_stderr = nginx_process.communicate(timeout=1)
            raise IngressProbeError(
                f"Nginx exited before readiness: {nginx_stderr or ''}",
            )
        try:
            response = _request_health(
                port,
                use_tls=use_tls,
                ca_certificate=ca_certificate,
            )
            if response.status == HTTP_OK and response.body == expected_body:
                return
            last_failure = f"status={response.status} body={response.body!r}"
        except (IngressProbeError, OSError, http.client.HTTPException, UnicodeError) as error:
            last_failure = repr(error)
        time.sleep(0.05)
    raise IngressProbeError(last_failure)


def probe_tls_ingress(ca_certificate: Path, *, port: int = 443) -> None:
    """起動済みNginxへhostname検証付きTLS health requestを1回送る.

    Args:
        ca_certificate (Path): Server certificateを発行したroot CA PEM path.
        port (int): TLS ingressへ接続するloopback port.

    Returns:
        None: HTTP 200を確認し、呼び出し側へ値を返さずに完了する.

    Raises:
        IngressProbeError: Health responseがHTTP 200ではない場合.
        OSError: Socket接続、TLS handshake、送受信に失敗した場合.
        http.client.HTTPException: HTTP responseをparseできない場合.
        UnicodeError: Response bodyがUTF-8ではない場合.
    """
    response = _request_health(port, use_tls=True, ca_certificate=ca_certificate)
    if response.status != HTTP_OK:
        raise IngressProbeError(f"Nginx TLS health response returned HTTP {response.status}")


def run_isolated_integration(
    repository_root: Path,
    ip_command: Path,
    nginx_command: Path,
    ca_certificate: Path,
) -> None:
    """Isolated namespaceでHTTPとverified TLS ingressを実process検証する.

    Args:
        repository_root (Path): Generated Nginx configとcertificateを持つfixture root.
        ip_command (Path): Namespace loopbackを有効化する`ip` executable path.
        nginx_command (Path): 起動するNginx executable path.
        ca_certificate (Path): Fixture server certificateを発行したroot CA PEM path.

    Returns:
        None: HTTP/TLS forwarding contractを確認し、processを終了して完了する.

    Raises:
        IngressProbeError: Nginxまたはingress responseが期待するcontractを満たさない場合.
        OSError: Backend bind、process起動、socket操作に失敗した場合.
        subprocess.SubprocessError: Namespace loopbackを有効化できない場合.
    """
    _ = subprocess.run(
        [str(ip_command), "link", "set", "lo", "up"],
        check=True,
        capture_output=True,
        text=True,
    )
    backend_server = ThreadingHTTPServer(
        (LOOPBACK_ADDRESS, 8000),
        HealthRequestHandler,
    )
    backend_thread = threading.Thread(target=backend_server.serve_forever, daemon=True)
    backend_thread.start()
    nginx_process = subprocess.Popen(
        [
            str(nginx_command),
            "-p",
            f"{repository_root}/",
            "-e",
            str(repository_root / ".state" / "nginx" / "error.log"),
            "-c",
            str(repository_root / ".state" / "nginx" / "nginx.conf"),
            "-g",
            "user root; daemon off;",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_expected_health(
            nginx_process,
            port=80,
            use_tls=False,
            ca_certificate=None,
            expected_body=f"{SERVER_NAME}|http",
        )
        _wait_for_expected_health(
            nginx_process,
            port=443,
            use_tls=True,
            ca_certificate=ca_certificate,
            expected_body=f"{SERVER_NAME}|https",
        )
    finally:
        if nginx_process.poll() is None:
            nginx_process.send_signal(signal.SIGQUIT)
            _ = nginx_process.wait(timeout=5)
        backend_server.shutdown()
        backend_server.server_close()
        backend_thread.join(timeout=5)


def _parse_arguments() -> Command:
    """Nginx TLS probeのcommand line argumentsをtyped commandへ変換する.

    Returns:
        Command: Probeまたはisolated integrationの実行入力.
    """
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    probe_parser = subparsers.add_parser("probe")
    _ = probe_parser.add_argument("ca_certificate", type=Path)
    _ = probe_parser.add_argument("--port", type=int, default=443)
    integration_parser = subparsers.add_parser("integration")
    _ = integration_parser.add_argument("repository_root", type=Path)
    _ = integration_parser.add_argument("ip_command", type=Path)
    _ = integration_parser.add_argument("nginx_command", type=Path)
    _ = integration_parser.add_argument("ca_certificate", type=Path)
    arguments = parser.parse_args()
    command_name = cast("CommandName", arguments.command)
    if command_name == "probe":
        return ProbeCommand(
            ca_certificate=cast("Path", arguments.ca_certificate),
            port=cast("int", arguments.port),
        )
    return IntegrationCommand(
        repository_root=cast("Path", arguments.repository_root),
        ip_command=cast("Path", arguments.ip_command),
        nginx_command=cast("Path", arguments.nginx_command),
        ca_certificate=cast("Path", arguments.ca_certificate),
    )


def main() -> int:
    """選択されたNginx TLS probe commandを実行する.

    Returns:
        int: Ingress contractを満たす場合は0、検証またはprocess操作に失敗した場合は1.
    """
    command = _parse_arguments()
    try:
        if isinstance(command, ProbeCommand):
            probe_tls_ingress(command.ca_certificate, port=command.port)
        else:
            run_isolated_integration(
                command.repository_root,
                command.ip_command,
                command.nginx_command,
                command.ca_certificate,
            )
    except (
        IngressProbeError,
        OSError,
        subprocess.SubprocessError,
        http.client.HTTPException,
        UnicodeError,
    ) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
