"""PasswordServiceのpassword hash,照合,禁止判定の契約を検証するmodule.

stable client互換のMD5 credentialとargon2id hash,HIBPおよびcustom禁止listの
observable outcomeを対象にする.
"""

from __future__ import annotations

import hashlib

from structlog.testing import capture_logs

from osu_server.services.queries.identity.password_service import PasswordService
from tests.support import FakeHIBPClient


class TestHash:
    """PasswordService.hashのargon2id hash生成契約を検証する."""

    async def test_returns_argon2id_hash(self) -> None:
        """hashがargon2id形式の保存文字列を返す契約を検証する.

        Returns:
            None: 生成されたhash形式を検証して完了し,呼び出し側へ値を返さない.
        """
        svc = PasswordService()
        hashed = await svc.hash("some_password")
        assert hashed.startswith("$argon2id$")

    async def test_different_inputs_produce_different_hashes(self) -> None:
        """異なるpassword入力が異なるhash文字列になる契約を検証する.

        Returns:
            None: 異なる入力のhash結果を比較して完了し,呼び出し側へ値を返さない.
        """
        svc = PasswordService()
        h1 = await svc.hash("password_a")
        h2 = await svc.hash("password_b")
        assert h1 != h2

    async def test_same_input_produces_different_hashes(self) -> None:
        """同じpassword入力でもsaltによりhashが変わる契約を検証する.

        Returns:
            None: 同一入力の2回のhash結果を比較して完了し,呼び出し側へ値を返さない.
        """
        svc = PasswordService()
        h1 = await svc.hash("same_password")
        h2 = await svc.hash("same_password")
        assert h1 != h2


class TestVerify:
    """PasswordService.verifyのcredential照合契約を検証する."""

    async def test_roundtrip_success(self) -> None:
        """hash直後の正しいcredentialを照合できる契約を検証する.

        Returns:
            None: 成功した照合結果を検証して完了し,呼び出し側へ値を返さない.
        """
        svc = PasswordService()
        password = "correct_password"
        hashed = await svc.hash(password)
        assert await svc.verify(hashed, password) is True

    async def test_mismatch_returns_false(self) -> None:
        """異なるcredentialを照合した場合にFalseとなる契約を検証する.

        Returns:
            None: 不一致時の照合結果を検証して完了し,呼び出し側へ値を返さない.
        """
        svc = PasswordService()
        hashed = await svc.hash("correct_password")
        assert await svc.verify(hashed, "wrong_password") is False

    async def test_empty_password_mismatch(self) -> None:
        """空文字列credentialが保存済みhashと一致しない契約を検証する.

        Returns:
            None: 空文字列の照合結果を検証して完了し,呼び出し側へ値を返さない.
        """
        svc = PasswordService()
        hashed = await svc.hash("non_empty")
        assert await svc.verify(hashed, "") is False


