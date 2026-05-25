"""禁止ワードのみの description を拒否するカスタムルール."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from gitlint.rules import CommitRule, RuleViolation  # pyright: ignore[reportMissingTypeStubs]

if TYPE_CHECKING:

    class _Message(Protocol):
        @property
        def title(self) -> str: ...

    class _Commit(Protocol):
        @property
        def message(self) -> _Message: ...


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

    Conventional Commits 形式 ``type(scope): description`` の description 部分を抽出し、
    禁止ワードのみで構成されている場合に RuleViolation を返す。
    大文字小文字は区別しない。
    """

    name: str = "forbidden-words"  # pyright: ignore[reportIncompatibleUnannotatedOverride]
    id: str = "UC1"  # pyright: ignore[reportIncompatibleUnannotatedOverride]

    def validate(self, commit: _Commit) -> list[RuleViolation] | None:
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
