"""Tests for BeatmapFileProvider contract and BeatmapFileProviderService.

TDD: RED phase first, then GREEN.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import runtime_checkable

import httpx
import pytest
from structlog.testing import capture_logs

from osu_server.domain.beatmap import (
    BeatmapFileProvider,
    BeatmapFileSource,
    BeatmapSourceError,
    BeatmapSourceErrorCategory,
    OsuFileFetchResult,
)
from osu_server.infrastructure.http import BeatmapHttpClient
from osu_server.services.beatmap_mirror import (
    BeatmapFileProviderService,
)

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
    """Build a httpx.MockTransport handler from per-source scenarios.

    Each *_error, when set, will raise that exception instead of returning
    a response for the corresponding source URL.
    """

    def handler(request: httpx.Request) -> httpx.Response:
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
    def test_osu_current_value(self) -> None:
        assert BeatmapFileSource.OSU_CURRENT.value == "osu_current"

    def test_osu_legacy_value(self) -> None:
        assert BeatmapFileSource.OSU_LEGACY.value == "osu_legacy"

    def test_community_mirror_value(self) -> None:
        assert BeatmapFileSource.COMMUNITY_MIRROR.value == "community_mirror"

    def test_archive_extracted_value(self) -> None:
        assert BeatmapFileSource.ARCHIVE_EXTRACTED.value == "archive_extracted"

    def test_all_values_are_strings(self) -> None:
        for member in BeatmapFileSource:
            assert isinstance(member.value, str)


# ---------------------------------------------------------------------------
# OsuFileFetchResult dataclass tests
# ---------------------------------------------------------------------------


class TestOsuFileFetchResult:
    def test_creates_with_valid_fields(self) -> None:
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
        result = OsuFileFetchResult(
            beatmap_id=2000,
            body=b"content",
            source=BeatmapFileSource.OSU_CURRENT,
            original_filename=None,
        )
        assert result.original_filename is None

    def test_is_frozen(self) -> None:
        result = OsuFileFetchResult(
            beatmap_id=2000,
            body=b"content",
            source=BeatmapFileSource.OSU_CURRENT,
            original_filename=None,
        )
        with pytest.raises(FrozenInstanceError):
            result.beatmap_id = 9999  # type: ignore[misc]  # pyright: ignore[reportAttributeAccessIssue]

    def test_uses_slots(self) -> None:
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
    def test_protocol_is_runtime_checkable(self) -> None:
        assert runtime_checkable(BeatmapFileProvider) is BeatmapFileProvider

    def test_matching_implementation_passes_isinstance(self) -> None:
        class GoodProvider:
            async def fetch_osu_file(self, beatmap_id: int) -> OsuFileFetchResult:
                return OsuFileFetchResult(
                    beatmap_id=beatmap_id,
                    body=b"",
                    source=BeatmapFileSource.OSU_CURRENT,
                    original_filename=None,
                )

        provider = GoodProvider()
        assert isinstance(provider, BeatmapFileProvider)

    def test_protocol_missing_method_fails_isinstance(self) -> None:
        class BadProvider:
            def other_method(self) -> None: ...

        provider = BadProvider()
        assert not isinstance(provider, BeatmapFileProvider)


# ---------------------------------------------------------------------------
# BeatmapFileProviderService tests
# ---------------------------------------------------------------------------


class TestBeatmapFileProviderServicePrimarySource:
    """Tests for primary source (osu_current) fetch behavior."""

    async def test_fetch_from_primary_source_success(self) -> None:
        provider = _make_provider()
        result = await provider.fetch_osu_file(_BEATMAP_ID)
        assert result.beatmap_id == _BEATMAP_ID
        assert result.body == _MOCK_OSU_BODY
        assert result.source is BeatmapFileSource.OSU_CURRENT

    async def test_primary_404_without_mirror_raises_not_found(self) -> None:
        provider = _make_provider(
            primary_status=404,
            legacy_status=404,
            mirror_status=200,  # mirror would succeed, but must not be tried
        )
        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.fetch_osu_file(_BEATMAP_ID)
        assert exc_info.value.category is BeatmapSourceErrorCategory.NOT_FOUND

    async def test_primary_404_then_legacy_404_raises_not_found(self) -> None:
        provider = _make_provider(primary_status=404, legacy_status=404)
        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.fetch_osu_file(_BEATMAP_ID)
        assert exc_info.value.category is BeatmapSourceErrorCategory.NOT_FOUND


class TestBeatmapFileProviderServiceLegacyFallback:
    """Tests for legacy source fallback behavior."""

    async def test_fallback_to_legacy_on_primary_429(self) -> None:
        provider = _make_provider(primary_status=429)
        result = await provider.fetch_osu_file(_BEATMAP_ID)
        assert result.source is BeatmapFileSource.OSU_LEGACY

    async def test_fallback_to_legacy_on_primary_503(self) -> None:
        provider = _make_provider(primary_status=503)
        result = await provider.fetch_osu_file(_BEATMAP_ID)
        assert result.source is BeatmapFileSource.OSU_LEGACY

    async def test_fallback_to_legacy_on_primary_500(self) -> None:
        provider = _make_provider(primary_status=500)
        result = await provider.fetch_osu_file(_BEATMAP_ID)
        assert result.source is BeatmapFileSource.OSU_LEGACY

    async def test_fallback_to_legacy_on_primary_502(self) -> None:
        provider = _make_provider(primary_status=502)
        result = await provider.fetch_osu_file(_BEATMAP_ID)
        assert result.source is BeatmapFileSource.OSU_LEGACY

    async def test_fallback_to_legacy_on_connection_error(self) -> None:
        provider = _make_provider(primary_error=httpx.ConnectError)
        result = await provider.fetch_osu_file(_BEATMAP_ID)
        assert result.source is BeatmapFileSource.OSU_LEGACY

    async def test_fallback_to_legacy_on_timeout(self) -> None:
        provider = _make_provider(primary_error=httpx.TimeoutException)
        result = await provider.fetch_osu_file(_BEATMAP_ID)
        assert result.source is BeatmapFileSource.OSU_LEGACY

    async def test_legacy_404_when_primary_fails_raises_not_found(self) -> None:
        """If primary is temporarily unavailable but legacy returns 404,
        the composite should raise NOT_FOUND (404 propagates from last direct source)."""
        provider = _make_provider(primary_status=429, legacy_status=404)
        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.fetch_osu_file(_BEATMAP_ID)
        assert exc_info.value.category is BeatmapSourceErrorCategory.NOT_FOUND


class TestBeatmapFileProviderServiceMirrorFallback:
    """Tests for mirror fallback when both direct sources are unavailable."""

    async def test_fallback_to_mirror_when_both_direct_fail(self) -> None:
        provider = _make_provider(
            primary_status=429,
            legacy_status=503,
        )
        result = await provider.fetch_osu_file(_BEATMAP_ID)
        assert result.source is BeatmapFileSource.COMMUNITY_MIRROR

    async def test_mirror_result_has_mirror_source(self) -> None:
        provider = _make_provider(
            primary_status=429,
            legacy_status=503,
        )
        result = await provider.fetch_osu_file(_BEATMAP_ID)
        assert result.body == _MOCK_OSU_BODY
        assert result.beatmap_id == _BEATMAP_ID

    async def test_no_mirror_fallback_when_primary_is_temp_unavailable_legacy_is_200(self) -> None:
        """When primary fails temporarily but legacy succeeds, mirror must NOT be tried."""
        provider = _make_provider(primary_status=503)
        result = await provider.fetch_osu_file(_BEATMAP_ID)
        assert result.source is BeatmapFileSource.OSU_LEGACY

    async def test_all_sources_exhausted_raises_error(self) -> None:
        provider = _make_provider(
            primary_status=503,
            legacy_status=503,
            mirror_status=503,
        )
        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.fetch_osu_file(_BEATMAP_ID)
        assert exc_info.value.category is BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE


class TestBeatmapFileProviderServiceFilenameCapture:
    """Tests for original filename capture from Content-Disposition header."""

    async def test_captures_filename_from_content_disposition(self) -> None:
        provider = _make_provider(
            primary_headers={
                "Content-Disposition": 'attachment; filename="2000.osu"',
            },
        )
        result = await provider.fetch_osu_file(_BEATMAP_ID)
        assert result.original_filename == "2000.osu"

    async def test_none_filename_when_no_content_disposition(self) -> None:
        provider = _make_provider()
        result = await provider.fetch_osu_file(_BEATMAP_ID)
        assert result.original_filename is None

    async def test_none_filename_when_content_disposition_has_no_filename(self) -> None:
        provider = _make_provider(
            primary_headers={"Content-Disposition": "inline"},
        )
        result = await provider.fetch_osu_file(_BEATMAP_ID)
        assert result.original_filename is None


class TestBeatmapFileProviderServiceErrorCategoryMapping:
    """Tests for error normalization and category mapping."""

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
        """When all sources return the same non-success status, the composite
        raises a BeatmapSourceError whose category matches the last source's status."""
        provider = _make_provider(
            primary_status=status_code,
            legacy_status=status_code,
            mirror_status=status_code,
        )
        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.fetch_osu_file(_BEATMAP_ID)
        assert exc_info.value.category is expected_category


