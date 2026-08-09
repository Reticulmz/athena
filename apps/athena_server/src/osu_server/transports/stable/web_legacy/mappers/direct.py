"""Stable legacy osu!direct queryをdomain requestへ変換するmodule."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from osu_server.domain.beatmaps import DirectSearchRequest
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


__all__ = [
    "StableDirectSearchParseError",
    "StableDirectSearchParseResult",
    "StableDirectSearchQueryParser",
]
