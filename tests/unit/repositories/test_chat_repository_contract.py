"""Tests for ChatRepository contract types."""

from __future__ import annotations

import pytest

from osu_server.repositories.interfaces import chat_repository
from osu_server.repositories.interfaces.chat_repository import (
    ChatPersistenceFailureReason,
    ChatPersistenceResult,
    ChatRepository,
)


class ContractOnlyChatRepository:
    """Minimal runtime implementation used to verify the Protocol shape."""

    async def save_channel_message(
        self,
        *,
        sender_id: int,
        channel_name: str,
        content: str,
    ) -> ChatPersistenceResult:
        _ = sender_id
        _ = channel_name
        _ = content
        return ChatPersistenceResult.success_result()

    async def save_private_message(
        self,
        *,
        sender_id: int,
        target_id: int,
        content: str,
    ) -> ChatPersistenceResult:
        _ = sender_id
        _ = target_id
        _ = content
        return ChatPersistenceResult.success_result()


def test_contract_runtime_conformance() -> None:
    repo = ContractOnlyChatRepository()

    assert isinstance(repo, ChatRepository)


def test_success_result_has_no_failure_reason() -> None:
    result = ChatPersistenceResult.success_result()

    assert result.success is True
    assert result.reason is None


def test_channel_not_found_failure_is_typed() -> None:
    result = ChatPersistenceResult.failure(
        ChatPersistenceFailureReason.CHANNEL_NOT_FOUND,
    )

    assert result.success is False
    assert result.reason is ChatPersistenceFailureReason.CHANNEL_NOT_FOUND
    assert result.reason.value == "channel_not_found"


def test_storage_error_failure_is_typed() -> None:
    result = ChatPersistenceResult.failure(
        ChatPersistenceFailureReason.STORAGE_ERROR,
    )

    assert result.success is False
    assert result.reason is ChatPersistenceFailureReason.STORAGE_ERROR
    assert result.reason.value == "storage_error"


def test_runtime_unavailable_failure_is_typed() -> None:
    result = ChatPersistenceResult.failure(
        ChatPersistenceFailureReason.RUNTIME_UNAVAILABLE,
    )

    assert result.success is False
    assert result.reason is ChatPersistenceFailureReason.RUNTIME_UNAVAILABLE
    assert result.reason.value == "runtime_unavailable"


def test_failure_without_reason_is_rejected() -> None:
    with pytest.raises(ValueError, match="failed chat persistence requires a reason"):
        _ = ChatPersistenceResult(success=False)


def test_success_with_failure_reason_is_rejected() -> None:
    with pytest.raises(ValueError, match="successful chat persistence cannot have a reason"):
        _ = ChatPersistenceResult(
            success=True,
            reason=ChatPersistenceFailureReason.STORAGE_ERROR,
        )


def test_contract_module_does_not_export_sqlalchemy_models() -> None:
    exported_names = set(chat_repository.__all__)

    assert exported_names == {
        "ChatPersistenceFailureReason",
        "ChatPersistenceResult",
        "ChatRepository",
    }
    assert "ChannelModel" not in exported_names
    assert "ChannelMessageModel" not in exported_names
    assert "PrivateMessageModel" not in exported_names
