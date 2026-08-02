"""Query repository 用の in-memory state snapshot provider を提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


class InMemoryQueryStateSnapshotProvider:
    """Query repository 向けに committed in-memory state snapshot を返す.

    Attributes:
        _state (InMemoryCommandRepositoryState): repository family が共有する committed state.

    Notes:
        Command Unit of Work factory には依存しない. 各 snapshot 呼び出しで clone を返し,
        query repository が committed state の container を直接変更しないようにする.
    """

    def __init__(self, state: InMemoryCommandRepositoryState) -> None:
        """共有する committed state を snapshot source として保持する.

        Args:
            state (InMemoryCommandRepositoryState): query repository family が読む committed state.
        """
        self._state: InMemoryCommandRepositoryState = state

    def snapshot(self) -> InMemoryCommandRepositoryState:
        """Committed in-memory state の read snapshot を clone して返す.

        Returns:
            InMemoryCommandRepositoryState: committed state から clone した snapshot.

        Notes:
            返した snapshot への変更は provider の committed state に反映されない.
        """
        return self._state.clone()
