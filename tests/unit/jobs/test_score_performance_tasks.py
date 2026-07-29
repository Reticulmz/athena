"""Score performance Taskiq adapterとworker wakeのunit testを提供する."""

from __future__ import annotations

import inspect
from datetime import UTC
from typing import TYPE_CHECKING, final

import pytest
import structlog.testing
from taskiq import Context, InMemoryBroker, TaskiqMessage, TaskiqState

from osu_server.infrastructure.jobs.registry import jobs
from osu_server.jobs import score_performance
from osu_server.jobs.score_performance import (
    TaskiqPerformanceCalculationWorkerWake,
    TaskiqPerformanceRecalculationBatchWorkerWake,
    calculate_score_performance,
    get_performance_recalculation_batch_processor,
    get_score_performance_calculation_executor,
    process_performance_recalculation_batch,
)
from osu_server.services.commands.scores.performance import (
    ExecutePerformanceCalculationOutcome,
    ExecutePerformanceCalculationResult,
    ProcessPerformanceRecalculationBatchOutcome,
    ProcessPerformanceRecalculationBatchResult,
)

if TYPE_CHECKING:
    from osu_server.services.commands.scores.performance import (
        ExecutePerformanceCalculationCommand,
        ProcessPerformanceRecalculationBatchCommand,
    )


class _FakeCalculationExecutor:
    """performance calculation commandを記録して既定結果を返すtest double.

    Attributes:
        calls (list[ExecutePerformanceCalculationCommand]): executeへ渡された
            calculation command履歴.
    """

    calls: list[ExecutePerformanceCalculationCommand]

    def __init__(self) -> None:
        """空のcalculation command履歴を持つexecutor doubleを初期化する."""
        self.calls = []

    async def execute(
        self,
        command: ExecutePerformanceCalculationCommand,
    ) -> ExecutePerformanceCalculationResult:
        """Calculation commandを記録してclaim未取得の既定結果を返す.

        Args:
            command (ExecutePerformanceCalculationCommand): task adapterが構築した
                calculation command.

        Returns:
            ExecutePerformanceCalculationResult: commandのcalculation IDを含むclaim未取得結果.
        """
        self.calls.append(command)
        return ExecutePerformanceCalculationResult(
            outcome=ExecutePerformanceCalculationOutcome.CLAIM_NOT_ACQUIRED,
            calculation_id=command.calculation_id,
        )


class _FakeBatchProcessor:
    """recalculation batch commandを記録して設定済み結果を返すtest double.

    Attributes:
        calls (list[ProcessPerformanceRecalculationBatchCommand]): executeへ渡された
            batch command履歴.
        _result (ProcessPerformanceRecalculationBatchResult | None): 既定のNO_WORK結果を
            置き換える結果.
    """

    calls: list[ProcessPerformanceRecalculationBatchCommand]
    _result: ProcessPerformanceRecalculationBatchResult | None

    def __init__(
        self,
        result: ProcessPerformanceRecalculationBatchResult | None = None,
    ) -> None:
        """batch実行結果の上書き値と空のcommand履歴を初期化する.

        Args:
            result (ProcessPerformanceRecalculationBatchResult | None): executeで返す結果.
                NoneならNO_WORK.
        """
        self.calls = []
        self._result = result

    async def execute(
        self,
        command: ProcessPerformanceRecalculationBatchCommand,
    ) -> ProcessPerformanceRecalculationBatchResult:
        """Batch commandを記録して設定済みまたはNO_WORK結果を返す.

        Args:
            command (ProcessPerformanceRecalculationBatchCommand): task adapterが構築した
                batch command.

        Returns:
            ProcessPerformanceRecalculationBatchResult: 設定済みまたはcommandのbatch IDを
                含むNO_WORK結果.
        """
        self.calls.append(command)
        if self._result is not None:
            return self._result
        return ProcessPerformanceRecalculationBatchResult(
            outcome=ProcessPerformanceRecalculationBatchOutcome.NO_WORK,
            batch_id=command.batch_id,
        )


