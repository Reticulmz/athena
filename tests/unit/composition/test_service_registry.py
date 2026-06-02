"""Tests for service registry composition."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_register_services_binds_bancho_endpoint_graph() -> None:
    """BanchoEndpoint graph is bound in DI."""
    pytest.skip("covered by integration tests in task 5.1")
