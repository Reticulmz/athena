"""Beatmap Leaderboard再構築Taskiq adapterのunit testを提供する."""

from __future__ import annotations

import inspect
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
import structlog.testing
from taskiq import Context, InMemoryBroker, TaskiqMessage, TaskiqState

from osu_server.infrastructure.jobs.registry import jobs
from osu_server.jobs import beatmap_leaderboards, register_all_jobs
from osu_server.jobs.beatmap_leaderboards import (
    TaskiqBeatmapLeaderboardRebuildWorkerWake,
    get_beatmap_leaderboard_beatmapset_rebuild_use_case,
    get_beatmap_leaderboard_user_rebuild_use_case,
    rebuild_beatmap_leaderboards_for_beatmapset,
    rebuild_beatmap_leaderboards_for_user,
)
from osu_server.services.commands.scores.leaderboards import RebuildBeatmapLeaderboardsResult

if TYPE_CHECKING:
    from osu_server.services.commands.scores.leaderboards import (
        RebuildBeatmapLeaderboardsForBeatmapsetCommand,
        RebuildBeatmapLeaderboardsForUserCommand,
    )


class _FakeUserRebuildUseCase:
    """user単位再構築commandを記録し,設定済み結果または例外を返すtest double.

    Attributes:
        calls (list[RebuildBeatmapLeaderboardsForUserCommand]): executeへ渡されたcommand履歴.
        _result (RebuildBeatmapLeaderboardsResult | None): 既定結果を置き換える返却結果.
        _error (Exception | None): executeで送出する永続化失敗の再現値.
    """

    calls: list[RebuildBeatmapLeaderboardsForUserCommand]
    _result: RebuildBeatmapLeaderboardsResult | None
    _error: Exception | None

    def __init__(
        self,
        *,
        result: RebuildBeatmapLeaderboardsResult | None = None,
        error: Exception | None = None,
    ) -> None:
        """再構築結果または失敗を設定したtest doubleを初期化する.

        Args:
            result (RebuildBeatmapLeaderboardsResult | None): executeで返す結果.
                Noneなら既定成功結果.
            error (Exception | None): executeで送出する例外. Noneなら送出しない.
        """
        self.calls = []
        self._result = result
        self._error = error

    async def execute(
        self,
        command: RebuildBeatmapLeaderboardsForUserCommand,
    ) -> RebuildBeatmapLeaderboardsResult:
        """user再構築commandを記録して設定済みの実行結果を返す.

        Args:
            command (RebuildBeatmapLeaderboardsForUserCommand): adapterが構築したuser再構築command.

        Returns:
            RebuildBeatmapLeaderboardsResult: 設定済みまたは既定の再構築結果.
        """
        self.calls.append(command)
        if self._error is not None:
            raise self._error
        if self._result is not None:
            return self._result
        return RebuildBeatmapLeaderboardsResult(
            target_found=True,
            source_score_count=2,
            projection_row_count=3,
        )


class _FakeBeatmapsetRebuildUseCase:
    """beatmapset単位再構築commandを記録し,設定済み結果または例外を返すtest double.

    Attributes:
        calls (list[RebuildBeatmapLeaderboardsForBeatmapsetCommand]): executeへ渡されたcommand履歴.
        _result (RebuildBeatmapLeaderboardsResult | None): 既定結果を置き換える返却結果.
        _error (Exception | None): executeで送出する永続化失敗の再現値.
    """

    calls: list[RebuildBeatmapLeaderboardsForBeatmapsetCommand]
    _result: RebuildBeatmapLeaderboardsResult | None
    _error: Exception | None

    def __init__(
        self,
        *,
        result: RebuildBeatmapLeaderboardsResult | None = None,
        error: Exception | None = None,
    ) -> None:
        """再構築結果または失敗を設定したtest doubleを初期化する.

        Args:
            result (RebuildBeatmapLeaderboardsResult | None): executeで返す結果.
                Noneなら既定成功結果.
            error (Exception | None): executeで送出する例外. Noneなら送出しない.
        """
        self.calls = []
        self._result = result
        self._error = error

    async def execute(
        self,
        command: RebuildBeatmapLeaderboardsForBeatmapsetCommand,
    ) -> RebuildBeatmapLeaderboardsResult:
        """beatmapset再構築commandを記録して設定済みの実行結果を返す.

        Args:
            command (RebuildBeatmapLeaderboardsForBeatmapsetCommand): adapterが構築した
                beatmapset再構築command.

        Returns:
            RebuildBeatmapLeaderboardsResult: 設定済みまたは既定の再構築結果.
        """
        self.calls.append(command)
        if self._error is not None:
            raise self._error
        if self._result is not None:
            return self._result
        return RebuildBeatmapLeaderboardsResult(
            target_found=True,
            source_score_count=4,
            projection_row_count=5,
        )


