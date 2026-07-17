"""Diagnostics integration tests for the legacy getscores endpoint.

Asserts that the handler emits structlog events for auth failures, parse
warnings, invalid identity, lookup conflicts, unavailable / update-available
outcomes, and anti-cheat signal — without leaking ``ha`` (password md5),
raw ``us`` values, or internal provenance fields in stable response bodies.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
import structlog.testing
from starlette.testclient import TestClient

from athena_cli.stable_verification.getscores_evidence import (
    GetscoresEvidenceStatus,
    GetscoresWireShapeId,
    load_getscores_completion_evidence,
)
from athena_cli.stable_verification.parsers import (
    GetscoresResponseKind,
    parse_getscores_response,
)
from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileAttachment,
    BeatmapFileSource,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapSourceVerification,
)
from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role
from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.identity.users import User
from osu_server.domain.scores.leaderboards import ScoreRankKey
from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score
from osu_server.repositories.interfaces.commands.beatmap_leaderboards import (
    BeatmapLeaderboardUserBestScope,
    UpsertBeatmapLeaderboardUserBest,
)
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
from osu_server.services.queries.identity.password_service import PasswordService
from tests.support.app import create_in_memory_app as create_app
from tests.support.app import resolve_dependency
from tests.support.getscores_contract import build_getscores_contract_query
from tests.support.persistence import (
    attach_beatmap_file,
    seed_beatmapset,
    seed_role,
    seed_user,
)

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping

    import httpx2
    from starlette.applications import Starlette
    from structlog.typing import EventDict

    from athena_cli.stable_verification.getscores_evidence import (
        GetscoresBranchCase,
        GetscoresWireShapeFixture,
    )


_TEST_USERNAME = "StableUser"
_TEST_PASSWORD_PLAIN = "ExamplePass1234"  # gitleaks:allow
_TEST_PASSWORD_MD5 = hashlib.md5(_TEST_PASSWORD_PLAIN.encode()).hexdigest()
_KNOWN_CHECKSUM = "0123456789abcdef0123456789abcdef"
_KNOWN_FILENAME = "Camellia - Exit This Earth's Atomosphere (Realazy) [Insane].osu"
_NOW = datetime(2026, 6, 7, tzinfo=UTC)
_NEXT_REFRESH = _NOW + timedelta(days=30)
_LEADERBOARD_VISIBLE_ROLE = Role(
    id=100,
    name="Leaderboard Visible",
    permissions=Privileges.NORMAL | Privileges.UNRESTRICTED,
    position=0,
)
_FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
_MANIFEST_ROOT = _FIXTURE_ROOT / "stable_compatibility" / "getscores"
_BODY_ROOT = _FIXTURE_ROOT / "web_legacy" / "getscores" / "completion"
_GETSCORES_EVIDENCE = load_getscores_completion_evidence(_MANIFEST_ROOT, _BODY_ROOT)
_GETSCORES_CASES = {case.case_id: case for case in _GETSCORES_EVIDENCE.branch_cases}
_GETSCORES_SHAPES = {shape.shape_id: shape for shape in _GETSCORES_EVIDENCE.response_shapes}
_MALFORMED_DIAGNOSTIC_CASE_IDS = (
    "malformed-mode",
    "malformed-mods",
    "malformed-leaderboard-type",
    "malformed-leaderboard-version",
    "malformed-song-select-flag",
    "malformed-anti-cheat-signal",
    "malformed-beatmapset-hint",
    "malformed-multiple-optional-fields",
)
_INVARIANCE_CONTROL_CASE_IDS = (
    "valid-anti-cheat-signal-invariant",
    "request-version-variant-invariant",
)
_INTERNAL_PROVENANCE_TOKENS = (
    "_source",
    "_verified",
    "_policy",
    "_fetch_state",
    "local_status_override",
    "official_status_source",
    "official_status_verified",
    "metadata_fetch_state",
    "file_state",
)


@contextmanager
def _test_env() -> Generator[None]:
    old_env = os.environ.get("ENVIRONMENT")
    old_domain = os.environ.get("DOMAIN")
    os.environ["ENVIRONMENT"] = "test"
    os.environ["DOMAIN"] = "athena.localhost"
    _ = os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/athena")
    _ = os.environ.setdefault("VALKEY_URL", "redis://localhost:6379")
    try:
        yield
    finally:
        if old_env is None:
            _ = os.environ.pop("ENVIRONMENT", None)
        else:
            os.environ["ENVIRONMENT"] = old_env
        if old_domain is None:
            _ = os.environ.pop("DOMAIN", None)
        else:
            os.environ["DOMAIN"] = old_domain


async def _seed_user_with_session(app: Starlette) -> int:
    password_service = await resolve_dependency(app, PasswordService)
    session_store = await resolve_dependency(app, SessionStore)

    password_hash = await password_service.hash(_TEST_PASSWORD_MD5)
    user = await seed_user(
        app,
        User(
            id=0,
            username=_TEST_USERNAME,
            safe_username=User.normalize_username(_TEST_USERNAME),
            email="player@example.com",
            password_hash=password_hash,
            country="JP",
            created_at=_NOW,
            updated_at=_NOW,
        ),
    )
    await session_store.create(
        user.id,
        token="test-session-token",
        data=SessionData(
            user_id=user.id,
            username=user.username,
            privileges=0,
            country="JP",
            osu_version="b20231130",
            utc_offset=9,
            display_city=False,
            client_hashes="",
            pm_private=False,
        ),
    )
    return user.id


async def _seed_known_beatmap(
    app: Starlette,
    *,
    next_refresh_at: datetime = _NEXT_REFRESH,
) -> None:
    beatmap = Beatmap(
        id=75,
        beatmapset_id=1,
        checksum_md5=_KNOWN_CHECKSUM,
        mode=BeatmapMode.OSU,
        version="Insane",
        total_length=240,
        hit_length=220,
        max_combo=1234,
        bpm=180.0,
        cs=4.0,
        od=8.5,
        ar=9.4,
        hp=6.5,
        difficulty_rating=5.67,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        local_status_override=None,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=BeatmapFileState.MISSING,
        file_attachment=None,
        last_fetched_at=_NOW,
        next_refresh_at=next_refresh_at,
    )
    beatmapset = BeatmapSet(
        id=1,
        artist="Camellia",
        title="Exit This Earth's Atomosphere",
        creator="Realazy",
        artist_unicode=None,
        title_unicode=None,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        beatmaps=(beatmap,),
        last_fetched_at=_NOW,
        next_refresh_at=next_refresh_at,
    )
    await seed_beatmapset(app, beatmapset)


async def _assign_leaderboard_visible_role(
    app: Starlette,
    user_ids: tuple[int, ...],
) -> None:
    """Getscores rowへ表示するsynthetic userにroleを付与する。

    Args:
        app (Starlette): Unit of Work dependencyを解決するtest application。
        user_ids (tuple[int, ...]): Leaderboard表示を許可するUser ID群。

    Returns:
        None: Role付与とcommitが完了したことを示す。
    """
    await seed_role(app, _LEADERBOARD_VISIBLE_ROLE)
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        for user_id in user_ids:
            await uow.roles.assign_role(user_id, _LEADERBOARD_VISIBLE_ROLE.id)
        await uow.commit()


async def _seed_visible_user(app: Starlette, *, username: str) -> int:
    """Leaderboard row用のsynthetic userを作成する。

    Args:
        app (Starlette): Unit of Work dependencyを解決するtest application。
        username (str): Response rowに使うsynthetic username。

    Returns:
        int: 永続化したUser ID。
    """
    user = await seed_user(
        app,
        User(
            id=0,
            username=username,
            safe_username=User.normalize_username(username),
            email=f"{User.normalize_username(username)}@example.com",
            password_hash="!synthetic-password-hash",
            country="JP",
            created_at=_NOW,
            updated_at=_NOW,
        ),
    )
    return user.id


async def _seed_leaderboard_score(
    app: Starlette,
    *,
    user_id: int,
    score_value: int,
    submitted_offset_seconds: int,
) -> None:
    """Getscores diagnosticsのPBとrow用scoreを作成する。

    Args:
        app (Starlette): Unit of Work dependencyを解決するtest application。
        user_id (int): Scoreを所有するUser ID。
        score_value (int): Leaderboard順位に使うscore値。
        submitted_offset_seconds (int): 基準日時へ加算する秒数。

    Returns:
        None: Scoreとleaderboard projectionがcommit済みであることを示す。

    Raises:
        AssertionError: Repositoryが永続化後のScore IDを返さない場合。
    """
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        score = await uow.scores.create(
            Score(
                id=None,
                user_id=user_id,
                beatmap_id=75,
                beatmap_checksum=_KNOWN_CHECKSUM,
                online_checksum=f"diagnostic-score-{user_id}-{score_value}",
                ruleset=Ruleset.OSU,
                playstyle=Playstyle.VANILLA,
                mods=ModCombination.none(),
                n300=300,
                n100=2,
                n50=1,
                geki=5,
                katu=4,
                miss=3,
                score=score_value,
                max_combo=1_234,
                accuracy=98.76,
                grade=Grade.S,
                passed=True,
                perfect=True,
                client_version="b20260717",
                submitted_at=_NOW + timedelta(seconds=submitted_offset_seconds),
                beatmap_status_at_submission=BeatmapRankStatus.RANKED,
                leaderboard_eligible_at_submission=True,
            )
        )
        assert score.id is not None
        _ = await uow.beatmap_leaderboards.upsert_if_better(
            UpsertBeatmapLeaderboardUserBest(
                scope=BeatmapLeaderboardUserBestScope(
                    beatmap_id=score.beatmap_id,
                    beatmap_checksum=score.beatmap_checksum,
                    ruleset=score.ruleset,
                    playstyle=score.playstyle,
                    user_id=score.user_id,
                    mods=score.mods,
                ),
                score_id=score.id,
                rank_key=ScoreRankKey(
                    score=score.score,
                    submitted_at=score.submitted_at,
                    score_id=score.id,
                ),
            )
        )
        await uow.commit()


async def _seed_diagnostic_leaderboard(app: Starlette) -> None:
    """Fallback shapeを識別できる2-row scenarioを作成する。

    Args:
        app (Starlette): Unit of Work dependencyを解決するtest application。

    Returns:
        None: Viewer PBと2件のleaderboard rowがquery可能なことを示す。
    """
    viewer_id = await _seed_user_with_session(app)
    rival_id = await _seed_visible_user(app, username="DiagnosticRival")
    await _seed_known_beatmap(
        app,
        next_refresh_at=_NOW + timedelta(days=3_650),
    )
    _ = await attach_beatmap_file(
        app,
        BeatmapFileAttachment(
            beatmap_id=75,
            blob_id=1,
            checksum_md5=_KNOWN_CHECKSUM,
            source=BeatmapFileSource.LEGACY_OFFICIAL,
            original_filename=_KNOWN_FILENAME,
            fetched_at=_NOW,
            verified_at=_NOW,
        ),
    )
    await _assign_leaderboard_visible_role(app, (viewer_id, rival_id))
    await _seed_leaderboard_score(
        app,
        user_id=viewer_id,
        score_value=900_000,
        submitted_offset_seconds=2,
    )
    await _seed_leaderboard_score(
        app,
        user_id=rival_id,
        score_value=1_000_000,
        submitted_offset_seconds=1,
    )


def _query(
    *,
    checksum: str | None = _KNOWN_CHECKSUM,
    username: str | None = _TEST_USERNAME,
    password_md5: str | None = _TEST_PASSWORD_MD5,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    params: dict[str, str] = {}
    if checksum is not None:
        params["c"] = checksum
    if username is not None:
        params["us"] = username
    if password_md5 is not None:
        params["ha"] = password_md5
    _ = params.setdefault("s", "0")
    _ = params.setdefault("vv", "4")
    _ = params.setdefault("v", "1")
    _ = params.setdefault("m", "0")
    _ = params.setdefault("mods", "0")
    if extra is not None:
        params.update(extra)
    return params


def _events_with(logs: list[EventDict], event_name: str) -> list[EventDict]:
    return [
        entry for entry in logs if cast("Mapping[str, object]", entry).get("event") == event_name
    ]


def _no_credentials_leaked(entry: EventDict) -> bool:
    """Operator diagnosticがcredentialとrequest usernameを含まないか返す。

    Args:
        entry (EventDict): Structlogが生成した1件のevent。

    Returns:
        bool: Raw password MD5とrequest usernameがどちらもなければTrue。
    """
    diagnostic_text = repr(cast("Mapping[str, object]", entry))
    return _TEST_PASSWORD_MD5 not in diagnostic_text and _TEST_USERNAME not in diagnostic_text


def _warning_values(logs: list[EventDict]) -> tuple[str, ...]:
    events = _events_with(logs, "getscores_parse_warning")
    if not events:
        return ()
    assert len(events) == 1
    warnings = cast("Mapping[str, object]", events[0]).get("warnings")
    assert isinstance(warnings, list)
    values = cast("list[object]", warnings)
    assert all(isinstance(value, str) for value in values)
    return tuple(value for value in values if isinstance(value, str))


def _terminal_lf_count(body: bytes) -> int:
    return len(body) - len(body.rstrip(b"\n"))


def _assert_diagnostic_shape(
    response: httpx2.Response,
    case: GetscoresBranchCase,
    shape: GetscoresWireShapeFixture,
) -> None:
    assert shape.shape_id is case.expected_shape_id
    assert shape.shape_id in {
        GetscoresWireShapeId.HEADER_ONLY,
        GetscoresWireShapeId.HEADER_WITH_ROWS,
    }
    assert response.status_code == shape.http_status
    assert response.headers["content-length"] == str(len(response.content))
    assert response.headers["content-type"] == shape.required_headers["content-type"]
    for header_name in shape.absent_headers:
        assert header_name not in response.headers
    assert _terminal_lf_count(response.content) == shape.terminal_lf_count

    parsed = parse_getscores_response(response.content)
    assert parsed.error is None
    assert parsed.response is not None
    assert parsed.response.kind is GetscoresResponseKind.HEADER
    assert parsed.response.header is not None
    header = parsed.response.header
    assert (header.personal_best_row is not None) is shape.personal_best_present
    assert header.score_count == shape.leaderboard_row_count
    assert len(header.score_rows) == shape.leaderboard_row_count


def _assert_diagnostic_redaction(
    logs: list[EventDict],
    query: Mapping[str, str],
) -> None:
    diagnostic_text = repr(cast("list[object]", logs))
    raw_malformed_values = tuple(value for value in query.values() if value.startswith("invalid-"))
    forbidden_tokens = (
        _TEST_PASSWORD_MD5,
        _TEST_USERNAME,
        "DiagnosticRival",
        *raw_malformed_values,
        *_INTERNAL_PROVENANCE_TOKENS,
    )
    for token in forbidden_tokens:
        assert token not in diagnostic_text


def _assert_case_evidence_redaction(
    case: GetscoresBranchCase,
    query: Mapping[str, str],
) -> None:
    evidence_text = repr(case)
    raw_malformed_values = tuple(value for value in query.values() if value.startswith("invalid-"))
    forbidden_tokens = (
        _TEST_PASSWORD_MD5,
        _TEST_USERNAME,
        *raw_malformed_values,
        *_INTERNAL_PROVENANCE_TOKENS,
    )
    for token in forbidden_tokens:
        assert token not in evidence_text


# ---------------------------------------------------------------------------
# Auth failure observability (Req 12.2, 12.3, 2.4)
# ---------------------------------------------------------------------------


class TestAuthFailureDiagnostics:
    """Auth failures emit getscores_auth_failed without credential leakage."""

    def test_missing_credentials_emits_auth_failed_event(self) -> None:
        with _test_env():
            app = create_app()
            with (
                TestClient(
                    app,
                    base_url="http://osu.athena.localhost",
                    raise_server_exceptions=False,
                ) as client,
                structlog.testing.capture_logs() as logs,
            ):
                response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(username=None, password_md5=None),
                )
                assert response.status_code == HTTPStatus.UNAUTHORIZED

        events = _events_with(logs, "getscores_auth_failed")
        assert len(events) == 1
        entry = events[0]
        assert entry.get("failure_reason") == "invalid_credentials"
        assert "ha" not in entry
        assert _no_credentials_leaked(entry)

    def test_invalid_credentials_emits_auth_failed_event(self) -> None:
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:
                _ = asyncio.run(_seed_user_with_session(app))
                with structlog.testing.capture_logs() as logs:
                    response = client.get(
                        "/web/osu-osz2-getscores.php",
                        params=_query(password_md5="0" * 32),
                    )
                    assert response.status_code == HTTPStatus.UNAUTHORIZED

        events = _events_with(logs, "getscores_auth_failed")
        assert len(events) >= 1
        for entry in events:
            assert entry.get("failure_reason") == "invalid_credentials"
            assert "ha" not in entry
            assert _no_credentials_leaked(entry)

    def test_no_session_emits_auth_failed_event(self) -> None:
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:

                async def _seed_user_only() -> None:
                    password_service = await resolve_dependency(app, PasswordService)
                    password_hash = await password_service.hash(_TEST_PASSWORD_MD5)
                    _ = await seed_user(
                        app,
                        User(
                            id=0,
                            username=_TEST_USERNAME,
                            safe_username=User.normalize_username(_TEST_USERNAME),
                            email="player@example.com",
                            password_hash=password_hash,
                            country="JP",
                            created_at=_NOW,
                            updated_at=_NOW,
                        ),
                    )

                asyncio.run(_seed_user_only())
                with structlog.testing.capture_logs() as logs:
                    response = client.get(
                        "/web/osu-osz2-getscores.php",
                        params=_query(),
                    )
                    assert response.status_code == HTTPStatus.UNAUTHORIZED

        events = _events_with(logs, "getscores_auth_failed")
        assert len(events) >= 1
        last = events[-1]
        assert last.get("failure_reason") == "no_session"
        assert "ha" not in last
        assert _no_credentials_leaked(last)


# ---------------------------------------------------------------------------
# Identity / parse / outcome diagnostics (Req 12.3, 12.4, 12.5, 4.5)
# ---------------------------------------------------------------------------


class TestRequestDiagnostics:
    """Authorized requests emit appropriate diagnostic events."""

    def test_missing_identity_emits_identity_invalid(self) -> None:
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:
                _ = asyncio.run(_seed_user_with_session(app))
                with structlog.testing.capture_logs() as logs:
                    response = client.get(
                        "/web/osu-osz2-getscores.php",
                        params=_query(checksum=None),
                    )
                    assert response.status_code == HTTPStatus.OK
                    assert response.content == b"-1|false"

        events = _events_with(logs, "getscores_identity_invalid")
        assert len(events) == 1
        entry = events[0]
        assert entry.get("parse_error") == "missing_identity"
        assert "ha" not in entry
        assert _no_credentials_leaked(entry)
        assert _events_with(logs, "beatmap_file_warmup") == []

    def test_malformed_identity_does_not_request_warmup_or_log_raw_query(self) -> None:
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:
                _ = asyncio.run(_seed_user_with_session(app))
                with structlog.testing.capture_logs() as logs:
                    response = client.get(
                        "/web/osu-osz2-getscores.php",
                        params=_query(checksum="not-a-valid-md5"),
                    )
                    assert response.status_code == HTTPStatus.OK
                    assert response.content == b"-1|false"

        events = _events_with(logs, "getscores_identity_invalid")
        assert len(events) == 1
        entry = events[0]
        assert entry.get("parse_error") == "invalid_checksum"
        assert "not-a-valid-md5" not in entry.values()
        assert "ha" not in entry
        assert _no_credentials_leaked(entry)
        assert _events_with(logs, "beatmap_file_warmup") == []

    def test_unknown_checksum_emits_unavailable(self) -> None:
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:
                _ = asyncio.run(_seed_user_with_session(app))
                with structlog.testing.capture_logs() as logs:
                    response = client.get(
                        "/web/osu-osz2-getscores.php",
                        params=_query(checksum="ff" * 16),
                    )
                    assert response.status_code == HTTPStatus.OK
                    assert response.content == b"-1|false"

        events = _events_with(logs, "getscores_unavailable")
        assert len(events) == 1
        entry = events[0]
        assert entry.get("resolve_reason") in {
            "not_found",
            "not_submitted",
            "pending_fetch",
            "failed_metadata",
        }
        assert "ha" not in entry
        assert _no_credentials_leaked(entry)

        warmup_events = _events_with(logs, "beatmap_file_warmup")
        assert len(warmup_events) == 1
        warmup_entry = warmup_events[0]
        assert warmup_entry.get("entrance") == "stable_getscores"
        assert warmup_entry.get("outcome") == "metadata_pending"
        assert warmup_entry.get("beatmap_id") is None
        assert warmup_entry.get("checksum_md5") == "ff" * 16
        assert "ha" not in warmup_entry
        assert _no_credentials_leaked(warmup_entry)

    def test_update_available_emits_warmup_event_without_changing_short_body(self) -> None:
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:

                async def _setup() -> None:
                    _ = await _seed_user_with_session(app)
                    await _seed_known_beatmap(app)
                    _ = await attach_beatmap_file(
                        app,
                        BeatmapFileAttachment(
                            beatmap_id=75,
                            blob_id=1,
                            checksum_md5=_KNOWN_CHECKSUM,
                            source=BeatmapFileSource.LEGACY_OFFICIAL,
                            original_filename=_KNOWN_FILENAME,
                            fetched_at=_NOW,
                            verified_at=_NOW,
                        ),
                    )

                asyncio.run(_setup())
                with structlog.testing.capture_logs() as logs:
                    # Same set+filename, different checksum -> UPDATE_AVAILABLE
                    response = client.get(
                        "/web/osu-osz2-getscores.php",
                        params=_query(
                            checksum="aa" * 16,
                            extra={
                                "f": _KNOWN_FILENAME,
                                "i": "1",
                            },
                        ),
                    )
                    assert response.status_code == HTTPStatus.OK
                    assert response.content == b"1|false"

        events = _events_with(logs, "getscores_update_available")
        assert len(events) == 1
        assert "ha" not in events[0]
        assert _no_credentials_leaked(events[0])
        warmup_events = _events_with(logs, "beatmap_file_warmup")
        assert len(warmup_events) == 1
        warmup_entry = warmup_events[0]
        assert warmup_entry.get("entrance") == "stable_getscores"
        assert warmup_entry.get("outcome") == "already_available"
        assert warmup_entry.get("beatmap_id") == 75
        assert warmup_entry.get("checksum_md5") is None
        assert "ha" not in warmup_entry
        assert _no_credentials_leaked(warmup_entry)

    @pytest.mark.parametrize("case_id", _MALFORMED_DIAGNOSTIC_CASE_IDS)
    def test_malformed_catalog_case_matches_warning_shape_and_redaction(
        self,
        case_id: str,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Malformed caseをwarning, fallback shape, redactionへ照合する。

        Args:
            case_id (str): Canonical malformed branch case ID。
            caplog (pytest.LogCaptureFixture): Raw request URLを出すhttpx INFO logの制御。

        Returns:
            None: Provisional state, shape, warning集合, redactionが一致したことを示す。

        Raises:
            KeyError: Canonical caseまたはshapeがtyped evidence bundleにない場合。
            AssertionError: Runtimeまたはevidenceがcatalog contractと異なる場合。
        """
        caplog.set_level(logging.WARNING, logger="httpx")
        case = _GETSCORES_CASES[case_id]
        shape = _GETSCORES_SHAPES[case.expected_shape_id]
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:
                asyncio.run(_seed_diagnostic_leaderboard(app))
                query = build_getscores_contract_query(case, _query())
                with structlog.testing.capture_logs() as logs:
                    response = client.get(
                        "/web/osu-osz2-getscores.php",
                        params=query,
                    )

        assert case.evidence_status is GetscoresEvidenceStatus.PROVISIONAL_ATHENA_BEHAVIOR
        _assert_case_evidence_redaction(case, query)
        _assert_diagnostic_shape(response, case, shape)
        _assert_diagnostic_redaction(logs, query)
        actual_warnings = _warning_values(logs)
        expected_warnings = tuple(warning.value for warning in case.expected_warning_categories)
        assert len(actual_warnings) == len(expected_warnings)
        assert frozenset(actual_warnings) == frozenset(expected_warnings)
        assert _events_with(logs, "getscores_anti_cheat_signal") == []

    @pytest.mark.parametrize("case_id", _INVARIANCE_CONTROL_CASE_IDS)
    def test_diagnostic_control_case_preserves_shape_without_warning(
        self,
        case_id: str,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Valid diagnostic variantがresponse selectionを変更しないことを確認する。

        Args:
            case_id (str): Canonical invariance control case ID。
            caplog (pytest.LogCaptureFixture): Raw request URLを出すhttpx INFO logの制御。

        Returns:
            None: Athena deterministic state, row shape, empty warningが一致したことを示す。

        Raises:
            KeyError: Canonical caseまたはshapeがtyped evidence bundleにない場合。
            AssertionError: Runtimeまたはevidenceがcatalog contractと異なる場合。
        """
        caplog.set_level(logging.WARNING, logger="httpx")
        case = _GETSCORES_CASES[case_id]
        shape = _GETSCORES_SHAPES[case.expected_shape_id]
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:
                asyncio.run(_seed_diagnostic_leaderboard(app))
                query = build_getscores_contract_query(case, _query())
                with structlog.testing.capture_logs() as logs:
                    response = client.get(
                        "/web/osu-osz2-getscores.php",
                        params=query,
                    )

        assert case.evidence_status is GetscoresEvidenceStatus.ATHENA_DETERMINISTIC
        assert case.expected_warning_categories == ()
        _assert_case_evidence_redaction(case, query)
        _assert_diagnostic_shape(response, case, shape)
        _assert_diagnostic_redaction(logs, query)
        assert _warning_values(logs) == ()
        anti_cheat_events = _events_with(logs, "getscores_anti_cheat_signal")
        if case_id == "valid-anti-cheat-signal-invariant":
            assert len(anti_cheat_events) == 1
        else:
            assert anti_cheat_events == []

    def test_known_header_emits_warmup_event_without_changing_body(self) -> None:
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:

                async def _setup() -> None:
                    _ = await _seed_user_with_session(app)
                    await _seed_known_beatmap(app)

                asyncio.run(_setup())
                with structlog.testing.capture_logs() as logs:
                    response = client.get(
                        "/web/osu-osz2-getscores.php",
                        params=_query(),
                    )
                    assert response.status_code == HTTPStatus.OK
                    assert response.content.split(b"\n")[0] == b"2|false|75|1|0||"

        warmup_events = _events_with(logs, "beatmap_file_warmup")
        assert len(warmup_events) == 1
        entry = warmup_events[0]
        assert entry.get("entrance") == "stable_getscores"
        assert entry.get("outcome") == "requested"
        assert entry.get("beatmap_id") == 75
        assert entry.get("checksum_md5") is None
        assert "ha" not in entry
        assert _no_credentials_leaked(entry)


# ---------------------------------------------------------------------------
# Stable response body purity (Req 12.5)
# ---------------------------------------------------------------------------


class TestStableResponsePurity:
    """Stable response bodies must never contain provenance fields."""

    _BANNED_TOKENS: tuple[bytes, ...] = (
        b"_source",
        b"_verified",
        b"_policy",
        b"_fetch_state",
        b"local_status_override",
        b"official_status_source",
        b"official_status_verified",
        b"metadata_fetch_state",
        b"file_state",
    )

    def test_known_header_response_has_no_provenance(self) -> None:
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:

                async def _setup() -> None:
                    _ = await _seed_user_with_session(app)
                    await _seed_known_beatmap(app)

                asyncio.run(_setup())
                response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(),
                )
                assert response.status_code == HTTPStatus.OK
                for token in self._BANNED_TOKENS:
                    assert token not in response.content

    def test_unavailable_response_has_no_provenance(self) -> None:
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:
                _ = asyncio.run(_seed_user_with_session(app))
                response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(checksum="ff" * 16),
                )
                assert response.status_code == HTTPStatus.OK
                for token in self._BANNED_TOKENS:
                    assert token not in response.content
