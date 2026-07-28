"""禁止ワードのみの description を拒否するカスタムルール."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from gitlint.rules import CommitRule, RuleViolation  # pyright: ignore[reportMissingTypeStubs]

if TYPE_CHECKING:

    class _Message(Protocol):
        """この Protocol は gitlint が公開する commit message の最小 interface を表す."""

        @property
        def title(self) -> str:
            """Commit message の title を返す.

            Returns:
                str: rule が description を抽出するための commit title.
            """
            ...

    class _Commit(Protocol):
        """この Protocol は gitlint が validate hook へ渡す commit の最小 interface を表す."""

        @property
        def message(self) -> _Message:
            """Commit に紐付く message を返す.

            Returns:
                _Message: title を提供する commit message.
            """
            ...


FORBIDDEN_WORDS: set[str] = {
    "update",
    "fix",
    "change",
    "modify",
    "wip",
    "更新",
    "修正",
    "変更",
    "対応",
}


class ForbiddenWords(CommitRule):
    """description が禁止ワード単体の場合に違反を報告する.

    Conventional Commits 形式 ``type(scope): description`` の description 部分を抽出し,
    禁止ワードのみで構成されている場合に RuleViolation を返す. 大文字小文字は区別しない.

    Attributes:
        name (str): gitlint が rule を識別する名前.
        id (str): 違反へ設定する固定 rule identifier.
    """

    name: str = "forbidden-words"  # pyright: ignore[reportIncompatibleUnannotatedOverride]
    id: str = "UC1"  # pyright: ignore[reportIncompatibleUnannotatedOverride]

    def validate(self, commit: _Commit) -> list[RuleViolation] | None:
        """Commit title の description が単独の禁止ワードかを検証する.

        Args:
            commit (_Commit): title を持つ gitlint の commit object.

        Returns:
            list[RuleViolation] | None: 禁止ワードだけの場合は UC1 violation の list,
                それ以外は None.

        Notes:
            colon がない title は message 全体を description として評価する.
        """
        title: str = commit.message.title
        description: str = title.split(":", 1)[-1].strip().lower()
        if description in FORBIDDEN_WORDS:
            return [
                RuleViolation(
                    self.id,
                    f"Description must not be only a forbidden word: '{description}'",
                    line_nr=1,
                ),
            ]
        return None