@final
class _FakeEnqueueableTask:
    """worker wakeのenqueue payloadを記録し,設定済み失敗を再現するtask double.

    Attributes:
        _error (Exception | None): kiqで送出する例外. Noneならenqueue成功を返す.
        calls (list[tuple[tuple[object, ...], dict[str, object]]]): kiqへ渡されたpayload履歴.
    """

    def __init__(self, *, error: Exception | None = None) -> None:
        """enqueue失敗の有無と空のpayload履歴を設定する.

        Args:
            error (Exception | None): kiqで送出する例外. Noneなら正常に完了する.
        """
        self._error = error
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


@final
class _FakeBroker:
    """指定taskを返し,worker wakeのlookupを記録するbroker double.

    Attributes:
        _task (_FakeEnqueueableTask | None): lookup時に返すtask. Noneは未登録を表す.
        task_names (list[str]): find_taskへ渡されたtask名の履歴.
    """

    def __init__(self, task: _FakeEnqueueableTask | None) -> None:
        """lookup結果に使うtask doubleを初期化する.

        Args:
            task (_FakeEnqueueableTask | None): 返すtask. Noneなら未登録状態を再現する.
        """
        self._task = task
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


def _make_context(
    *,
    broker: InMemoryBroker | None = None,
    **services: object,
) -> Context:
    """指定serviceと任意brokerを持つscore performance用Taskiq contextを構築する.

    Args:
        broker (InMemoryBroker | None): 使用するbroker. Noneなら新しいInMemoryBroker.
        **services (object): state属性名と登録するservice doubleの対応.

    Returns:
        Context: score performance taskを実行できるTaskiq context.
    """
    broker = broker or InMemoryBroker()
    for key, value in services.items():
        object.__setattr__(broker.state, key, value)
    message = TaskiqMessage(
        task_id="score-performance-test-task",
        task_name="test",
        labels={},
        args=[],
        kwargs={},
    )
    return Context(message, broker)


def _make_requeue_broker(calls: list[int]) -> InMemoryBroker:
    """再enqueueしたbatch IDを記録するin-place実行brokerを構築する.

    Args:
        calls (list[int]): 再enqueue taskが追加するbatch IDの履歴.

    Returns:
        InMemoryBroker: process_performance_recalculation_batchを同期的に実行するbroker.
    """
    broker = InMemoryBroker()
    broker.await_inplace = True

    async def _record_batch(batch_id: int) -> None:
        """再enqueueされたbatch IDを記録する.

        Args:
            batch_id (int): 再実行対象としてenqueueされたbatchの識別子.

        Returns:
            None: batch IDを履歴へ追加して値を返さずに完了する.
        """
        calls.append(batch_id)

    _ = broker.register_task(
        _record_batch,
        task_name="process_performance_recalculation_batch",
    )
    return broker


class TestScorePerformanceTaskRegistration:
    """score performance taskがjobs registryへ登録される契約を検証する."""

    def test_calculation_task_is_registered(self) -> None:
        """Score calculation task名がregistryから発見できることを検証する.

        Returns:
            None: calculate_score_performanceが登録済みであることを確認して完了する.
        """
        assert "calculate_score_performance" in jobs.task_names

    def test_recalculation_batch_task_is_registered(self) -> None:
        """Recalculation batch task名がregistryから発見できることを検証する.

        Returns:
            None: process_performance_recalculation_batchが登録済みであることを確認する.
        """
        assert "process_performance_recalculation_batch" in jobs.task_names


def test_score_performance_job_stays_queue_adapter_only() -> None:
    """Score performance jobがrepositoryやcalculator実装を所有しないことを検証する.

    Returns:
        None: sourceにSQLAlchemy,repository,Valkey,Rosu calculator参照がないことを確認する.
    """
    source = inspect.getsource(score_performance)

    assert "sqlalchemy" not in source
    assert "osu_server.repositories" not in source
    assert "Valkey" not in source
    assert "RosuPerformanceCalculator" not in source
    assert "RosuPerformanceCalculator(" not in source


