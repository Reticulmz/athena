"""Unit tests for stable score payload mapper."""

import pytest

from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.payload_parser import ParsedScore, ParseError
from osu_server.transports.stable.web_legacy.mappers import StableScorePayloadParser


def _parse(payload: str) -> ParsedScore:
    return StableScorePayloadParser().parse(payload)


def test_parse_valid_payload() -> None:
    """Valid colon-separated payloadを正しくparseする。"""
    # Format: user_id:username:beatmap_checksum:online_checksum:ruleset:mods
    #         :n300:n100:n50:geki:katu:miss:score:max_combo:perfect:passed
    payload = "100:testuser:abc123:xyz789:0:0:300:50:10:0:0:5:500000:350:0:1"

    result = _parse(payload)

    assert isinstance(result, ParsedScore)
    assert result.user_id == 100
    assert result.username == "testuser"
    assert result.beatmap_checksum == "abc123"
    assert result.online_checksum == "xyz789"
    assert result.ruleset == 0
    assert result.mods == ModCombination.none()
    assert result.n300 == 300
    assert result.n100 == 50
    assert result.n50 == 10
    assert result.geki == 0
    assert result.katu == 0
    assert result.miss == 5
    assert result.score == 500000
    assert result.max_combo == 350
    assert result.perfect is False
    assert result.passed is True


def test_parse_stable_client_payload() -> None:
    """Stable client 19-field payload を正しくparseする。"""
    payload = (
        "8119fb28af74b9445f4a685f8b09eec2:PlayerOne:"
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb:552:2:1:1066:53:4:"
        "943904:1264:False:S:0:True:3:260610132044:20260412:50695543"
    )

    result = _parse(payload)

    assert result.user_id == 0
    assert result.username == "PlayerOne"
    assert result.beatmap_checksum == "8119fb28af74b9445f4a685f8b09eec2"
    assert result.online_checksum == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    assert result.ruleset == 3
    assert result.mods == ModCombination.none()
    assert result.n300 == 552
    assert result.n100 == 2
    assert result.n50 == 1
    assert result.geki == 1066
    assert result.katu == 53
    assert result.miss == 4
    assert result.score == 943904
    assert result.max_combo == 1264
    assert result.perfect is False
    assert result.passed is True
    assert result.client_grade == "S"
    assert result.client_submitted_at == "260610132044"
    assert result.client_version == "20260412"
    assert result.client_checksum == "50695543"


def test_parse_with_perfect_flag() -> None:
    """Perfect flag (1) を正しくparseする。"""
    payload = "100:user:abc:xyz:0:0:300:0:0:0:0:0:500000:300:1:1"

    result = _parse(payload)

    assert result.perfect is True


def test_parse_failed_score() -> None:
    """Failed score (passed=0) を正しくparseする。"""
    payload = "100:user:abc:xyz:0:0:100:50:30:0:0:20:200000:150:0:0"

    result = _parse(payload)

    assert result.passed is False


def test_parse_with_mods() -> None:
    """Mods値を正しくparseする。"""
    payload = "100:user:abc:xyz:0:72:300:0:0:0:0:0:500000:300:0:1"

    result = _parse(payload)

    assert result.mods == ModCombination.from_bitmask(72)  # HD+DT


def test_parse_different_rulesets() -> None:
    """各rulesetを正しくparseする。"""
    for ruleset_id in [0, 1, 2, 3]:
        payload = f"100:user:abc:xyz:{ruleset_id}:0:100:50:10:0:0:5:300000:200:0:1"

        result = _parse(payload)

        assert result.ruleset == ruleset_id


def test_parse_invalid_field_count() -> None:
    """フィールド数が不正な場合ParseErrorを発生させる。"""
    payload = "100:user:abc:xyz:0:0"  # Too few fields

    with pytest.raises(ParseError) as exc_info:
        _ = _parse(payload)

    assert "fields" in str(exc_info.value).lower()


def test_parse_invalid_integer() -> None:
    """整数フィールドが不正な場合ParseErrorを発生させる。"""
    payload = "invalid:user:abc:xyz:0:0:300:50:10:0:0:5:500000:350:0:1"

    with pytest.raises(ParseError) as exc_info:
        _ = _parse(payload)

    assert "user_id" in str(exc_info.value).lower() or "integer" in str(exc_info.value).lower()


def test_parse_empty_payload() -> None:
    """Empty payloadでParseErrorを発生させる。"""
    with pytest.raises(ParseError):
        _ = _parse("")


def test_parse_username_with_special_characters() -> None:
    """特殊文字を含むusernameを正しくparseする。"""
    payload = "100:test_user-123:abc:xyz:0:0:300:50:10:0:0:5:500000:350:0:1"

    result = _parse(payload)

    assert result.username == "test_user-123"
