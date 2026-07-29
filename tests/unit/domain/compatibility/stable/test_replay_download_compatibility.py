"""Stable replay download compatibility vocabulary の契約を検証する."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import TypedDict, cast

from osu_server.domain.compatibility.stable import (
    REPLAY_DOWNLOAD_CONTRACT_BRANCH_LABELS_BY_BRANCH,
    ReplayDownloadBodyStrategy,
    ReplayDownloadBranch,
    ReplayDownloadResponseBody,
    ReplayDownloadStoredBlobObject,
)

TEST_ROOT = Path(__file__).resolve().parents[4]
PROJECT_ROOT = TEST_ROOT.parent
FIXTURE_DIR = TEST_ROOT / "fixtures" / "stable_compatibility" / "replay_download"
DOMAIN_MODULE = (
    PROJECT_ROOT
    / "src"
    / "osu_server"
    / "domain"
    / "compatibility"
    / "stable"
    / "replay_download.py"
)


class BodyDecisionPayload(TypedDict):
    """body assembly decision fixture に含まれるpayloadを表す.

    Attributes:
        download_body_strategy (str): fixtureが宣言するresponse body生成方針.
    """

    download_body_strategy: str


class BodyDecisionFixture(TypedDict):
    """body assembly decision fixture全体の構造を表す.

    Attributes:
        decision (BodyDecisionPayload): response bodyの生成方針を含むdecision.
    """

    decision: BodyDecisionPayload


class ResponseContractBranchFixture(TypedDict):
    """response contract fixture内の一つのbranchを表す.

    Attributes:
        branch (str): client-visible response branch label.
    """

    branch: str


class ResponseContractFixture(TypedDict):
    """response contract fixture全体の構造を表す.

    Attributes:
        branches (list[ResponseContractBranchFixture]): 検証対象のclient-visible branch群.
    """

    branches: list[ResponseContractBranchFixture]


def test_replay_download_branch_values_cover_runtime_response_vocabulary() -> None:
    """全runtime response branchが固定のclient-visible語彙を持つことを検証する.

    Returns:
        None: enum member名と値を完全一致で検証して完了する.

    Raises:
        AssertionError: branchの追加, 欠落, 順序またはwire value変更があった場合.
    """
    members = [(member.name, member.value) for member in ReplayDownloadBranch]

    assert members == [
        ("SUCCESS", "success"),
        ("AUTH_FAILURE", "auth_failure"),
        ("HIDDEN_SCORE", "hidden_score"),
        ("STORAGE_MISSING", "storage_missing"),
        ("MISSING_REPLAY_PROVISIONAL", "missing_replay_provisional"),
        ("MALFORMED_REQUEST_PROVISIONAL", "malformed_request_provisional"),
        ("BODY_STRATEGY_BLOCKED", "body_strategy_blocked"),
    ]


def test_replay_download_body_strategy_values_match_decision_fixture() -> None:
    """Body strategy enumがfixtureで許可されたdecision valueを表すことを検証する.

    Returns:
        None: enum語彙とfixtureのstrategy参照を検証して完了する.

    Raises:
        AssertionError: enumの固定語彙またはfixtureとの対応が壊れた場合.
    """
    members = [(member.name, member.value) for member in ReplayDownloadBodyStrategy]
    decision = cast(
        "BodyDecisionFixture",
        json.loads((FIXTURE_DIR / "body_assembly_decision.json").read_text()),
    )

    assert members == [
        ("BLOCKED", "blocked"),
        ("DIRECT_BLOB_BYTES", "direct_blob_bytes"),
        ("ASSEMBLE_DOWNLOAD_BODY", "assemble_download_body"),
    ]
    assert decision["decision"]["download_body_strategy"] in {
        strategy.value for strategy in ReplayDownloadBodyStrategy
    }


def test_replay_download_branch_contract_labels_match_response_fixture() -> None:
    """Branch label mappingがresponse contract fixtureの全labelを過不足なく表すことを検証する.

    Returns:
        None: fixture labelとbranch別contract labelを検証して完了する.

    Raises:
        AssertionError: labelの欠落, 追加, またはbranch別の固定対応が変わった場合.
    """
    contract = cast(
        "ResponseContractFixture",
        json.loads((FIXTURE_DIR / "response_contract.json").read_text()),
    )
    fixture_labels = {branch["branch"] for branch in contract["branches"]}

    mapped_labels = {
        label
        for labels in REPLAY_DOWNLOAD_CONTRACT_BRANCH_LABELS_BY_BRANCH.values()
        for label in labels
    }

    assert fixture_labels == mapped_labels
    assert REPLAY_DOWNLOAD_CONTRACT_BRANCH_LABELS_BY_BRANCH[ReplayDownloadBranch.SUCCESS] == (
        "success",
    )
    assert REPLAY_DOWNLOAD_CONTRACT_BRANCH_LABELS_BY_BRANCH[
        ReplayDownloadBranch.MISSING_REPLAY_PROVISIONAL
    ] == ("missing_replay",)
    assert REPLAY_DOWNLOAD_CONTRACT_BRANCH_LABELS_BY_BRANCH[
        ReplayDownloadBranch.BODY_STRATEGY_BLOCKED
    ] == ("body_strategy_blocked",)
    assert REPLAY_DOWNLOAD_CONTRACT_BRANCH_LABELS_BY_BRANCH[
        ReplayDownloadBranch.MALFORMED_REQUEST_PROVISIONAL
    ] == (
        "missing_score_id",
        "malformed_score_id",
        "missing_mode",
        "malformed_mode",
        "unknown_field",
    )


def test_replay_download_response_body_is_not_stored_blob_object() -> None:
    """同一payloadでもresponse bodyとstored blob objectを別型かつ非公開値として扱うことを検証する.

    Returns:
        None: byte数の一致, 型の分離, reprからのpayload秘匿を検証して完了する.

    Raises:
        AssertionError: value objectの同一視またはpayloadのrepr露出が発生した場合.
    """
    response_body = ReplayDownloadResponseBody(payload=b"synthetic-response-body")
    stored_blob = ReplayDownloadStoredBlobObject(payload=b"synthetic-response-body")

    assert response_body != stored_blob
    assert response_body.byte_size == stored_blob.byte_size
    assert type(response_body) is not type(stored_blob)
    assert "synthetic-response-body" not in repr(response_body)
    assert "synthetic-response-body" not in repr(stored_blob)


def test_replay_download_compatibility_module_has_no_runtime_boundary_imports() -> None:
    """Replay download domain moduleがruntime adapter境界へ依存しないことを検証する.

    Returns:
        None: ASTから収集したimport集合に禁止rootがないことを検証して完了する.

    Raises:
        AssertionError: transport, repository, serviceまたはinfrastructure依存を追加した場合.
    """
    forbidden_roots = (
        "athena_cli",
        "fastapi",
        "sqlalchemy",
        "starlette",
        "taskiq",
        "valkey",
        "osu_server.infrastructure",
        "osu_server.jobs",
        "osu_server.repositories",
        "osu_server.services",
        "osu_server.transports",
    )
    tree = ast.parse(DOMAIN_MODULE.read_text(encoding="utf-8"))
    imported_modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module)

    forbidden_imports = {
        module
        for module in imported_modules
        if any(module == root or module.startswith(f"{root}.") for root in forbidden_roots)
    }

    assert forbidden_imports == set()
