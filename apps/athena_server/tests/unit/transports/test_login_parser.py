"""Stable login requestとclient info parserのunit testを提供する."""

from __future__ import annotations

import pytest

from osu_server.domain.identity.authentication import ClientInfo, LoginRequest
from osu_server.transports.stable.bancho.parsers.login import (
    parse_client_info,
    parse_login_request,
)


class TestParseLoginRequest:
    """Raw login bodyをLoginRequestへparseするcontractを検証する."""

    def test_valid_body(self) -> None:
        """正常な3行login bodyがLoginRequestへparseされる契約を検証する.

        Returns:
            None: username, password MD5, client infoの型を確認して完了する.
        """
        body = (
            b"TestUser\n"
            b"d41d8cd98f00b204e9800998ecf8427e\n"
            b"b20240101.1|9|1|abc123:def456:ghi789:jkl012:mno345|0\n"
        )
        result = parse_login_request(body)

        assert isinstance(result, LoginRequest)
        assert result.username == "TestUser"
        assert result.password_md5 == "d41d8cd98f00b204e9800998ecf8427e"
        assert isinstance(result.client_info, ClientInfo)

    def test_client_info_fields_parsed(self) -> None:
        """Login body内のclient info fieldが正しい型と値へparseされる契約を検証する.

        Returns:
            None: version, offset, flag, hashの各fieldを確認して完了する.
        """
        body = b"Player\nhashvalue\nb20240101.1|9|1|hashes|0\n"
        result = parse_login_request(body)

        assert result.client_info.osu_version == "b20240101.1"
        assert result.client_info.utc_offset == 9
        assert result.client_info.display_city is True
        assert result.client_info.client_hashes == "hashes"
        assert result.client_info.pm_private is False

    def test_crlf_line_endings(self) -> None:
        """CRLF区切りlogin bodyを受け入れるcontractを検証する.

        Returns:
            None: username, password MD5, client versionのparse結果を確認して完了する.
        """
        body = b"User\r\npasshash\r\nb20240101|0|0|h|1\r\n"
        result = parse_login_request(body)

        assert result.username == "User"
        assert result.password_md5 == "passhash"
        assert result.client_info.osu_version == "b20240101"

    def test_no_trailing_newline(self) -> None:
        """末尾newlineなしのlogin bodyを受け入れるcontractを検証する.

        Returns:
            None: usernameとpassword MD5が失われないことを確認して完了する.
        """
        body = b"User\npasshash\nb20240101|0|0|h|1"
        result = parse_login_request(body)

        assert result.username == "User"
        assert result.password_md5 == "passhash"

    def test_empty_body_raises_value_error(self) -> None:
        """空のlogin bodyをValueErrorで拒否するcontractを検証する.

        Returns:
            None: error messageを含むValueErrorを確認して完了する.
        """
        with pytest.raises(ValueError, match="login request body"):
            _ = parse_login_request(b"")

    def test_one_line_raises_value_error(self) -> None:
        """1行だけのlogin bodyをValueErrorで拒否するcontractを検証する.

        Returns:
            None: 不完全request formatのValueErrorを確認して完了する.
        """
        with pytest.raises(ValueError, match="login request body"):
            _ = parse_login_request(b"username_only\n")

    def test_two_lines_raises_value_error(self) -> None:
        """Client infoを欠く2行login bodyをValueErrorで拒否するcontractを検証する.

        Returns:
            None: 不完全request formatのValueErrorを確認して完了する.
        """
        with pytest.raises(ValueError, match="login request body"):
            _ = parse_login_request(b"user\npasshash\n")

    def test_whitespace_only_body_raises_value_error(self) -> None:
        """Whitespaceだけのlogin bodyをValueErrorで拒否するcontractを検証する.

        Returns:
            None: 空と同等のrequest format errorを確認して完了する.
        """
        with pytest.raises(ValueError, match="login request body"):
            _ = parse_login_request(b"  \n  \n")

    def test_username_preserved_as_is(self) -> None:
        """Parserがusernameを正規化せずdomain layerへ渡すcontractを検証する.

        Returns:
            None: 空白を含むusernameがそのまま保存されることを確認して完了する.
        """
        body = b"My User Name\nhash\nb20240101|0|0|h|0\n"
        result = parse_login_request(body)
        assert result.username == "My User Name"


