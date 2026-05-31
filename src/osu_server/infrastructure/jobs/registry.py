"""Taskiq job registration utilities."""

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
    """A function and task name awaiting broker attachment."""

    task_name: str
    function: Callable[..., Awaitable[object]]


class JobRegistry:
    """Collect task functions before attaching them to a taskiq broker."""

    def __init__(self) -> None:
        self._jobs: list[JobDefinition] = []

    def register(
        self,
        *,
        task_name: str,
    ) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
        """Register a coroutine function under a taskiq task name."""

        def decorator(function: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
            self._jobs.append(JobDefinition(task_name=task_name, function=function))
            return function

        return decorator

    def attach_to(self, broker: AsyncBroker) -> None:
        """Attach all registered jobs to a taskiq broker."""
        for job in self._jobs:
            _ = broker.task(task_name=job.task_name)(job.function)


jobs = JobRegistry()
