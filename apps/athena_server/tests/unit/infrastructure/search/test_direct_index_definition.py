"""osu!direct search index field declarationの契約を検証するmodule."""

from osu_server.infrastructure.search.direct_index_definition import (
    DIRECT_SEARCH_INDEX_DEFINITION,
    SearchIndexDefinition,
)


def test_direct_search_index_definition_declares_initial_fields() -> None:
    """共有field宣言が初期の検索, 絞り込み, 並び替え, 表示fieldを固定することを検証する.

    Requirements 7.1-7.4に基づき, SQL validationと外部index settingsが同じ宣言を
    参照できるようにcode-ownedなfield集合を確認する.

    Returns:
        None: field集合が仕様どおりであることを検証して完了する.
    """
    assert isinstance(DIRECT_SEARCH_INDEX_DEFINITION, SearchIndexDefinition)
    assert DIRECT_SEARCH_INDEX_DEFINITION.searchable_fields == (
        "artist",
        "title",
        "creator",
        "source",
        "tags",
        "difficulty_names",
        "artist_unicode",
        "title_unicode",
    )
    assert DIRECT_SEARCH_INDEX_DEFINITION.filterable_fields == (
        "status",
        "modes",
        "beatmapset_id",
    )
    assert DIRECT_SEARCH_INDEX_DEFINITION.sortable_fields == (
        "last_update_at",
        "beatmapset_id",
    )
    assert DIRECT_SEARCH_INDEX_DEFINITION.displayed_fields == (
        "beatmapset_id",
        "document_version",
    )


def test_direct_search_index_definition_requires_explicit_revalidation() -> None:
    """field宣言の変更時にbackend再検証へ使うversionを持つことを検証する.

    Requirements 7.5-7.6に基づき, 任意metadataからfieldを推測せず, 宣言versionの
    変更をSQL validationと外部index settingsの再検証triggerとして扱えることを確認する.

    Returns:
        None: 明示fieldとversionの契約を検証して完了する.
    """
    declared_fields = (
        DIRECT_SEARCH_INDEX_DEFINITION.searchable_fields
        + DIRECT_SEARCH_INDEX_DEFINITION.filterable_fields
        + DIRECT_SEARCH_INDEX_DEFINITION.sortable_fields
        + DIRECT_SEARCH_INDEX_DEFINITION.displayed_fields
    )

    assert DIRECT_SEARCH_INDEX_DEFINITION.definition_version == 1
    assert "description" not in declared_fields
    assert "genre" not in declared_fields
