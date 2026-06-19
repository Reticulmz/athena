"""Tests for ClientPacketID and ServerPacketID enums.

Validates:
- Req 2.1: ClientPacketID contains all C2S packet IDs
- Req 2.2: ServerPacketID contains all S2C packet IDs
- Req 2.3: Two enums are independent; same numeric ID can coexist
- Req 2.4: Values conform to bancho-documentation Wiki (ID 0-109)
"""

from enum import IntEnum

from osu_server.transports.stable.bancho.protocol.enums import (
    ClientPacketID,
    ServerPacketID,
)

# ---- Req 2.1: ClientPacketID ----


class TestClientPacketID:
    """ClientPacketID enum tests."""

    def test_is_int_enum(self) -> None:
        assert issubclass(ClientPacketID, IntEnum)

    def test_total_count(self) -> None:
        assert len(ClientPacketID) == 49

    def test_known_values(self) -> None:
        """Spot-check representative C2S packet IDs."""
        assert ClientPacketID.STATUS_CHANGE == 0
        assert ClientPacketID.SEND_MESSAGE == 1
        assert ClientPacketID.EXIT == 2
        assert ClientPacketID.PONG == 4
        assert ClientPacketID.START_SPECTATING == 16
        assert ClientPacketID.SEND_PRIVATE_MESSAGE == 25
        assert ClientPacketID.CREATE_MATCH == 31
        assert ClientPacketID.JOIN_CHANNEL == 63
        assert ClientPacketID.STATS_REQUEST == 85
        assert ClientPacketID.PRESENCE_REQUEST == 97
        assert ClientPacketID.PRESENCE_REQUEST_ALL == 98
        assert ClientPacketID.CHANGE_FRIENDONLY_DMS == 99
        assert ClientPacketID.TOURNAMENT_JOIN_MATCH_CHANNEL == 108
        assert ClientPacketID.TOURNAMENT_LEAVE_MATCH_CHANNEL == 109

    def test_all_expected_members(self) -> None:
        """Verify every expected C2S member exists with correct value."""
        expected: dict[str, int] = {
            "STATUS_CHANGE": 0,
            "SEND_MESSAGE": 1,
            "EXIT": 2,
            "REQUEST_STATUS": 3,
            "PONG": 4,
            "START_SPECTATING": 16,
            "STOP_SPECTATING": 17,
            "SEND_FRAMES": 18,
            "ERROR_REPORT": 20,
            "CANT_SPECTATE": 21,
            "SEND_PRIVATE_MESSAGE": 25,
            "PART_LOBBY": 29,
            "JOIN_LOBBY": 30,
            "CREATE_MATCH": 31,
            "JOIN_MATCH": 32,
            "LEAVE_MATCH": 33,
            "MATCH_CHANGE_SLOT": 38,
            "MATCH_READY": 39,
            "MATCH_LOCK": 40,
            "MATCH_CHANGE_SETTINGS": 41,
            "MATCH_START": 44,
            "MATCH_SCORE_UPDATE": 47,
            "MATCH_COMPLETE": 49,
            "MATCH_CHANGE_BEATMAP": 50,
            "MATCH_CHANGE_MODS": 51,
            "MATCH_LOAD_COMPLETE": 52,
            "MATCH_NO_BEATMAP": 54,
            "MATCH_NOT_READY": 55,
            "MATCH_FAILED": 56,
            "MATCH_HAS_BEATMAP": 59,
            "MATCH_SKIP": 60,
            "JOIN_CHANNEL": 63,
            "BEATMAP_INFO": 68,
            "MATCH_TRANSFER_HOST": 70,
            "ADD_FRIEND": 73,
            "REMOVE_FRIEND": 74,
            "MATCH_CHANGE_TEAM": 77,
            "LEAVE_CHANNEL": 78,
            "RECEIVE_UPDATES": 79,
            "SET_AWAY_MESSAGE": 82,
            "STATS_REQUEST": 85,
            "MATCH_INVITE": 87,
            "MATCH_CHANGE_PASSWORD": 90,
            "TOURNAMENT_MATCH_INFO": 93,
            "PRESENCE_REQUEST": 97,
            "PRESENCE_REQUEST_ALL": 98,
            "CHANGE_FRIENDONLY_DMS": 99,
            "TOURNAMENT_JOIN_MATCH_CHANNEL": 108,
            "TOURNAMENT_LEAVE_MATCH_CHANNEL": 109,
        }
        actual = {member.name: member.value for member in ClientPacketID}
        assert actual == expected

    def test_int_coercion(self) -> None:
        """IntEnum members are usable as plain ints."""
        assert int(ClientPacketID.EXIT) == 2
        assert ClientPacketID.PONG + 1 == 5


# ---- Req 2.2: ServerPacketID ----


