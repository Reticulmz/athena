"""GetscoresQueryParser — convert stable getscores query params into typed request.

Accepts raw query mapping, separates identity fields from parse-only controls,
and emits parse warnings for malformed non-identity fields without blocking
known identity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

_MD5_HEX_PATTERN = re.compile(r"^[0-9a-fA-F]{32}$")


class GetscoresParseError(Enum):
    MISSING_IDENTITY = "missing_identity"
    INVALID_CHECKSUM = "invalid_checksum"


class GetscoresParseWarning(Enum):
    INVALID_MODE = "invalid_mode"
    INVALID_MODS = "invalid_mods"
    INVALID_LEADERBOARD_TYPE = "invalid_leaderboard_type"
    INVALID_LEADERBOARD_VERSION = "invalid_leaderboard_version"
    INVALID_SONG_SELECT_FLAG = "invalid_song_select_flag"
    INVALID_ANTI_CHEAT_SIGNAL = "invalid_anti_cheat_signal"
    INVALID_BEATMAPSET_ID_HINT = "invalid_beatmapset_id_hint"


@dataclass(slots=True, frozen=True)
class GetscoresRequest:
    checksum_md5: str | None
    filename: str | None
    beatmapset_id_hint: int | None
    mode: int | None
    mods: int | None
    leaderboard_type: int | None
    leaderboard_version: int | None
    song_select: bool | None
    anti_cheat_signal: bool = False
    parse_warnings: tuple[GetscoresParseWarning, ...] = ()


@dataclass(slots=True, frozen=True)
class GetscoresParseResult:
    request: GetscoresRequest | None = None
    error: GetscoresParseError | None = None


class GetscoresQueryParser:
    """Converts stable query params into a typed single-map request.

    Identity fields (c, f, i) are separated from parse-only controls
    (m, mods, v, vv, s, a).  Malformed non-identity fields produce
    parse warnings without blocking a known identity.
    """

    def parse(self, query: Mapping[str, str]) -> GetscoresParseResult:
        """Parse a raw query mapping into a GetscoresParseResult.

        Args:
            query: Raw query parameter mapping (e.g. from Starlette request.query_params).

        Returns:
            GetscoresParseResult with parsed request or parse error.
        """
        warnings: list[GetscoresParseWarning] = []

        # -- Identity fields -------------------------------------------------
        checksum_raw = query.get("c")
        filename = query.get("f") or None
        beatmapset_id_hint = self._parse_int(
            query.get("i"), warnings, GetscoresParseWarning.INVALID_BEATMAPSET_ID_HINT
        )

        # Validate checksum format
        checksum_md5: str | None = None
        if checksum_raw is not None:
            if _MD5_HEX_PATTERN.match(checksum_raw):
                checksum_md5 = checksum_raw.lower()
            else:
                return GetscoresParseResult(error=GetscoresParseError.INVALID_CHECKSUM)

        # -- Parse-only controls ---------------------------------------------
        mode = self._parse_int(query.get("m"), warnings, GetscoresParseWarning.INVALID_MODE)
        mods = self._parse_int(query.get("mods"), warnings, GetscoresParseWarning.INVALID_MODS)
        leaderboard_type = self._parse_int(
            query.get("v"), warnings, GetscoresParseWarning.INVALID_LEADERBOARD_TYPE
        )
        leaderboard_version = self._parse_int(
            query.get("vv"), warnings, GetscoresParseWarning.INVALID_LEADERBOARD_VERSION
        )
        song_select = self._parse_bool(
            query.get("s"), warnings, GetscoresParseWarning.INVALID_SONG_SELECT_FLAG
        )

        # -- Anti-cheat signal -----------------------------------------------
        anti_cheat_signal = "a" in query

        # -- Identity sufficiency check --------------------------------------
        has_checksum = checksum_md5 is not None
        has_fallback = filename is not None and beatmapset_id_hint is not None
        if not has_checksum and not has_fallback:
            return GetscoresParseResult(error=GetscoresParseError.MISSING_IDENTITY)

        return GetscoresParseResult(
            request=GetscoresRequest(
                checksum_md5=checksum_md5,
                filename=filename,
                beatmapset_id_hint=beatmapset_id_hint,
                mode=mode,
                mods=mods,
                leaderboard_type=leaderboard_type,
                leaderboard_version=leaderboard_version,
                song_select=song_select,
                anti_cheat_signal=anti_cheat_signal,
                parse_warnings=tuple(warnings),
            )
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_int(
        raw: str | None,
        warnings: list[GetscoresParseWarning],
        warning_kind: GetscoresParseWarning,
    ) -> int | None:
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            warnings.append(warning_kind)
            return None

    @staticmethod
    def _parse_bool(
        raw: str | None,
        warnings: list[GetscoresParseWarning],
        warning_kind: GetscoresParseWarning,
    ) -> bool | None:
        if raw is None:
            return None
        try:
            return bool(int(raw))
        except ValueError:
            warnings.append(warning_kind)
            return None
