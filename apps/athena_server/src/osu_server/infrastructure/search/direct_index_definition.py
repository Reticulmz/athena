"""osu!direct検索indexの共有field宣言を定義するmodule."""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class SearchIndexDefinition:
    """osu!direct検索documentでindex backendへ渡すfield集合を表す.

    Attributes:
        searchable_fields (tuple[str, ...]): text検索対象として明示されたfield名.
        filterable_fields (tuple[str, ...]): 絞り込み対象として明示されたfield名.
        sortable_fields (tuple[str, ...]): 並び替え対象として明示されたfield名.
        displayed_fields (tuple[str, ...]): 外部indexから取り出してよい最小field名.
        definition_version (int): field宣言変更時にbackend再検証へ使うversion.
    """

    searchable_fields: tuple[str, ...]
    filterable_fields: tuple[str, ...]
    sortable_fields: tuple[str, ...]
    displayed_fields: tuple[str, ...]
    definition_version: int


DIRECT_SEARCH_INDEX_DEFINITION: Final = SearchIndexDefinition(
    searchable_fields=(
        "artist",
        "title",
        "creator",
        "source",
        "tags",
        "difficulty_names",
        "artist_unicode",
        "title_unicode",
    ),
    filterable_fields=(
        "status",
        "modes",
        "beatmapset_id",
    ),
    sortable_fields=(
        "last_update_at",
        "beatmapset_id",
    ),
    displayed_fields=(
        "beatmapset_id",
        "document_version",
    ),
    definition_version=1,
)

__all__ = [
    "DIRECT_SEARCH_INDEX_DEFINITION",
    "SearchIndexDefinition",
]
