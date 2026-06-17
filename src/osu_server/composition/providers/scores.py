"""Shared score providers for app and worker dependency graphs."""

from __future__ import annotations

from typing import final

from dishka import Provider, Scope

from osu_server.composition.providers._dishka import provide
from osu_server.infrastructure.crypto import ScoreCryptoService
from osu_server.repositories.interfaces.queries.beatmap_score_listing import (
    BeatmapScoreListingQueryRepository,
)
from osu_server.repositories.interfaces.queries.personal_bests import PersonalBestQueryRepository
from osu_server.services.queries.scores import BeatmapScoreListingQuery

_DISHKA_RUNTIME_HINTS = (BeatmapScoreListingQueryRepository, PersonalBestQueryRepository)


@final
class ScoreProviderSet(Provider):
    """Providers for shared score helpers and read-side score queries."""

    scope = Scope.APP

    @provide
    def score_crypto_service(self) -> ScoreCryptoService:
        return ScoreCryptoService()

    @provide
    def beatmap_score_listing_query(
        self,
        repository: BeatmapScoreListingQueryRepository,
        personal_bests: PersonalBestQueryRepository,
    ) -> BeatmapScoreListingQuery:
        return BeatmapScoreListingQuery(repository, personal_bests)
