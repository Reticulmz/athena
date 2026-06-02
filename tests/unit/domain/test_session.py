from __future__ import annotations

from dataclasses import asdict

from osu_server.domain.session import SessionData

SAMPLE_PRIVILEGES = 131  # NORMAL | VERIFIED | UNRESTRICTED


class TestSessionData:
    def test_slots(self) -> None:
        assert hasattr(SessionData, "__slots__")

    def test_creation(self) -> None:
        sd = SessionData(
            user_id=1,
            username="TestPlayer",
            privileges=SAMPLE_PRIVILEGES,
            country="JP",
            osu_version="b20240101.1",
            utc_offset=9,
            display_city=True,
            client_hashes="abc:def",
            pm_private=False,
        )
        assert sd.user_id == 1
        assert sd.username == "TestPlayer"
        assert sd.privileges == SAMPLE_PRIVILEGES
        assert sd.country == "JP"
        assert sd.role_ids == ()

    def test_asdict_roundtrip(self) -> None:
        sd = SessionData(
            user_id=42,
            username="Player",
            privileges=1,
            country="US",
            osu_version="b20240101",
            utc_offset=-5,
            display_city=False,
            client_hashes="hash",
            pm_private=True,
        )
        d = asdict(sd)
        # dict[str, Any] unpacking triggers reportAny for constructor parameters
        restored = SessionData(**d)  # pyright: ignore[reportAny]
        assert restored.user_id == sd.user_id
        assert restored.username == sd.username
        assert restored.privileges == sd.privileges
        assert restored.country == sd.country
        assert restored.osu_version == sd.osu_version
        assert restored.utc_offset == sd.utc_offset
        assert restored.display_city == sd.display_city
        assert restored.client_hashes == sd.client_hashes
        assert restored.pm_private == sd.pm_private
        assert restored.role_ids == sd.role_ids

    def test_all_fields_in_dict(self) -> None:
        sd = SessionData(
            user_id=1,
            username="P",
            privileges=0,
            country="XX",
            osu_version="v",
            utc_offset=0,
            display_city=False,
            client_hashes="",
            pm_private=False,
        )
        d = asdict(sd)
        expected_keys = {
            "user_id",
            "username",
            "privileges",
            "country",
            "osu_version",
            "utc_offset",
            "display_city",
            "client_hashes",
            "pm_private",
            "role_ids",
            "silence_end",
        }
        assert set(d.keys()) == expected_keys
