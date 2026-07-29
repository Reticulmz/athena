"""外部serviceが利用不能な場合にintegration testをskipするhelperを提供する."""

from __future__ import annotations

import os
import socket
from contextlib import closing
from urllib.parse import urlsplit

import pytest


def require_tcp_service_url(
    env_var: str,
    *,
    default_port: int,
    timeout: float = 0.5,
) -> str:
    """TCP endpointへ接続できるservice URLを返し, 利用不能ならtestをskipする.

    Args:
        env_var (str): service URLを持つenvironment variable名.
        default_port (int): URLにportがない場合に接続するTCP port.
        timeout (float): TCP connection確立へ許容する秒数.

    Returns:
        str: 接続可能と確認したenvironment由来のservice URL.

    Notes:
        URL未設定, host不在, 不正port, またはTCP接続失敗時はpytest.skipを呼び出す.
    """
    url = os.environ.get(env_var)
    if not url:
        pytest.skip(f"{env_var} not set")

    parsed = urlsplit(url)
    host = parsed.hostname
    if host is None:
        pytest.skip(f"{env_var} does not include a TCP host")

    try:
        port = parsed.port or default_port
    except ValueError as exc:
        pytest.skip(f"{env_var} has invalid port: {exc}")

    try:
        with closing(socket.create_connection((host, port), timeout=timeout)):
            pass
    except OSError as exc:
        pytest.skip(f"{env_var} is set but service is unavailable at {host}:{port}: {exc}")

    return url