class TestScorePerformanceTaskRuntimeUnavailable:
    """必須serviceがTaskiq stateにない場合のtask失敗契約を検証する."""

    async def test_calculation_task_raises_when_runtime_missing(self) -> None:
        """Calculation executor未登録時に例外とerror logを残すことを検証する.

        Returns:
            None: score IDとcalculation IDを含むruntime unavailable eventを確認する.
        """
        context = _make_context()

        with (
            structlog.testing.capture_logs() as logs,
            pytest.raises(
                RuntimeError,
                match="score performance calculation use-case is not registered",
            ),
        ):
            await calculate_score_performance(
                score_id=123,
                calculation_id=456,
                context=context,
            )

        entries = [
            entry
            for entry in logs
            if entry.get("event") == "score_performance_calculation_runtime_unavailable"
        ]
        assert len(entries) == 1
        assert entries[0]["task_name"] == "calculate_score_performance"
        assert entries[0]["score_id"] == 123
        assert entries[0]["calculation_id"] == 456
        assert entries[0]["log_level"] == "error"

    async def test_recalculation_batch_task_raises_when_runtime_missing(self) -> None:
        """Batch processor未登録時に例外とerror logを残すことを検証する.

        Returns:
            None: batch IDを含むruntime unavailable eventを確認して完了する.
        """
        context = _make_context()

        with (
            structlog.testing.capture_logs() as logs,
            pytest.raises(
                RuntimeError,
                match="performance recalculation batch use-case is not registered",
            ),
        ):
            await process_performance_recalculation_batch(
                batch_id=789,
                context=context,
            )

        entries = [
            entry
            for entry in logs
            if entry.get("event") == "performance_recalculation_batch_runtime_unavailable"
        ]
        assert len(entries) == 1
        assert entries[0]["task_name"] == "process_performance_recalculation_batch"
        assert entries[0]["batch_id"] == 789
        assert entries[0]["log_level"] == "error"

    async def test_calculation_task_does_not_call_wrong_runtime_state(self) -> None:
        """異なるstate keyのcalculation executorをtaskが実行しないことを検証する.

        Returns:
            None: runtime未登録例外後もexecutorのcommand履歴が空であることを確認する.
        """
        fake = _FakeCalculationExecutor()
        context = _make_context(wrong_key=fake)

        with pytest.raises(RuntimeError):
            await calculate_score_performance(
                score_id=123,
                calculation_id=456,
                context=context,
            )

        assert fake.calls == []

    async def test_recalculation_batch_task_does_not_call_wrong_runtime_state(self) -> None:
        """異なるstate keyのbatch processorをtaskが実行しないことを検証する.

        Returns:
            None: runtime未登録例外後もprocessorのcommand履歴が空であることを確認する.
        """
        fake = _FakeBatchProcessor()
        context = _make_context(wrong_key=fake)

        with pytest.raises(RuntimeError):
            await process_performance_recalculation_batch(batch_id=789, context=context)

        assert fake.calls == []


class TestScorePerformanceTaskExecution:
    """正当なpayloadをperformance commandへ変換してserviceへ委譲する契約を検証する."""

    async def test_calculation_task_delegates_to_executor_with_command(self) -> None:
        """Calculation taskがTaskiq task IDをclaim ownerにしたcommandを委譲することを検証する.

        Returns:
            None: calculation ID,claim owner,UTC claim時刻を持つcommandを確認して完了する.
        """
        fake = _FakeCalculationExecutor()
        context = _make_context(score_performance_calculation_executor=fake)

        await calculate_score_performance(
            score_id=123,
            calculation_id=456,
            context=context,
        )

        assert len(fake.calls) == 1
        command = fake.calls[0]
        assert command.calculation_id == 456
        assert command.claim_owner == "taskiq:score-performance-test-task"
        assert command.claimed_at.tzinfo is UTC

    async def test_recalculation_batch_task_delegates_to_processor(self) -> None:
        """Batch taskがTaskiq task IDをclaim ownerにしたcommandを委譲することを検証する.

        Returns:
            None: batch ID,claim owner,UTC claim時刻を持つcommandを確認して完了する.
        """
        fake = _FakeBatchProcessor()
        context = _make_context(performance_recalculation_batch_processor=fake)

        await process_performance_recalculation_batch(batch_id=789, context=context)

        assert len(fake.calls) == 1
        command = fake.calls[0]
        assert command.batch_id == 789
        assert command.claim_owner == "taskiq:score-performance-test-task"
        assert command.claimed_at.tzinfo is UTC

    async def test_recalculation_batch_task_reenqueues_after_non_empty_pass(self) -> None:
        """処理済みbatchが残作業を探索するため同じbatch IDを再enqueueすることを検証する.

        Returns:
            None: processorを1回実行後に同じbatch IDが1回再enqueueされることを確認する.
        """
        fake = _FakeBatchProcessor(
            ProcessPerformanceRecalculationBatchResult(
                outcome=ProcessPerformanceRecalculationBatchOutcome.PROCESSED,
                batch_id=789,
                claimed_count=2,
            )
        )
        requeued_batches: list[int] = []
        broker = _make_requeue_broker(requeued_batches)
        context = _make_context(
            broker=broker,
            performance_recalculation_batch_processor=fake,
        )

        await process_performance_recalculation_batch(batch_id=789, context=context)

        assert len(fake.calls) == 1
        assert requeued_batches == [789]


