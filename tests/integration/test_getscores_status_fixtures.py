"""Legacy getscores endpointのstatus crosswalkをend-to-endで検証する.

全canonical ``BeatmapRankStatus``をsubmitted headerまたはexact unavailable
responseへ対応付ける. Approvedを含むwire status, persisted local override後の
effective status, header field, display title, rating, empty score sectionを検証する.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from starlette.testclient import TestClient

from athena_cli.stable_verification.getscores_evidence import (
    GetscoresWireShapeId,
    StatusRepresentation,
    load_getscores_completion_evidence,
)
from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapSourceVerification,
    LocalBeatmapStatus,
)
from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.identity.users import User
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.services.queries.identity.password_service import PasswordService
from tests.support.app import create_in_memory_app as create_app
from tests.support.app import resolve_dependency
from tests.support.persistence import seed_beatmapset, seed_user

if TYPE_CHECKING:
    from collections.abc import Generator

    from starlette.applications import Starlette


_TEST_USERNAME = "StableUser"
_TEST_PASSWORD_PLAIN = "ExamplePass1234"  # gitleaks:allow
_TEST_PASSWORD_MD5 = hashlib.md5(_TEST_PASSWORD_PLAIN.encode()).hexdigest()
_NOW = datetime(2026, 6, 7, tzinfo=UTC)
_NEXT_REFRESH = _NOW + timedelta(days=30)
_FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
_MANIFEST_ROOT = _FIXTURE_ROOT / "stable_compatibility" / "getscores"
_BODY_ROOT = _FIXTURE_ROOT / "web_legacy" / "getscores" / "completion"
_GETSCORES_EVIDENCE = load_getscores_completion_evidence(_MANIFEST_ROOT, _BODY_ROOT)
_STATUS_CROSSWALK_BY_STATUS = {
    entry.canonical_status: entry for entry in _GETSCORES_EVIDENCE.status_crosswalk
}
_WIRE_SHAPES_BY_ID = {shape.shape_id: shape for shape in _GETSCORES_EVIDENCE.response_shapes}
_UNAVAILABLE_SHAPE = _WIRE_SHAPES_BY_ID[GetscoresWireShapeId.UNAVAILABLE]


@contextmanager
def _test_env() -> Generator[None]:
    """Integration test実行中だけ必要な環境変数を設定する.

    Yields:
        None: test用の環境変数が設定されたblockを実行する.

    Notes:
        終了時にENVIRONMENTとDOMAINを呼出前の値へ復元する.
    """
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


@dataclass(frozen=True)
class _StatusFixture:
    """Canonical statusごとのsynthetic seedと期待wire valueを保持する.

    Attributes:
        name (str): Pytest parameter IDに使うsafeなfixture名.
        rank_status (BeatmapRankStatus): Persistするofficial canonical status.
        expected_wire_status (int | None): Crosswalk由来のgetscores wire value.
        beatmap_id (int): Synthetic beatmap ID.
        beatmapset_id (int): Synthetic beatmapset ID.
        checksum (str): Synthetic lowercase MD5 checksum.
        artist (str): Header display title用のartist.
        title (str): Header display title用のtitle.
        local_status_override (LocalBeatmapStatus | None): Persistするlocal override.

    Notes:
        expected_wire_statusはtyped crosswalkから取得する. Noneはunavailable
        representationだけを表し, numeric statusを推測しない.
    """

    name: str
    rank_status: BeatmapRankStatus
    expected_wire_status: int | None
    beatmap_id: int
    beatmapset_id: int
    checksum: str
    artist: str
    title: str
    local_status_override: LocalBeatmapStatus | None = None


_FIXTURES = (
    _StatusFixture(
        name="ranked",
        rank_status=BeatmapRankStatus.RANKED,
        expected_wire_status=_STATUS_CROSSWALK_BY_STATUS[
            BeatmapRankStatus.RANKED
        ].getscores.wire_status,
        beatmap_id=75,
        beatmapset_id=1,
        checksum="0123456789abcdef0123456789abcdef",
        artist="Suzaku",
        title="Anisakis -sakuya-",
    ),
    _StatusFixture(
        name="approved",
        rank_status=BeatmapRankStatus.APPROVED,
        expected_wire_status=_STATUS_CROSSWALK_BY_STATUS[
            BeatmapRankStatus.APPROVED
        ].getscores.wire_status,
        beatmap_id=350,
        beatmapset_id=35,
        checksum="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        artist="Ryu*",
        title="Sakura Reflection",
    ),
    _StatusFixture(
        name="loved",
        rank_status=BeatmapRankStatus.LOVED,
        expected_wire_status=_STATUS_CROSSWALK_BY_STATUS[
            BeatmapRankStatus.LOVED
        ].getscores.wire_status,
        beatmap_id=500,
        beatmapset_id=50,
        checksum="11111111111111111111111111111111",
        artist="Hatsune Miku",
        title="World is Mine -Full ver.-",
    ),
    _StatusFixture(
        name="qualified",
        rank_status=BeatmapRankStatus.QUALIFIED,
        expected_wire_status=_STATUS_CROSSWALK_BY_STATUS[
            BeatmapRankStatus.QUALIFIED
        ].getscores.wire_status,
        beatmap_id=1200,
        beatmapset_id=100,
        checksum="22222222222222222222222222222222",
        artist="DECO*27",
        title="Ghost Rule",
    ),
    _StatusFixture(
        name="pending",
        rank_status=BeatmapRankStatus.PENDING,
        expected_wire_status=_STATUS_CROSSWALK_BY_STATUS[
            BeatmapRankStatus.PENDING
        ].getscores.wire_status,
        beatmap_id=2500,
        beatmapset_id=200,
        checksum="33333333333333333333333333333333",
        artist="t+pazolite",
        title="Oshama Scramble!",
    ),
    _StatusFixture(
        name="wip",
        rank_status=BeatmapRankStatus.WIP,
        expected_wire_status=_STATUS_CROSSWALK_BY_STATUS[
            BeatmapRankStatus.WIP
        ].getscores.wire_status,
        beatmap_id=3000,
        beatmapset_id=250,
        checksum="44444444444444444444444444444444",
        artist="Camellia",
        title="Exit This Earth's Atomosphere",
    ),
    _StatusFixture(
        name="graveyard",
        rank_status=BeatmapRankStatus.GRAVEYARD,
        expected_wire_status=_STATUS_CROSSWALK_BY_STATUS[
            BeatmapRankStatus.GRAVEYARD
        ].getscores.wire_status,
        beatmap_id=4500,
        beatmapset_id=400,
        checksum="55555555555555555555555555555555",
        artist="xi",
        title="Freedom Dive",
    ),
)
_UNAVAILABLE_FIXTURES = (
    _StatusFixture(
        name="not-submitted",
        rank_status=BeatmapRankStatus.NOT_SUBMITTED,
        expected_wire_status=_STATUS_CROSSWALK_BY_STATUS[
            BeatmapRankStatus.NOT_SUBMITTED
        ].getscores.wire_status,
        beatmap_id=5_000,
        beatmapset_id=450,
        checksum="66666666666666666666666666666666",
        artist="Synthetic Artist",
        title="Not Submitted",
    ),
    _StatusFixture(
        name="unknown",
        rank_status=BeatmapRankStatus.UNKNOWN,
        expected_wire_status=_STATUS_CROSSWALK_BY_STATUS[
            BeatmapRankStatus.UNKNOWN
        ].getscores.wire_status,
        beatmap_id=5_500,
        beatmapset_id=500,
        checksum="77777777777777777777777777777777",
        artist="Synthetic Artist",
        title="Unknown Status",
    ),
)
_LOCAL_OVERRIDE_FIXTURE = _StatusFixture(
    name="pending-overridden-ranked",
    rank_status=BeatmapRankStatus.PENDING,
    expected_wire_status=_STATUS_CROSSWALK_BY_STATUS[
        BeatmapRankStatus.RANKED
    ].getscores.wire_status,
    beatmap_id=6_000,
    beatmapset_id=550,
    checksum="88888888888888888888888888888888",
    artist="Synthetic Artist",
    title="Effective Ranked Override",
    local_status_override=LocalBeatmapStatus.RANKED,
)
_FIXTURE_IDS = tuple(f.name for f in _FIXTURES)
_UNAVAILABLE_FIXTURE_IDS = tuple(f.name for f in _UNAVAILABLE_FIXTURES)
_ALL_STATUS_FIXTURES = (*_FIXTURES, *_UNAVAILABLE_FIXTURES)
_BELOW_RANKED_FIXTURES = tuple(f for f in _FIXTURES if f.expected_wire_status == 0)
_BELOW_RANKED_IDS = tuple(f.name for f in _BELOW_RANKED_FIXTURES)


async def _seed_user_with_session(app: Starlette) -> int:
    """Getscores request用のactive sessionを持つUserをseedする.

    Args:
        app (Starlette): dependency graphを持つtest application.

    Returns:
        int: 永続化したUser ID.
    """
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


async def _seed_beatmap_for_fixture(app: Starlette, fixture: _StatusFixture) -> None:
    """Status fixtureのbeatmapsetをin-memory persistenceへ保存する.

    Args:
        app (Starlette): Dependency graphを持つtest application.
        fixture (_StatusFixture): 保存するstatusとsynthetic metadata.

    Returns:
        None: Beatmapsetを保存して処理を終了する.

    Notes:
        Dependency resolutionまたはUnit of Work commitの例外はそのまま伝播する.
    """
    beatmap = Beatmap(
        id=fixture.beatmap_id,
        beatmapset_id=fixture.beatmapset_id,
        checksum_md5=fixture.checksum,
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
        official_status=fixture.rank_status,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        local_status_override=fixture.local_status_override,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=BeatmapFileState.MISSING,
        file_attachment=None,
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
        local_status_override_changed_at=(
            _NOW if fixture.local_status_override is not None else None
        ),
    )
    beatmapset = BeatmapSet(
        id=fixture.beatmapset_id,
        artist=fixture.artist,
        title=fixture.title,
        creator="Author",
        artist_unicode=None,
        title_unicode=None,
        official_status=fixture.rank_status,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        beatmaps=(beatmap,),
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
    )
    await seed_beatmapset(app, beatmapset)


def _query_for_fixture(fixture: _StatusFixture) -> dict[str, str]:
    """Status fixtureを取得するbaseline query parameterを構築する.

    Args:
        fixture (_StatusFixture): checksumを持つcanonical status fixture.

    Returns:
        dict[str, str]: stable client互換fieldを含むquery parameter.
    """
    return {
        "c": fixture.checksum,
        "us": _TEST_USERNAME,
        "ha": _TEST_PASSWORD_MD5,
        "s": "0",
        "vv": "4",
        "v": "1",
        "m": "0",
        "mods": "0",
    }


def _exercise_endpoint_response(
    fixture: _StatusFixture,
) -> tuple[int, dict[str, str], bytes]:
    """Status fixtureをseedしてendpointのclient-visible responseを取得する.

    Args:
        fixture (_StatusFixture): Canonical statusとsynthetic beatmap seed.

    Returns:
        tuple[int, dict[str, str], bytes]: HTTP status, header mapping, exact body bytes.

    Notes:
        TestClientは`raise_server_exceptions=False`で起動するため, endpoint exceptionは
        Python exceptionとして再送出せずHTTP responseとして返す.
    """
    with _test_env():
        app = create_app()
        with TestClient(
            app,
            base_url="http://osu.athena.localhost",
            raise_server_exceptions=False,
        ) as client:

            async def _setup() -> None:
                """Authenticated Userとfixture Beatmapをseedする.

                Returns:
                    None: status responseを取得できるtest dataを永続化して完了する.
                """
                _ = await _seed_user_with_session(app)
                await _seed_beatmap_for_fixture(app, fixture)

            asyncio.run(_setup())
            response = client.get(
                "/web/osu-osz2-getscores.php",
                params=_query_for_fixture(fixture),
            )
            return response.status_code, dict(response.headers.items()), response.content


def _exercise_endpoint(fixture: _StatusFixture) -> bytes:
    """Status fixtureのsuccessful text response bodyを取得する.

    Args:
        fixture (_StatusFixture): Canonical statusとsynthetic beatmap seed.

    Returns:
        bytes: Getscores endpointのexact response body.

    Raises:
        AssertionError: HTTP statusまたはcontent typeがheader contractと異なる場合.
    """
    status_code, headers, body = _exercise_endpoint_response(fixture)
    assert status_code == HTTPStatus.OK
    assert headers["content-type"].startswith("text/plain")
    return body


# ---------------------------------------------------------------------------
# Per-fixture wire-format checks
# ---------------------------------------------------------------------------


class TestSubmittedStatusFixtures:
    """submitted statusごとのheader fieldがcrosswalkと一致することを検証する."""

    @pytest.mark.parametrize("fixture", _FIXTURES, ids=_FIXTURE_IDS)
    def test_status_line_fields(self, fixture: _StatusFixture) -> None:
        """Submitted statusのheader lineをtyped crosswalkへ照合する.

        Args:
            fixture (_StatusFixture): Wire representationを持つsubmitted status fixture.

        Returns:
            None: Statusとbeatmap identity fieldが期待値へ一致したことを示す.

        Raises:
            AssertionError: Crosswalk representationまたはheader fieldが異なる場合.
        """
        crosswalk_entry = _STATUS_CROSSWALK_BY_STATUS[fixture.rank_status]
        assert crosswalk_entry.getscores.representation is StatusRepresentation.WIRE
        assert fixture.expected_wire_status is not None
        assert fixture.expected_wire_status == crosswalk_entry.getscores.wire_status
        body = _exercise_endpoint(fixture)
        first_line = body.split(b"\n")[0]
        parts = first_line.split(b"|")
        # Format: <status>|false|<beatmap_id>|<beatmapset_id>|0||
        assert int(parts[0]) == fixture.expected_wire_status
        assert parts[1] == b"false"
        assert int(parts[2]) == fixture.beatmap_id
        assert int(parts[3]) == fixture.beatmapset_id
        assert parts[4] == b"0", "score_count must be 0"
        # Trailing || produces two empty tail entries
        assert parts[-2] == b""
        assert parts[-1] == b""

    @pytest.mark.parametrize("fixture", _FIXTURES, ids=_FIXTURE_IDS)
    def test_offset_line_is_zero(self, fixture: _StatusFixture) -> None:
        """Submitted statusのoffset lineが0であることを検証する.

        Args:
            fixture (_StatusFixture): header responseを返すsubmitted status fixture.

        Returns:
            None: offset lineがMVP contractどおり0であることを確認して完了する.
        """
        body = _exercise_endpoint(fixture)
        lines = body.split(b"\n")
        assert lines[1] == b"0", "Beatmap offset line must be '0' in MVP"

    @pytest.mark.parametrize("fixture", _FIXTURES, ids=_FIXTURE_IDS)
    def test_display_title_line_format(self, fixture: _StatusFixture) -> None:
        """Submitted statusのdisplay title line formatを検証する.

        Args:
            fixture (_StatusFixture): artistとtitleを持つsubmitted status fixture.

        Returns:
            None: BBCode prefixを含むartistとtitleのlineを確認して完了する.
        """
        body = _exercise_endpoint(fixture)
        lines = body.split(b"\n")
        display = lines[2]
        expected = f"[bold:0,size:20]{fixture.artist}|{fixture.title}".encode()
        assert display == expected

    @pytest.mark.parametrize("fixture", _FIXTURES, ids=_FIXTURE_IDS)
    def test_rating_line_is_zero(self, fixture: _StatusFixture) -> None:
        """Submitted statusのrating lineが0であることを検証する.

        Args:
            fixture (_StatusFixture): header responseを返すsubmitted status fixture.

        Returns:
            None: rating lineがMVP contractどおり0であることを確認して完了する.
        """
        body = _exercise_endpoint(fixture)
        lines = body.split(b"\n")
        assert lines[3] == b"0", "Rating line must be '0' in MVP"

    @pytest.mark.parametrize("fixture", _FIXTURES, ids=_FIXTURE_IDS)
    def test_no_score_rows_or_personal_best(self, fixture: _StatusFixture) -> None:
        """score未seedのsubmitted statusがempty score sectionを返すことを検証する.

        Args:
            fixture (_StatusFixture): scoreを持たないsubmitted status fixture.

        Returns:
            None: Personal Bestとscore row用のtrailing placeholderを確認して完了する.
        """
        body = _exercise_endpoint(fixture)
        lines = body.split(b"\n")
        # Header body shape: 4 data lines + 2 blank trailing lines (placeholder
        # for personal-best and score-rows sections), terminated by final LF.
        # split('\n') therefore produces: 4 data + 2 empty + 1 trailing empty = 7.
        non_empty = [line for line in lines if line]
        assert len(non_empty) == 4, (
            f"Expected exactly 4 data lines (status, offset, display, rating); got {non_empty!r}"
        )
        # Confirm trailing placeholder lines exist (two blank sections).
        assert lines[-3:] == [b"", b"", b""], (
            f"Expected two trailing blank section placeholders, got tail {lines[-3:]!r}"
        )


def test_endpoint_status_fixtures_cover_crosswalk_once() -> None:
    """Integration fixtureがcrosswalkのcanonical statusを重複なく網羅する.

    Returns:
        None: 全statusがsubmittedまたはunavailable fixtureへ一度だけ対応することを示す.

    Raises:
        AssertionError: Fixture statusの欠落, 重複, 余分なentryが存在する場合.
    """
    fixture_statuses = tuple(fixture.rank_status for fixture in _ALL_STATUS_FIXTURES)
    crosswalk_statuses = tuple(_STATUS_CROSSWALK_BY_STATUS)

    assert len(fixture_statuses) == len(crosswalk_statuses)
    assert len(set(fixture_statuses)) == len(fixture_statuses)
    assert set(fixture_statuses) == set(crosswalk_statuses)


class TestUnavailableStatusFixtures:
    """Unsupported canonical statusをexact unavailable responseへ対応付ける.

    Notes:
        Crosswalkのunavailable representationをnumeric headerへ変換しない.
    """

    @pytest.mark.parametrize(
        "fixture",
        _UNAVAILABLE_FIXTURES,
        ids=_UNAVAILABLE_FIXTURE_IDS,
    )
    def test_status_returns_exact_unavailable_response(
        self,
        fixture: _StatusFixture,
    ) -> None:
        """NotSubmittedとUnknownのstatus, header, bodyをexact fixtureへ照合する.

        Args:
            fixture (_StatusFixture): Unavailable representationを持つstatus fixture.

        Returns:
            None: Runtime responseがcanonical unavailable shapeと一致したことを示す.

        Raises:
            AssertionError: Crosswalk representationまたはresponse shapeが異なる場合.
        """
        crosswalk_entry = _STATUS_CROSSWALK_BY_STATUS[fixture.rank_status]
        assert crosswalk_entry.getscores.representation is StatusRepresentation.UNAVAILABLE
        assert crosswalk_entry.getscores.wire_status is None
        assert fixture.expected_wire_status is None

        status_code, headers, body = _exercise_endpoint_response(fixture)

        assert status_code == _UNAVAILABLE_SHAPE.http_status
        for header_name, expected_value in _UNAVAILABLE_SHAPE.required_headers.items():
            assert headers[header_name] == expected_value
        for header_name in _UNAVAILABLE_SHAPE.absent_headers:
            assert header_name not in headers
        assert body == _UNAVAILABLE_SHAPE.read_body_bytes()
        assert body == b"-1|false"


class TestEffectiveLocalStatusOverride:
    """Persisted local override適用後のeffective statusをwireへ変換する.

    Notes:
        Official statusではなくpersistenceから復元したeffective statusを入力にする.
    """

    def test_persisted_override_selects_effective_wire_status(self) -> None:
        """Pending beatmapのRanked overrideがRanked wire valueを返すことを検証する.

        Returns:
            None: Persistence経由のeffective statusがheader statusへ反映されたことを示す.

        Raises:
            AssertionError: Official statusが選択された場合, またはeffective wire
                valueがRankedの値と異なる場合.
        """
        official_entry = _STATUS_CROSSWALK_BY_STATUS[BeatmapRankStatus.PENDING]
        effective_entry = _STATUS_CROSSWALK_BY_STATUS[BeatmapRankStatus.RANKED]
        assert official_entry.getscores.wire_status == 0
        assert effective_entry.getscores.wire_status == 2
        assert _LOCAL_OVERRIDE_FIXTURE.expected_wire_status == 2

        body = _exercise_endpoint(_LOCAL_OVERRIDE_FIXTURE)
        first_line = body.split(b"\n", maxsplit=1)[0]

        assert int(first_line.split(b"|", maxsplit=1)[0]) == 2


# ---------------------------------------------------------------------------
# Official-precedence assertions: Pending / WIP / Graveyard return headers
# ---------------------------------------------------------------------------


class TestOfficialPrecedenceOverBanchopy:
    """Pending, WIP, Graveyardがshort bodyではなくheader bodyを返すことを検証する."""

    @pytest.mark.parametrize(
        "fixture",
        _BELOW_RANKED_FIXTURES,
        ids=_BELOW_RANKED_IDS,
    )
    def test_below_ranked_returns_header_body_not_short(self, fixture: _StatusFixture) -> None:
        """Below ranked statusがdisplay titleを含むheader bodyを返すことを検証する.

        Args:
            fixture (_StatusFixture): wire statusが0となるsubmitted status fixture.

        Returns:
            None: unavailableまたはupdate available short bodyではないことを確認して完了する.
        """
        body = _exercise_endpoint(fixture)
        # Short bodies are exactly b"-1|false" or b"1|false"; header bodies
        # are multi-line and contain the display title with the bbcode prefix.
        assert body != b"-1|false"
        assert body != b"1|false"
        assert b"[bold:0,size:20]" in body, (
            f"{fixture.name} must return a header body (bancho.py would short-respond)"
        )


# ---------------------------------------------------------------------------
# Provenance must never leak into stable response body
# ---------------------------------------------------------------------------


class TestStableResponsePurity:
    """header bodyがinternal provenance fieldを含まないことを検証する.

    Attributes:
        _BANNED_TOKENS (tuple[bytes, ...]): response bodyへ現れてはならないinternal field名.
    """

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

    @pytest.mark.parametrize("fixture", _FIXTURES, ids=_FIXTURE_IDS)
    def test_no_provenance_tokens_in_body(self, fixture: _StatusFixture) -> None:
        """Submitted status bodyからinternal provenance tokenを除外することを検証する.

        Args:
            fixture (_StatusFixture): header bodyを返すsubmitted status fixture.

        Returns:
            None: 禁止tokenがresponse bodyに含まれないことを確認して完了する.
        """
        body = _exercise_endpoint(fixture)
        for token in self._BANNED_TOKENS:
            assert token not in body, (
                f"{fixture.name} body contains internal provenance token {token!r}"
            )
