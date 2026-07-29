"""Taskiq broker への job 登録を遅延収集する utility を定義します."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ParamSpec, TypeVar

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from taskiq import AsyncBroker

P = ParamSpec("P")
R = TypeVar("R")


@dataclass(slots=True, frozen=True)
class JobDefinition:
    """Taskiq broker への接続を待つ task 名と coroutine 関数です.

    Attributes:
        task_name (str): broker 上で公開する task の一意な名前です.
        function (Callable[..., Awaitable[object]]): broker task として登録する非同期関数です.
    """

    task_name: str
    function: Callable[..., Awaitable[object]]


class JobRegistry:
    """Taskiq broker へ接続する前に task 関数を収集します.

    Attributes:
        _jobs (list[JobDefinition]): broker へ未接続の job 定義を登録順で保持します.
    """

    def __init__(self) -> None:
        """空の job 定義一覧で registry を初期化します."""
        self._jobs: list[JobDefinition] = []

    def register(
        self,
        *,
        task_name: str,
    ) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
        """非同期関数を Taskiq の task 名で登録する decorator を返します.

        Args:
            task_name (str): broker で公開する task の名前です.

        Returns:
            Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
                関数を registry へ追加し,同じ関数を返す decorator です.
        """

        def decorator(function: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
            """関数を registry へ追加して元の呼び出し可能値を返します.

            Args:
                function (Callable[P, Awaitable[R]]): 指定した task 名で登録する coroutine
                    関数です.

            Returns:
                Callable[P, Awaitable[R]]: 追加後も同じ callable contract を持つ関数です.
            """
            self._jobs.append(JobDefinition(task_name=task_name, function=function))
            return function

        return decorator

    @property
    def task_names(self) -> frozenset[str]:
        """登録済み task 名の集合を返します.

        Returns:
            frozenset[str]: 重複を除いた登録済み task 名です.
        """
        return frozenset(j.task_name for j in self._jobs)

    def attach_to(self, broker: AsyncBroker) -> None:
        """登録済みの全 job を Taskiq broker へ接続します.

        Args:
            broker (AsyncBroker): task decorator を提供する接続先 Taskiq broker です.

        Returns:
            None: 全 job の broker 接続処理が完了したことを表します.
        """
        for job in self._jobs:
            _ = broker.task(task_name=job.task_name)(job.function)


jobs = JobRegistry()
