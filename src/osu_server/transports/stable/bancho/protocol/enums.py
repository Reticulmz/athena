"""Bancho binary protocolのC2S/S2C packet ID enumを定義する.

同じ数値IDをdirectionごとに表現するため, 独立したIntEnum型を使う.
"""

from enum import IntEnum


class ClientPacketID(IntEnum):
    """Clientからserverへ送るpacket identifierを表す.

    Attributes:
        STATUS_CHANGE (ClientPacketID): C2S packetの固定wire ID 0.
        SEND_MESSAGE (ClientPacketID): C2S packetの固定wire ID 1.
        EXIT (ClientPacketID): C2S packetの固定wire ID 2.
        REQUEST_STATUS (ClientPacketID): C2S packetの固定wire ID 3.
        PONG (ClientPacketID): C2S packetの固定wire ID 4.
        START_SPECTATING (ClientPacketID): C2S packetの固定wire ID 16.
        STOP_SPECTATING (ClientPacketID): C2S packetの固定wire ID 17.
        SEND_FRAMES (ClientPacketID): C2S packetの固定wire ID 18.
        ERROR_REPORT (ClientPacketID): C2S packetの固定wire ID 20.
        CANT_SPECTATE (ClientPacketID): C2S packetの固定wire ID 21.
        SEND_PRIVATE_MESSAGE (ClientPacketID): C2S packetの固定wire ID 25.
        PART_LOBBY (ClientPacketID): C2S packetの固定wire ID 29.
        JOIN_LOBBY (ClientPacketID): C2S packetの固定wire ID 30.
        CREATE_MATCH (ClientPacketID): C2S packetの固定wire ID 31.
        JOIN_MATCH (ClientPacketID): C2S packetの固定wire ID 32.
        LEAVE_MATCH (ClientPacketID): C2S packetの固定wire ID 33.
        MATCH_CHANGE_SLOT (ClientPacketID): C2S packetの固定wire ID 38.
        MATCH_READY (ClientPacketID): C2S packetの固定wire ID 39.
        MATCH_LOCK (ClientPacketID): C2S packetの固定wire ID 40.
        MATCH_CHANGE_SETTINGS (ClientPacketID): C2S packetの固定wire ID 41.
        MATCH_START (ClientPacketID): C2S packetの固定wire ID 44.
        MATCH_SCORE_UPDATE (ClientPacketID): C2S packetの固定wire ID 47.
        MATCH_COMPLETE (ClientPacketID): C2S packetの固定wire ID 49.
        MATCH_CHANGE_BEATMAP (ClientPacketID): C2S packetの固定wire ID 50.
        MATCH_CHANGE_MODS (ClientPacketID): C2S packetの固定wire ID 51.
        MATCH_LOAD_COMPLETE (ClientPacketID): C2S packetの固定wire ID 52.
        MATCH_NO_BEATMAP (ClientPacketID): C2S packetの固定wire ID 54.
        MATCH_NOT_READY (ClientPacketID): C2S packetの固定wire ID 55.
        MATCH_FAILED (ClientPacketID): C2S packetの固定wire ID 56.
        MATCH_HAS_BEATMAP (ClientPacketID): C2S packetの固定wire ID 59.
        MATCH_SKIP (ClientPacketID): C2S packetの固定wire ID 60.
        JOIN_CHANNEL (ClientPacketID): C2S packetの固定wire ID 63.
        BEATMAP_INFO (ClientPacketID): C2S packetの固定wire ID 68.
        MATCH_TRANSFER_HOST (ClientPacketID): C2S packetの固定wire ID 70.
        ADD_FRIEND (ClientPacketID): C2S packetの固定wire ID 73.
        REMOVE_FRIEND (ClientPacketID): C2S packetの固定wire ID 74.
        MATCH_CHANGE_TEAM (ClientPacketID): C2S packetの固定wire ID 77.
        LEAVE_CHANNEL (ClientPacketID): C2S packetの固定wire ID 78.
        RECEIVE_UPDATES (ClientPacketID): C2S packetの固定wire ID 79.
        SET_AWAY_MESSAGE (ClientPacketID): C2S packetの固定wire ID 82.
        STATS_REQUEST (ClientPacketID): C2S packetの固定wire ID 85.
        MATCH_INVITE (ClientPacketID): C2S packetの固定wire ID 87.
        MATCH_CHANGE_PASSWORD (ClientPacketID): C2S packetの固定wire ID 90.
        TOURNAMENT_MATCH_INFO (ClientPacketID): C2S packetの固定wire ID 93.
        PRESENCE_REQUEST (ClientPacketID): C2S packetの固定wire ID 97.
        PRESENCE_REQUEST_ALL (ClientPacketID): C2S packetの固定wire ID 98.
        CHANGE_FRIENDONLY_DMS (ClientPacketID): C2S packetの固定wire ID 99.
        TOURNAMENT_JOIN_MATCH_CHANNEL (ClientPacketID): C2S packetの固定wire ID 108.
        TOURNAMENT_LEAVE_MATCH_CHANNEL (ClientPacketID): C2S packetの固定wire ID 109.
    """

    STATUS_CHANGE = 0
    SEND_MESSAGE = 1
    EXIT = 2
    REQUEST_STATUS = 3
    PONG = 4
    START_SPECTATING = 16
    STOP_SPECTATING = 17
    SEND_FRAMES = 18
    ERROR_REPORT = 20
    CANT_SPECTATE = 21
    SEND_PRIVATE_MESSAGE = 25
    PART_LOBBY = 29
    JOIN_LOBBY = 30
    CREATE_MATCH = 31
    JOIN_MATCH = 32
    LEAVE_MATCH = 33
    MATCH_CHANGE_SLOT = 38
    MATCH_READY = 39
    MATCH_LOCK = 40
    MATCH_CHANGE_SETTINGS = 41
    MATCH_START = 44
    MATCH_SCORE_UPDATE = 47
    MATCH_COMPLETE = 49
    MATCH_CHANGE_BEATMAP = 50
    MATCH_CHANGE_MODS = 51
    MATCH_LOAD_COMPLETE = 52
    MATCH_NO_BEATMAP = 54
    MATCH_NOT_READY = 55
    MATCH_FAILED = 56
    MATCH_HAS_BEATMAP = 59
    MATCH_SKIP = 60
    JOIN_CHANNEL = 63
    BEATMAP_INFO = 68
    MATCH_TRANSFER_HOST = 70
    ADD_FRIEND = 73
    REMOVE_FRIEND = 74
    MATCH_CHANGE_TEAM = 77
    LEAVE_CHANNEL = 78
    RECEIVE_UPDATES = 79
    SET_AWAY_MESSAGE = 82
    STATS_REQUEST = 85
    MATCH_INVITE = 87
    MATCH_CHANGE_PASSWORD = 90
    TOURNAMENT_MATCH_INFO = 93
    PRESENCE_REQUEST = 97
    PRESENCE_REQUEST_ALL = 98
    CHANGE_FRIENDONLY_DMS = 99
    TOURNAMENT_JOIN_MATCH_CHANNEL = 108
    TOURNAMENT_LEAVE_MATCH_CHANNEL = 109


