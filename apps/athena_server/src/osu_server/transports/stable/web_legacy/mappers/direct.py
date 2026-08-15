"""Stable legacy osu!direct queryをdomain requestへ変換するmodule."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from osu_server.domain.beatmaps import DirectPointLookupRequest, DirectSearchRequest
from osu_server.domain.compatibility.stable.direct import (
    STABLE_DIRECT_PAGE_SIZE,
    StableDirectSearchParseError,
    stable_direct_listing_from_query,
    stable_direct_mode_from_wire,
    stable_direct_page_from_wire,
    stable_direct_statuses_from_wire,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(slots=True, frozen=True)
class StableDirectSearchParseResult:
    """Stable direct search parserのsanitize済みresultを表す.

    Attributes:
        request (DirectSearchRequest | None): 解析済み検索request. 失敗時はNone.
        error (StableDirectSearchParseError | None): 失敗時のsanitize済み理由.

    Notes:
        query全体, username, password hashは保持しない. requestもreprから除外する.
    """

    request: DirectSearchRequest | None = field(default=None, repr=False)
    error: StableDirectSearchParseError | None = None


class StableDirectPointLookupParseError(StrEnum):
    """Stable osu!direct point lookup queryのsanitize済みparse errorを表す.

    Attributes:
        MISSING_TARGET (StableDirectPointLookupParseError): `s`, `b`, `c` targetがない.
        MALFORMED_TARGET (StableDirectPointLookupParseError): target値をdomain requestにできない.
    """

    MISSING_TARGET = "missing_target"
    MALFORMED_TARGET = "malformed_target"


@dataclass(slots=True, frozen=True)
class StableDirectPointLookupParseResult:
    """Stable direct point lookup parserのsanitize済みresultを表す.

    Attributes:
        request (DirectPointLookupRequest | None): 解析済みlookup request. 失敗時はNone.
        error (StableDirectPointLookupParseError | None): 失敗時のsanitize済み理由.

    Notes:
        query全体, username, password hashは保持しない. requestもreprから除外する.
    """

    request: DirectPointLookupRequest | None = field(default=None, repr=False)
    error: StableDirectPointLookupParseError | None = None


class StableDirectSearchQueryParser:
    """Stable osu-search.php queryをtyped direct search requestへ変換する."""

    def parse(
        self,
        query: Mapping[str, str],
        *,
        authenticated_user_id: int,
    ) -> StableDirectSearchParseResult:
        """Stable direct search queryをsanitize済みparse resultへ変換する.

        Args:
            query (Mapping[str, str]): Starlette QueryParams互換またはplain mappingのquery values.
            authenticated_user_id (int): legacy認証で解決済みのuser ID.

        Returns:
            StableDirectSearchParseResult: 有効なrequestまたはsanitize済みparse error.

        Notes:
            `u`と`h`はauth mapping専用のため保持しない. AR/OD/CS/HPなどのsong select filterは
            stable osu!direct検索queryとして扱わない.
        """
        statuses = stable_direct_statuses_from_wire(query.get("r"))
        if isinstance(statuses, StableDirectSearchParseError):
            return StableDirectSearchParseResult(error=statuses)

        mode = stable_direct_mode_from_wire(query.get("m"))
        if isinstance(mode, StableDirectSearchParseError):
            return StableDirectSearchParseResult(error=mode)

        page = stable_direct_page_from_wire(query.get("p"))
        if isinstance(page, StableDirectSearchParseError):
            return StableDirectSearchParseResult(error=page)

        query_text, listing = stable_direct_listing_from_query(query.get("q") or "")
        return StableDirectSearchParseResult(
            request=DirectSearchRequest(
                authenticated_user_id=authenticated_user_id,
                query_text=query_text,
                statuses=statuses,
                mode=mode,
                page=page,
                page_size=STABLE_DIRECT_PAGE_SIZE,
                listing=listing,
            )
        )


class StableDirectPointLookupQueryParser:
    """Stable osu-search-set.php queryをtyped direct point lookup requestへ変換する."""

    def parse(
        self,
        query: Mapping[str, str],
        *,
        authenticated_user_id: int,
    ) -> StableDirectPointLookupParseResult:
        """Stable direct point lookup queryをsanitize済みparse resultへ変換する.

        Args:
            query (Mapping[str, str]): Starlette QueryParams互換またはplain mappingのquery values.
            authenticated_user_id (int): legacy認証で解決済みのuser ID.

        Returns:
            StableDirectPointLookupParseResult: 有効なrequestまたはsanitize済みparse error.

        Notes:
            `u`と`h`はauth mapping専用のため保持しない. stable HTTP endpointでは
            beatmapset ID (`s`), beatmap ID (`b`), checksum (`c`) を受ける.
        """
        target = _lookup_target(query)
        if target is None:
            return StableDirectPointLookupParseResult(
                error=StableDirectPointLookupParseError.MISSING_TARGET
            )
        target_field, target_value = target

        try:
            if target_field == "s":
                request = DirectPointLookupRequest.beatmapset_id(
                    authenticated_user_id=authenticated_user_id,
                    beatmapset_id=_required_positive_int(target_value),
                )
            elif target_field == "b":
                request = DirectPointLookupRequest.beatmap_id(
                    authenticated_user_id=authenticated_user_id,
                    beatmap_id=_required_positive_int(target_value),
                )
            else:
                request = DirectPointLookupRequest.checksum(
                    authenticated_user_id=authenticated_user_id,
                    checksum_md5=target_value,
                )
        except ValueError:
            return StableDirectPointLookupParseResult(
                error=StableDirectPointLookupParseError.MALFORMED_TARGET
            )
        return StableDirectPointLookupParseResult(request=request)


def _non_empty(value: str | None) -> str | None:
    """Query parameter値から空白だけの値を除外する.

    Args:
        value (str | None): query parameterの値.

    Returns:
        str | None: strip後に空でない値. 未指定または空ならNone.
    """
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _lookup_target(query: Mapping[str, str]) -> tuple[str, str] | None:
    """Point lookup queryから最初のtarget fieldを返す.

    Args:
        query (Mapping[str, str]): stable clientが送るquery parameter mapping.

    Returns:
        tuple[str, str] | None: `s`, `b`, `c`の順で見つけたtarget fieldと値.
    """
    for target_field in ("s", "b", "c"):
        target_value = _non_empty(query.get(target_field))
        if target_value is not None:
            return (target_field, target_value)
    return None


def _required_positive_int(value: str) -> int:
    """Stable direct ID fieldを正の整数へ変換する.

    Args:
        value (str): `s`または`b` query fieldの値.

    Returns:
        int: 正の整数.

    Raises:
        ValueError: 変換不能または0以下の場合.
    """
    parsed = int(value)
    if parsed <= 0:
        msg = "direct point lookup id must be positive"
        raise ValueError(msg)
    return parsed


__all__ = [
    "StableDirectPointLookupParseError",
    "StableDirectPointLookupParseResult",
    "StableDirectPointLookupQueryParser",
    "StableDirectSearchParseError",
    "StableDirectSearchParseResult",
    "StableDirectSearchQueryParser",
]
