"""In-memory query repository state snapshot provider."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


class InMemoryQueryStateSnapshotProvider:
    """Query repository 向けに committed in-memory state snapshot を返す.

    引数:
        state: In-memory repository family が共有する committed state.

    戻り値:
        Class のため戻り値はない.

    例外:
        なし.

    制約:
        Command Unit of Work factory には依存しない. 呼び出しごとに clone を返し,
        query repository が mutable committed state を直接変更できないようにする.
    """

    def __init__(self, state: InMemoryCommandRepositoryState) -> None:
        self._state: InMemoryCommandRepositoryState = state

    def snapshot(self) -> InMemoryCommandRepositoryState:
        """Committed in-memory state の read snapshot を返す.

        引数:
            なし.

        戻り値:
            Committed state から複製した snapshot.

        例外:
            なし.

        制約:
            返した snapshot の変更は committed state に反映されない.
        """

        return self._state.clone()
