"""Chat command repositoryの公開contract型を検証する."""

from __future__ import annotations

import pytest

from osu_server.domain.chat import (
    ChatPersistenceFailureReason,
    ChatPersistenceResult,
)
from osu_server.repositories.interfaces.commands import chat
from osu_server.repositories.interfaces.commands.chat import ChatCommandRepository


class ContractOnlyChatRepository:
    """ChatCommandRepositoryのruntime conformanceだけを表すfake repository."""

    async def save_channel_message(
        self,
        *,
        sender_id: int,
        channel_name: str,
        content: str,
    ) -> ChatPersistenceResult:
        """Channel message保存contractを成功結果だけで実装する.

        Args:
            sender_id (int): message送信者の識別子.
            channel_name (str): 保存先channelの名前.
            content (str): 保存するmessage本文.

        Returns:
            ChatPersistenceResult: reasonを持たない成功結果.
        """
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
        """Private message保存contractを成功結果だけで実装する.

        Args:
            sender_id (int): message送信者の識別子.
            target_id (int): message受信者の識別子.
            content (str): 保存するmessage本文.

        Returns:
            ChatPersistenceResult: reasonを持たない成功結果.
        """
        _ = sender_id
        _ = target_id
        _ = content
        return ChatPersistenceResult.success_result()


def test_contract_runtime_conformance() -> None:
    """Contract-only fakeがChatCommandRepositoryを満たすことを検証する.

    Returns:
        None: runtime Protocol instance判定を検証して完了する.
    """
    repo = ContractOnlyChatRepository()

    assert isinstance(repo, ChatCommandRepository)


def test_success_result_has_no_failure_reason() -> None:
    """成功したchat persistence結果にfailure reasonがないことを検証する.

    Returns:
        None: 成功flagとNone reasonの組合せを検証して完了する.
    """
    result = ChatPersistenceResult.success_result()

    assert result.success is True
    assert result.reason is None


def test_channel_not_found_failure_is_typed() -> None:
    """Channel未検出のpersistence失敗がtyped reasonを返すことを検証する.

    Returns:
        None: CHANNEL_NOT_FOUND enumとwire valueを検証して完了する.
    """
    result = ChatPersistenceResult.failure(
        ChatPersistenceFailureReason.CHANNEL_NOT_FOUND,
    )

    assert result.success is False
    assert result.reason is ChatPersistenceFailureReason.CHANNEL_NOT_FOUND
    assert result.reason.value == "channel_not_found"


def test_storage_error_failure_is_typed() -> None:
    """Storage errorのpersistence失敗がtyped reasonを返すことを検証する.

    Returns:
        None: STORAGE_ERROR enumとwire valueを検証して完了する.
    """
    result = ChatPersistenceResult.failure(
        ChatPersistenceFailureReason.STORAGE_ERROR,
    )

    assert result.success is False
    assert result.reason is ChatPersistenceFailureReason.STORAGE_ERROR
    assert result.reason.value == "storage_error"


def test_runtime_unavailable_failure_is_typed() -> None:
    """Runtime unavailableのpersistence失敗がtyped reasonを返すことを検証する.

    Returns:
        None: RUNTIME_UNAVAILABLE enumとwire valueを検証して完了する.
    """
    result = ChatPersistenceResult.failure(
        ChatPersistenceFailureReason.RUNTIME_UNAVAILABLE,
    )

    assert result.success is False
    assert result.reason is ChatPersistenceFailureReason.RUNTIME_UNAVAILABLE
    assert result.reason.value == "runtime_unavailable"


def test_failure_without_reason_is_rejected() -> None:
    """Failure reasonなしの失敗persistence結果を拒否することを検証する.

    Returns:
        None: failure stateに対するValueErrorを検証して完了する.
    """
    with pytest.raises(ValueError, match="failed chat persistence requires a reason"):
        _ = ChatPersistenceResult(success=False)


def test_success_with_failure_reason_is_rejected() -> None:
    """Failure reasonを持つ成功persistence結果を拒否することを検証する.

    Returns:
        None: success stateに対するValueErrorを検証して完了する.
    """
    with pytest.raises(ValueError, match="successful chat persistence cannot have a reason"):
        _ = ChatPersistenceResult(
            success=True,
            reason=ChatPersistenceFailureReason.STORAGE_ERROR,
        )


def test_contract_module_does_not_export_sqlalchemy_models() -> None:
    """Chat contract moduleがSQLAlchemy modelをexportしない境界を検証する.

    Returns:
        None: public export集合と禁止model名の不在を検証して完了する.
    """
    exported_names = set(chat.__all__)

    assert exported_names == {"ChatCommandRepository"}
    assert "ChannelModel" not in exported_names
    assert "ChannelMessageModel" not in exported_names
    assert "PrivateMessageModel" not in exported_names