class TestPreparePassword:
    """PasswordService.prepare_passwordのstable互換保存契約を検証する."""

    def test_legacy_plaintext_md5_matches_stable_client_hash(self) -> None:
        """平文passwordのMD5がstable client互換のlowercase hexとなる契約を検証する.

        Returns:
            None: stable clientと同じMD5 hexを検証して完了し,呼び出し側へ値を返さない.
        """
        svc = PasswordService()
        plain = "my_secure_password"

        assert (
            svc.legacy_plaintext_md5(plain)
            == hashlib.md5(plain.encode(), usedforsecurity=False).hexdigest()
        )

    async def test_prepare_password_roundtrip(self) -> None:
        """prepare_passwordの結果を平文passwordのMD5で照合できる契約を検証する.

        Returns:
            None: stable互換credentialによる照合成功を検証して完了し,呼び出し側へ値を返さない.
        """
        svc = PasswordService()
        plain = "my_secure_password"
        stored_hash = await svc.prepare_password(plain)

        md5_of_plain = hashlib.md5(plain.encode(), usedforsecurity=False).hexdigest()
        assert await svc.verify(stored_hash, md5_of_plain) is True

    async def test_prepare_password_returns_argon2id(self) -> None:
        """prepare_passwordがargon2id形式の保存hashを返す契約を検証する.

        Returns:
            None: 保存hashの形式を検証して完了し,呼び出し側へ値を返さない.
        """
        svc = PasswordService()
        stored_hash = await svc.prepare_password("test_password")
        assert stored_hash.startswith("$argon2id$")

    async def test_prepare_password_wrong_plain_fails(self) -> None:
        """別の平文passwordのMD5では照合に失敗する契約を検証する.

        Returns:
            None: 異なる平文由来credentialの拒否を検証して完了し,呼び出し側へ値を返さない.
        """
        svc = PasswordService()
        stored_hash = await svc.prepare_password("original_password")

        wrong_md5 = hashlib.md5(b"different_password", usedforsecurity=False).hexdigest()
        assert await svc.verify(stored_hash, wrong_md5) is False

    async def test_prepare_password_simulates_login_flow(self) -> None:
        """登録時の保存hashをlogin時のMD5 credentialで照合できる契約を検証する.

        Returns:
            None: 登録からloginまでの互換照合結果を検証して完了し,呼び出し側へ値を返さない.
        """
        svc = PasswordService()
        plain = "hunter2"

        # Registration
        stored_hash = await svc.prepare_password(plain)

        # Login — client computes MD5 client-side
        client_md5 = hashlib.md5(plain.encode(), usedforsecurity=False).hexdigest()
        assert await svc.verify(stored_hash, client_md5) is True

    async def test_prepare_password_accepts_uppercase_client_md5(self) -> None:
        """Stable authのpassword MD5 hexが大文字でも照合できる契約を検証する.

        Returns:
            None: 大文字MD5 credentialの照合成功を検証して完了し,呼び出し側へ値を返さない.
        """
        svc = PasswordService()
        plain = "SecurePass1234"
        stored_hash = await svc.prepare_password(plain)

        client_md5 = hashlib.md5(plain.encode(), usedforsecurity=False).hexdigest().upper()

        assert await svc.verify(stored_hash, client_md5) is True


class TestCheckHibp:
    """PasswordService.check_hibpのHIBP照会契約を検証する."""

    async def test_returns_true_when_compromised(self) -> None:
        """HIBPが漏洩済みと判定したpasswordを禁止扱いにする契約を検証する.

        Returns:
            None: 漏洩passwordのTrue結果と照会記録を検証して完了し,呼び出し側へ値を返さない.
        """
        hibp = FakeHIBPClient(compromised_passwords={"leaked_password"})
        svc = PasswordService(hibp_client=hibp, banned_passwords=[])

        result = await svc.check_hibp("leaked_password")

        assert result is True
        assert "leaked_password" in hibp.calls

    async def test_returns_false_when_safe(self) -> None:
        """HIBPが安全と判定したpasswordを禁止扱いにしない契約を検証する.

        Returns:
            None: 安全passwordのFalse結果を検証して完了し,呼び出し側へ値を返さない.
        """
        hibp = FakeHIBPClient()
        svc = PasswordService(hibp_client=hibp, banned_passwords=[])

        result = await svc.check_hibp("safe_password")

        assert result is False

    async def test_returns_false_when_hibp_client_is_none(self) -> None:
        """HIBP client未設定時にnetwork照会せずFalseを返す契約を検証する.

        Returns:
            None: HIBP無効時のFalse結果を検証して完了し,呼び出し側へ値を返さない.
        """
        svc = PasswordService(hibp_client=None, banned_passwords=[])

        result = await svc.check_hibp("any_password")

        assert result is False


