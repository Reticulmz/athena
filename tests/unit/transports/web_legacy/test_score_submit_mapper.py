"""Stable legacy score submit mapper tests."""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from athena_cli.stable_verification.parsers import parse_score_submit_response
from osu_server.domain.scores.decryption import DecryptedPayload
from osu_server.domain.scores.payload_parser import ParseError
from osu_server.domain.scores.personal_best import PersonalBestDelta
from osu_server.domain.scores.user_stats import UserCurrentStats
from osu_server.services.commands.scores import (
    BeatmapRankDelta,
    SubmissionOutcome,
    SubmissionResult,
)
from osu_server.transports.stable.web_legacy.mappers import (
    StableScorePayloadParser,
    StableScoreSubmitDecodeError,
    StableScoreSubmitDecoder,
    StableScoreSubmitMapper,
    StableScoreSubmitOverallStats,
)
from tests.support.fakes import StubScorePayloadDecryptor

_BEATMAP_CHART_REQUIRED_FIELDS = (
    "achieved",
    "rankBefore",
    "rankedScoreBefore",
    "rankedScoreAfter",
    "maxComboAfter",
    "accuracyAfter",
    "ppAfter",
    "onlineScoreId",
)
_OVERALL_CHART_REQUIRED_FIELDS = (
    "rankBefore",
    "rankedScoreBefore",
    "rankedScoreAfter",
    "totalScoreBefore",
    "totalScoreAfter",
    "maxComboAfter",
    "accuracyAfter",
    "ppAfter",
    "achievements-new",
    "onlineScoreId",
)


def _valid_multipart_body() -> bytes:
    encrypted_payload = base64.b64encode(b"encrypted_payload_data")
    iv = base64.b64encode(b"0" * 32)

    return b"".join(
        (
            b"------WebKitFormBoundary\r\n",
            b'Content-Disposition: form-data; name="score"\r\n\r\n',
            encrypted_payload,
            b"\r\n",
            b"------WebKitFormBoundary\r\n",
            b'Content-Disposition: form-data; name="iv"\r\n\r\n',
            iv,
            b"\r\n",
            b"------WebKitFormBoundary\r\n",
            b'Content-Disposition: form-data; name="pass"\r\n\r\n',
            b"password_md5_hash\r\n",
            b"------WebKitFormBoundary\r\n",
            b'Content-Disposition: form-data; name="x"\r\n\r\n',
            b"client_hash\r\n",
            b"------WebKitFormBoundary\r\n",
            b'Content-Disposition: form-data; name="ft"\r\n\r\n',
            b"0\r\n",
            b"------WebKitFormBoundary\r\n",
            b'Content-Disposition: form-data; name="osuver"\r\n\r\n',
            b"20241201\r\n",
            b"------WebKitFormBoundary\r\n",
            b'Content-Disposition: form-data; name="token"\r\n\r\n',
            b"session_token\r\n",
            b"------WebKitFormBoundary\r\n",
            b'Content-Disposition: form-data; name="score"\r\n\r\n',
            b"replay_binary_data\r\n",
            b"------WebKitFormBoundary--\r\n",
        )
    )


def _score_submit_decoder(
    payload: str = "1000:test_user:abc123:online_checksum:0:0:100:10:5:0:0:2:500000:99:1:1",
    *,
    checksum_valid: bool = True,
) -> StableScoreSubmitDecoder:
    return StableScoreSubmitDecoder(
        payload_decryptor=StubScorePayloadDecryptor(
            DecryptedPayload(plaintext=payload, checksum_valid=checksum_valid)
        ),
        payload_parser=StableScorePayloadParser(),
    )


