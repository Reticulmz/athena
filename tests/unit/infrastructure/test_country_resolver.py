"""CountryResolver と国コード変換のテスト。"""

from __future__ import annotations

from typing import ClassVar
from unittest.mock import MagicMock

from osu_server.infrastructure.country.cloudflare import CloudflareCountryResolver
from osu_server.infrastructure.country.codes import country_code_to_id
from osu_server.infrastructure.country.interfaces import CountryResolver


class TestCloudflareCountryResolver:
    """CloudflareCountryResolver のテスト。"""

    def test_returns_country_code_from_cf_header(self) -> None:
        """CF-IPCountry ヘッダが存在する場合、その値を返す。"""
        request = MagicMock(headers={"CF-IPCountry": "JP"})
        resolver = CloudflareCountryResolver()

        result = resolver.resolve(request)

        assert result == "JP"

    def test_returns_xx_when_header_missing(self) -> None:
        """CF-IPCountry ヘッダが存在しない場合、"XX" を返す。"""
        request = MagicMock(headers={})
        resolver = CloudflareCountryResolver()

        result = resolver.resolve(request)

        assert result == "XX"

    def test_returns_various_country_codes(self) -> None:
        """様々な国コードを正しく返す。"""
        for code in ("US", "KR", "GB", "FR", "DE"):
            request = MagicMock(headers={"CF-IPCountry": code})
            resolver = CloudflareCountryResolver()

            result = resolver.resolve(request)

            assert result == code

    def test_satisfies_protocol(self) -> None:
        """CloudflareCountryResolver は CountryResolver Protocol を満たす。"""
        resolver = CloudflareCountryResolver()

        assert isinstance(resolver, CountryResolver)


class TestCountryCodeToId:
    """country_code_to_id 変換のテスト。"""

    # 数値は ppy/osu CountryCode.cs の公式定義に準拠
    _EXPECTED: ClassVar[dict[str, int]] = {
        "JP": 120,
        "US": 239,
        "KR": 128,
        "GB": 83,
        "FR": 80,
        "DE": 61,
    }

    def test_known_codes(self) -> None:
        """既知の国コードは正しい数値 ID を返す。"""
        for code, expected_id in self._EXPECTED.items():
            assert country_code_to_id(code) == expected_id

    def test_unknown_code_returns_zero(self) -> None:
        """不明な国コードは 0 を返す。"""
        assert country_code_to_id("XX") == 0
        assert country_code_to_id("ZZ") == 0
        assert country_code_to_id("??") == 0

    def test_empty_string_returns_zero(self) -> None:
        """空文字列は 0 を返す。"""
        assert country_code_to_id("") == 0

    def test_case_sensitive(self) -> None:
        """国コード変換は大文字のみ受け付ける (小文字は不明扱い)。"""
        assert country_code_to_id("jp") == 0
        assert country_code_to_id("us") == 0
