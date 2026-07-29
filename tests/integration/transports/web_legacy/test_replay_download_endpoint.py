"""legacy replay download endpointの統合契約を検証する.

認証と可視性とblob storageのbranchごとのHTTP responseを確認する.
成功後accountingのbest-effort失敗がresponseと機密logに与える影響も検証する.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, cast, final

import pytest
import structlog.testing
from starlette.testclient import TestClient
from tests.support.app import resolve_dependency
from tests.support.credentials import FIXED_TEST_PASSWORD_MD5
from tests.support.persistence import seed_role, seed_user

from osu_server.app import create_app as create_runtime_app
from osu_server.composition.providers.test import (
    TestProviderSet,
    make_in_memory_runtime_provider_set,
    replace_value,
)
from osu_server.domain.beatmaps import BeatmapRankStatus
from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role
from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.identity.users import User
from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.replay import Replay
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
from osu_server.services.commands.scores.replay_download_accounting import (
    ReplayDownloadAccountingInput,
    ReplayDownloadAccountingPublisher,
)
from osu_server.services.commands.storage.blob_storage import BlobStorageService
from osu_server.services.queries.identity.password_service import PasswordService

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from dishka import Provider
    from starlette.applications import Starlette

_NOW = datetime(2026, 7, 5, tzinfo=UTC)
_TEST_USERNAME = "ReplayUser"
_VIEWER_USERNAME = "ReplayViewer"
_OWNER_USERNAME = "ReplayOwner"
_HIDDEN_OWNER_USERNAME = "ReplayHiddenOwner"
_VISIBLE_ROLE = Role(
    id=401,
    name="Replay Visible",
    permissions=Privileges.NORMAL | Privileges.UNRESTRICTED,
    position=0,
)


@final
class _FailingReplayDownloadAccounting:
    """accounting入力を記録して意図的に失敗するtest double.

    Attributes:
        inputs (list[ReplayDownloadAccountingInput]): publishへ渡されたaccounting入力の履歴.
    """

    inputs: list[ReplayDownloadAccountingInput]

    def __init__(self) -> None:
        """空のaccounting入力履歴を初期化する."""
        self.inputs = []

    async def publish(self, input_data: ReplayDownloadAccountingInput) -> None:
        """accounting入力を記録した後に失敗を送出する.

        Args:
            input_data (ReplayDownloadAccountingInput): replay download成功後にpublishされる入力.

        Returns:
            None: 正常終了せず例外を送出するため値を返さない.

        Raises:
            RuntimeError: endpointがaccounting失敗を抑制することを検証するため常に送出する.
        """
        self.inputs.append(input_data)
        raise RuntimeError("raw query token=secret /tmp/replay.osr")


@contextmanager
def _test_env() -> Generator[None]:
    """Endpoint test用の実行環境を一時的に設定する.

    Yields:
        None: ENVIRONMENTとDOMAINをtest用値にしたcontextを提供する.

    Notes:
        context終了時にENVIRONMENTとDOMAINは開始時の値へ復元する.
    """
    old_environment = os.environ.get("ENVIRONMENT")
    old_domain = os.environ.get("DOMAIN")
    os.environ["ENVIRONMENT"] = "test"
    os.environ["DOMAIN"] = "athena.localhost"
    _ = os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/athena")
    _ = os.environ.setdefault("VALKEY_URL", "redis://localhost:6379")
    try:
        yield
    finally:
        if old_environment is None:
            _ = os.environ.pop("ENVIRONMENT", None)
        else:
            os.environ["ENVIRONMENT"] = old_environment
        if old_domain is None:
            _ = os.environ.pop("DOMAIN", None)
        else:
            os.environ["DOMAIN"] = old_domain


def test_replay_download_route_returns_empty_401_for_auth_failure(tmp_path: Path) -> None:
    """credentialなしのrequestが空bodyのHTTP 401になることを検証する.

    test appをblob root付きで生成してquery parameterなしでendpointを呼ぶ.
    観測結果としてresponse statusはUNAUTHORIZEDでbodyは空になる.

    Args:
        tmp_path (Path): endpoint用blob storageを隔離する一時directory.

    Returns:
        None: authentication failureのlegacy response契約を検証して終了する.
    """
    with _test_env():
        app = _create_app(blob_root=tmp_path / "blobs")
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("http://osu.athena.localhost/web/osu-getreplay.php")

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.content == b""


def test_replay_download_route_returns_empty_404_for_missing_replay(tmp_path: Path) -> None:
    """存在しないreplayが空bodyのHTTP 404になることを検証する.

    認証済みかつ可視のscoreをseedして対応するreplayを保存せずendpointを呼ぶ.
    観測結果としてresponse statusはNOT_FOUNDでbodyは空になる.

    Args:
        tmp_path (Path): endpoint用blob storageを隔離する一時directory.

    Returns:
        None: missing replayのlegacy response契約を検証して終了する.
    """
    with _test_env():
        app = _create_app(blob_root=tmp_path / "blobs")
        with TestClient(app, raise_server_exceptions=False) as client:
            score_id = asyncio.run(_seed_authenticated_visible_score(app))

            response = client.get(
                "http://osu.athena.localhost/web/osu-getreplay.php",
                params=_query(score_id),
            )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.content == b""


def test_replay_download_route_returns_direct_blob_bytes_for_available_replay(
    tmp_path: Path,
) -> None:
    """可視replayがblob byte列とdownload headerを持つHTTP 200になることを検証する.

    viewerと可視ownerと保存済みreplayをseedしてviewer credentialでendpointを呼ぶ.
    観測結果としてresponseは保存済みbodyと固定headerを返し双方のactivity時刻は変わらない.

    Args:
        tmp_path (Path): endpoint用blob storageを隔離する一時directory.

    Returns:
        None: successful replay downloadのresponseとactivity不変性を検証して終了する.
    """
    with _test_env():
        app = _create_app(blob_root=tmp_path / "blobs")
        with TestClient(app, raise_server_exceptions=False) as client:
            viewer_id = asyncio.run(
                _seed_authenticated_user(app, username=_VIEWER_USERNAME),
            )
            owner_id = asyncio.run(_seed_visible_user(app, username=_OWNER_USERNAME))
            score_id = asyncio.run(_seed_visible_score(app, user_id=owner_id))
            asyncio.run(_attach_available_replay(app, score_id=score_id))
            before_viewer_activity = asyncio.run(
                _latest_activity_at(app, username=_VIEWER_USERNAME),
            )
            before_owner_activity = asyncio.run(
                _latest_activity_at(app, username=_OWNER_USERNAME),
            )

            response = client.get(
                "http://osu.athena.localhost/web/osu-getreplay.php",
                params=_query(score_id, username=_VIEWER_USERNAME),
            )
            viewer_activity = asyncio.run(
                _latest_activity_at(app, username=_VIEWER_USERNAME),
            )
            owner_activity = asyncio.run(_latest_activity_at(app, username=_OWNER_USERNAME))

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"synthetic-replay-download-body"
    assert response.headers["content-type"] == "zip"
    assert response.headers["content-disposition"] == 'attachment; filename="replay.osr"'
    assert before_viewer_activity == _NOW
    assert viewer_activity == before_viewer_activity
    assert owner_activity == before_owner_activity
    assert viewer_id != owner_id


def test_replay_download_route_preserves_success_response_when_accounting_fails(
    tmp_path: Path,
) -> None:
    """accounting失敗がsuccessful replay download responseを変えないことを検証する.

    publish時に例外を送出するaccounting test doubleと保存済みreplayを用意する.
    観測結果としてHTTP 200 responseは維持されdurable accountingは更新されずlogは機密値を含まない.

    Args:
        tmp_path (Path): endpoint用blob storageを隔離する一時directory.

    Returns:
        None: accounting failureのbest-effort隔離契約を検証して終了する.
    """
    accounting = _FailingReplayDownloadAccounting()
    with _test_env():
        app = _create_app(
            blob_root=tmp_path / "blobs",
            accounting=accounting,
        )
        with TestClient(app, raise_server_exceptions=False) as client:
            viewer_id = asyncio.run(
                _seed_authenticated_user(app, username=_VIEWER_USERNAME),
            )
            owner_id = asyncio.run(_seed_visible_user(app, username=_OWNER_USERNAME))
            score_id = asyncio.run(_seed_visible_score(app, user_id=owner_id))
            asyncio.run(_attach_available_replay(app, score_id=score_id))
            before_viewer_activity = asyncio.run(
                _latest_activity_at(app, username=_VIEWER_USERNAME),
            )

            with structlog.testing.capture_logs() as logs:
                response = client.get(
                    "http://osu.athena.localhost/web/osu-getreplay.php",
                    params=_query(score_id, username=_VIEWER_USERNAME),
                )

            replay_view_count = asyncio.run(_replay_view_count(app, score_id))
            viewer_activity = asyncio.run(
                _latest_activity_at(app, username=_VIEWER_USERNAME),
            )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"synthetic-replay-download-body"
    assert response.headers["content-type"] == "zip"
    assert response.headers["content-disposition"] == 'attachment; filename="replay.osr"'
    assert replay_view_count == 0
    assert viewer_activity == before_viewer_activity
    assert accounting.inputs == [
        ReplayDownloadAccountingInput(
            score_id=score_id,
            score_owner_user_id=owner_id,
            viewer_user_id=viewer_id,
            occurred_at=accounting.inputs[0].occurred_at,
        )
    ]
    accounting_logs = [
        log for log in logs if log.get("event") == "replay_download_accounting_failed"
    ]
    assert accounting_logs == [
        {
            "event": "replay_download_accounting_failed",
            "log_level": "warning",
            "operation": "accounting_command",
            "score_id": score_id,
            "viewer_user_id": viewer_id,
            "score_owner_user_id": owner_id,
            "outcome": "failed",
            "exception_type": "RuntimeError",
        }
    ]
    assert _logs_do_not_expose_sensitive_values(accounting_logs)


@pytest.mark.parametrize(
    ("scenario", "expected_status"),
    [
        ("auth_failure", HTTPStatus.UNAUTHORIZED),
        ("malformed_request", HTTPStatus.NOT_FOUND),
        ("hidden_score", HTTPStatus.NOT_FOUND),
        ("missing_replay", HTTPStatus.NOT_FOUND),
        ("storage_missing", HTTPStatus.NOT_FOUND),
    ],
)
def test_replay_download_route_failure_branches_do_not_update_accounting(
    tmp_path: Path,
    scenario: str,
    expected_status: HTTPStatus,
) -> None:
    """Failure branchがaccountingとactivity更新を実行しないことを検証する.

    認証失敗とmalformed requestと非公開scoreとreplay欠損とstorage欠損をparameterizeする.
    観測結果として各responseは空bodyかつdownload headerなしになる.
    view countとviewer activityは不変になる.

    Args:
        tmp_path (Path): endpoint用blob storageを隔離する一時directory.
        scenario (str): seedとqueryのfailure branchを決める識別子.
        expected_status (HTTPStatus): scenarioに対応して期待するHTTP status.

    Returns:
        None: failure branchのaccounting非更新契約を検証して終了する.
    """
    with _test_env():
        app = _create_app(blob_root=tmp_path / "blobs")
        with TestClient(app, raise_server_exceptions=False) as client:
            _ = asyncio.run(_seed_authenticated_user(app, username=_VIEWER_USERNAME))
            owner_id = asyncio.run(_seed_scenario_owner(app, scenario=scenario))
            score_id = asyncio.run(_seed_visible_score(app, user_id=owner_id))
            if scenario == "storage_missing":
                asyncio.run(_attach_storage_missing_replay(app, score_id=score_id))
            before_viewer_activity = asyncio.run(
                _latest_activity_at(app, username=_VIEWER_USERNAME),
            )

            response = client.get(
                "http://osu.athena.localhost/web/osu-getreplay.php",
                params=_failure_query(score_id, scenario=scenario),
            )
            replay_view_count = asyncio.run(_replay_view_count(app, score_id))
            viewer_activity = asyncio.run(
                _latest_activity_at(app, username=_VIEWER_USERNAME),
            )

    assert response.status_code == expected_status
    assert response.content == b""
    assert "content-type" not in response.headers
    assert "content-disposition" not in response.headers
    assert replay_view_count == 0
    assert viewer_activity == before_viewer_activity


async def _seed_authenticated_visible_score(app: Starlette) -> int:
    """認証済み可視利用者が所有するscoreをseedする.

    Args:
        app (Starlette): in-memory providerを持つlifespan開始済みapplication.

    Returns:
        int: 認証済みかつ可視の利用者が所有する作成済みscore ID.
    """
    user_id = await _seed_authenticated_user(app, username=_TEST_USERNAME)
    return await _seed_visible_score(app, user_id=user_id)


async def _seed_authenticated_user(app: Starlette, *, username: str) -> int:
    """可視roleとlegacy credential sessionを持つ利用者をseedする.

    Args:
        app (Starlette): in-memory providerを持つlifespan開始済みapplication.
        username (str): seedする利用者名とsession tokenの正規化元.

    Returns:
        int: 作成した認証済み利用者のID.
    """
    user_id = await _seed_visible_user(app, username=username)
    session_store = await resolve_dependency(app, SessionStore)
    await session_store.create(
        user_id,
        f"replay-download-session-{User.normalize_username(username)}",
        data=SessionData(
            user_id=user_id,
            username=username,
            privileges=int(Privileges.NORMAL | Privileges.UNRESTRICTED),
            country="JP",
            osu_version="b20260705",
            utc_offset=9,
            display_city=False,
            client_hashes="",
            pm_private=False,
            role_ids=(_VISIBLE_ROLE.id,),
        ),
    )
    return user_id


async def _seed_visible_user(app: Starlette, *, username: str) -> int:
    """可視roleを持つ利用者をseedする.

    Args:
        app (Starlette): in-memory providerを持つlifespan開始済みapplication.
        username (str): seedする利用者名.

    Returns:
        int: 可視roleを割り当てた利用者のID.
    """
    user_id = await _seed_plain_user(app, username=username)
    await _assign_visible_role(app, user_id)
    return user_id


async def _seed_plain_user(app: Starlette, *, username: str) -> int:
    """roleとsessionを持たない利用者をseedする.

    Args:
        app (Starlette): in-memory providerを持つlifespan開始済みapplication.
        username (str): seedする利用者名とemail addressの正規化元.

    Returns:
        int: 固定日時とpassword hashを持つ作成済み利用者のID.
    """
    password_service = await resolve_dependency(app, PasswordService)
    password_hash = await password_service.hash(FIXED_TEST_PASSWORD_MD5)
    safe_username = User.normalize_username(username)
    user = await seed_user(
        app,
        User(
            id=0,
            username=username,
            safe_username=safe_username,
            email=f"{safe_username}@example.com",
            password_hash=password_hash,
            country="JP",
            created_at=_NOW,
            updated_at=_NOW,
        ),
    )
    return user.id


async def _assign_visible_role(app: Starlette, user_id: int) -> None:
    """利用者へreplay閲覧可能なroleを割り当てる.

    Args:
        app (Starlette): role repositoryを解決するlifespan開始済みapplication.
        user_id (int): _VISIBLE_ROLEを割り当てる利用者ID.

    Returns:
        None: role assignmentをcommitして値を返さない.
    """
    await seed_role(app, _VISIBLE_ROLE)
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        await uow.roles.assign_role(user_id, _VISIBLE_ROLE.id)
        await uow.commit()


async def _seed_visible_score(app: Starlette, *, user_id: int) -> int:
    """可視利用者に紐付くranked scoreをseedする.

    Args:
        app (Starlette): score repositoryを解決するlifespan開始済みapplication.
        user_id (int): 作成するscoreの所有者ID.

    Returns:
        int: commit済みscoreの非null ID.

    Raises:
        AssertionError: repositoryが作成済みscoreへIDを割り当てない場合.
    """
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        score = await uow.scores.create(
            Score(
                id=None,
                user_id=user_id,
                beatmap_id=75,
                beatmap_checksum="replay-download-checksum",
                online_checksum="replay-download-online-checksum",
                ruleset=Ruleset.OSU,
                playstyle=Playstyle.VANILLA,
                mods=ModCombination.none(),
                n300=300,
                n100=2,
                n50=1,
                geki=5,
                katu=4,
                miss=3,
                score=987_654,
                max_combo=1_234,
                accuracy=98.76,
                grade=Grade.S,
                passed=True,
                perfect=True,
                client_version="b20260705",
                submitted_at=_NOW,
                beatmap_status_at_submission=BeatmapRankStatus.RANKED,
                leaderboard_eligible_at_submission=True,
            )
        )
        await uow.commit()
    assert score.id is not None
    return score.id


async def _attach_available_replay(app: Starlette, *, score_id: int) -> None:
    """scoreへstorage上に存在するreplayを関連付ける.

    Args:
        app (Starlette): blob storageとreplay repositoryを解決するapplication.
        score_id (int): replayを関連付ける既存score ID.

    Returns:
        None: synthetic replay bodyを保存してmetadataをcommitし値を返さない.
    """
    blob_storage = await resolve_dependency(app, BlobStorageService)
    stored = await blob_storage.put_bytes(
        b"synthetic-replay-download-body",
        content_type="application/octet-stream",
    )
    blob = stored.blob
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        _ = await uow.replays.create(
            Replay(
                id=None,
                score_id=score_id,
                blob_id=blob.id,
                checksum_sha256=blob.sha256,
                byte_size=blob.byte_size,
            )
        )
        await uow.commit()


async def _attach_storage_missing_replay(app: Starlette, *, score_id: int) -> None:
    """storageに存在しないblob IDを持つreplay metadataを関連付ける.

    Args:
        app (Starlette): replay repositoryを解決するlifespan開始済みapplication.
        score_id (int): 欠損storageを表すreplayを関連付ける既存score ID.

    Returns:
        None: storage未保存blobを参照するreplay metadataをcommitして値を返さない.
    """
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        _ = await uow.replays.create(
            Replay(
                id=None,
                score_id=score_id,
                blob_id=9_999_999,
                checksum_sha256="0" * 64,
                byte_size=123,
            )
        )
        await uow.commit()


async def _replay_view_count(app: Starlette, score_id: int) -> int:
    """scoreに記録されたreplay view countを取得する.

    Args:
        app (Starlette): score repositoryを解決するlifespan開始済みapplication.
        score_id (int): countを取得する既存score ID.

    Returns:
        int: scoreに保存されたreplay_view_count.

    Raises:
        AssertionError: 指定scoreがrepositoryに存在しない場合.
    """
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        score = await uow.scores.get_by_id(score_id)
    if score is None:
        msg = f"score not found: {score_id}"
        raise AssertionError(msg)
    return score.replay_view_count


async def _latest_activity_at(app: Starlette, *, username: str) -> datetime:
    """利用者に保存されたlatest activity時刻を取得する.

    Args:
        app (Starlette): user repositoryを解決するlifespan開始済みapplication.
        username (str): 正規化して検索する利用者名.

    Returns:
        datetime: 指定利用者に保存されたlatest activity時刻.

    Raises:
        AssertionError: 指定利用者がrepositoryに存在しない場合.
    """
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        user = await uow.users.get_by_safe_username(User.normalize_username(username))
    if user is None:
        msg = f"user not found: {username}"
        raise AssertionError(msg)
    return user.latest_activity_at


async def _seed_scenario_owner(app: Starlette, *, scenario: str) -> int:
    """Failure scenarioに対応するscore ownerをseedする.

    Args:
        app (Starlette): user repositoryを解決するlifespan開始済みapplication.
        scenario (str): hidden_scoreか通常の可視ownerかを決める識別子.

    Returns:
        int: scenarioに適したscore ownerの利用者ID.
    """
    if scenario == "hidden_score":
        return await _seed_plain_user(app, username=_HIDDEN_OWNER_USERNAME)
    return await _seed_visible_user(app, username=_OWNER_USERNAME)


def _create_app(
    *,
    blob_root: Path,
    accounting: _FailingReplayDownloadAccounting | None = None,
) -> Starlette:
    """Replay download endpointを持つin-memory applicationを生成する.

    Args:
        blob_root (Path): replay blobを保存する一時directory.
        accounting (_FailingReplayDownloadAccounting | None): 成功時に置換する失敗用publisher.

    Returns:
        Starlette: 指定したblob rootと任意のaccounting overrideを持つapplication.
    """
    overrides: list[Provider] = [
        make_in_memory_runtime_provider_set(blob_root=blob_root),
    ]
    if accounting is not None:
        overrides.append(
            TestProviderSet(
                replace_value(
                    ReplayDownloadAccountingPublisher,
                    cast("ReplayDownloadAccountingPublisher", cast("object", accounting)),
                )
            )
        )
    return create_runtime_app(provider_overrides=tuple(overrides))


def _query(score_id: int, *, username: str = _TEST_USERNAME) -> dict[str, str]:
    """有効なlegacy replay download query parameterを構築する.

    Args:
        score_id (int): c parameterへ設定するscore ID.
        username (str): u parameterへ設定する認証利用者名.

    Returns:
        dict[str, str]: cとhとmとuを持つendpoint request query.
    """
    return {
        "c": str(score_id),
        "h": FIXED_TEST_PASSWORD_MD5,
        "m": str(Ruleset.OSU.value),
        "u": username,
    }


def _failure_query(score_id: int, *, scenario: str) -> dict[str, str]:
    """Failure scenario用のlegacy replay download query parameterを構築する.

    Args:
        score_id (int): c parameterへ設定するscore ID.
        scenario (str): credentialまたはscore IDを不正化するscenario識別子.

    Returns:
        dict[str, str]: scenarioに対応するfailure branchを起こすrequest query.
    """
    query = _query(score_id, username=_VIEWER_USERNAME)
    if scenario == "auth_failure":
        query["h"] = "not-the-password-md5"
    elif scenario == "malformed_request":
        _ = query.pop("c")
    return query


def _logs_do_not_expose_sensitive_values(logs: object) -> bool:
    """Accounting failure logが機密候補値を含まないことを判定する.

    Args:
        logs (object): structlog capture結果としてrender可能なlog collection.

    Returns:
        bool: raw queryとtokenとpathとcredentialとtest利用者名の全てが不在ならTrue.
    """
    rendered = repr(logs)
    forbidden_fragments = (
        "raw query",
        "token=",
        "/tmp/",
        ".osr",
        "secret",
        FIXED_TEST_PASSWORD_MD5,
        _VIEWER_USERNAME,
        _OWNER_USERNAME,
    )
    return all(fragment not in rendered for fragment in forbidden_fragments)
