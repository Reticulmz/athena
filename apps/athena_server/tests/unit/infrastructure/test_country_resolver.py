"""Cloudflare country resolverとstable country code conversionの契約を検証するmodule."""

from __future__ import annotations

from typing import ClassVar

from osu_server.infrastructure.country.cloudflare import CloudflareCountryResolver
from osu_server.infrastructure.country.codes import country_code_to_id
from osu_server.infrastructure.country.interfaces import CountryResolver


class TestCloudflareCountryResolver:
    """Cloudflare headerから国コードを解決するCountryResolver契約を検証するtest群."""

    def test_returns_country_code_from_cf_header(self) -> None:
        """CF-IPCountry headerにJPを与えてresolveしたとき同じJPを返すことを確認する.

        Returns:
            None: 検証またはtest helperの処理を完了し値を返さない.
        """
        resolver = CloudflareCountryResolver()

        result = resolver.resolve({"CF-IPCountry": "JP"})

        assert result == "JP"

    def test_returns_xx_when_header_missing(self) -> None:
        """CF-IPCountry headerなしでresolveしたとき不明国codeのXXを返すことを確認する.

        Returns:
            None: 検証またはtest helperの処理を完了し値を返さない.
        """
        resolver = CloudflareCountryResolver()

        result = resolver.resolve({})

        assert result == "XX"

    def test_returns_various_country_codes(self) -> None:
        """複数の有効国codeをCF-IPCountry headerへ与えたとき各入力値をそのまま返すことを確認する.

        Returns:
            None: 検証またはtest helperの処理を完了し値を返さない.
        """
        for code in ("US", "KR", "GB", "FR", "DE"):
            resolver = CloudflareCountryResolver()

            result = resolver.resolve({"CF-IPCountry": code})

            assert result == code

    def test_satisfies_protocol(self) -> None:
        """Cloudflare resolverがCountryResolver Protocolとして認識されることを検証する.

        Returns:
            None: 検証またはtest helperの処理を完了し値を返さない.
        """
        resolver = CloudflareCountryResolver()

        assert isinstance(resolver, CountryResolver)


class TestCountryCodeToId:
    """stable bancho country codeから数値IDへの変換契約を検証するtest群.

    Attributes:
        _EXPECTED (ClassVar[dict[str, int]]): stable protocol用の国codeと数値IDの対応表.
    """

    # 数値は osuAkatsuki/bancho.py の stable bancho プロトコル準拠
    _EXPECTED: ClassVar[dict[str, int]] = {
        "JP": 111,
        "US": 225,
        "KR": 119,
        "GB": 77,
        "FR": 74,
        "DE": 56,
    }

    def test_known_codes(self) -> None:
        """既知の大文字国codeを変換しstable protocolの数値IDを検証する.

        Returns:
            None: 検証またはtest helperの処理を完了し値を返さない.
        """
        for code, expected_id in self._EXPECTED.items():
            assert country_code_to_id(code) == expected_id

    def test_unknown_code_returns_zero(self) -> None:
        """未知国codeを変換したときfallback値0を返すことを確認する.

        Returns:
            None: 検証またはtest helperの処理を完了し値を返さない.
        """
        assert country_code_to_id("ZZ") == 0
        assert country_code_to_id("??") == 0

    def test_xx_returns_244(self) -> None:
        """不明国codeのXXを変換したときstable protocolの244を返すことを確認する.

        Returns:
            None: 検証またはtest helperの処理を完了し値を返さない.
        """
        assert country_code_to_id("XX") == 244

    def test_empty_string_returns_zero(self) -> None:
        """空文字列を変換したときfallback値0を返すことを確認する.

        Returns:
            None: 検証またはtest helperの処理を完了し値を返さない.
        """
        assert country_code_to_id("") == 0

    def test_case_sensitive(self) -> None:
        """小文字国codeを変換したとき入力を大文字化せずfallback値0を返すことを確認する.

        Returns:
            None: 検証またはtest helperの処理を完了し値を返さない.
        """
        assert country_code_to_id("jp") == 0
        assert country_code_to_id("us") == 0
