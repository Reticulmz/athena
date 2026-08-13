"""stable web legacy transportのproviderを構成する."""

from __future__ import annotations

from typing import final

from dishka import Provider, Scope

from osu_server.composition.providers._dishka import provide
from osu_server.config import AppConfig
from osu_server.domain.beatmaps import DirectAccessPolicy, DirectAccessPolicyMode
from osu_server.infrastructure.crypto import ScoreCryptoService
from osu_server.infrastructure.messaging.local import LocalEventBus
from osu_server.infrastructure.parsers.multipart_parser import MultipartLimits
from osu_server.repositories.interfaces.queries.beatmap_leaderboards import (
    BeatmapLeaderboardQueryRepository,
)
from osu_server.repositories.interfaces.queries.beatmap_score_listing import (
    BeatmapScoreListingQueryRepository,
)
from osu_server.repositories.interfaces.queries.users import UserQueryRepository
from osu_server.services.commands.beatmaps import (
    RecordDirectSearchCoverageUseCase,
    RequestBeatmapFileWarmupUseCase,
)
from osu_server.services.commands.identity import RegisterUserCommandUseCase
from osu_server.services.commands.scores import (
    ProcessScoreSubmissionUseCase,
    ReplayDownloadAccountingPublisher,
)
from osu_server.services.queries.beatmaps import DirectPointLookupQuery, DirectSearchQuery
from osu_server.services.queries.beatmaps.mirror import BeatmapMirrorService
from osu_server.services.queries.identity import (
    GetFriendEligibleUserIdsQuery,
    PermissionService,
    SessionCredentialsQueryUseCase,
)
from osu_server.services.queries.scores import (
    BeatmapLeaderboardQuery,
    BeatmapScoreListingQuery,
    CurrentUserStatsQuery,
    ReplayDownloadQuery,
)
from osu_server.transports.stable.web_legacy.direct import (
    StableDirectPointLookupHandler,
    StableDirectSearchHandler,
)
from osu_server.transports.stable.web_legacy.direct_access import StableDirectAccessGate
from osu_server.transports.stable.web_legacy.getscores import GetscoresHandler
from osu_server.transports.stable.web_legacy.mappers import (
    GetscoresQueryParser,
    GetscoresStatusMapper,
    ReplayDownloadQueryParser,
    StableDirectPointLookupQueryParser,
    StableDirectSearchQueryParser,
    StableScorePayloadParser,
    StableScoreSubmitDecoder,
    StableScoreSubmitMapper,
)
from osu_server.transports.stable.web_legacy.registration import RegistrationHandler
from osu_server.transports.stable.web_legacy.replay_download import ReplayDownloadHandler
from osu_server.transports.stable.web_legacy.score_submit import ScoreSubmitHandler

_DISHKA_RUNTIME_HINTS = (
    AppConfig,
    BeatmapLeaderboardQueryRepository,
    BeatmapLeaderboardQuery,
    DirectAccessPolicy,
    DirectPointLookupQuery,
    DirectSearchQuery,
    BeatmapMirrorService,
    BeatmapScoreListingQueryRepository,
    BeatmapScoreListingQuery,
    GetFriendEligibleUserIdsQuery,
    PermissionService,
    ProcessScoreSubmissionUseCase,
    CurrentUserStatsQuery,
    LocalEventBus,
    RegisterUserCommandUseCase,
    RequestBeatmapFileWarmupUseCase,
    RecordDirectSearchCoverageUseCase,
    ReplayDownloadAccountingPublisher,
    ReplayDownloadQuery,
    ReplayDownloadQueryParser,
    ReplayDownloadHandler,
    ScoreCryptoService,
    SessionCredentialsQueryUseCase,
    StableDirectAccessGate,
    StableDirectPointLookupHandler,
    StableDirectPointLookupQueryParser,
    StableDirectSearchHandler,
    StableDirectSearchQueryParser,
    StableScorePayloadParser,
    StableScoreSubmitDecoder,
    UserQueryRepository,
)