class TestBeatmapFileProviderServiceNoMirrors:
    """Tests for providers with empty mirror URL list."""

    async def test_no_fallback_when_no_mirrors_configured(self) -> None:
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
    """Tests for rate-limit observability (Requirement 16.6)."""

    async def test_rate_limit_error_includes_source_info(self) -> None:
        provider = _make_provider(primary_status=429, legacy_status=429, mirror_status=429)
        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.fetch_osu_file(_BEATMAP_ID)
        assert exc_info.value.category is BeatmapSourceErrorCategory.RATE_LIMITED
        assert str(_BEATMAP_ID) in exc_info.value.lookup_key


class TestBeatmapFileProviderServiceLogging:
    """Structured observability for file source operations (16.3, 16.4, 16.6)."""

    async def test_logs_rate_limited_event_on_429(self) -> None:
        """When a direct source returns 429, a rate limit event is logged."""
        provider = _make_provider(primary_status=429, legacy_status=200)
        with capture_logs() as logs:
            _ = await provider.fetch_osu_file(_BEATMAP_ID)

        rate_limited = [e for e in logs if e.get("event") == "beatmap_source_rate_limited"]
        assert len(rate_limited) >= 1
        assert rate_limited[0]["source"] == "osu_current"
        assert rate_limited[0]["beatmap_id"] == _BEATMAP_ID

    async def test_logs_rate_limited_for_legacy_429(self) -> None:
        """Rate limit on the legacy source is also logged."""
        provider2 = _make_provider(primary_status=429, legacy_status=429, mirror_status=200)
        with capture_logs() as logs:
            _ = await provider2.fetch_osu_file(_BEATMAP_ID)

        rate_limited = [e for e in logs if e.get("event") == "beatmap_source_rate_limited"]
        # Both osu_current and osu_legacy should log rate-limited
        sources = {e["source"] for e in rate_limited}
        assert "osu_current" in sources
        assert "osu_legacy" in sources

    async def test_logs_mirror_fallback_event(self) -> None:
        """When mirror is used, a mirror fallback event is logged."""
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
        """No mirror fallback event when primary source succeeds."""
        provider = _make_provider()
        with capture_logs() as logs:
            _ = await provider.fetch_osu_file(_BEATMAP_ID)

        mirror_events = [e for e in logs if e.get("event") == "beatmap_mirror_fallback_used"]
        assert len(mirror_events) == 0

    async def test_no_api_credentials_in_rate_limit_log(self) -> None:
        """Rate limit log must not include API credentials or tokens."""
        provider = _make_provider(primary_status=429, legacy_status=200)
        with capture_logs() as logs:
            _ = await provider.fetch_osu_file(_BEATMAP_ID)

        sensitive = {"api_key", "token", "secret", "credential", "authorization", "bearer"}
        for entry in logs:
            for key in entry:
                assert not any(s in key.lower() for s in sensitive), (
                    f"Sensitive field '{key}' in log event '{entry.get('event')}'"
                )
