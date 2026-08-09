"""osu!direct search backendが共有するinfrastructure定義を公開するpackage."""

from osu_server.infrastructure.search.direct_index_definition import (
    DIRECT_SEARCH_INDEX_DEFINITION,
    SearchIndexDefinition,
)

__all__ = [
    "DIRECT_SEARCH_INDEX_DEFINITION",
    "SearchIndexDefinition",
]
