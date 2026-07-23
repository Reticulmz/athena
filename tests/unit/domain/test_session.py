"""SessionDataのserializationとdataclass contractを検証するmodule."""

from __future__ import annotations

from dataclasses import asdict

from osu_server.domain.identity.sessions import SessionData

SAMPLE_PRIVILEGES = 131  # NORMAL | VERIFIED | UNRESTRICTED


class TestSessionData:
    """Active sessionに保存するSessionDataの表現契約を検証する."""

    def test_slots(self) -> None:
        """SessionDataがslotsを持つvalue objectであることを検証する.

        Returns:
            None: slotsの存在を検証して完了し,呼び出し側へ値を返さない.
        """
        assert hasattr(SessionData, "__slots__")

    def test_creation(self) -> None:
        """SessionDataがconstructor inputと既定role_idsを保持することを検証する.

        role_idsを省略してsession dataを生成し,主要fieldと空tupleの既定値を確認する.

        Returns:
            None: 生成結果を検証して完了し,呼び出し側へ値を返さない.
        """
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
        """asdictの出力からSessionDataを復元してfield値を保つことを検証する.

        全fieldを持つsession dataをdataclass辞書へ変換してconstructorへ渡し,復元後の各値が元と
        一致する観測結果を確認する.

        Returns:
            None: serialization roundtripを検証して完了し,呼び出し側へ値を返さない.
        """
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
        """asdictがSessionDataの全persistent fieldを出力することを検証する.

        最小値を持つinstanceを辞書化し,key集合がsession serialization contractと一致する
        観測結果を確認する.

        Returns:
            None: serialization field集合を検証して完了し,呼び出し側へ値を返さない.
        """
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
