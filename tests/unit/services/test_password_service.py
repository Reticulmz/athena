from __future__ import annotations

import hashlib

from structlog.testing import capture_logs

from osu_server.services.queries.identity.password_service import PasswordService
from tests.support import FakeHIBPClient


class TestHash:
    async def test_returns_argon2id_hash(self) -> None:
        svc = PasswordService()
        hashed = await svc.hash("some_password")
        assert hashed.startswith("$argon2id$")

    async def test_different_inputs_produce_different_hashes(self) -> None:
        svc = PasswordService()
        h1 = await svc.hash("password_a")
        h2 = await svc.hash("password_b")
        assert h1 != h2

    async def test_same_input_produces_different_hashes(self) -> None:
        """argon2 uses random salt, so hashing the same input twice yields different strings."""
        svc = PasswordService()
        h1 = await svc.hash("same_password")
        h2 = await svc.hash("same_password")
        assert h1 != h2


class TestVerify:
    async def test_roundtrip_success(self) -> None:
        svc = PasswordService()
        password = "correct_password"
        hashed = await svc.hash(password)
        assert await svc.verify(hashed, password) is True

    async def test_mismatch_returns_false(self) -> None:
        svc = PasswordService()
        hashed = await svc.hash("correct_password")
        assert await svc.verify(hashed, "wrong_password") is False

    async def test_empty_password_mismatch(self) -> None:
        svc = PasswordService()
        hashed = await svc.hash("non_empty")
        assert await svc.verify(hashed, "") is False


class TestPreparePassword:
    def test_legacy_plaintext_md5_matches_stable_client_hash(self) -> None:
        """legacy_plaintext_md5 は stable client 互換の lowercase MD5 hex を返す。"""
        svc = PasswordService()
        plain = "my_secure_password"

        assert (
            svc.legacy_plaintext_md5(plain)
            == hashlib.md5(plain.encode(), usedforsecurity=False).hexdigest()
        )

    async def test_prepare_password_roundtrip(self) -> None:
        """prepare_password(plain) produces a hash verifiable with md5(plain)."""
        svc = PasswordService()
        plain = "my_secure_password"
        stored_hash = await svc.prepare_password(plain)

        md5_of_plain = hashlib.md5(plain.encode(), usedforsecurity=False).hexdigest()
        assert await svc.verify(stored_hash, md5_of_plain) is True

    async def test_prepare_password_returns_argon2id(self) -> None:
        svc = PasswordService()
        stored_hash = await svc.prepare_password("test_password")
        assert stored_hash.startswith("$argon2id$")

    async def test_prepare_password_wrong_plain_fails(self) -> None:
        """Verifying with md5 of a different plaintext must fail."""
        svc = PasswordService()
        stored_hash = await svc.prepare_password("original_password")

        wrong_md5 = hashlib.md5(b"different_password", usedforsecurity=False).hexdigest()
        assert await svc.verify(stored_hash, wrong_md5) is False

    async def test_prepare_password_simulates_login_flow(self) -> None:
        """Registration: prepare_password(plain) → store hash.
        Login: client sends md5(plain), server calls verify(hash, client_md5).
        """
        svc = PasswordService()
        plain = "hunter2"

        # Registration
        stored_hash = await svc.prepare_password(plain)

        # Login — client computes MD5 client-side
        client_md5 = hashlib.md5(plain.encode(), usedforsecurity=False).hexdigest()
        assert await svc.verify(stored_hash, client_md5) is True

    async def test_prepare_password_accepts_uppercase_client_md5(self) -> None:
        """Stable auth の password MD5 hex は大小文字差を認証差にしない."""
        svc = PasswordService()
        plain = "SecurePass1234"
        stored_hash = await svc.prepare_password(plain)

        client_md5 = hashlib.md5(plain.encode(), usedforsecurity=False).hexdigest().upper()

        assert await svc.verify(stored_hash, client_md5) is True


class TestCheckHibp:
    """PasswordService.check_hibp のテスト。"""

    async def test_returns_true_when_compromised(self) -> None:
        """HIBPClient が漏洩判定した場合 True を返す。"""
        hibp = FakeHIBPClient(compromised_passwords={"leaked_password"})
        svc = PasswordService(hibp_client=hibp, banned_passwords=[])

        result = await svc.check_hibp("leaked_password")

        assert result is True
        assert "leaked_password" in hibp.calls

    async def test_returns_false_when_safe(self) -> None:
        """HIBPClient が安全判定した場合 False を返す。"""
        hibp = FakeHIBPClient()
        svc = PasswordService(hibp_client=hibp, banned_passwords=[])

        result = await svc.check_hibp("safe_password")

        assert result is False

    async def test_returns_false_when_hibp_client_is_none(self) -> None:
        """HIBPClient が None の場合 False を返す(HIBP 無効環境)。"""
        svc = PasswordService(hibp_client=None, banned_passwords=[])

        result = await svc.check_hibp("any_password")

        assert result is False


