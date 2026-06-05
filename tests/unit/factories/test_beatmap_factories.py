from __future__ import annotations

from datetime import UTC, datetime

import pytest
from tests.factories.beatmap import (
    FakeBeatmapFileProvider,
    FakeBeatmapMetadataProvider,
    FakeProviderErrorKind,
    FakeProviderResultKind,
    make_beatmap_fetch_state_factory,
    make_beatmap_file_attachment_factory,
    make_beatmap_file_body,
    make_beatmap_snapshot_factory,
    make_beatmapset_snapshot_factory,
    make_file_provider_response,
    make_metadata_provider_response,
)


def test_make_beatmapset_snapshot_factory_creates_complete_snapshot() -> None:
    snapshot = make_beatmapset_snapshot_factory()

    assert snapshot.beatmapset_id == 1_000
    assert snapshot.artist == "Camellia"
    assert snapshot.title == "Exit This Earth's Atomosphere"
    assert snapshot.source == "official"
    assert snapshot.verified is True
    assert len(snapshot.beatmaps) == 1
    assert snapshot.beatmaps[0].beatmap_id == 2_000
    assert snapshot.beatmaps[0].checksum_md5 == "0123456789abcdef0123456789abcdef"


def test_make_beatmap_snapshot_factory_allows_overrides() -> None:
    fetched_at = datetime.now(UTC)

    beatmap = make_beatmap_snapshot_factory(
        beatmap_id=42,
        beatmapset_id=24,
        checksum_md5="abcdefabcdefabcdefabcdefabcdefab",
        mode="taiko",
        version="Oni",
        official_status="loved",
        local_status_override="ranked",
        last_fetched_at=fetched_at,
    )

    assert beatmap.beatmap_id == 42
    assert beatmap.beatmapset_id == 24
    assert beatmap.mode == "taiko"
    assert beatmap.version == "Oni"
    assert beatmap.official_status == "loved"
    assert beatmap.local_status_override == "ranked"
    assert beatmap.last_fetched_at == fetched_at


def test_make_fetch_state_and_file_attachment_factories_are_typed() -> None:
    state = make_beatmap_fetch_state_factory(
        target_type="file",
        target_key="2000",
        status="failed",
        last_error="checksum_mismatch",
    )
    attachment = make_beatmap_file_attachment_factory(blob_id=99, source="mirror")

    assert state.target_type == "file"
    assert state.target_key == "2000"
    assert state.status == "failed"
    assert state.last_error == "checksum_mismatch"
    assert attachment.beatmap_id == 2_000
    assert attachment.blob_id == 99
    assert attachment.checksum_md5 == "0123456789abcdef0123456789abcdef"
    assert attachment.source == "mirror"


def test_make_beatmap_file_body_matches_default_checksum() -> None:
    body = make_beatmap_file_body()

    assert body.md5 == "0123456789abcdef0123456789abcdef"
    assert body.content.startswith(b"osu file format")


@pytest.mark.parametrize(
    "kind",
    [
        FakeProviderResultKind.SUCCESS,
        FakeProviderResultKind.PENDING,
        FakeProviderResultKind.NOT_FOUND,
        FakeProviderResultKind.RATE_LIMITED,
        FakeProviderResultKind.TIMEOUT,
        FakeProviderResultKind.SERVER_FAILURE,
    ],
)
async def test_fake_metadata_provider_returns_configured_result(
    kind: FakeProviderResultKind,
) -> None:
    provider = FakeBeatmapMetadataProvider(
        by_beatmap_id={2_000: make_metadata_provider_response(kind=kind)}
    )

    result = await provider.lookup_by_beatmap_id(2_000)

    assert result.kind is kind
    assert provider.calls == [("beatmap_id", "2000")]


@pytest.mark.parametrize(
    "error_kind",
    [
        FakeProviderErrorKind.RATE_LIMITED,
        FakeProviderErrorKind.TIMEOUT,
        FakeProviderErrorKind.SERVER_FAILURE,
        FakeProviderErrorKind.CHECKSUM_MISMATCH,
    ],
)
async def test_fake_file_provider_returns_failure_scenarios(
    error_kind: FakeProviderErrorKind,
) -> None:
    response = make_file_provider_response(error_kind=error_kind)
    provider = FakeBeatmapFileProvider(by_beatmap_id={2_000: response})

    result = await provider.fetch_osu_file(2_000)

    assert result.error_kind is error_kind
    assert result.body is None
    assert provider.calls == [2_000]


async def test_fake_file_provider_returns_successful_body() -> None:
    provider = FakeBeatmapFileProvider(
        by_beatmap_id={
            2_000: make_file_provider_response(
                body=make_beatmap_file_body(
                    content=b"body",
                    md5="841a2d689ad86bd1611447453c22c6fc",
                )
            )
        }
    )

    result = await provider.fetch_osu_file(2_000)

    assert result.kind is FakeProviderResultKind.SUCCESS
    assert result.body is not None
    assert result.body.content == b"body"
    assert result.body.md5 == "841a2d689ad86bd1611447453c22c6fc"
