"""Tests for service registry composition — endpoint graph wiring."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from osu_server.composition.service_registry import register_services
from osu_server.config import AppConfig
from osu_server.infrastructure.di.providers import build_container
from osu_server.infrastructure.storage.errors import UnsupportedBlobStorageBackendError
from osu_server.infrastructure.storage.interfaces import BlobStorageBackend
from osu_server.infrastructure.storage.local import LocalBlobStorageBackend
from osu_server.repositories.interfaces.blob_repository import BlobRepository
from osu_server.repositories.memory.blob_repository import InMemoryBlobRepository
from osu_server.services.blob_storage_service import BlobStorageService
from osu_server.services.commands.identity import (
    LoginCommandUseCase,
    RefreshRoleAuthorizationCommandUseCase,
    RefreshUserAuthorizationCommandUseCase,
    RegisterUserCommandUseCase,
)
from osu_server.services.queries.identity import (
    ComputePermissionsQueryUseCase,
    ComputeSessionAuthorizationQueryUseCase,
    ListOnlineUsersQueryUseCase,
    SessionCredentialsQueryUseCase,
)
from osu_server.services.session_authorization_service import (
    SessionAuthorizationService,
)
from osu_server.transports.bancho.dispatch import PacketDispatcher
from osu_server.transports.bancho.endpoint import BanchoEndpoint
from osu_server.transports.bancho.protocol.enums import ClientPacketID
from osu_server.transports.bancho.workflows.login import LoginWorkflow
from osu_server.transports.bancho.workflows.login_response_builder import (
    LoginResponseBuilder,
)
from osu_server.transports.bancho.workflows.polling import PollingWorkflow

if TYPE_CHECKING:
    from pathlib import Path


def _make_config(
    *,
    environment: str = "test",
    blob_storage_backend: str = "local",
    blob_storage_local_root: str = ".data/test-blobs",
) -> AppConfig:
    return AppConfig.model_validate(
        {
            "database_url": "postgresql://test:test@localhost:5432/test",
            "valkey_url": "redis://localhost:6379/0",
            "environment": environment,
            "blob_storage_backend": blob_storage_backend,
            "blob_storage_local_root": blob_storage_local_root,
        },
    )


@pytest.mark.asyncio
async def test_register_services_binds_bancho_endpoint_graph() -> None:
    """register_services builds the full endpoint graph without manual wiring.

    Every component in the bancho endpoint graph is resolvable from the
    container, endpoint-internal workflow references are the same instances
    returned by the container, and the polling dispatcher carries the
    C2S handlers registered during composition.
    """
    config = _make_config()
    container = await build_container(config)
    await register_services(container, config)

    endpoint = await container.resolve(BanchoEndpoint)
    login_workflow = await container.resolve(LoginWorkflow)
    polling_workflow = await container.resolve(PollingWorkflow)
    response_builder = await container.resolve(LoginResponseBuilder)
    dispatcher = await container.resolve(PacketDispatcher)

    assert isinstance(endpoint, BanchoEndpoint)
    assert isinstance(login_workflow, LoginWorkflow)
    assert isinstance(polling_workflow, PollingWorkflow)
    assert isinstance(response_builder, LoginResponseBuilder)
    assert isinstance(dispatcher, PacketDispatcher)

    # No manual wiring — endpoint holds container-resolved instances
    assert endpoint._login_workflow is login_workflow  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    assert endpoint._polling_workflow is polling_workflow  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    # Polling dispatcher is the same instance that received handler registrations
    assert polling_workflow._packet_dispatcher is dispatcher  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    assert ClientPacketID.SEND_MESSAGE in dispatcher.get_handlers()
    assert ClientPacketID.JOIN_CHANNEL in dispatcher.get_handlers()


@pytest.mark.asyncio
async def test_register_services_resolves_session_authorization_service() -> None:
    """SessionAuthorizationService is resolvable from the container after registration."""
    config = _make_config()
    container = await build_container(config)
    await register_services(container, config)

    svc = await container.resolve(SessionAuthorizationService)

    assert isinstance(svc, SessionAuthorizationService)


@pytest.mark.asyncio
async def test_register_services_resolves_identity_command_query_use_cases() -> None:
    """Identity command/query use-cases are container-resolvable after registration."""
    config = _make_config()
    container = await build_container(config)
    await register_services(container, config)

    assert isinstance(await container.resolve(LoginCommandUseCase), LoginCommandUseCase)
    assert isinstance(
        await container.resolve(RegisterUserCommandUseCase),
        RegisterUserCommandUseCase,
    )
    assert isinstance(
        await container.resolve(RefreshUserAuthorizationCommandUseCase),
        RefreshUserAuthorizationCommandUseCase,
    )
    assert isinstance(
        await container.resolve(RefreshRoleAuthorizationCommandUseCase),
        RefreshRoleAuthorizationCommandUseCase,
    )
    assert isinstance(
        await container.resolve(ComputePermissionsQueryUseCase),
        ComputePermissionsQueryUseCase,
    )
    assert isinstance(
        await container.resolve(ComputeSessionAuthorizationQueryUseCase),
        ComputeSessionAuthorizationQueryUseCase,
    )
    assert isinstance(
        await container.resolve(ListOnlineUsersQueryUseCase),
        ListOnlineUsersQueryUseCase,
    )
    assert isinstance(
        await container.resolve(SessionCredentialsQueryUseCase),
        SessionCredentialsQueryUseCase,
    )


@pytest.mark.asyncio
async def test_register_services_resolves_blob_storage_graph(tmp_path: Path) -> None:
    """Blob storage service graph is resolvable with Local backend config."""
    config = _make_config(blob_storage_local_root=str(tmp_path / "blobs"))
    container = await build_container(config)
    await register_services(container, config)

    repo = await container.resolve(BlobRepository)
    backend = await container.resolve(BlobStorageBackend)
    service = await container.resolve(BlobStorageService)

    assert isinstance(repo, InMemoryBlobRepository)
    assert isinstance(backend, LocalBlobStorageBackend)
    assert isinstance(service, BlobStorageService)
    assert (tmp_path / "blobs").is_dir()


@pytest.mark.asyncio
async def test_register_services_rejects_s3_blob_backend(tmp_path: Path) -> None:
    """S3 is recognized but cannot silently fall back to Local."""
    config = _make_config(
        blob_storage_backend="s3",
        blob_storage_local_root=str(tmp_path / "blobs"),
    )
    container = await build_container(config)

    with pytest.raises(UnsupportedBlobStorageBackendError) as exc_info:
        await register_services(container, config)

    assert exc_info.value.backend == "s3"
    with pytest.raises(KeyError):
        _ = await container.resolve(BlobStorageService)