class TestParseClientInfo:
    """Pipe-delimited client infoをClientInfoへparseするcontractを検証する."""

    def test_valid_client_info(self) -> None:
        """正常なclient infoがClientInfoへparseされるcontractを検証する.

        Returns:
            None: 全fieldの値と型を確認して完了する.
        """
        raw = "b20240101.1|9|1|abc123:def456:ghi789:jkl012:mno345|0"
        result = parse_client_info(raw)

        assert isinstance(result, ClientInfo)
        assert result.osu_version == "b20240101.1"
        assert result.utc_offset == 9
        assert result.display_city is True
        assert result.client_hashes == "abc123:def456:ghi789:jkl012:mno345"
        assert result.pm_private is False

    def test_negative_utc_offset(self) -> None:
        """負のUTC offsetをintとしてparseするcontractを検証する.

        Returns:
            None: UTC-5が負のintegerとして保持されることを確認して完了する.
        """
        raw = "b20240101|-5|0|hashes|0"
        result = parse_client_info(raw)
        assert result.utc_offset == -5

    def test_zero_utc_offset(self) -> None:
        """Zero UTC offsetをparseするcontractを検証する.

        Returns:
            None: UTC offsetが0となることを確認して完了する.
        """
        raw = "b20240101|0|0|hashes|0"
        result = parse_client_info(raw)
        assert result.utc_offset == 0

    def test_large_positive_utc_offset(self) -> None:
        """最大の正UTC offsetをparseするcontractを検証する.

        Returns:
            None: UTC+14がintegerとして保持されることを確認して完了する.
        """
        raw = "b20240101|14|0|hashes|0"
        result = parse_client_info(raw)
        assert result.utc_offset == 14

    def test_large_negative_utc_offset(self) -> None:
        """最小の負UTC offsetをparseするcontractを検証する.

        Returns:
            None: UTC-12がintegerとして保持されることを確認して完了する.
        """
        raw = "b20240101|-12|0|hashes|0"
        result = parse_client_info(raw)
        assert result.utc_offset == -12

    def test_parse_valid_client_info(self) -> None:
        """標準client infoのdisplay city flagをparseするcontractを検証する.

        Returns:
            None: UTC+9 inputのdisplay cityがTrueとなることを確認して完了する.
        """
        raw = "b20240101|9|1|hashes|0"
        result = parse_client_info(raw)
        assert result.display_city is True

    def test_display_city_false(self) -> None:
        """Display city flagの0をFalseへparseするcontractを検証する.

        Returns:
            None: display cityがFalseとなることを確認して完了する.
        """
        raw = "b20240101|0|0|hashes|0"
        result = parse_client_info(raw)
        assert result.display_city is False

    def test_pm_private_true(self) -> None:
        """Private message flagの1をTrueへparseするcontractを検証する.

        Returns:
            None: pm_privateがTrueとなることを確認して完了する.
        """
        raw = "b20240101|0|0|hashes|1"
        result = parse_client_info(raw)
        assert result.pm_private is True

    def test_pm_private_false(self) -> None:
        """Private message flagの0をFalseへparseするcontractを検証する.

        Returns:
            None: pm_privateがFalseとなることを確認して完了する.
        """
        raw = "b20240101|0|0|hashes|0"
        result = parse_client_info(raw)
        assert result.pm_private is False

    def test_insufficient_fields_raises_value_error(self) -> None:
        """必要field数未満のclient infoをValueErrorで拒否するcontractを検証する.

        Returns:
            None: client_info format errorを確認して完了する.
        """
        with pytest.raises(ValueError, match="client_info"):
            _ = parse_client_info("b20240101|9|1")

    def test_empty_string_raises_value_error(self) -> None:
        """空のclient infoをValueErrorで拒否するcontractを検証する.

        Returns:
            None: client_info format errorを確認して完了する.
        """
        with pytest.raises(ValueError, match="client_info"):
            _ = parse_client_info("")

    def test_four_fields_raises_value_error(self) -> None:
        """5 field未満のclient infoをValueErrorで拒否するcontractを検証する.

        Returns:
            None: client_info format errorを確認して完了する.
        """
        with pytest.raises(ValueError, match="client_info"):
            _ = parse_client_info("b20240101|9|1|hashes")

    def test_non_integer_utc_offset_raises_value_error(self) -> None:
        """整数でないUTC offsetをValueErrorで拒否するcontractを検証する.

        Returns:
            None: utc_offset conversion errorを確認して完了する.
        """
        with pytest.raises(ValueError, match="utc_offset"):
            _ = parse_client_info("b20240101|abc|1|hashes|0")

    def test_non_boolean_display_city_raises_value_error(self) -> None:
        """Booleanでないdisplay city fieldをValueErrorで拒否するcontractを検証する.

        Returns:
            None: display_city conversion errorを確認して完了する.
        """
        with pytest.raises(ValueError, match="display_city"):
            _ = parse_client_info("b20240101|0|yes|hashes|0")

    def test_non_boolean_pm_private_raises_value_error(self) -> None:
        """Booleanでないprivate message fieldをValueErrorで拒否するcontractを検証する.

        Returns:
            None: pm_private conversion errorを確認して完了する.
        """
        with pytest.raises(ValueError, match="pm_private"):
            _ = parse_client_info("b20240101|0|0|hashes|yes")

    def test_client_hashes_with_colons_preserved(self) -> None:
        """Colon区切りclient hashを変更せず保持するcontractを検証する.

        Returns:
            None: hash stringのdelimiterと順序が保たれることを確認して完了する.
        """
        raw = "b20240101|0|0|a:b:c:d:e|0"
        result = parse_client_info(raw)
        assert result.client_hashes == "a:b:c:d:e"

    def test_extra_fields_ignored(self) -> None:
        """Extra pipe-delimited fieldを無視して既知fieldをparseするcontractを検証する.

        Returns:
            None: versionとpm_privateが既知fieldから得られることを確認して完了する.
        """
        raw = "b20240101|0|0|hashes|0|extra_field|another"
        result = parse_client_info(raw)
        assert result.osu_version == "b20240101"
        assert result.pm_private is False
