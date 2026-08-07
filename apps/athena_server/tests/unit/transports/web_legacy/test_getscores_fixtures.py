"""Stable Getscores response fixtureのwire compatibility contractを検証する."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Iterator

import pytest

from athena_cli.stable_verification.catalog import list_evidence
from athena_cli.stable_verification.models import (
    EvidenceScope,
    EvidenceType,
    StableSurface,
)
from athena_cli.stable_verification.parsers import parse_getscores_response

_FIXTURE_DIR = Path(__file__).parents[3] / "fixtures" / "web_legacy" / "getscores"

# -- Header fixture file -> expected status value --------------------------


_SUBMITTED_FIXTURES: dict[str, int] = {
    "ranked_response.txt": 2,
    "loved_response.txt": 5,
    "qualified_response.txt": 4,
    "pending_response.txt": 0,
    "wip_response.txt": 0,
    "graveyard_response.txt": 0,
}
_ALL_FIXTURE_FILES = [*_SUBMITTED_FIXTURES, "not_submitted_response.txt"]


def _header_fixture_paths() -> Iterator[tuple[str, Path, int]]:
    """Submitted status fixtureのfile名, path, expected statusをyieldする.

    Yields:
        tuple[str, Path, int]: fixture filename, fixture path, expected Getscores status.
    """
    for filename, expected_status in _SUBMITTED_FIXTURES.items():
        yield filename, _FIXTURE_DIR / filename, expected_status


# ---------------------------------------------------------------------------
# Header fixture structural checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "fixture_path", "expected_status"),
    list(_header_fixture_paths()),
    ids=list(_SUBMITTED_FIXTURES),
)
def test_header_fixture_exists_and_is_nonempty(
    filename: str,  # noqa: ARG001  # pyright: ignore[reportUnusedParameter]
    fixture_path: Path,
    expected_status: int,  # noqa: ARG001  # pyright: ignore[reportUnusedParameter]
) -> None:
    """Submitted status fixture fileが存在しnon-emptyであるcontractを検証する.

    Args:
        filename (str): test caseを識別するfixture filename.
        fixture_path (Path): 読み取るfixture file path.
        expected_status (int): parameterizationで渡すexpected status. 本testでは未使用.

    Returns:
        None: fixture fileの存在とcontent lengthを確認して完了する.
    """
    assert fixture_path.is_file(), f"Missing fixture: {fixture_path}"
    content = fixture_path.read_text(encoding="utf-8")
    assert len(content) > 0, f"Empty fixture: {fixture_path}"


@pytest.mark.parametrize(
    ("filename", "fixture_path", "expected_status"),
    list(_header_fixture_paths()),
    ids=list(_SUBMITTED_FIXTURES),
)
def test_header_fixture_first_line_format(
    filename: str,
    fixture_path: Path,
    expected_status: int,
) -> None:
    """Header fixtureのfirst lineがstable Getscores formatを保つcontractを検証する.

    Args:
        filename (str): error messageへ含めるfixture filename.
        fixture_path (Path): 読み取るfixture file path.
        expected_status (int): first fieldへ期待するGetscores status.

    Returns:
        None: status, failed flag, beatmap ID, beatmapset ID, score countを確認して完了する.
    """
    content = fixture_path.read_text(encoding="utf-8")
    first_line, _, _ = content.partition("\n")

    parts = first_line.split("|")
    # Format: status|false|beatmap_id|beatmapset_id|0||
    # The trailing || produces two empty tail entries after split.
    assert len(parts) >= 5, f"Expected at least 5 pipe-separated fields, got: {parts!r}"
    assert parts[1] == "false", f"Failed flag must be 'false', got: {parts[1]!r}"
    assert parts[4] == "0", f"Score count must be 0, got: {parts[4]!r}"

    fixture_status = int(parts[0])
    assert fixture_status == expected_status, (
        f"Status in {filename}: expected {expected_status}, got {fixture_status}"
    )

    beatmap_id = int(parts[2])
    assert beatmap_id > 0, f"beatmap_id must be positive, got: {beatmap_id}"

    beatmapset_id = int(parts[3])
    assert beatmapset_id > 0, f"beatmapset_id must be positive, got: {beatmapset_id}"


@pytest.mark.parametrize(
    ("filename", "fixture_path", "expected_status"),
    list(_header_fixture_paths()),
    ids=list(_SUBMITTED_FIXTURES),
)
def test_header_fixture_line_structure(
    filename: str,  # noqa: ARG001  # pyright: ignore[reportUnusedParameter]
    fixture_path: Path,
    expected_status: int,  # noqa: ARG001  # pyright: ignore[reportUnusedParameter]
) -> None:
    """Header fixtureが4 data lineとterminal blank entryを持つcontractを検証する.

    Args:
        filename (str): test caseを識別するfixture filename.
        fixture_path (Path): 読み取るfixture file path.
        expected_status (int): parameterizationで渡すexpected status. 本testでは未使用.

    Returns:
        None: status, offset, display, rating, trailing placeholderを確認して完了する.
    """
    content = fixture_path.read_text(encoding="utf-8")
    lines = content.split("\n")

    assert len(lines) == 5, (
        f"Expected 5 entries from split('\\n') "
        f"(4 data lines + trailing empty from terminal LF), "
        f"got {len(lines)}: {lines!r}"
    )

    # Line 2: beatmap offset (integer)
    assert lines[1].isdigit(), f"Line 2 must be a numeric offset, got: {lines[1]!r}"

    # Line 3: display title with bbcode prefix
    assert lines[2].startswith("[bold:0,size:20]"), (
        f"Line 3 must start with [bold:0,size:20], got: {lines[2]!r}"
    )

    # Line 4: rating (integer)
    assert lines[3].isdigit(), f"Line 4 must be a numeric rating, got: {lines[3]!r}"

    # Trailing entry from terminal LF: represents blank placeholder section
    assert lines[4] == "", (
        f"Trailing entry must be empty (blank section placeholder), got: {lines[4]!r}"
    )


@pytest.mark.parametrize(
    ("filename", "fixture_path", "expected_status"),
    list(_header_fixture_paths()),
    ids=list(_SUBMITTED_FIXTURES),
)
def test_header_fixture_display_line_has_artist_title(
    filename: str,  # noqa: ARG001  # pyright: ignore[reportUnusedParameter]
    fixture_path: Path,
    expected_status: int,  # noqa: ARG001  # pyright: ignore[reportUnusedParameter]
) -> None:
    """Header fixtureのdisplay lineがartistとtitleを持つcontractを検証する.

    Args:
        filename (str): test caseを識別するfixture filename.
        fixture_path (Path): 読み取るfixture file path.
        expected_status (int): parameterizationで渡すexpected status. 本testでは未使用.

    Returns:
        None: bbcode prefix後のartistとtitleがnon-emptyであることを確認して完了する.
    """
    content = fixture_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    display = lines[2]

    # Strip the bbcode prefix
    body = display.removeprefix("[bold:0,size:20]")

    parts = body.split("|")
    assert len(parts) >= 2, (
        f"Display line body must contain 'artist|title' with at least one pipe, got: {body!r}"
    )
    assert parts[0], f"Artist must be non-empty in display line: {body!r}"
    assert parts[1], f"Title must be non-empty in display line: {body!r}"


# ---------------------------------------------------------------------------
# Short response fixture checks
# ---------------------------------------------------------------------------


def test_not_submitted_fixture_is_short_response() -> None:
    """NotSubmitted fixtureがheaderなしのshort responseとなるcontractを検証する.

    Returns:
        None: bodyがexact -1|falseであることを確認して完了する.
    """
    fixture_path = _FIXTURE_DIR / "not_submitted_response.txt"
    content = fixture_path.read_text(encoding="utf-8").rstrip("\n")

    assert content == "-1|false", (
        f"NotSubmitted fixture must be exactly '-1|false', got: {content!r}"
    )


def test_fixtures_are_referenced_by_stable_verification_catalog() -> None:
    """Getscores fixture testがstable verification catalogから参照されるcontractを検証する.

    Returns:
        None: mandatory golden fixture evidenceが本fileを参照することを確認して完了する.
    """
    evidence = list_evidence(StableSurface.GETSCORES)
    expected_reference = (
        "apps/athena_server/tests/unit/transports/web_legacy/test_getscores_fixtures.py"
    )

    assert any(
        entry.evidence_type is EvidenceType.GOLDEN_FIXTURE
        and entry.scope is EvidenceScope.MANDATORY
        and entry.reference == expected_reference
        for entry in evidence
    )


@pytest.mark.parametrize("fixture_filename", _ALL_FIXTURE_FILES)
def test_fixture_parses_with_stable_verification_parser(fixture_filename: str) -> None:
    """各Getscores fixtureがstable verification parserでdecodeできるcontractを検証する.

    Args:
        fixture_filename (str): decodeするfixture filename.

    Returns:
        None: parse errorなしでresponseが得られることを確認して完了する.
    """
    fixture_path = _FIXTURE_DIR / fixture_filename

    parsed = parse_getscores_response(fixture_path.read_bytes())

    assert parsed.error is None
    assert parsed.response is not None


# ---------------------------------------------------------------------------
# Chunk framing absence (all fixtures)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture_filename", _ALL_FIXTURE_FILES)
def test_fixture_has_no_chunk_framing(fixture_filename: str) -> None:
    """FixtureがHTTP chunk framing markerを含まないcontractを検証する.

    Args:
        fixture_filename (str): framing absenceを検証するfixture filename.

    Returns:
        None: chunk size lineとterminal chunk markerがないことを確認して完了する.
    """
    fixture_path = _FIXTURE_DIR / fixture_filename
    content = fixture_path.read_text(encoding="utf-8")

    # Chunk framing lines look like hexadecimal numbers followed by CRLF
    lines = content.split("\n")
    for i, line in enumerate(lines):
        stripped = line.rstrip("\r")
        assert not _looks_like_chunk_header(stripped), (
            f"Line {i} of {fixture_filename} looks like a chunk size marker: {stripped!r}"
        )

    # Final chunk marker "0\r\n\r\n" at the very end
    assert not content.rstrip("\r\n").endswith("\r\n0"), (
        f"Fixture {fixture_filename} may contain trailing chunk terminator"
    )


def _looks_like_chunk_header(line: str) -> bool:
    """LineがHTTP chunk size markerに見えるかを判定する.

    Args:
        line (str): CRLFを除去したfixture line.

    Returns:
        bool: 2文字以上のhex-only lineならTrue. offsetの単一文字0はFalse.
    """
    if not line:
        return False
    if len(line) <= 1:
        return False
    try:
        int(line, 16)  # pyright: ignore[reportUnusedCallResult]
    except ValueError:
        return False
    return line.isalnum()


# ---------------------------------------------------------------------------
# Official-fixture precedence over bancho.py differences
# ---------------------------------------------------------------------------


def test_pending_wip_graveyard_are_header_responses_not_short() -> None:
    """Pending, WIP, Graveyardがshortではなくheader responseとなるcontractを検証する.

    Returns:
        None: official fixtureのmulti-line bodyとstatus 0を確認して完了する.
    """
    for fixture_filename in ("pending_response.txt", "wip_response.txt", "graveyard_response.txt"):
        fixture_path = _FIXTURE_DIR / fixture_filename
        content = fixture_path.read_text(encoding="utf-8")
        lines = content.splitlines()

        assert len(lines) >= 4, (
            f"{fixture_filename} must be a multi-line header response "
            f"(official behavior), not a short response (bancho.py behavior). "
            f"Got {len(lines)} lines."
        )
        # Status must be 0 (not a short response body)
        first_field = lines[0].split("|")[0]
        assert first_field == "0", (
            f"{fixture_filename} status must be 0 (Pending/WIP/Graveyard), got: {first_field}"
        )


def test_ranked_status_is_2_not_4() -> None:
    """RankedがGetscores status 2へmapされるcontractを検証する.

    Returns:
        None: ranked fixtureのfirst fieldが2であることを確認して完了する.
    """
    content = (_FIXTURE_DIR / "ranked_response.txt").read_text(encoding="utf-8")
    status = int(content.split("|")[0])
    assert status == 2, f"Ranked getscores status must be 2, got: {status}"


# ---------------------------------------------------------------------------
# Converted mode requests fixture
# ---------------------------------------------------------------------------


def test_converted_mode_requests_fixture_exists_and_valid() -> None:
    """Converted mode request fixtureがvalid JSON request arrayとなるcontractを検証する.

    Returns:
        None: required description, query, status, identity fieldを確認して完了する.
    """
    fixture_path = _FIXTURE_DIR / "converted_mode_requests.json"
    assert fixture_path.is_file(), "converted_mode_requests.json is missing"

    data = cast("list[dict[str, object]]", json.loads(fixture_path.read_text(encoding="utf-8")))
    assert len(data) >= 1, "Must have at least one request example"

    for entry in data:
        assert "description" in entry, f"Entry missing 'description': {entry}"
        assert "query" in entry, f"Entry missing 'query': {entry}"
        assert "expected_status" in entry, f"Entry missing 'expected_status': {entry}"
        query = cast("dict[str, object]", entry["query"])
        assert "m" in query, f"Query missing 'm' (mode): {entry}"
        assert "c" in query or "f" in query, f"Query missing identity field: {entry}"


def test_converted_mode_requests_cover_all_modes() -> None:
    """Converted mode fixtureがm=0からm=3の全rulesetをcoverするcontractを検証する.

    Returns:
        None: osu, taiko, catch, maniaのmode setを確認して完了する.
    """
    fixture_path = _FIXTURE_DIR / "converted_mode_requests.json"
    data = cast("list[dict[str, object]]", json.loads(fixture_path.read_text(encoding="utf-8")))

    modes_present = {
        int(cast("str", cast("dict[str, object]", entry["query"])["m"])) for entry in data
    }
    expected_modes = {0, 1, 2, 3}
    missing = expected_modes - modes_present
    assert not missing, (
        f"Converted mode fixtures missing modes: {sorted(missing)}. "
        f"Present: {sorted(modes_present)}"
    )


def test_converted_mode_requests_same_status() -> None:
    """同一beatmapのconverted mode requestが同じexpected statusを持つcontractを検証する.

    Returns:
        None: 全fixture entryのstatus集合が1値だけであることを確認して完了する.
    """
    fixture_path = _FIXTURE_DIR / "converted_mode_requests.json"
    data = cast("list[dict[str, object]]", json.loads(fixture_path.read_text(encoding="utf-8")))

    statuses = {entry["expected_status"] for entry in data}
    assert len(statuses) == 1, (
        f"All converted mode requests for the same beatmap must have "
        f"the same expected_status, got: {statuses}"
    )


# ---------------------------------------------------------------------------
# Fixture identity field round-trip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "fixture_path"),
    [
        ("not_submitted_response.txt", _FIXTURE_DIR / "not_submitted_response.txt"),
    ],
)
def test_short_response_has_no_beatmap_identity_leak(
    filename: str,
    fixture_path: Path,
) -> None:
    """Short responseがbeatmap identity fieldを漏らさないcontractを検証する.

    Args:
        filename (str): error messageへ含めるfixture filename.
        fixture_path (Path): 読み取るshort response fixture path.

    Returns:
        None: failed flag後にidentity fieldがないことを確認して完了する.
    """
    content = fixture_path.read_text(encoding="utf-8")
    assert "|false|" not in content.rstrip("\n"), (
        f"Short response {filename} must not contain beatmap identity fields"
    )


# ---------------------------------------------------------------------------
# Wire format: no source/provenance fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture_filename", _ALL_FIXTURE_FILES)
def test_fixture_has_no_provenance_fields(fixture_filename: str) -> None:
    """Fixtureがinternal provenance fieldをwire bodyへ露出しないcontractを検証する.

    Args:
        fixture_filename (str): provenance absenceを検証するfixture filename.

    Returns:
        None: source, verification, fetch state fieldがないことを確認して完了する.
    """
    content = (_FIXTURE_DIR / fixture_filename).read_text(encoding="utf-8")
    forbidden = ("_source:", "_verified:", "_policy:", "_fetch_state:", "_override:")
    for field in forbidden:
        assert field not in content, (
            f"Fixture {fixture_filename} contains internal provenance field: {field!r}"
        )


# ---------------------------------------------------------------------------
# MVP scope: no score rows or personal best rows
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "fixture_path", "expected_status"),
    list(_header_fixture_paths()),
    ids=list(_SUBMITTED_FIXTURES),
)
def test_header_fixture_has_no_score_rows(
    filename: str,
    fixture_path: Path,
    expected_status: int,  # noqa: ARG001  # pyright: ignore[reportUnusedParameter]
) -> None:
    """MVP header fixtureがempty score row sectionを持つcontractを検証する.

    Args:
        filename (str): error messageへ含めるfixture filename.
        fixture_path (Path): 読み取るheader fixture path.
        expected_status (int): parameterizationで渡すexpected status. 本testでは未使用.

    Returns:
        None: personal bestとscore row placeholderがemptyであることを確認して完了する.
    """
    content = fixture_path.read_text(encoding="utf-8")
    lines = content.split("\n")
    # Entry at index 4 is the trailing empty from terminal LF,
    # representing the blank personal-best and score-rows placeholders.
    assert lines[4] == "", f"Trailing entry must be empty (score rows placeholder): {filename}"
    assert len([e for e in lines if e]) == 4, (
        f"Expected exactly 4 non-empty entries (data lines), got {len([e for e in lines if e])}"
    )
