from __future__ import annotations

import hashlib

from osu_server.services.password_service import PasswordService


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
    async def test_prepare_password_roundtrip(self) -> None:
        """prepare_password(plain) produces a hash verifiable with md5(plain)."""
        svc = PasswordService()
        plain = "my_secure_password"
        stored_hash = await svc.prepare_password(plain)

        md5_of_plain = hashlib.md5(plain.encode()).hexdigest()
        assert await svc.verify(stored_hash, md5_of_plain) is True

    async def test_prepare_password_returns_argon2id(self) -> None:
        svc = PasswordService()
        stored_hash = await svc.prepare_password("test_password")
        assert stored_hash.startswith("$argon2id$")

    async def test_prepare_password_wrong_plain_fails(self) -> None:
        """Verifying with md5 of a different plaintext must fail."""
        svc = PasswordService()
        stored_hash = await svc.prepare_password("original_password")

        wrong_md5 = hashlib.md5(b"different_password").hexdigest()
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
        client_md5 = hashlib.md5(plain.encode()).hexdigest()
        assert await svc.verify(stored_hash, client_md5) is True