def test_score_submit_mapper_converts_multipart_to_request_mapping() -> None:
    mapper = StableScoreSubmitMapper()
    submitted_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

    request_mapping = mapper.to_request_mapping(
        body=_valid_multipart_body(),
        content_type="multipart/form-data; boundary=----WebKitFormBoundary",
        submitted_at=submitted_at,
    )

    assert request_mapping.encrypted_payload == b"encrypted_payload_data"
    assert request_mapping.iv == b"0" * 32
    assert request_mapping.password_md5 == "password_md5_hash"
    assert request_mapping.client_hash == "client_hash"
    assert request_mapping.fail_time_ms == 0
    assert request_mapping.osu_version == "20241201"
    assert request_mapping.submitted_at == submitted_at
    assert request_mapping.submission_metadata == {"token": "session_token"}


def test_score_submit_decoder_converts_request_mapping_to_command_input() -> None:
    mapper = StableScoreSubmitMapper()
    submitted_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    request_mapping = mapper.to_request_mapping(
        body=_valid_multipart_body(),
        content_type="multipart/form-data; boundary=----WebKitFormBoundary",
        submitted_at=submitted_at,
    )

    command_input = _score_submit_decoder().to_command_input(request_mapping)

    assert command_input.parsed_score.username == "test_user"
    assert command_input.parsed_score.online_checksum == "online_checksum"
    assert command_input.request_hash
    assert command_input.opaque_field_hashes == {
        "token_sha256": hashlib.sha256(b"session_token").hexdigest()
    }
    assert command_input.replay_data == b"replay_binary_data"
    assert command_input.password_md5 == "password_md5_hash"
    assert command_input.fail_time_ms == 0
    assert command_input.osu_version == "20241201"
    assert command_input.submitted_at == submitted_at


def test_score_submit_decoder_rejects_invalid_crypto_checksum() -> None:
    mapper = StableScoreSubmitMapper()
    request_mapping = mapper.to_request_mapping(
        body=_valid_multipart_body(),
        content_type="multipart/form-data; boundary=----WebKitFormBoundary",
        submitted_at=datetime.now(UTC),
    )

    with pytest.raises(StableScoreSubmitDecodeError) as exc_info:
        _ = _score_submit_decoder(checksum_valid=False).to_command_input(request_mapping)

    assert exc_info.value.reason == "crypto_checksum_invalid"
    assert exc_info.value.result.error_reason == "crypto_checksum_invalid"


def test_score_submit_decoder_rejects_unparseable_payload() -> None:
    mapper = StableScoreSubmitMapper()
    request_mapping = mapper.to_request_mapping(
        body=_valid_multipart_body(),
        content_type="multipart/form-data; boundary=----WebKitFormBoundary",
        submitted_at=datetime.now(UTC),
    )

    with pytest.raises(StableScoreSubmitDecodeError) as exc_info:
        _ = _score_submit_decoder(payload="not:enough:fields").to_command_input(request_mapping)

    assert exc_info.value.reason == "parse_failed"
    assert exc_info.value.error is not None
    assert ParseError.__name__ not in exc_info.value.error