class TestServerPacketID:
    """ServerPacketID enum tests."""

    def test_is_int_enum(self) -> None:
        assert issubclass(ServerPacketID, IntEnum)

    def test_total_count(self) -> None:
        assert len(ServerPacketID) == 62

    def test_known_values(self) -> None:
        """Spot-check representative S2C packet IDs."""
        assert ServerPacketID.LOGIN_REPLY == 5
        assert ServerPacketID.SEND_MESSAGE == 7
        assert ServerPacketID.PING == 8
        assert ServerPacketID.USER_STATS == 11
        assert ServerPacketID.USER_QUIT == 12
        assert ServerPacketID.ALL_PLAYERS_LOADED == 45
        assert ServerPacketID.MATCH_START == 46
        assert ServerPacketID.CHANNEL_JOIN_SUCCESS == 64
        assert ServerPacketID.LOGIN_PERMISSIONS == 71
        assert ServerPacketID.PROTOCOL_VERSION == 75
        assert ServerPacketID.USER_PRESENCE == 83
        assert ServerPacketID.SILENCE_INFO == 92
        assert ServerPacketID.ACCOUNT_RESTRICTED == 104
        assert ServerPacketID.RTX == 105
        assert ServerPacketID.SWITCH_TOURNAMENT_SERVER == 107

    def test_match_start_and_all_players_loaded_match_lekuruu(self) -> None:
        """Guard S2C 45/46 ordering from Lekuruu packet file names."""
        assert ServerPacketID.ALL_PLAYERS_LOADED == 45
        assert ServerPacketID.MATCH_START == 46

    def test_all_expected_members(self) -> None:
        """Verify every expected S2C member exists with correct value."""
        expected: dict[str, int] = {
            "LOGIN_REPLY": 5,
            "COMMAND_ERROR": 6,
            "SEND_MESSAGE": 7,
            "PING": 8,
            "IRC_CHANGE_USERNAME": 9,
            "IRC_QUIT": 10,
            "USER_STATS": 11,
            "USER_QUIT": 12,
            "SPECTATOR_JOINED": 13,
            "SPECTATOR_LEFT": 14,
            "SPECTATE_FRAMES": 15,
            "VERSION_UPDATE": 19,
            "CANT_SPECTATE": 22,
            "GET_ATTENTION": 23,
            "ANNOUNCE": 24,
            "MATCH_UPDATE": 26,
            "NEW_MATCH": 27,
            "MATCH_DISBAND": 28,
            "LOBBY_JOIN": 34,
            "LOBBY_PART": 35,
            "MATCH_JOIN_SUCCESS": 36,
            "MATCH_JOIN_FAIL": 37,
            "FELLOW_SPECTATOR_JOINED": 42,
            "FELLOW_SPECTATOR_LEFT": 43,
            "ALL_PLAYERS_LOADED": 45,
            "MATCH_START": 46,
            "MATCH_SCORE_UPDATE": 48,
            "MATCH_TRANSFER_HOST": 50,
            "MATCH_ALL_PLAYERS_LOADED": 53,
            "MATCH_PLAYER_FAILED": 57,
            "MATCH_COMPLETE": 58,
            "MATCH_SKIP": 61,
            "UNAUTHORIZED": 62,
            "CHANNEL_JOIN_SUCCESS": 64,
            "CHANNEL_AVAILABLE": 65,
            "CHANNEL_REVOKED": 66,
            "CHANNEL_AVAILABLE_AUTOJOIN": 67,
            "BEATMAP_INFO_REPLY": 69,
            "LOGIN_PERMISSIONS": 71,
            "FRIENDS_LIST": 72,
            "PROTOCOL_VERSION": 75,
            "MENU_ICON": 76,
            "MONITOR": 80,
            "MATCH_PLAYER_SKIPPED": 81,
            "USER_PRESENCE": 83,
            "IRC_ONLY": 84,
            "RESTART": 86,
            "INVITE": 88,
            "CHANNEL_INFO_COMPLETE": 89,
            "MATCH_CHANGE_PASSWORD": 91,
            "SILENCE_INFO": 92,
            "USER_SILENCED": 94,
            "USER_PRESENCE_SINGLE": 95,
            "USER_PRESENCE_BUNDLE": 96,
            "USER_DM_BLOCKED": 100,
            "TARGET_IS_SILENCED": 101,
            "VERSION_UPDATE_FORCED": 102,
            "SWITCH_SERVER": 103,
            "ACCOUNT_RESTRICTED": 104,
            "RTX": 105,
            "MATCH_ABORT": 106,
            "SWITCH_TOURNAMENT_SERVER": 107,
        }
        actual = {member.name: member.value for member in ServerPacketID}
        assert actual == expected

    def test_int_coercion(self) -> None:
        """IntEnum members are usable as plain ints."""
        assert int(ServerPacketID.LOGIN_REPLY) == 5
        assert ServerPacketID.PING + 1 == 9


# ---- Req 2.3: C2S / S2C separation ----


class TestEnumSeparation:
    """Verify C2S and S2C enums are independent."""

    def test_shared_numeric_ids_exist_in_both(self) -> None:
        """IDs like 50 appear in both enums with different names."""
        c2s_50 = ClientPacketID(50)
        s2c_50 = ServerPacketID(50)
        assert c2s_50.name == "MATCH_CHANGE_BEATMAP"
        assert s2c_50.name == "MATCH_TRANSFER_HOST"

    def test_enums_are_distinct_types(self) -> None:
        assert ClientPacketID is not ServerPacketID
        assert type(ClientPacketID.SEND_MESSAGE) is not type(ServerPacketID.SEND_MESSAGE)

    def test_same_name_different_value(self) -> None:
        """SEND_MESSAGE exists in both but with different numeric IDs."""
        assert ClientPacketID.SEND_MESSAGE == 1
        assert ServerPacketID.SEND_MESSAGE == 7
        assert ClientPacketID.SEND_MESSAGE != ServerPacketID.SEND_MESSAGE
