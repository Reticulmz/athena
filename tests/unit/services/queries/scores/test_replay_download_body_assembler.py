"""replay download body assemblerのunit testを定義する."""

from __future__ import annotations

from osu_server.domain.compatibility.stable import (
    ReplayDownloadBodyStrategy,
    ReplayDownloadBranch,
    ReplayDownloadResponseBody,
    ReplayDownloadStoredBlobObject,
)
from osu_server.services.queries.scores import (
    ReplayDownloadBodyAssembler,
    ReplayDownloadBodyBuildInput,
)


def test_blocked_strategy_returns_blocked_branch_without_response_body() -> None:
    """Blocked strategyがresponse bodyを生成しない契約を検証する.

    stored blobを与えてblocked strategyを実行し,body strategy blocked branchとNoneの
    response bodyを返すことを確認する.

    Returns:
        None: blocked branch,非成功状態,payload非露出を検証して完了する.
    """
    stored_payload = b"bk"

    result = ReplayDownloadBodyAssembler().build(
        ReplayDownloadBodyBuildInput(
            strategy=ReplayDownloadBodyStrategy.BLOCKED,
            stored_blob=_stored_blob(stored_payload),
        )
    )

    assert result.branch is ReplayDownloadBranch.BODY_STRATEGY_BLOCKED
    assert result.response_body is None
    assert result.is_success is False
    assert repr(stored_payload) not in repr(result)


def test_direct_blob_bytes_strategy_returns_stored_bytes_exactly() -> None:
    """Direct blob bytes strategyが保存済みbytesをそのまま返す契約を検証する.

    validation済みstored blobを与えてdirect strategyを実行し,成功bodyのpayloadとbyte sizeが
    入力と一致することを確認する.

    Returns:
        None: 成功branch,response body,payload非露出を検証して完了する.
    """
    stored_blob = _stored_blob(b"db")

    result = ReplayDownloadBodyAssembler().build(
        ReplayDownloadBodyBuildInput(
            strategy=ReplayDownloadBodyStrategy.DIRECT_BLOB_BYTES,
            stored_blob=stored_blob,
        )
    )

    assert result.branch is ReplayDownloadBranch.SUCCESS
    assert isinstance(result.response_body, ReplayDownloadResponseBody)
    assert result.response_body.payload == stored_blob.payload
    assert result.response_body.byte_size == stored_blob.byte_size
    assert result.is_success is True
    assert repr(stored_blob.payload) not in repr(result)
    assert repr(stored_blob.payload) not in repr(result.response_body)


def test_assemble_download_body_strategy_stays_blocked_without_local_decision() -> None:
    """未確定transformのassemble strategyがblockedのままになる契約を検証する.

    stored blobを与えてassemble strategyを実行し,local decisionでsuccess bodyを作らず
    blocked branchを返すことを確認する.

    Returns:
        None: blocked branch,Noneのresponse body,payload非露出を検証して完了する.
    """
    stored_payload = b"as"

    result = ReplayDownloadBodyAssembler().build(
        ReplayDownloadBodyBuildInput(
            strategy=ReplayDownloadBodyStrategy.ASSEMBLE_DOWNLOAD_BODY,
            stored_blob=_stored_blob(stored_payload),
        )
    )

    assert result.branch is ReplayDownloadBranch.BODY_STRATEGY_BLOCKED
    assert result.response_body is None
    assert result.is_success is False
    assert repr(stored_payload) not in repr(result)


def _stored_blob(payload: bytes) -> ReplayDownloadStoredBlobObject:
    """指定payloadを持つstored blob objectを構築する.

    Args:
        payload (bytes): replay responseに使うsynthetic stored bytes.

    Returns:
        ReplayDownloadStoredBlobObject: payloadとpayload由来のbyte sizeを持つstored blob.
    """
    return ReplayDownloadStoredBlobObject(payload=payload)
