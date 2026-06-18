"""Helpers for skipping integration tests when external services are unavailable."""

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
    """Return a service URL or skip when its TCP endpoint is unavailable."""
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
