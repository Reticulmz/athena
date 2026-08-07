"""Identity authentication value objectとerror契約を検証するmodule.

Stable loginとregistrationで利用する値型が保持するfieldおよびfailure情報を検証する.
"""

from __future__ import annotations

from dataclasses import fields

from osu_server.domain.identity.authentication import (
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
    """Stable login responseの結果code契約を検証するtest群."""

    def test_all_codes_negative(self) -> None:
        """すべてのLoginResultが負数codeというwire契約を検証する.

        全enum memberを走査し0未満の値だけがclientへ返ることを確認する.

        Returns:
            None: 負数codeの検証を完了する.
        """
        for member in LoginResult:
            assert member.value < 0

    def test_codes_are_distinct(self) -> None:
        """LoginResultの各failure codeが一意であることを検証する.

        enum memberから収集した値と重複を除いた値を比較しresponse reasonを区別できることを確認する.

        Returns:
            None: 一意なcode集合の検証を完了する.
        """
        values = [m.value for m in LoginResult]
        assert len(values) == len(set(values))

    def test_expected_members(self) -> None:
        """Stable loginが扱うfailure reason集合を検証する.

        LoginResultのmember名を期待集合と比較しfailure reasonの欠落や追加がないことを確認する.

        Returns:
            None: failure reason集合の検証を完了する.
        """
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
    """Stable client実行環境情報の保持契約を検証するtest群."""

    def test_slots(self) -> None:
        """ClientInfoがslotのみを持つvalue objectであることを検証する.

        型定義を調べて__slots__が存在しinstance dictionaryを増やさないことを確認する.

        Returns:
            None: slot利用の検証を完了する.
        """
        assert hasattr(ClientInfo, "__slots__")

    def test_creation(self) -> None:
        """ClientInfoがlogin時のclient情報を変更せず保持することを検証する.

        versionとtimezone等を指定して生成し各fieldから同じ値を取得できることを確認する.

        Returns:
            None: client情報保持の検証を完了する.
        """
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
    """Login request入力値の保持契約を検証するtest群."""

    def test_slots(self) -> None:
        """LoginRequestがslotのみを持つrequest value objectであることを検証する.

        型定義を調べて__slots__が存在しlogin requestが固定fieldだけを持つことを確認する.

        Returns:
            None: slot利用の検証を完了する.
        """
        assert hasattr(LoginRequest, "__slots__")

    def test_creation(self) -> None:
        """LoginRequestがcredentialとClientInfoの参照を保持することを検証する.

        login入力を組み立ててcredentialとclient_info参照が同じ入力値を保持することを確認する.

        Returns:
            None: login request保持の検証を完了する.
        """
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
    """Registration入力formのfield保持契約を検証するtest群."""

    def test_creation(self) -> None:
        """RegistrationFormが利用者入力をそのまま保持することを検証する.

        usernameとemailおよびpasswordを指定して生成し各fieldが入力値と一致することを確認する.

        Returns:
            None: registration form保持の検証を完了する.
        """
        form = RegistrationForm(
            username="NewPlayer",
            email="player@example.com",
            password="securepass123",
        )
        assert form.username == "NewPlayer"
        assert form.email == "player@example.com"
        assert form.password == "securepass123"


class TestRegistrationResult:
    """Registration結果の成功状態とvalidation error契約を検証するtest群."""

    def test_success(self) -> None:
        """成功したregistrationが空のerror mappingを返すことを検証する.

        successをTrueとして結果を生成し成功状態と空mappingが観測できることを確認する.

        Returns:
            None: 成功結果の検証を完了する.
        """
        result = RegistrationResult(success=True, errors={})
        assert result.success is True
        assert result.errors == {}

    def test_failure(self) -> None:
        """失敗したregistrationがfield別validation errorを返すことを検証する.

        username errorを持つ失敗結果を生成し成功状態がFalseでerror keyを取得できることを確認する.

        Returns:
            None: 失敗結果の検証を完了する.
        """
        result = RegistrationResult(
            success=False,
            errors={"username": ["Username already taken"]},
        )
        assert result.success is False
        assert "username" in result.errors


class TestLoginResponse:
    """成功login responseの固定field契約を検証するtest群."""

    def test_slots(self) -> None:
        """LoginResponseがslotのみを持つresponse value objectであることを検証する.

        型定義を調べて__slots__が存在しsession responseが固定fieldだけを持つことを確認する.

        Returns:
            None: slot利用の検証を完了する.
        """
        assert hasattr(LoginResponse, "__slots__")

    def test_fields(self) -> None:
        """LoginResponseがlogin完了に必要なfield集合を持つことを検証する.

        dataclass field名を期待集合と比較しtokenとsession情報の欠落や余分がないことを確認する.

        Returns:
            None: response field集合の検証を完了する.
        """
        field_names = {f.name for f in fields(LoginResponse)}
        expected = {"token", "user", "privileges", "role_ids", "country", "session_data"}
        assert field_names == expected


class TestAuthenticationError:
    """AuthenticationErrorのAppError継承とresult保持を検証するtest群."""

    def test_inherits_app_error(self) -> None:
        """AuthenticationErrorが共通application errorとして扱えることを検証する.

        failure codeで生成しAppError instanceと同じresultが取得できることを確認する.

        Returns:
            None: error継承とresult保持の検証を完了する.
        """
        err = AuthenticationError(LoginResult.AUTHENTICATION_FAILED)
        assert isinstance(err, AppError)
        assert err.result == LoginResult.AUTHENTICATION_FAILED

    def test_server_error(self) -> None:
        """AuthenticationErrorがserver failure codeを保持することを検証する.

        SERVER_ERRORで生成しstable clientへ変換するresultが変更されないことを確認する.

        Returns:
            None: server error code保持の検証を完了する.
        """
        err = AuthenticationError(LoginResult.SERVER_ERROR)
        assert err.result == LoginResult.SERVER_ERROR


class TestRegistrationError:
    """RegistrationErrorのAppError継承とerror mapping保持を検証するtest群."""

    def test_inherits_app_error(self) -> None:
        """RegistrationErrorがfield別validation errorを運ぶことを検証する.

        email error mappingで生成しAppError instanceであり元のmappingを取得できることを確認する.

        Returns:
            None: registration error保持の検証を完了する.
        """
        err = RegistrationError({"email": ["Invalid email"]})
        assert isinstance(err, AppError)
        assert err.errors == {"email": ["Invalid email"]}
