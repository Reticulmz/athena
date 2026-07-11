"""Replay download legacy endpoint integration smoke tests."""

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
    inputs: list[ReplayDownloadAccountingInput]

    def __init__(self) -> None:
        self.inputs = []

    async def publish(self, input_data: ReplayDownloadAccountingInput) -> None:
        self.inputs.append(input_data)
        raise RuntimeError("raw query token=secret /tmp/replay.osr")


@contextmanager
def _test_env() -> Generator[None]:
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
    with _test_env():
        app = _create_app(blob_root=tmp_path / "blobs")
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("http://osu.athena.localhost/web/osu-getreplay.php")

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.content == b""


def test_replay_download_route_returns_empty_404_for_missing_replay(tmp_path: Path) -> None:
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
    user_id = await _seed_authenticated_user(app, username=_TEST_USERNAME)
    return await _seed_visible_score(app, user_id=user_id)


async def _seed_authenticated_user(app: Starlette, *, username: str) -> int:
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
    user_id = await _seed_plain_user(app, username=username)
    await _assign_visible_role(app, user_id)
    return user_id


async def _seed_plain_user(app: Starlette, *, username: str) -> int:
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
    await seed_role(app, _VISIBLE_ROLE)
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        await uow.roles.assign_role(user_id, _VISIBLE_ROLE.id)
        await uow.commit()


async def _seed_visible_score(app: Starlette, *, user_id: int) -> int:
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
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        score = await uow.scores.get_by_id(score_id)
    if score is None:
        msg = f"score not found: {score_id}"
        raise AssertionError(msg)
    return score.replay_view_count


async def _latest_activity_at(app: Starlette, *, username: str) -> datetime:
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        user = await uow.users.get_by_safe_username(User.normalize_username(username))
    if user is None:
        msg = f"user not found: {username}"
        raise AssertionError(msg)
    return user.latest_activity_at


async def _seed_scenario_owner(app: Starlette, *, scenario: str) -> int:
    if scenario == "hidden_score":
        return await _seed_plain_user(app, username=_HIDDEN_OWNER_USERNAME)
    return await _seed_visible_user(app, username=_OWNER_USERNAME)


def _create_app(
    *,
    blob_root: Path,
    accounting: _FailingReplayDownloadAccounting | None = None,
) -> Starlette:
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
    return {
        "c": str(score_id),
        "h": FIXED_TEST_PASSWORD_MD5,
        "m": str(Ruleset.OSU.value),
        "u": username,
    }


def _failure_query(score_id: int, *, scenario: str) -> dict[str, str]:
    query = _query(score_id, username=_VIEWER_USERNAME)
    if scenario == "auth_failure":
        query["h"] = "not-the-password-md5"
    elif scenario == "malformed_request":
        _ = query.pop("c")
    return query


def _logs_do_not_expose_sensitive_values(logs: object) -> bool:
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
