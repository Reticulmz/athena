"""osu!direct catalog work kind を定義する."""

from __future__ import annotations

from enum import StrEnum


class DirectCatalogWorkKind(StrEnum):
    """共有upstream budgetを使うosu!direct work種別を表す.

    Attributes:
        POINT_LOOKUP (DirectCatalogWorkKind): stable requestのpoint lookup用work.
        FEED_SYNC (DirectCatalogWorkKind): background catalog feed同期work.
        ID_RANGE_CRAWL (DirectCatalogWorkKind): background id range crawl work.
    """

    POINT_LOOKUP = "point_lookup"
    FEED_SYNC = "feed_sync"
    ID_RANGE_CRAWL = "id_range_crawl"


__all__ = [
    "DirectCatalogWorkKind",
]
