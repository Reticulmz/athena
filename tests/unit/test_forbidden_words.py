"""ForbiddenWords gitlint ルールのユニットテスト."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from gitlint_rules.forbidden_words import FORBIDDEN_WORDS, ForbiddenWords


def _make_commit(title: str) -> MagicMock:
    """テスト用の GitCommit モックを生成する."""
    message = MagicMock()
    message.title = title
    commit = MagicMock()
    commit.message = message
    return commit


class TestForbiddenWordsDetection:
    """禁止ワードのみで構成された description を拒否する."""

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
        rule = ForbiddenWords()
        commit = _make_commit(title)
        violations = rule.validate(commit)
        assert violations is not None
        assert len(violations) == 1


class TestForbiddenWordsPassThrough:
    """正当な description は通過させる."""

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
        rule = ForbiddenWords()
        commit = _make_commit(title)
        violations = rule.validate(commit)
        assert violations is None

    def test_accepts_forbidden_word_as_part_of_phrase(self) -> None:
        """'update' 単体は拒否だが 'update dependencies' は通過."""
        rule = ForbiddenWords()
        commit = _make_commit("chore: update dependencies")
        violations = rule.validate(commit)
        assert violations is None

    def test_accepts_message_without_colon(self) -> None:
        """コロンなしのメッセージでも description 全体を評価する."""
        rule = ForbiddenWords()
        commit = _make_commit("merge branch main")
        violations = rule.validate(commit)
        assert violations is None


class TestForbiddenWordsConstants:
    """禁止ワードリストの網羅性を検証する."""

    def test_contains_all_english_forbidden_words(self) -> None:
        expected = {"update", "fix", "change", "modify", "wip"}
        assert expected <= FORBIDDEN_WORDS

    def test_contains_all_japanese_forbidden_words(self) -> None:
        expected = {"更新", "修正", "変更", "対応"}
        assert expected <= FORBIDDEN_WORDS

    def test_no_unexpected_extra_words(self) -> None:
        expected = {"update", "fix", "change", "modify", "wip", "更新", "修正", "変更", "対応"}
        assert expected == FORBIDDEN_WORDS
