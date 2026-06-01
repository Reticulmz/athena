from __future__ import annotations

from dataclasses import fields

from osu_server.domain.auth import (
    AuthenticationError,
    ClientInfo,
    LoginRequest,
    LoginResponse,
    LoginResult,
    RegistrationError,
    RegistrationForm,
    RegistrationResult,
)
from osu_server.shared.errors import AppError


class TestLoginResult:
    def test_all_codes_negative(self) -> None:
        for member in LoginResult:
            assert member.value < 0

    def test_codes_are_distinct(self) -> None:
        values = [m.value for m in LoginResult]
        assert len(values) == len(set(values))

    def test_expected_members(self) -> None:
        names = {m.name for m in LoginResult}
        expected = {
            "AUTHENTICATION_FAILED",
            "OLD_CLIENT",
            "BANNED",
            "BANNED_ALT",
            "SERVER_ERROR",
            "SUPPORTER_ONLY",
            "PASSWORD_RESET",
        }
        assert names == expected


class TestClientInfo:
    def test_slots(self) -> None:
        assert hasattr(ClientInfo, "__slots__")

    def test_creation(self) -> None:
        info = ClientInfo(
            osu_version="b20240101.1",
            utc_offset=9,
            display_city=True,
            client_hashes="abc:def:ghi",
            pm_private=False,
        )
        assert info.osu_version == "b20240101.1"
        assert info.utc_offset == 9
        assert info.display_city is True
        assert info.client_hashes == "abc:def:ghi"
        assert info.pm_private is False


class TestLoginRequest:
    def test_slots(self) -> None:
        assert hasattr(LoginRequest, "__slots__")

    def test_creation(self) -> None:
        client_info = ClientInfo(
            osu_version="b20240101.1",
            utc_offset=9,
            display_city=True,
            client_hashes="abc",
            pm_private=False,
        )
        req = LoginRequest(
            username="TestUser",
            password_md5="d41d8cd98f00b204e9800998ecf8427e",
            client_info=client_info,
        )
        assert req.username == "TestUser"
        assert req.password_md5 == "d41d8cd98f00b204e9800998ecf8427e"
        assert req.client_info is client_info


class TestRegistrationForm:
    def test_creation(self) -> None:
        form = RegistrationForm(
            username="NewPlayer",
            email="player@example.com",
            password="securepass123",
        )
        assert form.username == "NewPlayer"
        assert form.email == "player@example.com"
        assert form.password == "securepass123"


class TestRegistrationResult:
    def test_success(self) -> None:
        result = RegistrationResult(success=True, errors={})
        assert result.success is True
        assert result.errors == {}

    def test_failure(self) -> None:
        result = RegistrationResult(
            success=False,
            errors={"username": ["Username already taken"]},
        )
        assert result.success is False
        assert "username" in result.errors


class TestLoginResponse:
    def test_slots(self) -> None:
        assert hasattr(LoginResponse, "__slots__")

    def test_fields(self) -> None:
        field_names = {f.name for f in fields(LoginResponse)}
        expected = {"token", "user", "privileges", "role_ids", "country", "session_data"}
        assert field_names == expected


class TestAuthenticationError:
    def test_inherits_app_error(self) -> None:
        err = AuthenticationError(LoginResult.AUTHENTICATION_FAILED)
        assert isinstance(err, AppError)
        assert err.result == LoginResult.AUTHENTICATION_FAILED

    def test_server_error(self) -> None:
        err = AuthenticationError(LoginResult.SERVER_ERROR)
        assert err.result == LoginResult.SERVER_ERROR


class TestRegistrationError:
    def test_inherits_app_error(self) -> None:
        err = RegistrationError({"email": ["Invalid email"]})
        assert isinstance(err, AppError)
        assert err.errors == {"email": ["Invalid email"]}
