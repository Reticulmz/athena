"""Replay download body assembler の tests."""

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
    """Blocked strategy は success body を生成しない."""
    result = ReplayDownloadBodyAssembler().build(
        ReplayDownloadBodyBuildInput(
            strategy=ReplayDownloadBodyStrategy.BLOCKED,
            stored_blob=_stored_blob(b"synthetic-blocked"),
        )
    )

    assert result.branch is ReplayDownloadBranch.BODY_STRATEGY_BLOCKED
    assert result.response_body is None
    assert result.is_success is False


def test_direct_blob_bytes_strategy_returns_stored_bytes_exactly() -> None:
    """Direct strategy は validation 済み stored bytes だけを返す."""
    stored_blob = _stored_blob(b"synthetic-direct")

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


def test_assemble_download_body_strategy_stays_blocked_without_local_decision() -> None:
    """Assemble strategy は未確定 transform では success body を生成しない."""
    result = ReplayDownloadBodyAssembler().build(
        ReplayDownloadBodyBuildInput(
            strategy=ReplayDownloadBodyStrategy.ASSEMBLE_DOWNLOAD_BODY,
            stored_blob=_stored_blob(b"synthetic-assemble"),
        )
    )

    assert result.branch is ReplayDownloadBranch.BODY_STRATEGY_BLOCKED
    assert result.response_body is None
    assert result.is_success is False


def _stored_blob(payload: bytes) -> ReplayDownloadStoredBlobObject:
    return ReplayDownloadStoredBlobObject(payload=payload)