def _make_context(**services: object) -> Context:
    """指定use-caseをTaskiq stateへ登録したtest contextを構築する.

    Args:
        **services (object): state属性名と登録するuse-case doubleの対応.

    Returns:
        Context: leaderboard再構築taskを実行できるTaskiq context.
    """
    broker = InMemoryBroker()
    for key, value in services.items():
        object.__setattr__(broker.state, key, value)
    message = TaskiqMessage(
        task_id="beatmap-leaderboard-test-task",
        task_name="test",
        labels={},
        args=[],
        kwargs={},
    )
    return Context(message, broker)


class _FakeEnqueueableTask:
    """worker wakeがenqueueするpayloadと失敗を再現するtask double.

    Attributes:
        _error (Exception | None): kiqで送出する例外. Noneならenqueue成功を返す.
        calls (list[tuple[tuple[object, ...], dict[str, object]]]): kiqへ渡されたpayload履歴.
    """

    def __init__(self, *, error: Exception | None = None) -> None:
        """enqueue失敗の有無と空のpayload履歴を設定する.

        Args:
            error (Exception | None): kiqで送出する例外. Noneなら正常に完了する.
        """
        self._error: Exception | None = error
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def kiq(self, *args: object, **kwargs: object) -> object:
        """payloadを記録して成功objectを返すか,設定済み例外を送出する.

        Args:
            *args (object): taskへ渡される位置引数payload.
            **kwargs (object): taskへ渡される名前付きpayload.

        Returns:
            object: enqueue成功を表す新しいobject.
        """
        self.calls.append((args, kwargs))
        if self._error is not None:
            raise self._error
        return object()


class _FakeBroker:
    """指定taskを返し,worker wakeのtask lookupを記録するbroker double.

    Attributes:
        _task (_FakeEnqueueableTask | None): lookup時に返すtask. Noneは未登録を表す.
        task_names (list[str]): find_taskへ渡されたtask名の履歴.
    """

    def __init__(self, task: _FakeEnqueueableTask | None) -> None:
        """lookup結果に使うtask doubleを初期化する.

        Args:
            task (_FakeEnqueueableTask | None): 返すtask. Noneなら未登録状態を再現する.
        """
        self._task: _FakeEnqueueableTask | None = task
        self.task_names: list[str] = []

    def find_task(self, task_name: str) -> _FakeEnqueueableTask | None:
        """task名を記録して設定済みtaskを返す.

        Args:
            task_name (str): worker wakeが解決を試みるtask名.

        Returns:
            _FakeEnqueueableTask | None: 設定済みtask,または未登録を表すNone.
        """
        self.task_names.append(task_name)
        return self._task


