"""ForbiddenWords gitlint ルールのユニットテストを提供する."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from gitlint_rules.forbidden_words import FORBIDDEN_WORDS, ForbiddenWords


def _make_commit(title: str) -> MagicMock:
    """指定 title を持つ GitCommit モックを生成する.

    Args:
        title (str): commit message の title.

    Returns:
        MagicMock: message.title を持つ GitCommit 互換モック.
    """
    message = MagicMock()
    message.title = title
    commit = MagicMock()
    commit.message = message
    return commit


class TestForbiddenWordsDetection:
    """禁止ワードだけの description を拒否する契約を集約する."""

    @pytest.mark.parametrize(
        "title",
        [
            "feat: update",
            "fix(scope): fix",
            "chore: change",
            "refactor: modify",
            "docs: wip",
            "feat: 更新",
            "fix: 修正",
            "chore: 変更",
            "refactor: 対応",
        ],
    )
    def test_rejects_forbidden_word_only_description(self, title: str) -> None:
        """前提: description が禁止ワードだけから成る commit title を用意する.

        操作: ForbiddenWords rule で commit を検証する.
        結果: UC1 violation が1件返る.

        Args:
            title (str): 検証する parameterized commit title.

        Returns:
            None: 禁止 description の拒否契約を検証する.
        """
        rule = ForbiddenWords()
        commit = _make_commit(title)
        violations = rule.validate(commit)
        assert violations is not None
        assert len(violations) == 1
        assert violations[0].rule_id == "UC1"

    @pytest.mark.parametrize(
        "title",
        [
            "feat: Update",
            "fix: FIX",
            "chore: CHANGE",
            "refactor: WIP",
            "docs: Modify",
        ],
    )
    def test_case_insensitive_detection(self, title: str) -> None:
        """前提: 禁止ワードを大文字小文字違いで含む commit title を用意する.

        操作: ForbiddenWords rule で commit を検証する.
        結果: case に関わらず violation が1件返る.

        Args:
            title (str): 検証する parameterized commit title.

        Returns:
            None: case-insensitive 検出契約を検証する.
        """
        rule = ForbiddenWords()
        commit = _make_commit(title)
        violations = rule.validate(commit)
        assert violations is not None
        assert len(violations) == 1


class TestForbiddenWordsPassThrough:
    """正当な description を通過させる契約を集約する."""

    @pytest.mark.parametrize(
        "title",
        [
            "feat(scope): add new feature",
            "fix: resolve null pointer in login handler",
            "docs: add API reference for session store",
            "refactor: extract packet parsing into dedicated module",
            "test: add unit tests for forbidden words rule",
            "chore: bump dependency versions",
        ],
    )
    def test_accepts_valid_description(self, title: str) -> None:
        """前提: 禁止ワードだけではない有効な commit title を用意する.

        操作: ForbiddenWords rule で commit を検証する.
        結果: violation は返らない.

        Args:
            title (str): 検証する parameterized commit title.

        Returns:
            None: 有効 description の通過契約を検証する.
        """
        rule = ForbiddenWords()
        commit = _make_commit(title)
        violations = rule.validate(commit)
        assert violations is None

    def test_accepts_forbidden_word_as_part_of_phrase(self) -> None:
        """前提: 禁止ワードを説明句の一部として含む commit title を用意する.

        操作: ForbiddenWords rule で commit を検証する.
        結果: 単独の禁止ワードではないため violation は返らない.

        Returns:
            None: phrase の通過契約を検証する.
        """
        rule = ForbiddenWords()
        commit = _make_commit("chore: update dependencies")
        violations = rule.validate(commit)
        assert violations is None

    def test_accepts_message_without_colon(self) -> None:
        """前提: colon を含まない commit message を用意する.

        操作: ForbiddenWords rule で message 全体を検証する.
        結果: 禁止ワードだけではない message は通過する.

        Returns:
            None: colon 非依存の評価契約を検証する.
        """
        rule = ForbiddenWords()
        commit = _make_commit("merge branch main")
        violations = rule.validate(commit)
        assert violations is None


class TestForbiddenWordsConstants:
    """禁止ワード定数の網羅性契約を集約する."""

    def test_contains_all_english_forbidden_words(self) -> None:
        """前提: ForbiddenWords の英語禁止語集合が定義される.

        操作: 定数に必須英語語が含まれるか照合する.
        結果: 全必須英語語が定数に含まれる.

        Returns:
            None: 英語禁止語の網羅契約を検証する.
        """
        expected = {"update", "fix", "change", "modify", "wip"}
        assert expected <= FORBIDDEN_WORDS

    def test_contains_all_japanese_forbidden_words(self) -> None:
        """前提: ForbiddenWords の日本語禁止語集合が定義される.

        操作: 定数に必須日本語語が含まれるか照合する.
        結果: 全必須日本語語が定数に含まれる.

        Returns:
            None: 日本語禁止語の網羅契約を検証する.
        """
        expected = {"更新", "修正", "変更", "対応"}
        assert expected <= FORBIDDEN_WORDS

    def test_no_unexpected_extra_words(self) -> None:
        """前提: ForbiddenWords の完全な禁止語集合が定義される.

        操作: 定数と期待集合を完全一致で照合する.
        結果: 未承認の追加禁止語は存在しない.

        Returns:
            None: 禁止語集合の精密な契約を検証する.
        """
        expected = {"update", "fix", "change", "modify", "wip", "更新", "修正", "変更", "対応"}
        assert expected == FORBIDDEN_WORDS