class ServerPacketID(IntEnum):
    """Serverからclientへ送るpacket identifierを表す.

    Attributes:
        LOGIN_REPLY (ServerPacketID): S2C packetの固定wire ID 5.
        COMMAND_ERROR (ServerPacketID): S2C packetの固定wire ID 6.
        SEND_MESSAGE (ServerPacketID): S2C packetの固定wire ID 7.
        PING (ServerPacketID): S2C packetの固定wire ID 8.
        IRC_CHANGE_USERNAME (ServerPacketID): S2C packetの固定wire ID 9.
        IRC_QUIT (ServerPacketID): S2C packetの固定wire ID 10.
        USER_STATS (ServerPacketID): S2C packetの固定wire ID 11.
        USER_QUIT (ServerPacketID): S2C packetの固定wire ID 12.
        SPECTATOR_JOINED (ServerPacketID): S2C packetの固定wire ID 13.
        SPECTATOR_LEFT (ServerPacketID): S2C packetの固定wire ID 14.
        SPECTATE_FRAMES (ServerPacketID): S2C packetの固定wire ID 15.
        VERSION_UPDATE (ServerPacketID): S2C packetの固定wire ID 19.
        CANT_SPECTATE (ServerPacketID): S2C packetの固定wire ID 22.
        GET_ATTENTION (ServerPacketID): S2C packetの固定wire ID 23.
        ANNOUNCE (ServerPacketID): S2C packetの固定wire ID 24.
        MATCH_UPDATE (ServerPacketID): S2C packetの固定wire ID 26.
        NEW_MATCH (ServerPacketID): S2C packetの固定wire ID 27.
        MATCH_DISBAND (ServerPacketID): S2C packetの固定wire ID 28.
        LOBBY_JOIN (ServerPacketID): S2C packetの固定wire ID 34.
        LOBBY_PART (ServerPacketID): S2C packetの固定wire ID 35.
        MATCH_JOIN_SUCCESS (ServerPacketID): S2C packetの固定wire ID 36.
        MATCH_JOIN_FAIL (ServerPacketID): S2C packetの固定wire ID 37.
        FELLOW_SPECTATOR_JOINED (ServerPacketID): S2C packetの固定wire ID 42.
        FELLOW_SPECTATOR_LEFT (ServerPacketID): S2C packetの固定wire ID 43.
        ALL_PLAYERS_LOADED (ServerPacketID): S2C packetの固定wire ID 45.
        MATCH_START (ServerPacketID): S2C packetの固定wire ID 46.
        MATCH_SCORE_UPDATE (ServerPacketID): S2C packetの固定wire ID 48.
        MATCH_TRANSFER_HOST (ServerPacketID): S2C packetの固定wire ID 50.
        MATCH_ALL_PLAYERS_LOADED (ServerPacketID): S2C packetの固定wire ID 53.
        MATCH_PLAYER_FAILED (ServerPacketID): S2C packetの固定wire ID 57.
        MATCH_COMPLETE (ServerPacketID): S2C packetの固定wire ID 58.
        MATCH_SKIP (ServerPacketID): S2C packetの固定wire ID 61.
        UNAUTHORIZED (ServerPacketID): S2C packetの固定wire ID 62.
        CHANNEL_JOIN_SUCCESS (ServerPacketID): S2C packetの固定wire ID 64.
        CHANNEL_AVAILABLE (ServerPacketID): S2C packetの固定wire ID 65.
        CHANNEL_REVOKED (ServerPacketID): S2C packetの固定wire ID 66.
        CHANNEL_AVAILABLE_AUTOJOIN (ServerPacketID): S2C packetの固定wire ID 67.
        BEATMAP_INFO_REPLY (ServerPacketID): S2C packetの固定wire ID 69.
        LOGIN_PERMISSIONS (ServerPacketID): S2C packetの固定wire ID 71.
        FRIENDS_LIST (ServerPacketID): S2C packetの固定wire ID 72.
        PROTOCOL_VERSION (ServerPacketID): S2C packetの固定wire ID 75.
        MENU_ICON (ServerPacketID): S2C packetの固定wire ID 76.
        MONITOR (ServerPacketID): S2C packetの固定wire ID 80.
        MATCH_PLAYER_SKIPPED (ServerPacketID): S2C packetの固定wire ID 81.
        USER_PRESENCE (ServerPacketID): S2C packetの固定wire ID 83.
        IRC_ONLY (ServerPacketID): S2C packetの固定wire ID 84.
        RESTART (ServerPacketID): S2C packetの固定wire ID 86.
        INVITE (ServerPacketID): S2C packetの固定wire ID 88.
        CHANNEL_INFO_COMPLETE (ServerPacketID): S2C packetの固定wire ID 89.
        MATCH_CHANGE_PASSWORD (ServerPacketID): S2C packetの固定wire ID 91.
        SILENCE_INFO (ServerPacketID): S2C packetの固定wire ID 92.
        USER_SILENCED (ServerPacketID): S2C packetの固定wire ID 94.
        USER_PRESENCE_SINGLE (ServerPacketID): S2C packetの固定wire ID 95.
        USER_PRESENCE_BUNDLE (ServerPacketID): S2C packetの固定wire ID 96.
        USER_DM_BLOCKED (ServerPacketID): S2C packetの固定wire ID 100.
        TARGET_IS_SILENCED (ServerPacketID): S2C packetの固定wire ID 101.
        VERSION_UPDATE_FORCED (ServerPacketID): S2C packetの固定wire ID 102.
        SWITCH_SERVER (ServerPacketID): S2C packetの固定wire ID 103.
        ACCOUNT_RESTRICTED (ServerPacketID): S2C packetの固定wire ID 104.
        RTX (ServerPacketID): S2C packetの固定wire ID 105.
        MATCH_ABORT (ServerPacketID): S2C packetの固定wire ID 106.
        SWITCH_TOURNAMENT_SERVER (ServerPacketID): S2C packetの固定wire ID 107.
    """

    LOGIN_REPLY = 5
    COMMAND_ERROR = 6
    SEND_MESSAGE = 7
    PING = 8
    IRC_CHANGE_USERNAME = 9
    IRC_QUIT = 10
    USER_STATS = 11
    USER_QUIT = 12
    SPECTATOR_JOINED = 13
    SPECTATOR_LEFT = 14
    SPECTATE_FRAMES = 15
    VERSION_UPDATE = 19
    CANT_SPECTATE = 22
    GET_ATTENTION = 23
    ANNOUNCE = 24
    MATCH_UPDATE = 26
    NEW_MATCH = 27
    MATCH_DISBAND = 28
    LOBBY_JOIN = 34
    LOBBY_PART = 35
    MATCH_JOIN_SUCCESS = 36
    MATCH_JOIN_FAIL = 37
    FELLOW_SPECTATOR_JOINED = 42
    FELLOW_SPECTATOR_LEFT = 43
    ALL_PLAYERS_LOADED = 45
    MATCH_START = 46
    MATCH_SCORE_UPDATE = 48
    MATCH_TRANSFER_HOST = 50
    MATCH_ALL_PLAYERS_LOADED = 53
    MATCH_PLAYER_FAILED = 57
    MATCH_COMPLETE = 58
    MATCH_SKIP = 61
    UNAUTHORIZED = 62
    CHANNEL_JOIN_SUCCESS = 64
    CHANNEL_AVAILABLE = 65
    CHANNEL_REVOKED = 66
    CHANNEL_AVAILABLE_AUTOJOIN = 67
    BEATMAP_INFO_REPLY = 69
    LOGIN_PERMISSIONS = 71
    FRIENDS_LIST = 72
    PROTOCOL_VERSION = 75
    MENU_ICON = 76
    MONITOR = 80
    MATCH_PLAYER_SKIPPED = 81
    USER_PRESENCE = 83
    IRC_ONLY = 84
    RESTART = 86
    INVITE = 88
    CHANNEL_INFO_COMPLETE = 89
    MATCH_CHANGE_PASSWORD = 91
    SILENCE_INFO = 92
    USER_SILENCED = 94
    USER_PRESENCE_SINGLE = 95
    USER_PRESENCE_BUNDLE = 96
    USER_DM_BLOCKED = 100
    TARGET_IS_SILENCED = 101
    VERSION_UPDATE_FORCED = 102
    SWITCH_SERVER = 103
    ACCOUNT_RESTRICTED = 104
    RTX = 105
    MATCH_ABORT = 106
    SWITCH_TOURNAMENT_SERVER = 107
