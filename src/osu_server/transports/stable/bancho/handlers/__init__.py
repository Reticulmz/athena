"""PacketDispatcherへ登録するstable Bancho C2S handler群を公開する."""

from osu_server.transports.stable.bancho.handlers.presence import PresenceHandlers
from osu_server.transports.stable.bancho.handlers.stats import StatsRequestHandler
from osu_server.transports.stable.bancho.handlers.status import StatusChangeHandlers

__all__ = ["PresenceHandlers", "StatsRequestHandler", "StatusChangeHandlers"]