class TestTaskiqPerformanceCalculationWorkerWake:
    """score calculation worker wakeがTaskiq taskをenqueueする契約を検証する."""

    async def test_wake_enqueues_calculation_task_with_primitive_ids(self) -> None:
        """Score IDとcalculation IDをprimitive payloadでenqueueすることを検証する.

        Returns:
            None: calculation task lookupとID payload履歴が期待値と一致することを確認する.
        """
        task = _FakeEnqueueableTask()
        broker = _FakeBroker(task)
        wake = TaskiqPerformanceCalculationWorkerWake(broker)

        await wake.wake_score_calculation(score_id=123, calculation_id=456)

        assert broker.task_names == ["calculate_score_performance"]
        assert task.calls == [((123, 456), {})]

    async def test_wake_raises_and_logs_when_task_is_not_registered(self) -> None:
        """Calculation task未登録時に例外と対象情報付きerror logを残すことを検証する.

        Returns:
            None: task名,score ID,calculation IDを含む未登録eventを確認して完了する.
        """
        broker = _FakeBroker(None)
        wake = TaskiqPerformanceCalculationWorkerWake(broker)

        with (
            structlog.testing.capture_logs() as logs,
            pytest.raises(
                RuntimeError,
                match="score performance calculation task is not registered",
            ),
        ):
            await wake.wake_score_calculation(score_id=123, calculation_id=456)

        entries = [
            entry
            for entry in logs
            if entry.get("event") == "score_performance_calculation_task_not_registered"
        ]
        assert len(entries) == 1
        assert entries[0]["task_name"] == "calculate_score_performance"
        assert entries[0]["score_id"] == 123
        assert entries[0]["calculation_id"] == 456
        assert entries[0]["log_level"] == "error"

    async def test_wake_raises_and_logs_when_enqueue_fails(self) -> None:
        """Calculation taskのenqueue失敗を伝播しerror logへ記録することを検証する.

        Returns:
            None: broker由来例外と対象情報付きenqueue failure eventを確認して完了する.
        """
        task = _FakeEnqueueableTask(error=RuntimeError("broker unavailable"))
        broker = _FakeBroker(task)
        wake = TaskiqPerformanceCalculationWorkerWake(broker)

        with (
            structlog.testing.capture_logs() as logs,
            pytest.raises(RuntimeError, match="broker unavailable"),
        ):
            await wake.wake_score_calculation(score_id=123, calculation_id=456)

        entries = [
            entry
            for entry in logs
            if entry.get("event") == "score_performance_calculation_enqueue_failed"
        ]
        assert len(entries) == 1
        assert entries[0]["task_name"] == "calculate_score_performance"
        assert entries[0]["score_id"] == 123
        assert entries[0]["calculation_id"] == 456
        assert entries[0]["log_level"] == "error"