@final
class StableWebLegacyProviderSet(Provider):
    """stable legacy web handler,parser,mapperをAPP scopeで登録する.

    Attributes:
        scope (Scope): app container内で共有するDishkaのAPP scope.
    """

    scope = Scope.APP

    @provide
    def registration_handler(
        self,
        register_user_command: RegisterUserCommandUseCase,
    ) -> RegistrationHandler:
        """Legacy registration endpoint handlerをuser registration commandで構成する.

        Args:
            register_user_command (RegisterUserCommandUseCase):
                registration inputを検証してuserを作成するcommand.

        Returns:
            RegistrationHandler: ``osu.$DOMAIN`` の ``POST /users`` とlocal fallbackの
                ``POST /web/users`` を処理するhandler.
        """
        return RegistrationHandler(register_user_command=register_user_command)

    @provide
    def getscores_parser(self) -> GetscoresQueryParser:
        """Legacy getscores query parameter parserを構成する.

        Returns:
            GetscoresQueryParser: ``/web/osu-osz2-getscores.php`` requestをquery inputへ
                変換するparser.
        """
        return GetscoresQueryParser()

    @provide
    def getscores_status_mapper(self) -> GetscoresStatusMapper:
        """Legacy getscores response status mapperを構成する.

        Returns:
            GetscoresStatusMapper: query結果をstable client互換statusとresponseへ変換するmapper.
        """
        return GetscoresStatusMapper()

    @provide
    def replay_download_parser(self) -> ReplayDownloadQueryParser:
        """Legacy replay download query parameter parserを構成する.

        Returns:
            ReplayDownloadQueryParser: ``/web/osu-getreplay.php`` requestをquery inputへ
                変換するparser.
        """
        return ReplayDownloadQueryParser()

    @provide
    def direct_access_policy(self, config: AppConfig) -> DirectAccessPolicy:
        """設定値からstable direct access policyを構成する.

        Args:
            config (AppConfig): osu!direct access policy設定を持つ実行時設定.

        Returns:
            DirectAccessPolicy: stable direct handlerがwork前に適用するpolicy.
        """
        return DirectAccessPolicy(DirectAccessPolicyMode(config.osu_direct_access_policy))

    @provide
    def direct_access_gate(
        self,
        auth_query: SessionCredentialsQueryUseCase,
        access_policy: DirectAccessPolicy,
    ) -> StableDirectAccessGate:
        """Stable direct access gateをlegacy auth queryとpolicyで構成する.

        Args:
            auth_query (SessionCredentialsQueryUseCase): legacy credentialを検証するquery.
            access_policy (DirectAccessPolicy): direct work前に適用するaccess policy.

        Returns:
            StableDirectAccessGate: search/point lookup handler共通のaccess gate.
        """
        return StableDirectAccessGate(auth_query=auth_query, access_policy=access_policy)

    @provide
    def direct_search_parser(self) -> StableDirectSearchQueryParser:
        """Stable direct search query parserを構成する.

        Returns:
            StableDirectSearchQueryParser: `/web/osu-search.php` queryをtyped requestへ変換する
                parser.
        """
        return StableDirectSearchQueryParser()

    @provide
    def direct_point_lookup_parser(self) -> StableDirectPointLookupQueryParser:
        """Stable direct point lookup query parserを構成する.

        Returns:
            StableDirectPointLookupQueryParser: `/web/osu-search-set.php` queryをtyped requestへ
                変換するparser.
        """
        return StableDirectPointLookupQueryParser()

    @provide
    def direct_search_handler(
        self,
        access_gate: StableDirectAccessGate,
        search_parser: StableDirectSearchQueryParser,
        search_query: DirectSearchQuery,
        coverage_recorder: RecordDirectSearchCoverageUseCase,
    ) -> StableDirectSearchHandler:
        """Stable direct search handlerをaccess gate,parser,queryで構成する.

        Args:
            access_gate (StableDirectAccessGate): direct search前の認証とaccess policy.
            search_parser (StableDirectSearchQueryParser): stable query parameter parser.
            search_query (DirectSearchQuery): direct search query use-case.
            coverage_recorder (RecordDirectSearchCoverageUseCase):
                upstream検索coverage保存command.

        Returns:
            StableDirectSearchHandler: `/web/osu-search.php`互換requestを処理するhandler.
        """
        return StableDirectSearchHandler(
            access_gate=access_gate,
            search_parser=search_parser,
            search_query=search_query,
            coverage_recorder=coverage_recorder,
        )

    @provide
    def direct_point_lookup_handler(
        self,
        access_gate: StableDirectAccessGate,
        point_lookup_parser: StableDirectPointLookupQueryParser,
        point_lookup_query: DirectPointLookupQuery,
    ) -> StableDirectPointLookupHandler:
        """Stable direct point lookup handlerをaccess gate,parser,queryで構成する.

        Args:
            access_gate (StableDirectAccessGate): point lookup前の認証とaccess policy.
            point_lookup_parser (StableDirectPointLookupQueryParser):
                stable query parameter parser.
            point_lookup_query (DirectPointLookupQuery): direct point lookup query use-case.

        Returns:
            StableDirectPointLookupHandler: `/web/osu-search-set.php`互換requestを処理するhandler.
        """
        return StableDirectPointLookupHandler(
            access_gate=access_gate,
            point_lookup_parser=point_lookup_parser,
            point_lookup_query=point_lookup_query,
        )

    @provide
    def getscores_handler(
        self,
        auth_query: SessionCredentialsQueryUseCase,
        getscores_parser: GetscoresQueryParser,
        getscores_repository: BeatmapScoreListingQueryRepository,
        leaderboards: BeatmapLeaderboardQueryRepository,
        user_repository: UserQueryRepository,
        permission_service: PermissionService,
        friend_eligible_user_ids_query: GetFriendEligibleUserIdsQuery,
        status_mapper: GetscoresStatusMapper,
        beatmap_resolver: BeatmapMirrorService,
        beatmap_file_warmup: RequestBeatmapFileWarmupUseCase,
        config: AppConfig,
    ) -> GetscoresHandler:
        """Legacy getscores handlerを認証,score query,beatmap warmup依存で構成する.

        Args:
            auth_query (SessionCredentialsQueryUseCase):
                legacy requestのsession credentialを検証するquery.
            getscores_parser (GetscoresQueryParser):
                query parameterをgetscores inputへ変換するparser.
            getscores_repository (BeatmapScoreListingQueryRepository):
                beatmap score listを読むrepository.
            leaderboards (BeatmapLeaderboardQueryRepository):
                materialized leaderboardを読むrepository.
            user_repository (UserQueryRepository): score ownerとviewer userを読むrepository.
            permission_service (PermissionService): viewerのscore visibility権限を解決するservice.
            friend_eligible_user_ids_query (GetFriendEligibleUserIdsQuery):
                friend限定scoreの可視userを取得するquery.
            status_mapper (GetscoresStatusMapper): query結果をstable responseへ変換するmapper.
            beatmap_resolver (BeatmapMirrorService): request対象beatmapを解決するservice.
            beatmap_file_warmup (RequestBeatmapFileWarmupUseCase):
                必要なbeatmap file取得を要求するcommand.
            config (AppConfig): metadata待機上限を持つ実行時設定.

        Returns:
            GetscoresHandler: legacy getscores requestを認証してresponseを返すhandler.

        Notes:
            このprovider内で ``BeatmapLeaderboardQuery`` と
            ``BeatmapScoreListingQuery`` を組み立てる.
        """
        leaderboard_query = BeatmapLeaderboardQuery(
            getscores_repository,
            leaderboards,
            user_repository=user_repository,
            permission_service=permission_service,
            friend_eligible_user_ids_query=friend_eligible_user_ids_query,
        )
        getscores_query = BeatmapScoreListingQuery(leaderboard_query)
        return GetscoresHandler(
            auth_query=auth_query,
            getscores_parser=getscores_parser,
            getscores_query=getscores_query,
            status_mapper=status_mapper,
            beatmap_resolver=beatmap_resolver,
            beatmap_file_warmup=beatmap_file_warmup,
            beatmap_metadata_wait_seconds=config.beatmap_default_bounded_wait_seconds,
        )

    @provide
    def stable_score_submit_mapper(self, config: AppConfig) -> StableScoreSubmitMapper:
        """Stable multipart score submit requestとresponseを変換するmapperを構成する.

        Args:
            config (AppConfig): multipart size上限とserver domainを持つ実行時設定.

        Returns:
            StableScoreSubmitMapper: request size limitとstable web base URLを持つmapper.

        Notes:
            base URLは ``_stable_web_base_url`` で ``https://osu.`` hostへ正規化する.
        """
        return StableScoreSubmitMapper(
            limits=MultipartLimits(
                total_body_size=config.max_request_body_size,
                replay_size=config.score_submit_max_replay_size,
                text_field_size=config.score_submit_max_text_field_size,
            ),
            stable_web_base_url=_stable_web_base_url(config.domain),
        )

    @provide
    def stable_score_payload_parser(self) -> StableScorePayloadParser:
        """Stable plaintext score payloadをparseするtransport parserを構成する.

        Returns:
            StableScorePayloadParser: plaintext payloadをparsed scoreへ変換するparser.

        Notes:
            parserはstable transportのdecode境界で使用し,command use-caseへ直接渡さない.
        """
        return StableScorePayloadParser()

    @provide
    def stable_score_submit_decoder(
        self,
        payload_decryptor: ScoreCryptoService,
        payload_parser: StableScorePayloadParser,
    ) -> StableScoreSubmitDecoder:
        """Stable score submit decoderをcrypto serviceとpayload parserで構成する.

        Args:
            payload_decryptor (ScoreCryptoService): encrypted stable payloadを復号するservice.
            payload_parser (StableScorePayloadParser):
                復号後plaintextをparsed scoreへ変換するparser.

        Returns:
            StableScoreSubmitDecoder: stable request mappingをparsed submission inputへ
                変換するdecoder.

        Notes:
            復号とwire payload parseはstable transport境界に閉じ込める.
        """
        return StableScoreSubmitDecoder(
            payload_decryptor=payload_decryptor,
            payload_parser=payload_parser,
        )

    @provide
    def score_submit_handler(
        self,
        submit_score_command: ProcessScoreSubmissionUseCase,
        mapper: StableScoreSubmitMapper,
        decoder: StableScoreSubmitDecoder,
        current_user_stats_query: CurrentUserStatsQuery,
        event_bus: LocalEventBus,
    ) -> ScoreSubmitHandler:
        """Stable score submit handlerをcommand,decoder,response依存で構成する.

        Args:
            submit_score_command (ProcessScoreSubmissionUseCase):
                正規化済みscore submissionを処理するcommand.
            mapper (StableScoreSubmitMapper):
                stable multipart requestとresponse bodyを変換するmapper.
            decoder (StableScoreSubmitDecoder): stable payloadをcommand inputへ変換するdecoder.
            current_user_stats_query (CurrentUserStatsQuery):
                completed response用statsを補完するquery.
            event_bus (LocalEventBus): score submit後のdomain eventを配送するlocal event bus.

        Returns:
            ScoreSubmitHandler: ``/web/osu-submit-modular-selector.php`` 互換requestを
                処理するhandler.

        Notes:
            providerは依存を組み立てるだけでrequest stateやDB sessionを保持しない.
        """
        return ScoreSubmitHandler(
            submit_score_command=submit_score_command,
            decoder=decoder,
            mapper=mapper,
            current_user_stats_query=current_user_stats_query,
            event_bus=event_bus,
        )

    @provide
    def replay_download_handler(
        self,
        auth_query: SessionCredentialsQueryUseCase,
        replay_download_parser: ReplayDownloadQueryParser,
        replay_download_query: ReplayDownloadQuery,
        replay_download_accounting: ReplayDownloadAccountingPublisher,
    ) -> ReplayDownloadHandler:
        """Legacy replay download handlerを認証,parser,query,accounting publisherで構成する.

        Args:
            auth_query (SessionCredentialsQueryUseCase):
                legacy requestのsession credentialを検証するquery.
            replay_download_parser (ReplayDownloadQueryParser):
                query parameterをreplay download inputへ変換するparser.
            replay_download_query (ReplayDownloadQuery): replay可視性とbodyを取得するquery.
            replay_download_accounting (ReplayDownloadAccountingPublisher):
                successful downloadを非同期計上するpublisher.

        Returns:
            ReplayDownloadHandler: ``/web/osu-getreplay.php`` 互換requestを処理するhandler.
        """
        return ReplayDownloadHandler(
            auth_query=auth_query,
            replay_download_parser=replay_download_parser,
            replay_download_query=replay_download_query,
            replay_download_accounting=replay_download_accounting,
        )


def _stable_web_base_url(domain: str) -> str:
    """Stable web endpoint用のosu subdomain URLを生成する.

    Args:
        domain (str): leading/trailing periodを含み得るAthenaのbase domain.

    Returns:
        str: ``https://osu.`` prefixとperiodを除去した ``domain`` を結合したbase URL.

    Notes:
        domainの妥当性検証は行わず,leading/trailing periodだけを除去する.
    """
    return f"https://osu.{domain.strip('.')}"