def test_score_submit_mapper_formats_completed_response() -> None:
    mapper = StableScoreSubmitMapper(stable_web_base_url="https://osu.athena.localhost")

    response = mapper.to_response(
        SubmissionResult(
            outcome=SubmissionOutcome.COMPLETED,
            user_id=1001,
            score_id=12345,
            beatmap_id=654,
            beatmapset_id=321,
            score=7654321,
            max_combo=987,
            accuracy=0.956789,
            passed=True,
            beatmap_playcount=4,
            beatmap_passcount=3,
            beatmap_approved_at=datetime(2026, 6, 29, 12, 34, 56, tzinfo=UTC),
            stable_pp=248,
        ),
        overall_stats=StableScoreSubmitOverallStats(
            rank=12,
            ranked_score=123_456_789,
            total_score=9_876_543_210,
            accuracy=0.987654,
            stable_pp=321,
        ),
    )

    assert response.status_code == 200
    body = bytes(response.body)
    parsed = parse_score_submit_response(body)
    lines = body.splitlines()
    assert lines[0] == (
        b"beatmapId:654|beatmapSetId:321|beatmapPlaycount:4|beatmapPasscount:3|"
        b"approvedDate:2026-06-29 12:34:56"
    )
    assert lines[1].startswith(
        b"chartId:beatmap|chartUrl:https://osu.athena.localhost/b/654|chartName:Beatmap Ranking|"
    )
    assert b"rankedScoreAfter:7654321" in lines[1]
    assert b"maxComboAfter:987" in lines[1]
    assert b"accuracyAfter:95.6789" in lines[1]
    assert b"ppAfter:248" in lines[1]
    assert b"onlineScoreId:12345" in lines[1]
    assert lines[2].startswith(
        b"chartId:overall|chartUrl:https://osu.athena.localhost/u/1001|chartName:Overall Ranking|"
    )
    assert b"achievements-new:" in lines[2]
    assert b"password_md5_hash" not in body
    assert b"session_token" not in body
    assert b"replay_binary_data" not in body
    assert parsed.response is not None
    assert parsed.response.beatmap_chart.fields["achieved"] == "true"
    assert parsed.response.overall_chart.fields["rankAfter"] == "12"
    assert parsed.response.overall_chart.fields["rankedScoreAfter"] == "123456789"
    assert parsed.response.overall_chart.fields["totalScoreAfter"] == "9876543210"
    assert parsed.response.overall_chart.fields["accuracyAfter"] == "98.7654"
    assert parsed.response.overall_chart.fields["ppAfter"] == "321"
    for field in _BEATMAP_CHART_REQUIRED_FIELDS:
        assert field in parsed.response.beatmap_chart.fields
    for field in _OVERALL_CHART_REQUIRED_FIELDS:
        assert field in parsed.response.overall_chart.fields


def test_score_submit_mapper_formats_overall_stats_delta() -> None:
    mapper = StableScoreSubmitMapper()

    response = mapper.to_response(
        SubmissionResult(
            outcome=SubmissionOutcome.COMPLETED,
            user_id=1000,
            score_id=12345,
            beatmap_id=654,
            beatmapset_id=321,
            score=500000,
            max_combo=987,
            accuracy=0.9876,
            passed=True,
            overall_stats_before=UserCurrentStats(
                user_id=1000,
                pp=Decimal("122.4"),
                accuracy=0.9567,
                global_rank=2,
                play_count=7,
                ranked_score=400_000,
                total_score=900_000,
                max_combo=876,
            ),
            overall_stats_after=UserCurrentStats(
                user_id=1000,
                pp=Decimal("248.5"),
                accuracy=0.9876,
                global_rank=1,
                play_count=8,
                ranked_score=500_000,
                total_score=1_400_000,
                max_combo=987,
            ),
        )
    )

    parsed = parse_score_submit_response(bytes(response.body))

    assert parsed.response is not None
    overall_chart = parsed.response.overall_chart.fields
    assert overall_chart["rankBefore"] == "2"
    assert overall_chart["rankAfter"] == "1"
    assert overall_chart["rankedScoreBefore"] == "400000"
    assert overall_chart["rankedScoreAfter"] == "500000"
    assert overall_chart["totalScoreBefore"] == "900000"
    assert overall_chart["totalScoreAfter"] == "1400000"
    assert overall_chart["maxComboBefore"] == "876"
    assert overall_chart["maxComboAfter"] == "987"
    assert overall_chart["accuracyBefore"] == "95.67"
    assert overall_chart["accuracyAfter"] == "98.76"
    assert overall_chart["ppBefore"] == "122"
    assert overall_chart["ppAfter"] == "249"