class TestTaskiqPerformanceRecalculationBatchWorkerWake:
    """recalculation batch worker wakeがTaskiq taskをenqueueする契約を検証する."""

    async def test_wake_enqueues_recalculation_batch_task_with_primitive_id(self) -> None:
        """Batch IDをprimitive payloadでrecalculation taskへenqueueすることを検証する.

        Returns:
            None: batch task lookupとID payload履歴が期待値と一致することを確認する.
        """
        task = _FakeEnqueueableTask()
        broker = _FakeBroker(task)
        wake = TaskiqPerformanceRecalculationBatchWorkerWake(broker)

        await wake.wake_recalculation_batch(batch_id=789)

        assert broker.task_names == ["process_performance_recalculation_batch"]
        assert task.calls == [((789,), {})]

    async def test_wake_raises_and_logs_when_task_is_not_registered(self) -> None:
        """Recalculation task未登録時に例外とbatch ID付きerror logを残すことを検証する.

        Returns:
            None: task名とbatch IDを含む未登録eventを確認して完了する.
        """
        broker = _FakeBroker(None)
        wake = TaskiqPerformanceRecalculationBatchWorkerWake(broker)

        with (
            structlog.testing.capture_logs() as logs,
            pytest.raises(
                RuntimeError,
                match="performance recalculation batch task is not registered",
            ),
        ):
            await wake.wake_recalculation_batch(batch_id=789)

        entries = [
            entry
            for entry in logs
            if entry.get("event") == "performance_recalculation_batch_task_not_registered"
        ]
        assert len(entries) == 1
        assert entries[0]["task_name"] == "process_performance_recalculation_batch"
        assert entries[0]["batch_id"] == 789
        assert entries[0]["log_level"] == "error"

    async def test_wake_raises_and_logs_when_enqueue_fails(self) -> None:
        """Recalculation taskのenqueue失敗を伝播しerror logへ記録することを検証する.

        Returns:
            None: broker由来例外とtask名及びbatch IDを含むfailure eventを確認する.
        """
        task = _FakeEnqueueableTask(error=RuntimeError("broker unavailable"))
        broker = _FakeBroker(task)
        wake = TaskiqPerformanceRecalculationBatchWorkerWake(broker)

        with (
            structlog.testing.capture_logs() as logs,
            pytest.raises(RuntimeError, match="broker unavailable"),
        ):
            await wake.wake_recalculation_batch(batch_id=789)

        entries = [
            entry
            for entry in logs
            if entry.get("event") == "performance_recalculation_batch_enqueue_failed"
        ]
        assert len(entries) == 1
        assert entries[0]["task_name"] == "process_performance_recalculation_batch"
        assert entries[0]["batch_id"] == 789
        assert entries[0]["log_level"] == "error"


class TestScorePerformanceStateGetters:
    """Taskiq stateからscore performance serviceを解決するgetter契約を検証する."""

    def test_calculation_executor_getter_returns_service(self) -> None:
        """登録済みcalculation executorを同一instanceで返すことを検証する.

        Returns:
            None: stateへ登録したexecutorとgetter結果が同一であることを確認する.
        """
        fake = _FakeCalculationExecutor()
        state = TaskiqState()
        object.__setattr__(state, "score_performance_calculation_executor", fake)

        result = get_score_performance_calculation_executor(state)

        assert result is fake

    def test_calculation_executor_getter_returns_none_when_missing(self) -> None:
        """Calculation executor未登録時にgetterがNoneを返すことを検証する.

        Returns:
            None: 空のstateからのgetter結果がNoneであることを確認する.
        """
        state = TaskiqState()

        result = get_score_performance_calculation_executor(state)

        assert result is None

    def test_recalculation_batch_processor_getter_returns_service(self) -> None:
        """登録済みrecalculation batch processorを同一instanceで返すことを検証する.

        Returns:
            None: stateへ登録したprocessorとgetter結果が同一であることを確認する.
        """
        fake = _FakeBatchProcessor()
        state = TaskiqState()
        object.__setattr__(state, "performance_recalculation_batch_processor", fake)

        result = get_performance_recalculation_batch_processor(state)

        assert result is fake

    def test_recalculation_batch_processor_getter_returns_none_when_missing(self) -> None:
        """Recalculation batch processor未登録時にgetterがNoneを返すことを検証する.

        Returns:
            None: 空のstateからのgetter結果がNoneであることを確認する.
        """
        state = TaskiqState()

        result = get_performance_recalculation_batch_processor(state)

        assert result is None
