"""Beatmap取得Taskiq adapterのunit testを提供する.

registry登録,Taskiq stateからのuse-case解決,payload変換,runtime未登録時の
例外と構造化logを検証する.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import structlog.testing
from taskiq import Context, InMemoryBroker, TaskiqMessage, TaskiqState

from osu_server.domain.beatmaps import BeatmapFetchTargetKind
from osu_server.infrastructure.jobs.registry import jobs
from osu_server.jobs.beatmap_fetch import (
    fetch_beatmap_file,
    fetch_beatmap_metadata,
    get_beatmap_file_fetch,
    get_beatmap_metadata_fetch,
)

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import BeatmapFetchTarget


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeJob:
    """Task adapterが渡す取得対象を記録するtest double.

    Attributes:
        calls (list[BeatmapFetchTarget]): executeへ渡された取得対象の呼び出し順.
    """

    def __init__(self) -> None:
        """空の呼び出し履歴を持つtest doubleを初期化する."""
        self.calls: list[BeatmapFetchTarget] = []

    async def execute(self, target: BeatmapFetchTarget) -> None:
        """取得対象を記録してadapterの委譲を観測可能にする.

        Args:
            target (BeatmapFetchTarget): adapterが構築してuse-caseへ渡す取得対象.

        Returns:
            None: 取得対象を履歴へ追加して値を返さずに完了する.
        """
        self.calls.append(target)


def _make_context(**services: object) -> Context:
    """指定serviceをTaskiq stateへ登録したtest用contextを構築する.

    Args:
        **services (object): state属性名と登録するtest doubleの対応.

    Returns:
        Context: 指定serviceを参照できるTaskiq実行context.
    """
    broker = InMemoryBroker()
    for key, value in services.items():
        object.__setattr__(broker.state, key, value)
    message = TaskiqMessage(
        task_id="test-task-id",
        task_name="test",
        labels={},
        args=[],
        kwargs={},
    )
    return Context(message, broker)


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


class TestBeatmapFetchTaskRegistration:
    """Beatmap取得taskがjobs registryへ登録される契約を検証する."""

    def test_fetch_beatmap_metadata_is_registered(self) -> None:
        """metadata取得task名がregistryから発見できることを検証する.

        Returns:
            None: ``fetch_beatmap_metadata`` が登録済みであることを確認して完了する.
        """
        assert "fetch_beatmap_metadata" in jobs.task_names

    def test_fetch_beatmap_file_is_registered(self) -> None:
        """Beatmap file取得task名がregistryから発見できることを検証する.

        Returns:
            None: ``fetch_beatmap_file`` が登録済みであることを確認して完了する.
        """
        assert "fetch_beatmap_file" in jobs.task_names


# ---------------------------------------------------------------------------
# Runtime-unavailable tests
# ---------------------------------------------------------------------------


class TestBeatmapFetchTaskRuntimeUnavailable:
    """必須use-caseがTaskiq stateにない場合の失敗契約を検証する."""

    async def test_metadata_task_raises_when_runtime_missing(self) -> None:
        """metadata用use-case未登録時に例外とerror logを残すことを検証する.

        Returns:
            None: task名とpayloadを含むruntime unavailable logを確認して完了する.
        """
        context = _make_context()

        with (
            structlog.testing.capture_logs() as logs,
            pytest.raises(
                RuntimeError,
                match="beatmap metadata fetch use-case is not registered",
            ),
        ):
            await fetch_beatmap_metadata(
                target_type="metadata:beatmap",
                target_key="2000",
                context=context,
            )

        entries = [
            entry
            for entry in logs
            if entry.get("event") == "beatmap_metadata_fetch_runtime_unavailable"
        ]
        assert len(entries) == 1
        assert entries[0]["task_name"] == "fetch_beatmap_metadata"
        assert entries[0]["target_type"] == "metadata:beatmap"
        assert entries[0]["target_key"] == "2000"
        assert entries[0]["log_level"] == "error"

    async def test_file_task_raises_when_runtime_missing(self) -> None:
        """file用use-case未登録時に例外とerror logを残すことを検証する.

        Returns:
            None: task名とpayloadを含むruntime unavailable logを確認して完了する.
        """
        context = _make_context()

        with (
            structlog.testing.capture_logs() as logs,
            pytest.raises(
                RuntimeError,
                match="beatmap file fetch use-case is not registered",
            ),
        ):
            await fetch_beatmap_file(
                target_type="file:beatmap",
                target_key="2000",
                context=context,
            )

        entries = [
            entry
            for entry in logs
            if entry.get("event") == "beatmap_file_fetch_runtime_unavailable"
        ]
        assert len(entries) == 1
        assert entries[0]["task_name"] == "fetch_beatmap_file"
        assert entries[0]["target_type"] == "file:beatmap"
        assert entries[0]["target_key"] == "2000"
        assert entries[0]["log_level"] == "error"

    async def test_metadata_task_does_not_call_job_when_runtime_missing(self) -> None:
        """異なるstate keyのtest doubleをmetadata taskが実行しないことを検証する.

        Returns:
            None: runtime未登録の例外後もtest doubleの呼び出し履歴が空であることを確認する.
        """
        fake = _FakeJob()
        # Attach the fake under a *different* key so the task does not find it.
        context = _make_context(wrong_key=fake)
        with pytest.raises(RuntimeError):
            await fetch_beatmap_metadata(
                target_type="metadata:beatmap",
                target_key="2000",
                context=context,
            )
        assert len(fake.calls) == 0

    async def test_file_task_does_not_call_job_when_runtime_missing(self) -> None:
        """異なるstate keyのtest doubleをfile taskが実行しないことを検証する.

        Returns:
            None: runtime未登録の例外後もtest doubleの呼び出し履歴が空であることを確認する.
        """
        fake = _FakeJob()
        context = _make_context(wrong_key=fake)
        with pytest.raises(RuntimeError):
            await fetch_beatmap_file(
                target_type="file:beatmap",
                target_key="2000",
                context=context,
            )
        assert len(fake.calls) == 0


# ---------------------------------------------------------------------------
# Runtime-available tests
# ---------------------------------------------------------------------------


class TestBeatmapFetchTaskExecution:
    """登録済みuse-caseへTaskiq adapterが正しい取得対象を委譲する契約を検証する."""

    async def test_metadata_task_delegates_to_service(self) -> None:
        """Metadata taskがID取得対象をuse-caseへ1回だけ渡すことを検証する.

        Returns:
            None: kind,target key,既定refresh指定を含む取得対象を確認して完了する.
        """
        fake = _FakeJob()
        context = _make_context(beatmap_metadata_fetch=fake)
        await fetch_beatmap_metadata(
            target_type="metadata:beatmap",
            target_key="2000",
            context=context,
        )
        assert len(fake.calls) == 1
        assert fake.calls[0].kind is BeatmapFetchTargetKind.METADATA_BY_BEATMAP_ID
        assert fake.calls[0].target_key == "2000"
        assert fake.calls[0].force_refresh is False

    async def test_file_task_delegates_to_service(self) -> None:
        """File taskがID取得対象をuse-caseへ1回だけ渡すことを検証する.

        Returns:
            None: file用kindとtarget keyを含む取得対象を確認して完了する.
        """
        fake = _FakeJob()
        context = _make_context(beatmap_file_fetch=fake)
        await fetch_beatmap_file(
            target_type="file:beatmap",
            target_key="2000",
            context=context,
        )
        assert len(fake.calls) == 1
        assert fake.calls[0].kind is BeatmapFetchTargetKind.FILE_BY_BEATMAP_ID
        assert fake.calls[0].target_key == "2000"

    async def test_metadata_task_constructs_beatmap_fetch_target(self) -> None:
        """checksum形式payloadをmetadata取得対象へ変換することを検証する.

        Returns:
            None: checksum用kindと変更しないtarget keyを確認して完了する.
        """
        fake = _FakeJob()
        context = _make_context(beatmap_metadata_fetch=fake)
        await fetch_beatmap_metadata(
            target_type="metadata:checksum",
            target_key="md5:checksum-for-test",
            context=context,
        )
        assert len(fake.calls) == 1
        assert fake.calls[0].kind is BeatmapFetchTargetKind.METADATA_BY_CHECKSUM
        assert fake.calls[0].target_key == "md5:checksum-for-test"

    async def test_metadata_task_preserves_force_refresh_flag(self) -> None:
        """明示したforce refresh指定をmetadata取得対象へ保持することを検証する.

        Returns:
            None: use-caseへ渡す対象のforce_refreshがTrueであることを確認して完了する.
        """
        fake = _FakeJob()
        context = _make_context(beatmap_metadata_fetch=fake)
        await fetch_beatmap_metadata(
            target_type="metadata:beatmap",
            target_key="2000",
            force_refresh=True,
            context=context,
        )

        assert len(fake.calls) == 1
        assert fake.calls[0].force_refresh is True

    async def test_file_task_constructs_beatmap_fetch_target(self) -> None:
        """file形式payloadをbeatmap file取得対象へ変換することを検証する.

        Returns:
            None: file用kindと変更しないtarget keyを確認して完了する.
        """
        fake = _FakeJob()
        context = _make_context(beatmap_file_fetch=fake)
        await fetch_beatmap_file(
            target_type="file:beatmap",
            target_key="9999",
            context=context,
        )
        assert len(fake.calls) == 1
        assert fake.calls[0].kind is BeatmapFetchTargetKind.FILE_BY_BEATMAP_ID
        assert fake.calls[0].target_key == "9999"


# ---------------------------------------------------------------------------
# State getter tests
# ---------------------------------------------------------------------------


class TestBeatmapFetchStateGetters:
    """Taskiq stateからBeatmap取得use-caseを解決するgetter契約を検証する."""

    def test_get_beatmap_metadata_fetch_returns_service(self) -> None:
        """metadata取得use-caseが登録済みなら同一instanceを返すことを検証する.

        Returns:
            None: stateへ登録したtest doubleとgetter結果が同一であることを確認する.
        """
        fake = _FakeJob()
        state = TaskiqState()
        object.__setattr__(state, "beatmap_metadata_fetch", fake)
        result = get_beatmap_metadata_fetch(state)
        assert result is fake

    def test_get_beatmap_metadata_fetch_returns_none_when_missing(self) -> None:
        """metadata取得use-case未登録時にNoneを返すことを検証する.

        Returns:
            None: 空のstateからのgetter結果がNoneであることを確認する.
        """
        state = TaskiqState()
        result = get_beatmap_metadata_fetch(state)
        assert result is None

    def test_get_beatmap_file_fetch_returns_service(self) -> None:
        """file取得use-caseが登録済みなら同一instanceを返すことを検証する.

        Returns:
            None: stateへ登録したtest doubleとgetter結果が同一であることを確認する.
        """
        fake = _FakeJob()
        state = TaskiqState()
        object.__setattr__(state, "beatmap_file_fetch", fake)
        result = get_beatmap_file_fetch(state)
        assert result is fake

    def test_get_beatmap_file_fetch_returns_none_when_missing(self) -> None:
        """file取得use-case未登録時にNoneを返すことを検証する.

        Returns:
            None: 空のstateからのgetter結果がNoneであることを確認する.
        """
        state = TaskiqState()
        result = get_beatmap_file_fetch(state)
        assert result is None
