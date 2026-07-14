"""Getscores response formatter unit tests.

TDD RED -> GREEN -> REFACTOR.
Validates response body formatting: short bodies, header bodies,
delimiter sanitization, and fixture compatibility.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from starlette.responses import Response

_NOW = datetime(2026, 6, 7, tzinfo=UTC)
_NEXT_REFRESH = _NOW + timedelta(days=30)
_CHECKSUM = "0123456789abcdef0123456789abcdef"


def _response_body(response: Response) -> bytes:
    return bytes(response.body)


def _make_beatmap(
    *,
    beatmap_id: int = 75,
    beatmapset_id: int = 1,
    official_status: BeatmapRankStatus = BeatmapRankStatus.RANKED,
) -> Beatmap:
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
    has_replay: bool = True,
    rank: int = 3,
) -> GetscoresPersonalBest:
    return GetscoresPersonalBest(
        score_id=score_id,
        user_id=user_id,
        username=username,
        beatmap_id=75,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        score=score,
        max_combo=1_234,
        n50=1,
        n100=2,
        n300=300,
        miss=3,
        katu=4,
        geki=5,
        perfect=True,
        mods=24,
        rank=rank,
        submitted_at=_NOW,
        has_replay=has_replay,
    )


def _expected_score_row(row: GetscoresPersonalBest) -> bytes:
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
    """Unavailable outcome formats as '-1|false'."""
    body = _response_body(format_getscores_unavailable_response())
    assert body == b"-1|false"


def test_format_update_available_returns_short_body() -> None:
    """UpdateAvailable outcome formats as '1|false'."""
    body = _response_body(format_getscores_update_available_response())
    assert body == b"1|false"


# ---------------------------------------------------------------------------
# Header body — first line (requirements 8.4, 11.2)
# ---------------------------------------------------------------------------


def test_header_first_line_format() -> None:
    """First line: <status>|false|<beatmap_id>|<beatmapset_id>|0||"""
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
    """Score count is 0 when there are no returned rows."""
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


def test_header_failed_flag_is_false() -> None:
    """Failed flag must be 'false' (requirement 8.6)."""
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
    """Header body has exactly 6 lines (4 data + 2 blank sections, ending with newline)."""
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
    body = _response_body(
        format_getscores_header_response(
            status=2,
            beatmap=_make_beatmap(),
            beatmapset=_make_beatmapset(),
        )
    )

    assert body.split(b"\n")[4:] == [b"", b"", b""]


def test_header_second_line_is_beatmap_offset() -> None:
    """Second line is the beatmap offset (integer, '0' in MVP) (requirement 11.3)."""
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
    """Third line is [bold:0,size:20]artist|title (requirement 11.4)."""
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
    """Fourth line is the rating (0 in MVP) (requirement 11.5)."""
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
    """Header body terminates with a newline."""
    body = _response_body(
        format_getscores_header_response(
            status=2,
            beatmap=_make_beatmap(),
            beatmapset=_make_beatmapset(),
        )
    )
    assert body.endswith(b"\n")


def test_header_personal_best_row_uses_stable_score_listing_format() -> None:
    """Personal best row follows Bancho score row field order."""
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
    """Pipe in artist is replaced to avoid breaking delimited format (requirement 11.7)."""
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
    """Pipe in title is replaced (requirement 11.7)."""
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
    """Line breaks in artist are replaced (requirement 11.8)."""
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
    """Line breaks in title are replaced (requirement 11.8)."""
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
    """Header body must not expose internal provenance fields (requirement 12.5)."""
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
    """Short bodies must not expose provenance fields."""
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
    """All formatter output must be plain text without chunk framing (requirement 11.9)."""
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
    assert callable(format_getscores_unavailable_response)
    assert callable(format_getscores_update_available_response)
    assert callable(format_getscores_header_response)
