from __future__ import annotations

from pathlib import Path

from athena_cli.stable_verification.parsers import (
    GetscoresResponseKind,
    parse_getscores_response,
    parse_score_submit_response,
)

GETSCORES_FIXTURE_DIR = (
    Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "web_legacy" / "getscores"
)


def test_parse_score_submit_completed_response_sections() -> None:
    body = b"\n".join(
        (
            b"beatmapId:654|beatmapSetId:321|beatmapPlaycount:1|beatmapPasscount:1|approvedDate:",
            (
                b"chartId:beatmap|chartUrl:|chartName:Beatmap Ranking|achieved:true|"
                b"rankBefore:|rankAfter:0|maxComboBefore:0|maxComboAfter:987|"
                b"accuracyBefore:0|accuracyAfter:95.6789|rankedScoreBefore:0|"
                b"rankedScoreAfter:7654321|ppBefore:0|ppAfter:248|onlineScoreId:12345"
            ),
            (
                b"chartId:overall|chartUrl:|chartName:Overall Ranking|rankBefore:0|"
                b"rankAfter:0|rankedScoreBefore:0|rankedScoreAfter:0|totalScoreBefore:0|"
                b"totalScoreAfter:0|maxComboBefore:0|maxComboAfter:0|accuracyBefore:0|"
                b"accuracyAfter:0|ppBefore:0|ppAfter:0|achievements-new:|onlineScoreId:12345"
            ),
        )
    )

    result = parse_score_submit_response(body)

    assert result.error is None
    assert result.response is not None
    assert result.response.beatmap_metadata.beatmap_id == 654
    assert result.response.beatmap_metadata.beatmapset_id == 321
    assert result.response.beatmap_metadata.beatmap_playcount == 1
    assert result.response.beatmap_metadata.beatmap_passcount == 1
    assert result.response.beatmap_chart.chart_id == "beatmap"
    assert result.response.beatmap_chart.fields["achieved"] == "true"
    assert result.response.beatmap_chart.fields["rankedScoreAfter"] == "7654321"
    assert result.response.beatmap_chart.fields["ppAfter"] == "248"
    assert result.response.beatmap_chart.fields["onlineScoreId"] == "12345"
    assert result.response.overall_chart.chart_id == "overall"
    assert result.response.achievement_notification == ""


def test_parse_score_submit_malformed_body_returns_parse_failure() -> None:
    result = parse_score_submit_response(b"chartId:beatmap|missing-delimiter")

    assert result.response is None
    assert result.error is not None


def test_parse_getscores_short_responses() -> None:
    not_submitted = parse_getscores_response(b"-1|false")
    update_available = parse_getscores_response(b"1|false")

    assert not_submitted.response is not None
    assert not_submitted.response.kind is GetscoresResponseKind.NOT_SUBMITTED
    assert update_available.response is not None
    assert update_available.response.kind is GetscoresResponseKind.UPDATE_AVAILABLE


def test_parse_getscores_header_fixture_as_empty_leaderboard() -> None:
    fixture_body = (GETSCORES_FIXTURE_DIR / "ranked_response.txt").read_bytes()

    result = parse_getscores_response(fixture_body)

    assert result.error is None
    assert result.response is not None
    assert result.response.kind is GetscoresResponseKind.HEADER
    assert result.response.header is not None
    assert result.response.header.status == 2
    assert result.response.header.failed is False
    assert result.response.header.beatmap_id == 75
    assert result.response.header.beatmapset_id == 1
    assert result.response.header.score_count == 0
    assert result.response.header.empty_leaderboard is True
    assert result.response.header.personal_best_row is None
    assert result.response.header.score_rows == ()
    assert result.response.header.display_line == "[bold:0,size:20]Suzaku|Anisakis -sakuya-"


def test_parse_getscores_header_separates_personal_best_from_score_rows() -> None:
    body = (
        b"2|false|75|1|0||\n"
        b"0\n"
        b"[bold:0,size:20]Artist|Title\n"
        b"0\n"
        b"42|Player|987654|1234|1|2|300|3|4|5|1|24|7|0|1780790400|1\n"
        b"\n"
    )

    result = parse_getscores_response(body)

    assert result.error is None
    assert result.response is not None
    assert result.response.header is not None
    assert result.response.header.personal_best_row is not None
    assert result.response.header.score_rows == ()
    assert result.response.header.empty_leaderboard is True


def test_parse_getscores_malformed_body_returns_parse_failure() -> None:
    result = parse_getscores_response(b"2|false|missing-int")

    assert result.response is None
    assert result.error is not None
