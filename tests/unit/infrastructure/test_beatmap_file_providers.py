"""Beatmap file providerのsource選択とfailure契約を検証する."""

from __future__ import annotations

from typing import runtime_checkable

import httpx
import pytest
from structlog.testing import capture_logs

from osu_server.domain.beatmaps import (
    BeatmapFileProvider,
    BeatmapFileSource,
    BeatmapSourceError,
    BeatmapSourceErrorCategory,
    OsuFileFetchResult,
)
from osu_server.infrastructure.beatmaps import (
    BeatmapFileProviderService,
)
from osu_server.infrastructure.http.beatmap_http_client import BeatmapHttpClient
from tests.support.runtime_assertions import assert_rejects_setattr

# ---------------------------------------------------------------------------
# Mock httpx transport helpers
# ---------------------------------------------------------------------------

_MOCK_OSU_BODY = b"osu file format v14\n[General]\nAudioFilename: audio.mp3\n"
_BEATMAP_ID = 2000
_PRIMARY_URL = f"https://osu.ppy.sh/osu/{_BEATMAP_ID}"
_LEGACY_URL = f"https://old.ppy.sh/osu/{_BEATMAP_ID}"
_MIRROR_URL = f"https://catboy.best/osu/{_BEATMAP_ID}"


def _make_handler(
    *,
    primary_status: int = 200,
    primary_body: bytes | None = None,
    primary_headers: dict[str, str] | None = None,
    primary_error: type[Exception] | None = None,
    legacy_status: int = 200,
    legacy_body: bytes | None = None,
    legacy_headers: dict[str, str] | None = None,
    legacy_error: type[Exception] | None = None,
    mirror_status: int = 200,
    mirror_body: bytes | None = None,
    mirror_headers: dict[str, str] | None = None,
    mirror_error: type[Exception] | None = None,
) -> httpx.MockTransport:
    """Source別scenarioからhttpx.MockTransportを生成する.

    Args:
        primary_status (int): osu_current sourceが返すHTTP status.
        primary_body (bytes | None): osu_current response body. Noneなら既定osu bodyを使う.
        primary_headers (dict[str, str] | None): osu_current response headers.
        primary_error (type[Exception] | None): osu_current requestで送出する例外型.
        legacy_status (int): osu_legacy sourceが返すHTTP status.
        legacy_body (bytes | None): osu_legacy response body. Noneなら既定osu bodyを使う.
        legacy_headers (dict[str, str] | None): osu_legacy response headers.
        legacy_error (type[Exception] | None): osu_legacy requestで送出する例外型.
        mirror_status (int): community mirrorが返すHTTP status.
        mirror_body (bytes | None): community mirror response body. Noneなら既定osu bodyを使う.
        mirror_headers (dict[str, str] | None): community mirror response headers.
        mirror_error (type[Exception] | None): community mirror requestで送出する例外型.

    Returns:
        httpx.MockTransport: URLに対応するresponseまたはconfigured exceptionを返すtransport.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        """Request URLに対応するconfigured responseを返す.

        Args:
            request (httpx.Request): MockTransportが渡すHTTP request.

        Returns:
            httpx.Response: request sourceのstatusとbodyとheadersを持つresponse.

        Raises:
            Exception: 対応sourceにerror型が設定されている場合.
        """
        url = str(request.url)  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue, reportUnknownArgumentType]
        if _PRIMARY_URL in url:
            if primary_error is not None:
                raise primary_error("mock transport error")
            body = primary_body if primary_body is not None else _MOCK_OSU_BODY
            return httpx.Response(
                primary_status,
                content=body,
                headers=httpx.Headers(primary_headers or {}),
                request=request,
            )
        if _LEGACY_URL in url:
            if legacy_error is not None:
                raise legacy_error("mock transport error")
            body = legacy_body if legacy_body is not None else _MOCK_OSU_BODY
            return httpx.Response(
                legacy_status,
                content=body,
                headers=httpx.Headers(legacy_headers or {}),
                request=request,
            )
        if _MIRROR_URL in url:
            if mirror_error is not None:
                raise mirror_error("mock transport error")
            body = mirror_body if mirror_body is not None else _MOCK_OSU_BODY
            return httpx.Response(
                mirror_status,
                content=body,
                headers=httpx.Headers(mirror_headers or {}),
                request=request,
            )
        return httpx.Response(404, request=request)

    return httpx.MockTransport(handler)


def _make_client(
    *,
    primary_status: int = 200,
    primary_body: bytes | None = None,
    primary_headers: dict[str, str] | None = None,
    primary_error: type[Exception] | None = None,
    legacy_status: int = 200,
    legacy_body: bytes | None = None,
    legacy_headers: dict[str, str] | None = None,
    legacy_error: type[Exception] | None = None,
    mirror_status: int = 200,
    mirror_body: bytes | None = None,
    mirror_headers: dict[str, str] | None = None,
    mirror_error: type[Exception] | None = None,
) -> httpx.AsyncClient:
    """Source別scenarioを使う非同期HTTP clientを生成する.

    Args:
        primary_status (int): osu_current sourceが返すHTTP status.
        primary_body (bytes | None): osu_current response body. Noneなら既定osu bodyを使う.
        primary_headers (dict[str, str] | None): osu_current response headers.
        primary_error (type[Exception] | None): osu_current requestで送出する例外型.
        legacy_status (int): osu_legacy sourceが返すHTTP status.
        legacy_body (bytes | None): osu_legacy response body. Noneなら既定osu bodyを使う.
        legacy_headers (dict[str, str] | None): osu_legacy response headers.
        legacy_error (type[Exception] | None): osu_legacy requestで送出する例外型.
        mirror_status (int): community mirrorが返すHTTP status.
        mirror_body (bytes | None): community mirror response body. Noneなら既定osu bodyを使う.
        mirror_headers (dict[str, str] | None): community mirror response headers.
        mirror_error (type[Exception] | None): community mirror requestで送出する例外型.

    Returns:
        httpx.AsyncClient: configured MockTransportを使うtest client.
    """
    transport = _make_handler(
        primary_status=primary_status,
        primary_body=primary_body,
        primary_headers=primary_headers,
        primary_error=primary_error,
        legacy_status=legacy_status,
        legacy_body=legacy_body,
        legacy_headers=legacy_headers,
        legacy_error=legacy_error,
        mirror_status=mirror_status,
        mirror_body=mirror_body,
        mirror_headers=mirror_headers,
        mirror_error=mirror_error,
    )
    return httpx.AsyncClient(transport=transport)


def _make_provider(
    *,
    primary_status: int = 200,
    primary_body: bytes | None = None,
    primary_headers: dict[str, str] | None = None,
    primary_error: type[Exception] | None = None,
    legacy_status: int = 200,
    legacy_body: bytes | None = None,
    legacy_headers: dict[str, str] | None = None,
    legacy_error: type[Exception] | None = None,
    mirror_status: int = 200,
    mirror_body: bytes | None = None,
    mirror_headers: dict[str, str] | None = None,
    mirror_error: type[Exception] | None = None,
) -> BeatmapFileProviderService:
    """Source別scenarioを持つBeatmapFileProviderServiceを生成する.

    Args:
        primary_status (int): osu_current sourceが返すHTTP status.
        primary_body (bytes | None): osu_current response body. Noneなら既定osu bodyを使う.
        primary_headers (dict[str, str] | None): osu_current response headers.
        primary_error (type[Exception] | None): osu_current requestで送出する例外型.
        legacy_status (int): osu_legacy sourceが返すHTTP status.
        legacy_body (bytes | None): osu_legacy response body. Noneなら既定osu bodyを使う.
        legacy_headers (dict[str, str] | None): osu_legacy response headers.
        legacy_error (type[Exception] | None): osu_legacy requestで送出する例外型.
        mirror_status (int): community mirrorが返すHTTP status.
        mirror_body (bytes | None): community mirror response body. Noneなら既定osu bodyを使う.
        mirror_headers (dict[str, str] | None): community mirror response headers.
        mirror_error (type[Exception] | None): community mirror requestで送出する例外型.

    Returns:
        BeatmapFileProviderService: direct sourceとmirror fallbackを検証するprovider.
    """
    client = _make_client(
        primary_status=primary_status,
        primary_body=primary_body,
        primary_headers=primary_headers,
        primary_error=primary_error,
        legacy_status=legacy_status,
        legacy_body=legacy_body,
        legacy_headers=legacy_headers,
        legacy_error=legacy_error,
        mirror_status=mirror_status,
        mirror_body=mirror_body,
        mirror_headers=mirror_headers,
        mirror_error=mirror_error,
    )
    http_client = BeatmapHttpClient(client=client)
    return BeatmapFileProviderService(
        osu_current_url_template="https://osu.ppy.sh/osu/{beatmap_id}",
        osu_legacy_url_template="https://old.ppy.sh/osu/{beatmap_id}",
        mirror_url_templates=["https://catboy.best/osu/{beatmap_id}"],
        http_client=http_client,
    )


# ---------------------------------------------------------------------------
# BeatmapFileSource enum tests
# ---------------------------------------------------------------------------


class TestBeatmapFileSource:
    """BeatmapFileSourceのstable value契約を検証する."""

    def test_osu_current_value(self) -> None:
        """Osu_current enum値がprimary source識別子である契約を検証する.

        OSU_CURRENT memberのvalueを読み取り, source nameがosu_currentと一致することを確認する.

        Returns:
            None: enum値を検証して完了し, 呼び出し側へ値を返さない.
        """
        assert BeatmapFileSource.OSU_CURRENT.value == "osu_current"

    def test_osu_legacy_value(self) -> None:
        """Osu_legacy enum値がlegacy source識別子である契約を検証する.

        OSU_LEGACY memberのvalueを読み取り, source nameがosu_legacyと一致することを確認する.

        Returns:
            None: enum値を検証して完了し, 呼び出し側へ値を返さない.
        """
        assert BeatmapFileSource.OSU_LEGACY.value == "osu_legacy"

    def test_community_mirror_value(self) -> None:
        """Community_mirror enum値がmirror source識別子である契約を検証する.

        COMMUNITY_MIRROR memberのvalueを読み取る.
        source nameがcommunity_mirrorと一致することを確認する.

        Returns:
            None: enum値を検証して完了し, 呼び出し側へ値を返さない.
        """
        assert BeatmapFileSource.COMMUNITY_MIRROR.value == "community_mirror"

    def test_archive_extracted_value(self) -> None:
        """Archive_extracted enum値がarchive source識別子である契約を検証する.

        ARCHIVE_EXTRACTED memberのvalueを読み取る.
        source nameがarchive_extractedと一致することを確認する.

        Returns:
            None: enum値を検証して完了し, 呼び出し側へ値を返さない.
        """
        assert BeatmapFileSource.ARCHIVE_EXTRACTED.value == "archive_extracted"

    def test_all_values_are_strings(self) -> None:
        """全BeatmapFileSource memberが文字列valueを公開する契約を検証する.

        enum memberを走査し, 各valueがstr instanceであることを確認する.

        Returns:
            None: 全memberのvalue型を検証して完了し, 呼び出し側へ値を返さない.
        """
        for member in BeatmapFileSource:
            assert isinstance(member.value, str)


# ---------------------------------------------------------------------------
# OsuFileFetchResult dataclass tests
# ---------------------------------------------------------------------------


class TestOsuFileFetchResult:
    """OsuFileFetchResultのfieldとimmutable storage契約を検証する."""

    def test_creates_with_valid_fields(self) -> None:
        """有効なfile fetch fieldから結果値を生成する契約を検証する.

        beatmap IDとbodyとsourceとfilenameで結果を生成し, 全fieldが入力値を保持することを確認する.

        Returns:
            None: result fieldを検証して完了し, 呼び出し側へ値を返さない.
        """
        result = OsuFileFetchResult(
            beatmap_id=2000,
            body=b"osu file content",
            source=BeatmapFileSource.OSU_CURRENT,
            original_filename="2000.osu",
        )
        assert result.beatmap_id == 2000
        assert result.body == b"osu file content"
        assert result.source is BeatmapFileSource.OSU_CURRENT
        assert result.original_filename == "2000.osu"

    def test_original_filename_can_be_none(self) -> None:
        """Content-Dispositionがない結果でfilenameがNoneとなる契約を検証する.

        original_filenameをNoneにして結果を生成し, 同fieldがNoneのまま保持されることを確認する.

        Returns:
            None: optional filenameを検証して完了し, 呼び出し側へ値を返さない.
        """
        result = OsuFileFetchResult(
            beatmap_id=2000,
            body=b"content",
            source=BeatmapFileSource.OSU_CURRENT,
            original_filename=None,
        )
        assert result.original_filename is None

    def test_is_frozen(self) -> None:
        """OsuFileFetchResultが生成後のfield変更を拒否する契約を検証する.

        有効な結果を生成してbeatmap_idを代入し, immutable dataclassが代入を拒否することを確認する.

        Returns:
            None: frozen storageを検証して完了し, 呼び出し側へ値を返さない.
        """
        result = OsuFileFetchResult(
            beatmap_id=2000,
            body=b"content",
            source=BeatmapFileSource.OSU_CURRENT,
            original_filename=None,
        )
        assert_rejects_setattr(result, "beatmap_id", 9999)

    def test_uses_slots(self) -> None:
        """OsuFileFetchResultがslotsで任意attribute storageを持たない契約を検証する.

        有効な結果を生成し, instanceに__dict__ attributeがないことを確認する.

        Returns:
            None: slots使用を検証して完了し, 呼び出し側へ値を返さない.
        """
        result = OsuFileFetchResult(
            beatmap_id=2000,
            body=b"content",
            source=BeatmapFileSource.OSU_CURRENT,
            original_filename=None,
        )
        assert not hasattr(result, "__dict__")


# ---------------------------------------------------------------------------
# BeatmapFileProvider Protocol tests
# ---------------------------------------------------------------------------


class TestBeatmapFileProviderProtocol:
    """BeatmapFileProviderのruntime structural protocol契約を検証する."""

    def test_protocol_is_runtime_checkable(self) -> None:
        """BeatmapFileProviderがruntime isinstance検査を許可する契約を検証する.

        Protocolへruntime_checkableを適用し, 同じProtocol objectが返ることを確認する.

        Returns:
            None: runtime protocol化を検証して完了し, 呼び出し側へ値を返さない.
        """
        assert runtime_checkable(BeatmapFileProvider) is BeatmapFileProvider

    def test_matching_implementation_passes_isinstance(self) -> None:
        """Fetch_osu_fileを実装するobjectがProvider Protocolに適合する契約を検証する.

        必須async methodを持つlocal providerを生成する.
        isinstanceがBeatmapFileProviderとして成功することを確認する.

        Returns:
            None: structural protocol適合を検証して完了し, 呼び出し側へ値を返さない.
        """

        class GoodProvider:
            """BeatmapFileProviderの必須methodだけを実装するlocal fakeを表す."""

            async def fetch_osu_file(self, beatmap_id: int) -> OsuFileFetchResult:
                """指定beatmap IDの空osu file結果を返す.

                Args:
                    beatmap_id (int): 結果へ設定するbeatmap識別子.

                Returns:
                    OsuFileFetchResult: primary sourceと空bodyを持つfile結果.
                """
                return OsuFileFetchResult(
                    beatmap_id=beatmap_id,
                    body=b"",
                    source=BeatmapFileSource.OSU_CURRENT,
                    original_filename=None,
                )

        provider = GoodProvider()
        assert isinstance(provider, BeatmapFileProvider)

    def test_protocol_missing_method_fails_isinstance(self) -> None:
        """必須fetch_osu_fileがないobjectがProvider Protocolを満たさない契約を検証する.

        無関係なmethodだけを持つlocal providerを生成し, isinstanceがFalseとなることを確認する.

        Returns:
            None: structural protocol不適合を検証して完了し, 呼び出し側へ値を返さない.
        """

        class BadProvider:
            """BeatmapFileProviderの必須methodを持たないlocal fakeを表す."""

            def other_method(self) -> None:
                """無関係なmethodを実行して完了する.

                Returns:
                    None: 値を返さずに完了する.
                """

        provider = BadProvider()
        assert not isinstance(provider, BeatmapFileProvider)


# ---------------------------------------------------------------------------
# BeatmapFileProviderService tests
# ---------------------------------------------------------------------------


class TestBeatmapFileProviderServicePrimarySource:
    """Osu_current primary sourceからのfile取得契約を検証する."""

    async def test_fetch_from_primary_source_success(self) -> None:
        """Primary sourceの成功responseをそのsourceとして返す契約を検証する.

        既定200 responseのproviderでbeatmap fileを取得する.
        IDとbodyとsourceがprimary responseと一致することを確認する.

        Returns:
            None: primary fetch結果を検証して完了し, 呼び出し側へ値を返さない.
        """
        provider = _make_provider()
        result = await provider.fetch_osu_file(_BEATMAP_ID)
        assert result.beatmap_id == _BEATMAP_ID
        assert result.body == _MOCK_OSU_BODY
        assert result.source is BeatmapFileSource.OSU_CURRENT

    async def test_primary_404_without_mirror_raises_not_found(self) -> None:
        """Primaryとlegacyが404なら成功可能なmirrorを使わずNOT_FOUNDにする契約を検証する.

        primaryとlegacyを404かつmirrorを200に設定して取得し,
        NOT_FOUND categoryのBeatmapSourceErrorが送出されることを確認する.

        Returns:
            None: direct sourceの404処理を検証して完了し, 呼び出し側へ値を返さない.
        """
        provider = _make_provider(
            primary_status=404,
            legacy_status=404,
            mirror_status=200,  # mirror would succeed, but must not be tried
        )
        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.fetch_osu_file(_BEATMAP_ID)
        assert exc_info.value.category is BeatmapSourceErrorCategory.NOT_FOUND

    async def test_primary_404_then_legacy_404_raises_not_found(self) -> None:
        """Primary後のlegacy 404がNOT_FOUNDを伝える契約を検証する.

        両direct sourceを404に設定して取得し, error categoryがNOT_FOUNDとなることを確認する.

        Returns:
            None: legacy 404のerror mappingを検証して完了し, 呼び出し側へ値を返さない.
        """
        provider = _make_provider(primary_status=404, legacy_status=404)
        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.fetch_osu_file(_BEATMAP_ID)
        assert exc_info.value.category is BeatmapSourceErrorCategory.NOT_FOUND


class TestBeatmapFileProviderServiceLegacyFallback:
    """Primary障害時のosu_legacy fallback契約を検証する."""

    async def test_fallback_to_legacy_on_primary_429(self) -> None:
        """Primary 429後にlegacy sourceを使う契約を検証する.

        primaryを429に設定してfileを取得し, result sourceがOSU_LEGACYとなることを確認する.

        Returns:
            None: rate-limit fallbackを検証して完了し, 呼び出し側へ値を返さない.
        """
        provider = _make_provider(primary_status=429)
        result = await provider.fetch_osu_file(_BEATMAP_ID)
        assert result.source is BeatmapFileSource.OSU_LEGACY

    async def test_fallback_to_legacy_on_primary_503(self) -> None:
        """Primary 503後にlegacy sourceを使う契約を検証する.

        primaryを503に設定してfileを取得し, result sourceがOSU_LEGACYとなることを確認する.

        Returns:
            None: temporary failure fallbackを検証して完了し, 呼び出し側へ値を返さない.
        """
        provider = _make_provider(primary_status=503)
        result = await provider.fetch_osu_file(_BEATMAP_ID)
        assert result.source is BeatmapFileSource.OSU_LEGACY

    async def test_fallback_to_legacy_on_primary_500(self) -> None:
        """Primary 500後にlegacy sourceを使う契約を検証する.

        primaryを500に設定してfileを取得し, result sourceがOSU_LEGACYとなることを確認する.

        Returns:
            None: server error fallbackを検証して完了し, 呼び出し側へ値を返さない.
        """
        provider = _make_provider(primary_status=500)
        result = await provider.fetch_osu_file(_BEATMAP_ID)
        assert result.source is BeatmapFileSource.OSU_LEGACY

    async def test_fallback_to_legacy_on_primary_502(self) -> None:
        """Primary 502後にlegacy sourceを使う契約を検証する.

        primaryを502に設定してfileを取得し, result sourceがOSU_LEGACYとなることを確認する.

        Returns:
            None: gateway failure fallbackを検証して完了し, 呼び出し側へ値を返さない.
        """
        provider = _make_provider(primary_status=502)
        result = await provider.fetch_osu_file(_BEATMAP_ID)
        assert result.source is BeatmapFileSource.OSU_LEGACY

    async def test_fallback_to_legacy_on_connection_error(self) -> None:
        """Primary connection error後にlegacy sourceを使う契約を検証する.

        primary transportをConnectErrorに設定してfileを取得する.
        result sourceがOSU_LEGACYとなることを確認する.

        Returns:
            None: connection failure fallbackを検証して完了し, 呼び出し側へ値を返さない.
        """
        provider = _make_provider(primary_error=httpx.ConnectError)
        result = await provider.fetch_osu_file(_BEATMAP_ID)
        assert result.source is BeatmapFileSource.OSU_LEGACY

    async def test_fallback_to_legacy_on_timeout(self) -> None:
        """Primary timeout後にlegacy sourceを使う契約を検証する.

        primary transportをTimeoutExceptionに設定してfileを取得する.
        result sourceがOSU_LEGACYとなることを確認する.

        Returns:
            None: timeout fallbackを検証して完了し, 呼び出し側へ値を返さない.
        """
        provider = _make_provider(primary_error=httpx.TimeoutException)
        result = await provider.fetch_osu_file(_BEATMAP_ID)
        assert result.source is BeatmapFileSource.OSU_LEGACY

    async def test_legacy_404_when_primary_fails_raises_not_found(self) -> None:
        """Primary障害後のlegacy 404がNOT_FOUNDとなる契約を検証する.

        primaryを429かつlegacyを404に設定して取得する.
        最後のdirect sourceの404がNOT_FOUNDとして送出されることを確認する.

        Returns:
            None: final direct sourceの404伝播を検証して完了し, 呼び出し側へ値を返さない.
        """
        provider = _make_provider(primary_status=429, legacy_status=404)
        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.fetch_osu_file(_BEATMAP_ID)
        assert exc_info.value.category is BeatmapSourceErrorCategory.NOT_FOUND


class TestBeatmapFileProviderServiceMirrorFallback:
    """両direct source障害時のcommunity mirror fallback契約を検証する."""

    async def test_fallback_to_mirror_when_both_direct_fail(self) -> None:
        """両direct source障害後にcommunity mirrorを使う契約を検証する.

        primaryを429かつlegacyを503に設定して取得する.
        result sourceがCOMMUNITY_MIRRORとなることを確認する.

        Returns:
            None: mirror fallbackを検証して完了し, 呼び出し側へ値を返さない.
        """
        provider = _make_provider(
            primary_status=429,
            legacy_status=503,
        )
        result = await provider.fetch_osu_file(_BEATMAP_ID)
        assert result.source is BeatmapFileSource.COMMUNITY_MIRROR

    async def test_mirror_result_has_mirror_source(self) -> None:
        """Mirror fallbackが元のbodyとbeatmap IDを保持する契約を検証する.

        両direct sourceを障害にして取得し, result bodyとbeatmap IDが期待値と一致することを確認する.

        Returns:
            None: mirror resultのpayloadを検証して完了し, 呼び出し側へ値を返さない.
        """
        provider = _make_provider(
            primary_status=429,
            legacy_status=503,
        )
        result = await provider.fetch_osu_file(_BEATMAP_ID)
        assert result.body == _MOCK_OSU_BODY
        assert result.beatmap_id == _BEATMAP_ID

    async def test_no_mirror_fallback_when_primary_is_temp_unavailable_legacy_is_200(self) -> None:
        """Legacy成功時にmirrorを使わない契約を検証する.

        primaryを503かつlegacyを既定200に設定して取得する.
        result sourceがOSU_LEGACYとなることを確認する.

        Returns:
            None: direct fallback優先を検証して完了し, 呼び出し側へ値を返さない.
        """
        provider = _make_provider(primary_status=503)
        result = await provider.fetch_osu_file(_BEATMAP_ID)
        assert result.source is BeatmapFileSource.OSU_LEGACY

    async def test_all_sources_exhausted_raises_error(self) -> None:
        """全sourceがtemporary failureならエラーにする契約を検証する.

        primaryとlegacyとmirrorを503に設定して取得する.
        TEMPORARY_UNAVAILABLE categoryが送出されることを確認する.

        Returns:
            None: source exhaustion errorを検証して完了し, 呼び出し側へ値を返さない.
        """
        provider = _make_provider(
            primary_status=503,
            legacy_status=503,
            mirror_status=503,
        )
        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.fetch_osu_file(_BEATMAP_ID)
        assert exc_info.value.category is BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE


class TestBeatmapFileProviderServiceFilenameCapture:
    """Content-Dispositionからのoriginal filename抽出契約を検証する."""

    async def test_captures_filename_from_content_disposition(self) -> None:
        """Filename parameterをoriginal filenameとして保存する契約を検証する.

        filename付きContent-Dispositionを持つprimary responseを取得し,
        result filenameがheader値と一致することを確認する.

        Returns:
            None: filename captureを検証して完了し, 呼び出し側へ値を返さない.
        """
        provider = _make_provider(
            primary_headers={
                "Content-Disposition": 'attachment; filename="2000.osu"',
            },
        )
        result = await provider.fetch_osu_file(_BEATMAP_ID)
        assert result.original_filename == "2000.osu"

    async def test_none_filename_when_no_content_disposition(self) -> None:
        """Content-DispositionがないresponseでfilenameをNoneにする契約を検証する.

        headerなしのprimary responseを取得し, result original_filenameがNoneとなることを確認する.

        Returns:
            None: missing header処理を検証して完了し, 呼び出し側へ値を返さない.
        """
        provider = _make_provider()
        result = await provider.fetch_osu_file(_BEATMAP_ID)
        assert result.original_filename is None

    async def test_none_filename_when_content_disposition_has_no_filename(self) -> None:
        """Filename parameterのないContent-DispositionでfilenameをNoneにする契約を検証する.

        inline Content-Dispositionを持つresponseを取得する.
        result original_filenameがNoneとなることを確認する.

        Returns:
            None: incomplete header処理を検証して完了し, 呼び出し側へ値を返さない.
        """
        provider = _make_provider(
            primary_headers={"Content-Disposition": "inline"},
        )
        result = await provider.fetch_osu_file(_BEATMAP_ID)
        assert result.original_filename is None


class TestBeatmapFileProviderServiceErrorCategoryMapping:
    """HTTP statusからBeatmapSourceError categoryへのmapping契約を検証する."""

    @pytest.mark.parametrize(
        ("status_code", "expected_category"),
        [
            (429, BeatmapSourceErrorCategory.RATE_LIMITED),
            (404, BeatmapSourceErrorCategory.NOT_FOUND),
            (500, BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE),
            (502, BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE),
            (503, BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE),
            (504, BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE),
        ],
    )
    async def test_error_category_for_status_code(
        self, status_code: int, expected_category: BeatmapSourceErrorCategory
    ) -> None:
        """全sourceの同一non-success statusを対応error categoryへ写す契約を検証する.

        Args:
            status_code (int): primaryとlegacyとmirrorへ設定するHTTP failure status.
            expected_category (BeatmapSourceErrorCategory): 最終errorへ期待するcategory.

        全sourceを同じstatusに設定して取得する.
        送出されたBeatmapSourceError categoryが期待値と一致することを確認する.

        Returns:
            None: status category mappingを検証して完了し, 呼び出し側へ値を返さない.
        """
        provider = _make_provider(
            primary_status=status_code,
            legacy_status=status_code,
            mirror_status=status_code,
        )
        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.fetch_osu_file(_BEATMAP_ID)
        assert exc_info.value.category is expected_category


class TestBeatmapFileProviderServiceNoMirrors:
    """Mirror URL未設定providerのfailure契約を検証する."""

    async def test_no_fallback_when_no_mirrors_configured(self) -> None:
        """Mirror URLが空ならdirect source障害後にerrorとする契約を検証する.

        primaryを429かつlegacyを503にしたmirrorなしproviderで取得する.
        TEMPORARY_UNAVAILABLEが送出されることを確認する.

        Returns:
            None: mirror未設定時のfailureを検証して完了し, 呼び出し側へ値を返さない.
        """
        client = _make_client(primary_status=429, legacy_status=503)
        http_client = BeatmapHttpClient(client=client)
        provider = BeatmapFileProviderService(
            osu_current_url_template="https://osu.ppy.sh/osu/{beatmap_id}",
            osu_legacy_url_template="https://old.ppy.sh/osu/{beatmap_id}",
            mirror_url_templates=[],
            http_client=http_client,
        )
        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.fetch_osu_file(_BEATMAP_ID)
        assert exc_info.value.category is BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE


class TestBeatmapFileProviderServiceRateLimitObservability:
    """Rate-limit failureのsource識別情報を検証する."""

    async def test_rate_limit_error_includes_source_info(self) -> None:
        """Rate-limit errorがlookup keyを含む契約を検証する.

        全sourceを429に設定して取得し, RATE_LIMITED categoryとbeatmap IDを含むlookup keyを確認する.

        Returns:
            None: rate-limit error metadataを検証して完了し, 呼び出し側へ値を返さない.
        """
        provider = _make_provider(primary_status=429, legacy_status=429, mirror_status=429)
        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.fetch_osu_file(_BEATMAP_ID)
        assert exc_info.value.category is BeatmapSourceErrorCategory.RATE_LIMITED
        assert str(_BEATMAP_ID) in exc_info.value.lookup_key


class TestBeatmapFileProviderServiceLogging:
    """File source操作のstructured log契約を検証する."""

    async def test_logs_rate_limited_event_on_429(self) -> None:
        """Primary 429でrate-limit eventを記録する契約を検証する.

        primaryを429かつlegacyを200に設定して取得する.
        captured logにsourceとbeatmap IDを持つeventが出ることを確認する.

        Returns:
            None: primary rate-limit logを検証して完了し, 呼び出し側へ値を返さない.
        """
        provider = _make_provider(primary_status=429, legacy_status=200)
        with capture_logs() as logs:
            _ = await provider.fetch_osu_file(_BEATMAP_ID)

        rate_limited = [e for e in logs if e.get("event") == "beatmap_source_rate_limited"]
        assert len(rate_limited) >= 1
        assert rate_limited[0]["source"] == "osu_current"
        assert rate_limited[0]["beatmap_id"] == _BEATMAP_ID

    async def test_logs_rate_limited_for_legacy_429(self) -> None:
        """Legacy 429でもrate-limit eventを記録する契約を検証する.

        primaryとlegacyを429かつmirrorを200に設定して取得する.
        log source集合に両direct sourceが含まれることを確認する.

        Returns:
            None: legacy rate-limit logを検証して完了し, 呼び出し側へ値を返さない.
        """
        provider2 = _make_provider(primary_status=429, legacy_status=429, mirror_status=200)
        with capture_logs() as logs:
            _ = await provider2.fetch_osu_file(_BEATMAP_ID)

        rate_limited = [e for e in logs if e.get("event") == "beatmap_source_rate_limited"]
        # Both osu_current and osu_legacy should log rate-limited
        sources = {e["source"] for e in rate_limited}
        assert "osu_current" in sources
        assert "osu_legacy" in sources

    async def test_logs_mirror_fallback_event(self) -> None:
        """Mirrorを使った場合にfallback eventを記録する契約を検証する.

        direct sourceを429と503にしてmirrorを200に設定し,
        captured logにfile sourceとbeatmap IDを持つeventが1件出ることを確認する.

        Returns:
            None: mirror fallback logを検証して完了し, 呼び出し側へ値を返さない.
        """
        provider = _make_provider(
            primary_status=429,
            legacy_status=503,
            mirror_status=200,
        )
        with capture_logs() as logs:
            _ = await provider.fetch_osu_file(_BEATMAP_ID)

        mirror_events = [e for e in logs if e.get("event") == "beatmap_mirror_fallback_used"]
        assert len(mirror_events) == 1
        assert mirror_events[0]["source_type"] == "file"
        assert mirror_events[0]["beatmap_id"] == _BEATMAP_ID
        assert "source" in mirror_events[0]
        assert mirror_events[0]["source"] == BeatmapFileSource.COMMUNITY_MIRROR.value

    async def test_no_mirror_fallback_event_when_direct_succeeds(self) -> None:
        """Primary成功時にmirror fallback eventを記録しない契約を検証する.

        既定primary success providerで取得する.
        captured logのmirror fallback event数が0件となることを確認する.

        Returns:
            None: direct success時のlog抑制を検証して完了し, 呼び出し側へ値を返さない.
        """
        provider = _make_provider()
        with capture_logs() as logs:
            _ = await provider.fetch_osu_file(_BEATMAP_ID)

        mirror_events = [e for e in logs if e.get("event") == "beatmap_mirror_fallback_used"]
        assert len(mirror_events) == 0

    async def test_no_api_credentials_in_rate_limit_log(self) -> None:
        """Rate-limit logがAPI credential fieldを含まない契約を検証する.

        primaryを429に設定して取得する.
        captured logの全field名がsensitive credential名を含まないことを確認する.

        Returns:
            None: credential非露出を検証して完了し, 呼び出し側へ値を返さない.
        """
        provider = _make_provider(primary_status=429, legacy_status=200)
        with capture_logs() as logs:
            _ = await provider.fetch_osu_file(_BEATMAP_ID)

        sensitive = {"api_key", "token", "secret", "credential", "authorization", "bearer"}
        for entry in logs:
            for key in entry:
                assert not any(s in key.lower() for s in sensitive), (
                    f"Sensitive field '{key}' in log event '{entry.get('event')}'"
                )
