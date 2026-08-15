"""stable bancho transportのproviderを構成する."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from dishka import Provider, Scope

from osu_server.composition.providers._dishka import provide
from osu_server.config import AppConfig
from osu_server.domain.beatmaps import DirectAccessPolicyMode
from osu_server.domain.identity.system_users import SystemUserIdentity
from osu_server.infrastructure.country.interfaces import CountryResolver
from osu_server.infrastructure.messaging.local import LocalEventBus
from osu_server.infrastructure.state.interfaces.channel_state_store import ChannelStateStore
from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
from osu_server.infrastructure.state.interfaces.stable_user_status_store import (
    StableUserStatusStore,
)
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.services.commands.beatmaps import RequestBeatmapFileWarmupUseCase
from osu_server.services.commands.chat import (
    JoinChannelUseCase,
    LeaveChannelUseCase,
    SendChannelMessageUseCase,
    SendPrivateMessageUseCase,
)
from osu_server.services.commands.identity import (
    AddFriendUseCase,
    LoginCommandUseCase,
    RemoveFriendUseCase,
    UpdateFriendOnlyDmUseCase,
)
from osu_server.services.queries.chat import (
    ListAutojoinChannelsQuery,
    ListVisibleChannelsQuery,
)
from osu_server.services.queries.identity import (
    GetActiveSessionsByUserIdsQueryUseCase,
    ListActiveSessionsQueryUseCase,
    ListFriendIdsQuery,
)
from osu_server.services.queries.scores import CurrentUserStatsQuery
from osu_server.transports.stable.bancho.dispatch import PacketDispatcher
from osu_server.transports.stable.bancho.endpoint import BanchoEndpoint
from osu_server.transports.stable.bancho.handlers.chat import ChatHandlers
from osu_server.transports.stable.bancho.handlers.friends import FriendHandlers
from osu_server.transports.stable.bancho.handlers.lifecycle import LifecycleHandlers
from osu_server.transports.stable.bancho.handlers.presence import PresenceHandlers
from osu_server.transports.stable.bancho.handlers.stats import StatsRequestHandler
from osu_server.transports.stable.bancho.handlers.status import StatusChangeHandlers
from osu_server.transports.stable.bancho.listeners import setup_listeners
from osu_server.transports.stable.bancho.workflows.login import LoginWorkflow
from osu_server.transports.stable.bancho.workflows.login_response_builder import (
    LoginResponseBuilder,
)
from osu_server.transports.stable.bancho.workflows.polling import PollingWorkflow

_DISHKA_RUNTIME_HINTS = (
    AppConfig,
    ChannelStateStore,
    CountryResolver,
    LocalEventBus,
    JoinChannelUseCase,
    LeaveChannelUseCase,
    AddFriendUseCase,
    GetActiveSessionsByUserIdsQueryUseCase,
    ListActiveSessionsQueryUseCase,
    ListAutojoinChannelsQuery,
    ListFriendIdsQuery,
    ListVisibleChannelsQuery,
    LoginCommandUseCase,
    CurrentUserStatsQuery,
    PacketQueue,
    RequestBeatmapFileWarmupUseCase,
    RemoveFriendUseCase,
    SendChannelMessageUseCase,
    SendPrivateMessageUseCase,
    SessionStore,
    StableUserStatusStore,
    StatsRequestHandler,
    SystemUserIdentity,
    UpdateFriendOnlyDmUseCase,
)


@dataclass(frozen=True, slots=True)
class AppEventListeners:
    """app event listenerの登録完了を表すmarkerを持つ.

    Attributes:
        registered (bool): listener registrationが実行済みであることを示す固定値.
    """

    registered: bool = True


@final
class StableBanchoProviderSet(Provider):
    """stable banchoのlogin,polling,handler,listenerをAPP scopeで登録する.

    Attributes:
        scope (Scope): app container内で共有するDishkaのAPP scope.
    """

    scope = Scope.APP

    @provide
    def login_response_builder(
        self,
        visible_channels_query: ListVisibleChannelsQuery,
        autojoin_channels_query: ListAutojoinChannelsQuery,
        friend_ids_query: ListFriendIdsQuery,
        active_sessions_query: ListActiveSessionsQueryUseCase,
        current_user_stats_query: CurrentUserStatsQuery,
        stable_user_status_store: StableUserStatusStore,
        bot_identity: SystemUserIdentity,
        config: AppConfig,
    ) -> LoginResponseBuilder:
        """Stable login responseを組み立てるworkflow collaboratorを構成する.

        Args:
            visible_channels_query (ListVisibleChannelsQuery):
                login userに公開するchannelを列挙するquery.
            autojoin_channels_query (ListAutojoinChannelsQuery):
                login時のauto join channelを列挙するquery.
            friend_ids_query (ListFriendIdsQuery): login userのfriend IDを取得するquery.
            active_sessions_query (ListActiveSessionsQueryUseCase):
                online userのsessionを列挙するquery.
            current_user_stats_query (CurrentUserStatsQuery):
                login userのscore statsを取得するquery.
            stable_user_status_store (StableUserStatusStore): stable client向けstatusを読むstore.
            bot_identity (SystemUserIdentity): system botのidentityを表すvalue object.
            config (AppConfig): osu!direct access policyを持つ実行時設定.

        Returns:
            LoginResponseBuilder: channel,friend,presence,stats packetを含むlogin response
                builder.
        """
        return LoginResponseBuilder(
            visible_channels_query=visible_channels_query,
            autojoin_channels_query=autojoin_channels_query,
            friend_ids_query=friend_ids_query,
            active_sessions_query=active_sessions_query,
            current_user_stats_query=current_user_stats_query,
            stable_user_status_store=stable_user_status_store,
            bot_identity=bot_identity,
            grant_stable_supporter_feature_bit=(
                DirectAccessPolicyMode(config.osu_direct_access_policy)
                is DirectAccessPolicyMode.AUTHENTICATED
            ),
        )

    @provide
    def login_workflow(
        self,
        login_command: LoginCommandUseCase,
        country_resolver: CountryResolver,
        response_builder: LoginResponseBuilder,
        event_bus: LocalEventBus,
    ) -> LoginWorkflow:
        """Stable bancho login workflowをidentity,country,response依存で構成する.

        Args:
            login_command (LoginCommandUseCase): credentialを検証してsessionを開始するcommand.
            country_resolver (CountryResolver): request originからcountryを解決するadapter.
            response_builder (LoginResponseBuilder): successful login responseを組み立てるbuilder.
            event_bus (LocalEventBus): login lifecycle eventを配送するlocal event bus.

        Returns:
            LoginWorkflow: stable login requestを認可してpacket responseを生成するworkflow.
        """
        return LoginWorkflow(
            login_command=login_command,
            country_resolver=country_resolver,
            response_builder=response_builder,
            event_bus=event_bus,
        )

    @provide
    def lifecycle_handlers(
        self,
        session_store: SessionStore,
        event_bus: LocalEventBus,
    ) -> LifecycleHandlers:
        """Stable client lifecycle packet handler群を構成する.

        Args:
            session_store (SessionStore): login sessionを読み書きするvolatile store.
            event_bus (LocalEventBus): logoutなどのlifecycle eventを配送するlocal event bus.

        Returns:
            LifecycleHandlers: client lifecycle packetを登録するhandler group.
        """
        return LifecycleHandlers(session_store=session_store, event_bus=event_bus)

    @provide
    def chat_handlers(
        self,
        send_channel_message: SendChannelMessageUseCase,
        send_private_message: SendPrivateMessageUseCase,
        join_channel: JoinChannelUseCase,
        leave_channel: LeaveChannelUseCase,
        session_store: SessionStore,
        packet_queue: PacketQueue,
    ) -> ChatHandlers:
        """Stable chat packet handler群を送信commandとsession依存で構成する.

        Args:
            send_channel_message (SendChannelMessageUseCase): channel messageを配送するcommand.
            send_private_message (SendPrivateMessageUseCase): private messageを配送するcommand.
            join_channel (JoinChannelUseCase): channel参加を処理するcommand.
            leave_channel (LeaveChannelUseCase): channel退出を処理するcommand.
            session_store (SessionStore): packet senderのsessionを解決するvolatile store.
            packet_queue (PacketQueue): recipient向けpacketをenqueueするvolatile queue.

        Returns:
            ChatHandlers: stable chat関連packetを登録するhandler group.
        """
        return ChatHandlers(
            send_channel_message=send_channel_message,
            send_private_message=send_private_message,
            join_channel=join_channel,
            leave_channel=leave_channel,
            session_store=session_store,
            packet_queue=packet_queue,
        )

    @provide
    def friend_handlers(
        self,
        add_friend: AddFriendUseCase,
        remove_friend: RemoveFriendUseCase,
        update_friend_only_dm: UpdateFriendOnlyDmUseCase,
    ) -> FriendHandlers:
        """Stable friend packet handler群をfriend commandで構成する.

        Args:
            add_friend (AddFriendUseCase): friend追加を処理するcommand.
            remove_friend (RemoveFriendUseCase): friend削除を処理するcommand.
            update_friend_only_dm (UpdateFriendOnlyDmUseCase): friend-only DM設定を更新するcommand.

        Returns:
            FriendHandlers: friend追加,削除,DM設定packetを登録するhandler group.
        """
        return FriendHandlers(
            add_friend=add_friend,
            remove_friend=remove_friend,
            update_friend_only_dm=update_friend_only_dm,
        )

    @provide
    def status_change_handlers(
        self,
        beatmap_file_warmup: RequestBeatmapFileWarmupUseCase,
        current_user_stats_query: CurrentUserStatsQuery,
        active_sessions_query: ListActiveSessionsQueryUseCase,
        packet_queue: PacketQueue,
        stable_user_status_store: StableUserStatusStore,
    ) -> StatusChangeHandlers:
        """Stable user status変更packet handler群を構成する.

        Args:
            beatmap_file_warmup (RequestBeatmapFileWarmupUseCase):
                status内beatmap fileの取得を要求するcommand.
            current_user_stats_query (CurrentUserStatsQuery):
                status通知に含めるscore statsを取得するquery.
            active_sessions_query (ListActiveSessionsQueryUseCase):
                status通知先sessionを列挙するquery.
            packet_queue (PacketQueue): status packetをrecipientへenqueueするqueue.
            stable_user_status_store (StableUserStatusStore): stable client statusを更新するstore.

        Returns:
            StatusChangeHandlers: user status変更packetを登録するhandler group.
        """
        return StatusChangeHandlers(
            beatmap_file_warmup=beatmap_file_warmup,
            stable_user_status_store=stable_user_status_store,
            current_user_stats_query=current_user_stats_query,
            packet_queue=packet_queue,
            active_sessions_query=active_sessions_query,
        )

    @provide
    def presence_handlers(
        self,
        active_sessions_query: ListActiveSessionsQueryUseCase,
        active_sessions_by_user_ids_query: GetActiveSessionsByUserIdsQueryUseCase,
        packet_queue: PacketQueue,
        bot_identity: SystemUserIdentity,
        stable_user_status_store: StableUserStatusStore,
    ) -> PresenceHandlers:
        """Stable presence packet handler群をonline sessionとstatus依存で構成する.

        Args:
            active_sessions_query (ListActiveSessionsQueryUseCase): online sessionを列挙するquery.
            active_sessions_by_user_ids_query (GetActiveSessionsByUserIdsQueryUseCase):
                指定userのsessionを取得するquery.
            packet_queue (PacketQueue): presence packetをrecipientへenqueueするqueue.
            bot_identity (SystemUserIdentity): system botのpresenceを表すidentity.
            stable_user_status_store (StableUserStatusStore): stable client statusを読むstore.

        Returns:
            PresenceHandlers: presence requestとpresence filter packetを登録するhandler group.
        """
        return PresenceHandlers(
            active_sessions_query=active_sessions_query,
            active_sessions_by_user_ids_query=active_sessions_by_user_ids_query,
            packet_queue=packet_queue,
            bot_identity=bot_identity,
            stable_user_status_store=stable_user_status_store,
        )

    @provide
    def stats_request_handler(
        self,
        current_user_stats_query: CurrentUserStatsQuery,
        active_sessions_by_user_ids_query: GetActiveSessionsByUserIdsQueryUseCase,
        packet_queue: PacketQueue,
        stable_user_status_store: StableUserStatusStore,
        bot_identity: SystemUserIdentity,
    ) -> StatsRequestHandler:
        """Stable user stats request handlerをquery,queue,status依存で構成する.

        Args:
            current_user_stats_query (CurrentUserStatsQuery):
                requested userのscore statsを取得するquery.
            active_sessions_by_user_ids_query (GetActiveSessionsByUserIdsQueryUseCase):
                requested userのsessionを取得するquery.
            packet_queue (PacketQueue): stats response packetをenqueueするqueue.
            stable_user_status_store (StableUserStatusStore): stable client statusを読むstore.
            bot_identity (SystemUserIdentity): system botのstatsを表すidentity.

        Returns:
            StatsRequestHandler: user stats request packetを登録するhandler group.
        """
        return StatsRequestHandler(
            current_user_stats_query=current_user_stats_query,
            packet_queue=packet_queue,
            stable_user_status_store=stable_user_status_store,
            active_sessions_by_user_ids_query=active_sessions_by_user_ids_query,
            bot_identity=bot_identity,
        )

    @provide
    def app_event_listeners(
        self,
        event_bus: LocalEventBus,
        packet_queue: PacketQueue,
        active_sessions_query: ListActiveSessionsQueryUseCase,
        current_user_stats_query: CurrentUserStatsQuery,
        channel_state: ChannelStateStore,
        stable_user_status_store: StableUserStatusStore,
    ) -> AppEventListeners:
        """App event listenerを登録し,登録完了markerを返す.

        Args:
            event_bus (LocalEventBus): domain eventをsubscribeするlocal event bus.
            packet_queue (PacketQueue): event由来packetをrecipientへenqueueするqueue.
            active_sessions_query (ListActiveSessionsQueryUseCase):
                event通知先sessionを列挙するquery.
            current_user_stats_query (CurrentUserStatsQuery):
                stats更新event用のscore statsを取得するquery.
            channel_state (ChannelStateStore): channel state更新eventを反映するstore.
            stable_user_status_store (StableUserStatusStore):
                stable client status更新eventを反映するstore.

        Returns:
            AppEventListeners: listener登録が完了したことを依存graphへ伝えるmarker.

        Notes:
            ``PacketDispatcher`` がこのmarkerを要求するため,handler登録前に
            ``setup_listeners`` が実行される.
        """
        setup_listeners(
            event_bus,
            packet_queue,
            active_sessions_query,
            channel_state,
            current_user_stats_query,
            stable_user_status_store,
        )
        return AppEventListeners()

    @provide
    def packet_dispatcher(
        self,
        lifecycle_handlers: LifecycleHandlers,
        chat_handlers: ChatHandlers,
        friend_handlers: FriendHandlers,
        status_change_handlers: StatusChangeHandlers,
        presence_handlers: PresenceHandlers,
        stats_request_handler: StatsRequestHandler,
        listeners: AppEventListeners,
    ) -> PacketDispatcher:
        """全stable handler groupを登録したpacket dispatcherを構成する.

        Args:
            lifecycle_handlers (LifecycleHandlers): lifecycle packetを登録するhandler group.
            chat_handlers (ChatHandlers): chat packetを登録するhandler group.
            friend_handlers (FriendHandlers): friend packetを登録するhandler group.
            status_change_handlers (StatusChangeHandlers): status変更packetを登録するhandler group.
            presence_handlers (PresenceHandlers): presence packetを登録するhandler group.
            stats_request_handler (StatsRequestHandler):
                stats request packetを登録するhandler group.
            listeners (AppEventListeners): event listener登録完了を強制するmarker.

        Returns:
            PacketDispatcher: 全handlerをregistration済みのstable C2S packet dispatcher.

        Notes:
            ``listeners`` は値を使わず,Dishkaにevent listener providerの解決を
            要求するためだけに受け取る.
        """
        _ = listeners
        dispatcher = PacketDispatcher()
        lifecycle_handlers.register_all(dispatcher)
        chat_handlers.register_all(dispatcher)
        friend_handlers.register_all(dispatcher)
        status_change_handlers.register_all(dispatcher)
        presence_handlers.register_all(dispatcher)
        stats_request_handler.register_all(dispatcher)
        return dispatcher

    @provide
    def polling_workflow(
        self,
        session_store: SessionStore,
        packet_queue: PacketQueue,
        packet_dispatcher: PacketDispatcher,
        stable_user_status_store: StableUserStatusStore,
        config: AppConfig,
    ) -> PollingWorkflow:
        """Stable bancho polling workflowをsession,queue,dispatcherで構成する.

        Args:
            session_store (SessionStore): polling userのsessionを解決するvolatile store.
            packet_queue (PacketQueue): queued S2C packetを取り出すqueue.
            packet_dispatcher (PacketDispatcher): incoming C2S packetをdispatchするdispatcher.
            stable_user_status_store (StableUserStatusStore):
                stable client statusを読み書きするstore.
            config (AppConfig): session TTLと最大request body sizeを持つ設定.

        Returns:
            PollingWorkflow: stable bancho polling requestを処理するworkflow.
        """
        return PollingWorkflow(
            session_store=session_store,
            packet_queue=packet_queue,
            packet_dispatcher=packet_dispatcher,
            stable_user_status_store=stable_user_status_store,
            session_ttl=config.session_ttl,
            max_request_body_size=config.max_request_body_size,
        )

    @provide
    def bancho_endpoint(
        self,
        login_workflow: LoginWorkflow,
        polling_workflow: PollingWorkflow,
    ) -> BanchoEndpoint:
        """loginとpolling workflowを公開するstable bancho endpointを構成する.

        Args:
            login_workflow (LoginWorkflow): initial login requestを処理するworkflow.
            polling_workflow (PollingWorkflow): authenticated polling requestを処理するworkflow.

        Returns:
            BanchoEndpoint: stable client向けroot bancho HTTP endpoint.
        """
        return BanchoEndpoint(
            login_workflow=login_workflow,
            polling_workflow=polling_workflow,
        )