class TestIsPasswordBanned:
    """PasswordService.is_password_banned のテスト。"""

    async def test_banned_by_custom_list(self) -> None:
        """カスタム禁止リストに含まれるパスワードは True を返す。"""
        svc = PasswordService(hibp_client=None, banned_passwords=["forbidden", "secret123"])

        assert await svc.is_password_banned("forbidden") is True
        assert await svc.is_password_banned("secret123") is True

    async def test_custom_list_case_insensitive(self) -> None:
        """カスタム禁止リストの照合は大文字小文字を区別しない。"""
        svc = PasswordService(hibp_client=None, banned_passwords=["Forbidden"])

        assert await svc.is_password_banned("forbidden") is True
        assert await svc.is_password_banned("FORBIDDEN") is True

    async def test_not_in_custom_list_and_no_hibp(self) -> None:
        """禁止リストに無く、HIBP も None の場合は False。"""
        svc = PasswordService(hibp_client=None, banned_passwords=["other"])

        assert await svc.is_password_banned("safe_password") is False

    async def test_banned_by_hibp(self) -> None:
        """カスタムリストに無いが HIBP で漏洩判定された場合は True。"""
        hibp = FakeHIBPClient(compromised_passwords={"leaked_password"})
        svc = PasswordService(hibp_client=hibp, banned_passwords=[])

        result = await svc.is_password_banned("leaked_password")

        assert result is True

    async def test_custom_list_checked_before_hibp(self) -> None:
        """カスタムリストを先にチェックし、一致すれば HIBP は呼ばない。"""
        hibp = FakeHIBPClient()
        svc = PasswordService(hibp_client=hibp, banned_passwords=["banned_pass"])

        result = await svc.is_password_banned("banned_pass")

        assert result is True
        assert len(hibp.calls) == 0

    async def test_hibp_fallback_on_api_unreachable(self) -> None:
        """HIBP が False を返す(API 不達フォールバック)場合、カスタムリストのみで判定。"""
        hibp = FakeHIBPClient()
        svc = PasswordService(hibp_client=hibp, banned_passwords=["banned_one"])

        # カスタムリストに無い + HIBP False → False
        assert await svc.is_password_banned("safe_password") is False
        # カスタムリストに含まれる → True(HIBP 結果に関係なく)
        assert await svc.is_password_banned("banned_one") is True

    async def test_safe_password_with_both_checks(self) -> None:
        """両方のチェックをパスした場合のみ False。"""
        hibp = FakeHIBPClient()
        svc = PasswordService(hibp_client=hibp, banned_passwords=["other"])

        result = await svc.is_password_banned("completely_safe")

        assert result is False


class TestPasswordServiceBackwardCompatibility:
    """既存コンストラクタとの後方互換性テスト。"""

    async def test_default_constructor_still_works(self) -> None:
        """引数なしコンストラクタで既存動作が維持される。"""
        svc = PasswordService()
        hashed = await svc.hash("test")
        assert hashed.startswith("$argon2id$")

    async def test_check_hibp_returns_false_with_defaults(self) -> None:
        """デフォルト構築時、check_hibp は常に False。"""
        svc = PasswordService()
        assert await svc.check_hibp("anything") is False

    async def test_is_password_banned_returns_false_with_defaults(self) -> None:
        """デフォルト構築時、is_password_banned は常に False。"""
        svc = PasswordService()
        assert await svc.is_password_banned("anything") is False


class TestPasswordVerificationFailedLog:
    """verify() 失敗時の password_verification_failed ログイベント検証。"""

    async def test_mismatch_emits_log(self) -> None:
        """パスワード不一致時に password_verification_failed イベントが出力される。"""
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
        """パスワード一致時に password_verification_failed イベントは出力されない。"""
        svc = PasswordService()
        password = "correct_password"
        hashed = await svc.hash(password)
        with capture_logs() as cap_logs:
            result = await svc.verify(hashed, password)
        assert result is True
        events = [e for e in cap_logs if e["event"] == "password_verification_failed"]
        assert len(events) == 0


class TestPasswordBannedLog:
    """is_password_banned() の password_banned ログイベント検証。"""

    async def test_custom_list_emits_log_with_source(self) -> None:
        """カスタム禁止リスト一致時に source=custom_list でログが出力される。"""
        svc = PasswordService(hibp_client=None, banned_passwords=["forbidden"])
        with capture_logs() as cap_logs:
            result = await svc.is_password_banned("forbidden")
        assert result is True
        events = [e for e in cap_logs if e["event"] == "password_banned"]
        assert len(events) == 1
        assert events[0]["source"] == "custom_list"
        assert events[0]["log_level"] == "warning"

    async def test_hibp_emits_log_with_source(self) -> None:
        """HIBP 漏洩判定時に source=hibp でログが出力される。"""
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
        """安全なパスワードでは password_banned イベントは出力されない。"""
        hibp = FakeHIBPClient()
        svc = PasswordService(hibp_client=hibp, banned_passwords=["other"])
        with capture_logs() as cap_logs:
            result = await svc.is_password_banned("safe_password")
        assert result is False
        events = [e for e in cap_logs if e["event"] == "password_banned"]
        assert len(events) == 0

    async def test_custom_list_hit_does_not_call_hibp(self) -> None:
        """カスタムリスト一致時は HIBP を呼ばず custom_list のみログ出力される。"""
        hibp = FakeHIBPClient()
        svc = PasswordService(hibp_client=hibp, banned_passwords=["banned_pass"])
        with capture_logs() as cap_logs:
            result = await svc.is_password_banned("banned_pass")
        assert result is True
        assert len(hibp.calls) == 0
        events = [e for e in cap_logs if e["event"] == "password_banned"]
        assert len(events) == 1
        assert events[0]["source"] == "custom_list"