class TestIsPasswordBanned:
    """PasswordService.is_password_bannedの統合禁止判定契約を検証する."""

    async def test_banned_by_custom_list(self) -> None:
        """custom禁止listに含まれるpasswordを禁止と判定する契約を検証する.

        Returns:
            None: custom禁止listの一致結果を検証して完了し,呼び出し側へ値を返さない.
        """
        svc = PasswordService(hibp_client=None, banned_passwords=["forbidden", "secret123"])

        assert await svc.is_password_banned("forbidden") is True
        assert await svc.is_password_banned("secret123") is True

    async def test_custom_list_case_insensitive(self) -> None:
        """custom禁止listの照合が大文字小文字を区別しない契約を検証する.

        Returns:
            None: 大文字小文字の異なる入力の禁止結果を検証して完了し,呼び出し側へ値を返さない.
        """
        svc = PasswordService(hibp_client=None, banned_passwords=["Forbidden"])

        assert await svc.is_password_banned("forbidden") is True
        assert await svc.is_password_banned("FORBIDDEN") is True

    async def test_not_in_custom_list_and_no_hibp(self) -> None:
        """custom禁止list非一致かつHIBP未設定ならFalseとなる契約を検証する.

        Returns:
            None: 禁止根拠がないpasswordのFalse結果を検証して完了し,呼び出し側へ値を返さない.
        """
        svc = PasswordService(hibp_client=None, banned_passwords=["other"])

        assert await svc.is_password_banned("safe_password") is False

    async def test_banned_by_hibp(self) -> None:
        """custom禁止list非一致でもHIBP漏洩判定ならTrueとなる契約を検証する.

        Returns:
            None: HIBP由来の禁止結果を検証して完了し,呼び出し側へ値を返さない.
        """
        hibp = FakeHIBPClient(compromised_passwords={"leaked_password"})
        svc = PasswordService(hibp_client=hibp, banned_passwords=[])

        result = await svc.is_password_banned("leaked_password")

        assert result is True

    async def test_custom_list_checked_before_hibp(self) -> None:
        """custom禁止list一致時にHIBP照会を省略する順序契約を検証する.

        Returns:
            None: custom一致時の照会回数と禁止結果を検証して完了し,呼び出し側へ値を返さない.
        """
        hibp = FakeHIBPClient()
        svc = PasswordService(hibp_client=hibp, banned_passwords=["banned_pass"])

        result = await svc.is_password_banned("banned_pass")

        assert result is True
        assert len(hibp.calls) == 0

    async def test_hibp_fallback_on_api_unreachable(self) -> None:
        """HIBPが安全結果を返す場合にcustom禁止listだけで判定する契約を検証する.

        Returns:
            None: HIBP fallback時の安全と禁止の両結果を検証して完了し,呼び出し側へ値を返さない.
        """
        hibp = FakeHIBPClient()
        svc = PasswordService(hibp_client=hibp, banned_passwords=["banned_one"])

        # カスタムリストに無い + HIBP False → False
        assert await svc.is_password_banned("safe_password") is False
        # カスタムリストに含まれる → True(HIBP 結果に関係なく)
        assert await svc.is_password_banned("banned_one") is True

    async def test_safe_password_with_both_checks(self) -> None:
        """custom禁止listとHIBPの両方を通過したpasswordがFalseとなる契約を検証する.

        Returns:
            None: 両方の検査を通過した結果を検証して完了し,呼び出し側へ値を返さない.
        """
        hibp = FakeHIBPClient()
        svc = PasswordService(hibp_client=hibp, banned_passwords=["other"])

        result = await svc.is_password_banned("completely_safe")

        assert result is False


class TestPasswordServiceBackwardCompatibility:
    """PasswordServiceの既存constructor互換性を検証する."""

    async def test_default_constructor_still_works(self) -> None:
        """引数なしconstructorでもhash機能を利用できる契約を検証する.

        Returns:
            None: default構築後のhash形式を検証して完了し,呼び出し側へ値を返さない.
        """
        svc = PasswordService()
        hashed = await svc.hash("test")
        assert hashed.startswith("$argon2id$")

    async def test_check_hibp_returns_false_with_defaults(self) -> None:
        """default構築時にcheck_hibpがFalseを返す契約を検証する.

        Returns:
            None: HIBP未設定のdefault結果を検証して完了し,呼び出し側へ値を返さない.
        """
        svc = PasswordService()
        assert await svc.check_hibp("anything") is False

    async def test_is_password_banned_returns_false_with_defaults(self) -> None:
        """default構築時にis_password_bannedがFalseを返す契約を検証する.

        Returns:
            None: 禁止設定がないdefault結果を検証して完了し,呼び出し側へ値を返さない.
        """
        svc = PasswordService()
        assert await svc.is_password_banned("anything") is False