def test_score_submit_mapper_formats_personal_best_delta_values() -> None:
    mapper = StableScoreSubmitMapper()

    response = mapper.to_response(
        SubmissionResult(
            outcome=SubmissionOutcome.COMPLETED,
            score_id=12346,
            beatmap_id=654,
            beatmapset_id=321,
            score=1000000,
            max_combo=500,
            accuracy=0.9,
            passed=True,
            stable_pp=111,
            stable_pp_before=222,
            stable_pp_after=222,
            personal_best_delta=PersonalBestDelta(
                before_score_id=10,
                before_score=2000000,
                before_max_combo=700,
                before_accuracy=0.98,
                after_score_id=10,
                after_score=2000000,
                after_max_combo=700,
                after_accuracy=0.98,
                updated=False,
            ),
        )
    )

    parsed = parse_score_submit_response(bytes(response.body))

    assert parsed.response is not None
    beatmap_chart = parsed.response.beatmap_chart.fields
    assert beatmap_chart["rankedScoreBefore"] == "2000000"
    assert beatmap_chart["rankedScoreAfter"] == "2000000"
    assert beatmap_chart["maxComboBefore"] == "700"
    assert beatmap_chart["maxComboAfter"] == "700"
    assert beatmap_chart["accuracyBefore"] == "98"
    assert beatmap_chart["accuracyAfter"] == "98"
    assert beatmap_chart["ppBefore"] == "222"
    assert beatmap_chart["ppAfter"] == "222"
    assert beatmap_chart["onlineScoreId"] == "12346"


def test_score_submit_mapper_formats_beatmap_rank_delta() -> None:
    mapper = StableScoreSubmitMapper()

    response = mapper.to_response(
        SubmissionResult(
            outcome=SubmissionOutcome.COMPLETED,
            score_id=12347,
            beatmap_id=654,
            beatmapset_id=321,
            score=3000000,
            max_combo=800,
            accuracy=0.99,
            passed=True,
            stable_pp=333,
            beatmap_rank_delta=BeatmapRankDelta(before=4, after=2),
        )
    )

    parsed = parse_score_submit_response(bytes(response.body))

    assert parsed.response is not None
    beatmap_chart = parsed.response.beatmap_chart.fields
    assert beatmap_chart["rankBefore"] == "4"
    assert beatmap_chart["rankAfter"] == "2"


def test_score_submit_mapper_formats_failed_score_passcount_as_zero() -> None:
    mapper = StableScoreSubmitMapper()

    response = mapper.to_response(
        SubmissionResult(
            outcome=SubmissionOutcome.COMPLETED,
            score_id=12345,
            beatmap_id=654,
            beatmapset_id=321,
            score=123456,
            max_combo=42,
            accuracy=0.5,
            passed=False,
            stable_pp=None,
        )
    )

    assert response.status_code == 200
    body = bytes(response.body)
    parsed = parse_score_submit_response(body)
    lines = body.splitlines()
    assert lines[0] == (
        b"beatmapId:654|beatmapSetId:321|beatmapPlaycount:1|beatmapPasscount:0|approvedDate:"
    )
    assert parsed.response is not None
    assert parsed.response.beatmap_metadata.beatmap_passcount == 0
    assert parsed.response.beatmap_chart.fields["achieved"] == "false"


def test_score_submit_mapper_formats_completed_response_without_pp_as_zero() -> None:
    mapper = StableScoreSubmitMapper()

    response = mapper.to_response(
        SubmissionResult(
            outcome=SubmissionOutcome.COMPLETED,
            score_id=12345,
            beatmap_id=654,
            beatmapset_id=321,
            stable_pp=None,
            error_reason="performance_unavailable: calculator stack trace",
        )
    )

    assert response.status_code == 200
    body = bytes(response.body)
    assert b"ppAfter:0" in body
    assert b"performance_unavailable" not in body
    assert b"calculator" not in body
    assert b"stack trace" not in body


def test_score_submit_mapper_formats_rejection_and_retry_responses() -> None:
    mapper = StableScoreSubmitMapper()

    retryable = mapper.to_response(
        SubmissionResult(outcome=SubmissionOutcome.RETRYABLE, error_reason="temporary")
    )
    terminal = mapper.to_response(
        SubmissionResult(
            outcome=SubmissionOutcome.TERMINAL_REJECTED,
            error_reason="rejected",
        )
    )

    assert retryable.body == b"error: yes"
    assert terminal.body == b"error: no"
    assert b"temporary" not in retryable.body
    assert b"rejected" not in terminal.body
