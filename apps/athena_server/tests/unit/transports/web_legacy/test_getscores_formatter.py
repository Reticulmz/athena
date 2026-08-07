"""Getscores response formatterのshort body, header body, sanitization contractを検証する."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from athena_cli.stable_verification.getscores_evidence import (
    GetscoresWireShapeId,
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
)
from osu_server.domain.compatibility.stable.getscores import GetscoresPersonalBest
from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.transports.stable.web_legacy.getscores import (
    format_getscores_header_response,
    format_getscores_unavailable_response,
    format_getscores_update_available_response,
)
from tests.support.getscores_contract import read_getscores_expected_body

if TYPE_CHECKING:
    from starlette.responses import Response

_NOW = datetime(2026, 6, 7, tzinfo=UTC)
_NEXT_REFRESH = _NOW + timedelta(days=30)
_CHECKSUM = "0123456789abcdef0123456789abcdef"
_FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures"
_MANIFEST_ROOT = _FIXTURE_ROOT / "stable_compatibility" / "getscores"
_BODY_ROOT = _FIXTURE_ROOT / "web_legacy" / "getscores" / "completion"


def _response_body(response: Response) -> bytes:
    """Starlette responseからformatter検証用のbody bytesを取得する.

    Args:
        response (Response): Getscores formatterが返したHTTP response.

    Returns:
        bytes: response bodyのimmutable bytes copy.
    """
    return bytes(response.body)


def _make_beatmap(
    *,
    beatmap_id: int = 75,
    beatmapset_id: int = 1,
    official_status: BeatmapRankStatus = BeatmapRankStatus.RANKED,
) -> Beatmap:
    """Getscores header formatting用のbeatmap fixtureを構築する.

    Args:
        beatmap_id (int): header first lineへ入れるbeatmap ID.
        beatmapset_id (int): header first lineへ入れるbeatmapset ID.
        official_status (BeatmapRankStatus): formatterがstatusを導出するofficial status.

    Returns:
        Beatmap: fresh metadataとmissing osu file stateを持つbeatmap fixture.
    """
    return Beatmap(
        id=beatmap_id,
        beatmapset_id=beatmapset_id,
        checksum_md5=_CHECKSUM,
        mode=BeatmapMode.OSU,
        version="Insane",
        total_length=240,
        hit_length=220,
        max_combo=1_234,
        bpm=180.0,
        cs=4.0,
        od=8.5,
        ar=9.4,
        hp=6.5,
        difficulty_rating=5.67,
        official_status=official_status,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        local_status_override=None,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=BeatmapFileState.MISSING,
        file_attachment=None,
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
    )


def _make_beatmapset(
    *,
    beatmapset_id: int = 1,
    artist: str = "Camellia",
    title: str = "Exit This Earth's Atomosphere",
) -> BeatmapSet:
    """Getscores display line用のbeatmapset fixtureを構築する.

    Args:
        beatmapset_id (int): beatmapset identityとして設定するID.
        artist (str): display lineへ設定するartist text.
        title (str): display lineへ設定するtitle text.

    Returns:
        BeatmapSet: 指定artistとtitleを持つranked beatmapset fixture.
    """
    return BeatmapSet(
        id=beatmapset_id,
        artist=artist,
        title=title,
        creator="Realazy",
        artist_unicode=None,
        title_unicode=None,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        beatmaps=(),
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
    )


def _make_personal_best(
    *,
    score_id: int = 42,
    user_id: int = 7,
    username: str = "Player",
    score: int = 987_654,
    max_combo: int = 1_234,
    n50: int = 1,
    n100: int = 2,
    n300: int = 300,
    miss: int = 3,
    katu: int = 4,
    geki: int = 5,
    perfect: bool = True,
    mods: int = 24,
    has_replay: bool = True,
    rank: int = 3,
    submitted_at: datetime = _NOW,
) -> GetscoresPersonalBest:
    """Getscores personal bestまたはscore row fixtureを構築する.

    Args:
        score_id (int): score row identityとして設定するID.
        user_id (int): scoreを所有するuser ID.
        username (str): wire rowへ設定するusername.
        score (int): legacy score fieldへ設定するscore値.
        max_combo (int): rowへ設定する最大combo値.
        n50 (int): 50 hit count.
        n100 (int): 100 hit count.
        n300 (int): 300 hit count.
        miss (int): miss count.
        katu (int): katu count.
        geki (int): geki count.
        perfect (bool): full combo flag.
        mods (int): legacy mod bitmask.
        has_replay (bool): replay availability flag.
        rank (int): leaderboard rank.
        submitted_at (datetime): score submission timestamp.

    Returns:
        GetscoresPersonalBest: stable score listing formatへ変換可能なfixture.
    """
    return GetscoresPersonalBest(
        score_id=score_id,
        user_id=user_id,
        username=username,
        beatmap_id=75,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        score=score,
        max_combo=max_combo,
        n50=n50,
        n100=n100,
        n300=n300,
        miss=miss,
        katu=katu,
        geki=geki,
        perfect=perfect,
        mods=mods,
        rank=rank,
        submitted_at=submitted_at,
        has_replay=has_replay,
    )


def _expected_score_row(row: GetscoresPersonalBest) -> bytes:
    """Personal bestをexpected stable score row bytesへencodeする.

    Args:
        row (GetscoresPersonalBest): expected wire fieldを提供するpersonal best fixture.

    Returns:
        bytes: pipe-delimited stable score row bytes.
    """
    return (
        f"{row.score_id}|{row.username}|{row.score}|{row.max_combo}|{row.n50}|"
        f"{row.n100}|{row.n300}|{row.miss}|{row.katu}|{row.geki}|"
        f"{1 if row.perfect else 0}|{row.mods}|{row.user_id}|{row.rank}|"
        f"{int(row.submitted_at.timestamp())}|{1 if row.has_replay else 0}"
    ).encode()


# ---------------------------------------------------------------------------
# Short response bodies (requirements 7.5)
# ---------------------------------------------------------------------------


def test_format_unavailable_returns_short_body() -> None:
    """Unavailable outcomeが-1|false short bodyへformatされるcontractを検証する.

    Returns:
        None: exact unavailable bodyを確認して完了する.
    """
    body = _response_body(format_getscores_unavailable_response())
    assert body == b"-1|false"


def test_format_update_available_returns_short_body() -> None:
    """UpdateAvailable outcomeが1|false short bodyへformatされるcontractを検証する.

    Returns:
        None: exact update-available bodyを確認して完了する.
    """
    body = _response_body(format_getscores_update_available_response())
    assert body == b"1|false"


# ---------------------------------------------------------------------------
# Header body — first line (requirements 8.4, 11.2)
# ---------------------------------------------------------------------------


def test_header_first_line_format() -> None:
    """Header first lineがstatusとbeatmap identityをwire順に持つcontractを検証する.

    Returns:
        None: exact pipe-delimited first lineを確認して完了する.
    """
    beatmap = _make_beatmap(beatmap_id=75, beatmapset_id=1)
    beatmapset = _make_beatmapset(beatmapset_id=1)

    body = _response_body(
        format_getscores_header_response(
            status=2,
            beatmap=beatmap,
            beatmapset=beatmapset,
        )
    )
    first_line = body.split(b"\n")[0]
    assert first_line == b"2|false|75|1|0||"


def test_header_score_count_is_zero_without_rows() -> None:
    """Score rowがないheaderのscore countを0にするcontractを検証する.

    Returns:
        None: first lineのscore count fieldが0であることを確認して完了する.
    """
    body = _response_body(
        format_getscores_header_response(
            status=2,
            beatmap=_make_beatmap(),
            beatmapset=_make_beatmapset(),
        )
    )
    first_line = body.split(b"\n")[0]
    parts = first_line.split(b"|")
    assert parts[4] == b"0"


def test_header_score_count_uses_returned_rows_not_personal_best() -> None:
    """Header score countがpersonal bestではなくreturned row数を使うcontractを検証する.

    Returns:
        None: score count fieldがreturned row数と一致することを確認して完了する.
    """
    personal_best = _make_personal_best(score_id=99, rank=99)
    rows = (
        _make_personal_best(score_id=101, user_id=11, username="Top 1", rank=1),
        _make_personal_best(score_id=102, user_id=12, username="Top 2", rank=2),
    )

    body = _response_body(
        format_getscores_header_response(
            status=2,
            beatmap=_make_beatmap(),
            beatmapset=_make_beatmapset(),
            personal_best=personal_best,
            score_rows=rows,
        )
    )

    first_line = body.split(b"\n")[0]
    parts = first_line.split(b"|")
    assert parts[4] == b"2"


def test_header_with_rows_matches_exact_fixture_after_sanitization() -> None:
    """Sanitize済みheader, PB, rowsをcanonical bodyへexact照合する.

    Returns:
        None: Formatter bodyがfixtureと一致し, wire grammarを維持した状態.

    Raises:
        AssertionError: Body bytes, row count, delimiter grammarが異なる場合.
    """
    personal_best = _make_personal_best(username="PB|Player\rSafe\nText")
    score_rows = (
        _make_personal_best(
            score_id=43,
            user_id=8,
            username="Row|One\rSafe\nText",
            score=876_543,
            max_combo=999,
            n50=4,
            n100=5,
            n300=250,
            miss=6,
            katu=7,
            geki=8,
            perfect=False,
            mods=0,
            rank=1,
            submitted_at=_NOW + timedelta(minutes=1),
        ),
        _make_personal_best(
            score_id=44,
            user_id=9,
            username="Row|Two\rSafe\nText",
            score=765_432,
            max_combo=888,
            n50=9,
            n100=10,
            n300=200,
            miss=11,
            katu=12,
            geki=13,
            perfect=True,
            mods=64,
            rank=2,
            submitted_at=_NOW + timedelta(minutes=2),
            has_replay=False,
        ),
    )
    evidence = load_getscores_completion_evidence(_MANIFEST_ROOT, _BODY_ROOT)
    expected_body = read_getscores_expected_body(
        evidence,
        GetscoresWireShapeId.HEADER_WITH_ROWS,
    )

    body = _response_body(
        format_getscores_header_response(
            status=2,
            beatmap=_make_beatmap(),
            beatmapset=_make_beatmapset(
                artist="Fixture|Artist\rSafe\nText",
                title="Fixture|Title\rSafe\nText",
            ),
            personal_best=personal_best,
            score_rows=score_rows,
        )
    )

    lines = body.splitlines()
    assert body == expected_body
    assert lines[0].split(b"|")[4] == str(len(score_rows)).encode()
    assert lines[2].count(b"|") == 1
    assert all(line.count(b"|") == 15 for line in lines[4:])


def test_header_failed_flag_is_false() -> None:
    """Header failed flagをfalseへ固定するcontractを検証する.

    Returns:
        None: first lineのfailed fieldがfalseであることを確認して完了する.
    """
    body = _response_body(
        format_getscores_header_response(
            status=2,
            beatmap=_make_beatmap(),
            beatmapset=_make_beatmapset(),
        )
    )
    first_line = body.split(b"\n")[0]
    parts = first_line.split(b"|")
    assert parts[1] == b"false"


# ---------------------------------------------------------------------------
# Header body — structure (requirements 8.4, 11.3, 11.4, 11.5)
# ---------------------------------------------------------------------------


def test_header_body_line_count() -> None:
    """Header bodyが4 data lineと2 blank sectionを持つcontractを検証する.

    Returns:
        None: terminal newlineを含むsplit entry数とblank sectionを確認して完了する.
    """
    body = _response_body(
        format_getscores_header_response(
            status=2,
            beatmap=_make_beatmap(),
            beatmapset=_make_beatmapset(),
        )
    )
    lines = body.split(b"\n")
    # 4 data lines + 2 blank + trailing empty from terminal newline = 7 entries from split
    assert len(lines) == 7
    assert lines[4] == b""
    assert lines[5] == b""
    assert lines[6] == b""


def test_header_only_listing_has_empty_personal_best_and_rows_sections() -> None:
    """Header-only listingがpersonal bestとscore row sectionをemptyにするcontractを検証する.

    Returns:
        None: 2つのblank sectionとterminal newline entryを確認して完了する.
    """
    body = _response_body(
        format_getscores_header_response(
            status=2,
            beatmap=_make_beatmap(),
            beatmapset=_make_beatmapset(),
        )
    )

    assert body.split(b"\n")[4:] == [b"", b"", b""]


def test_header_second_line_is_beatmap_offset() -> None:
    """Header second lineがMVP beatmap offset 0となるcontractを検証する.

    Returns:
        None: second lineのexact byte値を確認して完了する.
    """
    body = _response_body(
        format_getscores_header_response(
            status=2,
            beatmap=_make_beatmap(),
            beatmapset=_make_beatmapset(),
        )
    )
    lines = body.split(b"\n")
    assert lines[1] == b"0"


def test_header_third_line_is_display_title() -> None:
    """Header third lineがbbcode prefix付きartist|titleとなるcontractを検証する.

    Returns:
        None: display lineのexact byte値を確認して完了する.
    """
    body = _response_body(
        format_getscores_header_response(
            status=2,
            beatmap=_make_beatmap(),
            beatmapset=_make_beatmapset(artist="Camellia", title="Exit This Earth's Atomosphere"),
        )
    )
    lines = body.split(b"\n")
    assert lines[2] == b"[bold:0,size:20]Camellia|Exit This Earth's Atomosphere"


def test_header_fourth_line_is_rating() -> None:
    """Header fourth lineがMVP rating 0となるcontractを検証する.

    Returns:
        None: fourth lineのexact byte値を確認して完了する.
    """
    body = _response_body(
        format_getscores_header_response(
            status=2,
            beatmap=_make_beatmap(),
            beatmapset=_make_beatmapset(),
        )
    )
    lines = body.split(b"\n")
    assert lines[3] == b"0"


def test_header_response_ends_with_newline() -> None:
    """Header responseがterminal newlineで終わるcontractを検証する.

    Returns:
        None: body末尾がnewline byteであることを確認して完了する.
    """
    body = _response_body(
        format_getscores_header_response(
            status=2,
            beatmap=_make_beatmap(),
            beatmapset=_make_beatmapset(),
        )
    )
    assert body.endswith(b"\n")


def test_header_personal_best_row_uses_stable_score_listing_format() -> None:
    """Personal best rowがstable score listing field orderを保つcontractを検証する.

    Returns:
        None: personal best sectionのexpected score row bytesを確認して完了する.
    """
    personal_best = _make_personal_best()
    body = _response_body(
        format_getscores_header_response(
            status=2,
            beatmap=_make_beatmap(),
            beatmapset=_make_beatmapset(),
            personal_best=personal_best,
        )
    )

    lines = body.split(b"\n")
    assert lines[0] == b"2|false|75|1|0||"
    assert lines[4] == _expected_score_row(personal_best)
    assert lines[5] == b""


def test_personal_best_can_duplicate_a_returned_row() -> None:
    """Personal bestがreturned score rowと同一でも両sectionへ出るcontractを検証する.

    Returns:
        None: personal bestとscore rowに同じscore bytesが存在することを確認して完了する.
    """
    personal_best = _make_personal_best(score_id=42, rank=3)

    body = _response_body(
        format_getscores_header_response(
            status=2,
            beatmap=_make_beatmap(),
            beatmapset=_make_beatmapset(),
            personal_best=personal_best,
            score_rows=(personal_best,),
        )
    )

    lines = body.split(b"\n")
    assert lines[0] == b"2|false|75|1|1||"
    assert lines[4] == _expected_score_row(personal_best)
    assert lines[5] == _expected_score_row(personal_best)


def test_personal_best_outside_returned_rows_keeps_its_actual_rank() -> None:
    """Returned row外のpersonal bestが実際のrankを保つcontractを検証する.

    Returns:
        None: personal bestとtop rowがそれぞれのrankを保持することを確認して完了する.
    """
    personal_best = _make_personal_best(score_id=200, user_id=20, score=100_000, rank=51)
    top_row = _make_personal_best(score_id=100, user_id=10, username="Top", score=999_999, rank=1)

    body = _response_body(
        format_getscores_header_response(
            status=2,
            beatmap=_make_beatmap(),
            beatmapset=_make_beatmapset(),
            personal_best=personal_best,
            score_rows=(top_row,),
        )
    )

    lines = body.split(b"\n")
    assert lines[0] == b"2|false|75|1|1||"
    assert lines[4] == _expected_score_row(personal_best)
    assert lines[5] == _expected_score_row(top_row)
    assert lines[4].split(b"|")[13] == b"51"
    assert lines[5].split(b"|")[13] == b"1"


def test_personal_best_username_is_sanitized() -> None:
    """Personal best username内のwire delimiterとnewlineをsanitizeするcontractを検証する.

    Returns:
        None: unsanitized delimiterがなくreplay flagが保たれることを確認して完了する.
    """
    body = _response_body(
        format_getscores_header_response(
            status=2,
            beatmap=_make_beatmap(),
            beatmapset=_make_beatmapset(),
            personal_best=_make_personal_best(username="A|B\nC", has_replay=False),
        )
    )

    lines = body.split(b"\n")
    assert b"A|B" not in lines[4]
    assert lines[4].endswith(b"|0")


# ---------------------------------------------------------------------------
# Sanitization (requirements 11.7, 11.8)
# ---------------------------------------------------------------------------


def test_pipe_delimiter_in_artist_is_replaced() -> None:
    """Artist内のpipe delimiterを置換してwire formatを保つcontractを検証する.

    Returns:
        None: display lineにunsanitized pipeがないことを確認して完了する.
    """
    body = _response_body(
        format_getscores_header_response(
            status=2,
            beatmap=_make_beatmap(),
            beatmapset=_make_beatmapset(artist="A|B", title="Song"),
        )
    )
    lines = body.split(b"\n")
    assert b"A|B" not in lines[2]
    assert b"A B" in lines[2] or b"A" in lines[2]


def test_pipe_delimiter_in_title_is_replaced() -> None:
    """Title内のpipe delimiterを置換してwire formatを保つcontractを検証する.

    Returns:
        None: display lineにunsanitized titleがないことを確認して完了する.
    """
    body = _response_body(
        format_getscores_header_response(
            status=2,
            beatmap=_make_beatmap(),
            beatmapset=_make_beatmapset(artist="Artist", title="Song|Remix"),
        )
    )
    lines = body.split(b"\n")
    assert b"Song|Remix" not in lines[2]


def test_line_break_in_artist_is_replaced() -> None:
    """Artist内のline breakを置換してwire lineを保つcontractを検証する.

    Returns:
        None: display lineにartistのunsanitized newlineがないことを確認して完了する.
    """
    body = _response_body(
        format_getscores_header_response(
            status=2,
            beatmap=_make_beatmap(),
            beatmapset=_make_beatmapset(artist="A\nB", title="Song"),
        )
    )
    lines = body.split(b"\n")
    assert b"A\nB" not in lines[2]


def test_line_break_in_title_is_replaced() -> None:
    """Title内のline breakを置換してwire lineを保つcontractを検証する.

    Returns:
        None: display lineにtitleのunsanitized newlineがないことを確認して完了する.
    """
    body = _response_body(
        format_getscores_header_response(
            status=2,
            beatmap=_make_beatmap(),
            beatmapset=_make_beatmapset(artist="Artist", title="Song\r\nRemix"),
        )
    )
    lines = body.split(b"\n")
    assert b"Song\r\nRemix" not in lines[2]


# ---------------------------------------------------------------------------
# Provenance isolation (requirement 12.5)
# ---------------------------------------------------------------------------


def test_header_body_has_no_provenance_fields() -> None:
    """Header bodyがinternal provenance fieldを露出しないcontractを検証する.

    Returns:
        None: source, verification, fetch state fieldがないことを確認して完了する.
    """
    body = _response_body(
        format_getscores_header_response(
            status=2,
            beatmap=_make_beatmap(),
            beatmapset=_make_beatmapset(),
        )
    )
    text = body.decode("utf-8")
    forbidden = ("_source:", "_verified:", "_policy:", "_fetch_state:", "_override:")
    for field in forbidden:
        assert field not in text, f"Header body contains provenance field: {field!r}"


def test_short_body_has_no_provenance_fields() -> None:
    """Short bodyがinternal provenance fieldを露出しないcontractを検証する.

    Returns:
        None: unavailableとupdate bodyにforbidden fieldがないことを確認して完了する.
    """
    for body in (
        _response_body(format_getscores_unavailable_response()),
        _response_body(format_getscores_update_available_response()),
    ):
        text = body.decode("utf-8")
        forbidden = ("_source:", "_verified:", "_policy:", "_fetch_state:", "_override:")
        for field in forbidden:
            assert field not in text, f"Short body contains provenance field: {field!r}"


# ---------------------------------------------------------------------------
# Chunk framing absence (requirement 11.9)
# ---------------------------------------------------------------------------


def test_formatter_output_is_plain_text_no_chunk_framing() -> None:
    """Formatter outputがHTTP chunk framingなしのplain textとなるcontractを検証する.

    Returns:
        None: short bodyとheader bodyにchunk markerがないことを確認して完了する.
    """
    bodies = [
        _response_body(format_getscores_unavailable_response()),
        _response_body(format_getscores_update_available_response()),
        _response_body(
            format_getscores_header_response(
                status=2,
                beatmap=_make_beatmap(),
                beatmapset=_make_beatmapset(),
            )
        ),
    ]
    for body in bodies:
        assert not body.startswith(b"0\r\n")
        assert not body.startswith(b"1a")
        assert b"\r\n0\r\n\r\n" not in body


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_module_formatter_helpers_have_expected_interface() -> None:
    """Getscores formatter moduleがrequired helper interfaceを公開するcontractを検証する.

    Returns:
        None: 3つのformatter helperがcallableであることを確認して完了する.
    """
    assert callable(format_getscores_unavailable_response)
    assert callable(format_getscores_update_available_response)
    assert callable(format_getscores_header_response)