class TestPasswordVerificationFailedLog:
    """verify失敗時のpassword_verification_failed log契約を検証する."""

    async def test_mismatch_emits_log(self) -> None:
        """credential不一致時にwarning logが一度出力される契約を検証する.

        Returns:
            None: 不一致結果とpassword_verification_failed logを検証して完了する.
                呼び出し側へ値を返さない.
        """
        svc = PasswordService()
        hashed = await svc.hash("correct_password")
        with capture_logs() as cap_logs:
            result = await svc.verify(hashed, "wrong_password")
        assert result is False
        events = [e for e in cap_logs if e["event"] == "password_verification_failed"]
        assert len(events) == 1
        assert events[0]["reason"] == "hash_mismatch"
        assert events[0]["log_level"] == "warning"

    async def test_success_does_not_emit_log(self) -> None:
        """credential一致時に失敗logを出力しない契約を検証する.

        Returns:
            None: 成功結果と失敗log不在を検証して完了し,呼び出し側へ値を返さない.
        """
        svc = PasswordService()
        password = "correct_password"
        hashed = await svc.hash(password)
        with capture_logs() as cap_logs:
            result = await svc.verify(hashed, password)
        assert result is True
        events = [e for e in cap_logs if e["event"] == "password_verification_failed"]
        assert len(events) == 0


class TestPasswordBannedLog:
    """is_password_banned時のpassword_banned log契約を検証する."""

    async def test_custom_list_emits_log_with_source(self) -> None:
        """custom禁止list一致時にcustom_list sourceのwarning logを出す契約を検証する.

        Returns:
            None: custom禁止結果とlog sourceを検証して完了し,呼び出し側へ値を返さない.
        """
        svc = PasswordService(hibp_client=None, banned_passwords=["forbidden"])
        with capture_logs() as cap_logs:
            result = await svc.is_password_banned("forbidden")
        assert result is True
        events = [e for e in cap_logs if e["event"] == "password_banned"]
        assert len(events) == 1
        assert events[0]["source"] == "custom_list"
        assert events[0]["log_level"] == "warning"

    async def test_hibp_emits_log_with_source(self) -> None:
        """HIBP漏洩判定時にhibp sourceのwarning logを出す契約を検証する.

        Returns:
            None: HIBP禁止結果とlog sourceを検証して完了し,呼び出し側へ値を返さない.
        """
        hibp = FakeHIBPClient(compromised_passwords={"leaked_password"})
        svc = PasswordService(hibp_client=hibp, banned_passwords=[])
        with capture_logs() as cap_logs:
            result = await svc.is_password_banned("leaked_password")
        assert result is True
        events = [e for e in cap_logs if e["event"] == "password_banned"]
        assert len(events) == 1
        assert events[0]["source"] == "hibp"
        assert events[0]["log_level"] == "warning"

    async def test_safe_password_does_not_emit_log(self) -> None:
        """安全なpasswordではpassword_banned logを出力しない契約を検証する.

        Returns:
            None: 安全結果と禁止log不在を検証して完了し,呼び出し側へ値を返さない.
        """
        hibp = FakeHIBPClient()
        svc = PasswordService(hibp_client=hibp, banned_passwords=["other"])
        with capture_logs() as cap_logs:
            result = await svc.is_password_banned("safe_password")
        assert result is False
        events = [e for e in cap_logs if e["event"] == "password_banned"]
        assert len(events) == 0

    async def test_custom_list_hit_does_not_call_hibp(self) -> None:
        """custom禁止list一致時にHIBPを呼ばずcustom_list logだけを出す契約を検証する.

        Returns:
            None: HIBP照会不在とcustom_list logを検証して完了し,呼び出し側へ値を返さない.
        """
        hibp = FakeHIBPClient()
        svc = PasswordService(hibp_client=hibp, banned_passwords=["banned_pass"])
        with capture_logs() as cap_logs:
            result = await svc.is_password_banned("banned_pass")
        assert result is True
        assert len(hibp.calls) == 0
        events = [e for e in cap_logs if e["event"] == "password_banned"]
        assert len(events) == 1
        assert events[0]["source"] == "custom_list"