class TestBeatmapLeaderboardTaskRegistration:
    """leaderboard再構築taskのregistry登録とimport時登録契約を検証する."""

    def test_user_rebuild_task_is_registered(self) -> None:
        """user再構築task名がjobs registryに存在することを検証する.

        Returns:
            None: user再構築task名が登録済みであることを確認して完了する.
        """
        assert "rebuild_beatmap_leaderboards_for_user" in jobs.task_names

    def test_beatmapset_rebuild_task_is_registered(self) -> None:
        """beatmapset再構築task名がjobs registryに存在することを検証する.

        Returns:
            None: beatmapset再構築task名が登録済みであることを確認して完了する.
        """
        assert "rebuild_beatmap_leaderboards_for_beatmapset" in jobs.task_names

    def test_register_all_jobs_attaches_rebuild_tasks_to_broker(self) -> None:
        """register_all_jobsが両再構築taskをbrokerへ接続することを検証する.

        Returns:
            None: user用とbeatmapset用のtaskをbrokerから発見できることを確認する.
        """
        broker = InMemoryBroker()

        register_all_jobs(broker)

        assert broker.find_task("rebuild_beatmap_leaderboards_for_user") is not None
        assert broker.find_task("rebuild_beatmap_leaderboards_for_beatmapset") is not None

    def test_register_all_jobs_loads_rebuild_tasks_in_fresh_process(self) -> None:
        """新規processでもimport経由の再構築task登録を完了できることを検証する.

        Returns:
            None: subprocessが両taskを発見して終了status 0になることを確認する.
        """
        code = """
from taskiq import InMemoryBroker
from osu_server.jobs import register_all_jobs

broker = InMemoryBroker()
register_all_jobs(broker)
assert broker.find_task("rebuild_beatmap_leaderboards_for_user") is not None
assert broker.find_task("rebuild_beatmap_leaderboards_for_beatmapset") is not None
"""

        result = subprocess.run(
            [sys.executable, "-c", code],
            check=False,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr


def test_beatmap_leaderboard_job_stays_queue_adapter_only() -> None:
    """Leaderboard jobがrepositoryや低水準infrastructureを所有しないことを検証する.

    Returns:
        None: sourceにSQLAlchemy,repository,Valkey参照がないことを確認して完了する.
    """
    source = inspect.getsource(beatmap_leaderboards)

    assert "sqlalchemy" not in source
    assert "osu_server.repositories" not in source
    assert "Valkey" not in source


class TestBeatmapLeaderboardTaskRuntimeUnavailable:
    """必須use-caseがTaskiq stateにない場合の失敗契約を検証する."""

    async def test_user_rebuild_task_raises_when_runtime_missing(self) -> None:
        """User use-case未登録時に例外と対象情報付きerror logを残すことを検証する.

        Returns:
            None: user IDを含むruntime unavailable eventを確認して完了する.
        """
        context = _make_context()

        with (
            structlog.testing.capture_logs() as logs,
            pytest.raises(
                RuntimeError,
                match="Beatmap Leaderboard user rebuild use-case is not registered",
            ),
        ):
            await rebuild_beatmap_leaderboards_for_user(
                user_id=1000,
                reason="visibility_changed",
                context=context,
            )

        entries = [
            entry
            for entry in logs
            if entry.get("event") == "beatmap_leaderboard_rebuild_runtime_unavailable"
        ]
        assert len(entries) == 1
        assert entries[0]["task_name"] == "rebuild_beatmap_leaderboards_for_user"
        assert entries[0]["target_kind"] == "user"
        assert entries[0]["user_id"] == 1000
        assert entries[0]["log_level"] == "error"

    async def test_beatmapset_rebuild_task_raises_when_runtime_missing(self) -> None:
        """Beatmapset use-case未登録時に例外と対象情報付きerror logを残すことを検証する.

        Returns:
            None: beatmapset IDを含むruntime unavailable eventを確認して完了する.
        """
        context = _make_context()

        with (
            structlog.testing.capture_logs() as logs,
            pytest.raises(
                RuntimeError,
                match="Beatmap Leaderboard beatmapset rebuild use-case is not registered",
            ),
        ):
            await rebuild_beatmap_leaderboards_for_beatmapset(
                beatmapset_id=2000,
                reason="beatmap_checksum_changed",
                context=context,
            )

        entries = [
            entry
            for entry in logs
            if entry.get("event") == "beatmap_leaderboard_rebuild_runtime_unavailable"
        ]
        assert len(entries) == 1
        assert entries[0]["task_name"] == "rebuild_beatmap_leaderboards_for_beatmapset"
        assert entries[0]["target_kind"] == "beatmapset"
        assert entries[0]["beatmapset_id"] == 2000
        assert entries[0]["log_level"] == "error"

    async def test_user_rebuild_task_does_not_call_wrong_runtime_state(self) -> None:
        """異なるstate keyのuser use-caseをtaskが実行しないことを検証する.

        Returns:
            None: runtime未登録例外後もtest doubleのcommand履歴が空であることを確認する.
        """
        fake = _FakeUserRebuildUseCase()
        context = _make_context(wrong_key=fake)

        with pytest.raises(RuntimeError):
            await rebuild_beatmap_leaderboards_for_user(
                user_id=1000,
                reason="visibility_changed",
                context=context,
            )

        assert fake.calls == []

    async def test_beatmapset_rebuild_task_does_not_call_wrong_runtime_state(self) -> None:
        """異なるstate keyのbeatmapset use-caseをtaskが実行しないことを検証する.

        Returns:
            None: runtime未登録例外後もtest doubleのcommand履歴が空であることを確認する.
        """
        fake = _FakeBeatmapsetRebuildUseCase()
        context = _make_context(wrong_key=fake)

        with pytest.raises(RuntimeError):
            await rebuild_beatmap_leaderboards_for_beatmapset(
                beatmapset_id=2000,
                reason="beatmap_checksum_changed",
                context=context,
            )

        assert fake.calls == []


class TestBeatmapLeaderboardTaskPayloadValidation:
    """leaderboard再構築taskが不正payloadを実行前に拒否する契約を検証する."""

    async def test_user_rebuild_rejects_non_int_user_id(self) -> None:
        """文字列user IDを正の整数として受理せずuse-caseを実行しないことを検証する.

        Returns:
            None: ValueError後もuser再構築command履歴が空であることを確認する.
        """
        fake = _FakeUserRebuildUseCase()
        context = _make_context(beatmap_leaderboard_user_rebuild_use_case=fake)

        with pytest.raises(ValueError, match="user_id must be a positive integer"):
            await rebuild_beatmap_leaderboards_for_user(
                user_id="1000",
                reason="visibility_changed",
                context=context,
            )

        assert fake.calls == []

    async def test_user_rebuild_rejects_bool_user_id(self) -> None:
        """boolのuser IDを正の整数として受理せずuse-caseを実行しないことを検証する.

        Returns:
            None: ValueError後もuser再構築command履歴が空であることを確認する.
        """
        fake = _FakeUserRebuildUseCase()
        context = _make_context(beatmap_leaderboard_user_rebuild_use_case=fake)

        with pytest.raises(ValueError, match="user_id must be a positive integer"):
            await rebuild_beatmap_leaderboards_for_user(
                user_id=True,
                reason="visibility_changed",
                context=context,
            )

        assert fake.calls == []

    async def test_beatmapset_rebuild_rejects_empty_reason(self) -> None:
        """空のreasonを受理せずbeatmapset use-caseを実行しないことを検証する.

        Returns:
            None: ValueError後もbeatmapset再構築command履歴が空であることを確認する.
        """
        fake = _FakeBeatmapsetRebuildUseCase()
        context = _make_context(beatmap_leaderboard_beatmapset_rebuild_use_case=fake)

        with pytest.raises(ValueError, match="reason must be a non-empty string"):
            await rebuild_beatmap_leaderboards_for_beatmapset(
                beatmapset_id=2000,
                reason="",
                context=context,
            )

        assert fake.calls == []


class TestBeatmapLeaderboardTaskExecution:
    """正当なpayloadを再構築commandへ変換してuse-caseへ委譲する契約を検証する."""

    async def test_user_rebuild_task_delegates_with_command(self) -> None:
        """User payloadをuser IDとreasonを持つcommandとして委譲することを検証する.

        Returns:
            None: use-caseが1回呼ばれ,commandの値がpayloadと一致することを確認する.
        """
        fake = _FakeUserRebuildUseCase()
        context = _make_context(beatmap_leaderboard_user_rebuild_use_case=fake)

        await rebuild_beatmap_leaderboards_for_user(
            user_id=1000,
            reason="visibility_changed",
            context=context,
        )

        assert len(fake.calls) == 1
        command = fake.calls[0]
        assert command.user_id == 1000
        assert command.reason == "visibility_changed"

    async def test_beatmapset_rebuild_task_delegates_with_command(self) -> None:
        """Beatmapset payloadをIDとreasonを持つcommandとして委譲することを検証する.

        Returns:
            None: use-caseが1回呼ばれ,commandの値がpayloadと一致することを確認する.
        """
        fake = _FakeBeatmapsetRebuildUseCase()
        context = _make_context(beatmap_leaderboard_beatmapset_rebuild_use_case=fake)

        await rebuild_beatmap_leaderboards_for_beatmapset(
            beatmapset_id=2000,
            reason="beatmap_checksum_changed",
            context=context,
        )

        assert len(fake.calls) == 1
        command = fake.calls[0]
        assert command.beatmapset_id == 2000
        assert command.reason == "beatmap_checksum_changed"

    async def test_duplicate_user_rebuild_execution_delegates_each_job_once(self) -> None:
        """同一user payloadの各task実行を独立したcommandとして委譲することを検証する.

        Returns:
            None: 2回のtask実行に対応する2件の同一内容command履歴を確認して完了する.
        """
        fake = _FakeUserRebuildUseCase()
        context = _make_context(beatmap_leaderboard_user_rebuild_use_case=fake)

        await rebuild_beatmap_leaderboards_for_user(
            user_id=1000,
            reason="visibility_changed",
            context=context,
        )
        await rebuild_beatmap_leaderboards_for_user(
            user_id=1000,
            reason="visibility_changed",
            context=context,
        )

        assert [(command.user_id, command.reason) for command in fake.calls] == [
            (1000, "visibility_changed"),
            (1000, "visibility_changed"),
        ]

    async def test_beatmapset_missing_target_is_noop_success(self) -> None:
        """存在しないbeatmapsetの再構築結果を成功としてinfo logへ記録することを検証する.

        Returns:
            None: use-case実行後にtarget_found=Falseを含むcompleted eventを確認して完了する.
        """
        fake = _FakeBeatmapsetRebuildUseCase(
            result=RebuildBeatmapLeaderboardsResult(
                target_found=False,
                source_score_count=0,
                projection_row_count=0,
            )
        )
        context = _make_context(beatmap_leaderboard_beatmapset_rebuild_use_case=fake)

        with structlog.testing.capture_logs() as logs:
            await rebuild_beatmap_leaderboards_for_beatmapset(
                beatmapset_id=404,
                reason="beatmap_status_changed",
                context=context,
            )

        assert len(fake.calls) == 1
        entries = [
            entry
            for entry in logs
            if entry.get("event") == "beatmap_leaderboard_rebuild_completed"
        ]
        assert len(entries) == 1
        assert entries[0]["task_name"] == "rebuild_beatmap_leaderboards_for_beatmapset"
        assert entries[0]["target_kind"] == "beatmapset"
        assert entries[0]["target_found"] is False
        assert entries[0]["log_level"] == "info"

    async def test_persistence_failure_surfaces(self) -> None:
        """use-caseの永続化失敗をtaskが握りつぶさず呼び出し側へ伝播することを検証する.

        Returns:
            None: RuntimeErrorと失敗前に1回実行したcommand履歴を確認して完了する.
        """
        fake = _FakeUserRebuildUseCase(error=RuntimeError("database unavailable"))
        context = _make_context(beatmap_leaderboard_user_rebuild_use_case=fake)

        with pytest.raises(RuntimeError, match="database unavailable"):
            await rebuild_beatmap_leaderboards_for_user(
                user_id=1000,
                reason="visibility_changed",
                context=context,
            )

        assert len(fake.calls) == 1


class TestBeatmapLeaderboardStateGetters:
    """Taskiq stateからleaderboard再構築use-caseを解決するgetter契約を検証する."""

    def test_user_rebuild_getter_returns_service(self) -> None:
        """登録済みuser再構築use-caseを同一instanceで返すことを検証する.

        Returns:
            None: stateへ登録したtest doubleとgetter結果が同一であることを確認する.
        """
        fake = _FakeUserRebuildUseCase()
        state = TaskiqState()
        object.__setattr__(state, "beatmap_leaderboard_user_rebuild_use_case", fake)

        result = get_beatmap_leaderboard_user_rebuild_use_case(state)

        assert result is fake

    def test_user_rebuild_getter_returns_none_when_missing(self) -> None:
        """user再構築use-case未登録時にgetterがNoneを返すことを検証する.

        Returns:
            None: 空のstateからのgetter結果がNoneであることを確認する.
        """
        state = TaskiqState()

        result = get_beatmap_leaderboard_user_rebuild_use_case(state)

        assert result is None

    def test_beatmapset_rebuild_getter_returns_service(self) -> None:
        """登録済みbeatmapset再構築use-caseを同一instanceで返すことを検証する.

        Returns:
            None: stateへ登録したtest doubleとgetter結果が同一であることを確認する.
        """
        fake = _FakeBeatmapsetRebuildUseCase()
        state = TaskiqState()
        object.__setattr__(state, "beatmap_leaderboard_beatmapset_rebuild_use_case", fake)

        result = get_beatmap_leaderboard_beatmapset_rebuild_use_case(state)

        assert result is fake

    def test_beatmapset_rebuild_getter_returns_none_when_missing(self) -> None:
        """beatmapset再構築use-case未登録時にgetterがNoneを返すことを検証する.

        Returns:
            None: 空のstateからのgetter結果がNoneであることを確認する.
        """
        state = TaskiqState()

        result = get_beatmap_leaderboard_beatmapset_rebuild_use_case(state)

        assert result is None


class TestTaskiqBeatmapLeaderboardRebuildWorkerWake:
    """worker wakeが再構築taskをprimitive payloadでenqueueする契約を検証する."""

    async def test_wake_user_rebuild_enqueues_primitive_payload(self) -> None:
        """user再構築wakeがtask名とprimitive ID及びreasonでenqueueすることを検証する.

        Returns:
            None: user task lookupとpayload履歴が期待値と一致することを確認する.
        """
        task = _FakeEnqueueableTask()
        broker = _FakeBroker(task)
        wake = TaskiqBeatmapLeaderboardRebuildWorkerWake(broker)

        await wake.wake_user_rebuild(user_id=1000, reason="user_visibility_changed")

        assert broker.task_names == ["rebuild_beatmap_leaderboards_for_user"]
        assert task.calls == [((1000, "user_visibility_changed"), {})]

    async def test_wake_beatmapset_rebuild_enqueues_primitive_payload(self) -> None:
        """beatmapset再構築wakeがtask名とprimitive ID及びreasonでenqueueすることを検証する.

        Returns:
            None: beatmapset task lookupとpayload履歴が期待値と一致することを確認する.
        """
        task = _FakeEnqueueableTask()
        broker = _FakeBroker(task)
        wake = TaskiqBeatmapLeaderboardRebuildWorkerWake(broker)

        await wake.wake_beatmapset_rebuild(
            beatmapset_id=2000,
            reason="beatmap_checksum_changed",
        )

        assert broker.task_names == ["rebuild_beatmap_leaderboards_for_beatmapset"]
        assert task.calls == [((2000, "beatmap_checksum_changed"), {})]

    async def test_wake_raises_when_task_is_not_registered(self) -> None:
        """user再構築task未登録時にworker wakeがRuntimeErrorを送出することを検証する.

        Returns:
            None: 未登録taskを示すRuntimeErrorが送出されることを確認して完了する.
        """
        broker = _FakeBroker(None)
        wake = TaskiqBeatmapLeaderboardRebuildWorkerWake(broker)

        with pytest.raises(
            RuntimeError,
            match="Beatmap Leaderboard user rebuild task is not registered",
        ):
            await wake.wake_user_rebuild(user_id=1000, reason="user_visibility_changed")

    async def test_wake_surfaces_enqueue_failure(self) -> None:
        """beatmapset再構築taskのenqueue失敗をworker wakeが伝播することを検証する.

        Returns:
            None: broker由来のRuntimeErrorが送出されることを確認して完了する.
        """
        task = _FakeEnqueueableTask(error=RuntimeError("broker unavailable"))
        broker = _FakeBroker(task)
        wake = TaskiqBeatmapLeaderboardRebuildWorkerWake(broker)

        with pytest.raises(RuntimeError, match="broker unavailable"):
            await wake.wake_beatmapset_rebuild(
                beatmapset_id=2000,
                reason="beatmap_checksum_changed",
            )
