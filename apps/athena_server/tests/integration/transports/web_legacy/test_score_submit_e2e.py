"""Stable score submit endpointのE2E contractを検証するintegration test.

multipart request, projection更新, terminal reject responseの互換性を確認する.
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, cast

import pytest
from starlette.datastructures import Headers
from tests.support.credentials import fixed_test_password_md5
from tests.support.fakes import (
    StubBlobStorageService,
    StubScorePayloadDecryptor,
    make_stable_score_submit_decoder,
    make_submit_score_use_case,
)

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapEligibility,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapResolveResult,
    BeatmapSourceVerification,
)
from osu_server.domain.scores.decryption import DecryptedPayload
from osu_server.domain.scores.leaderboards import ScoreRankKey
from osu_server.domain.scores.mods import Mod, ModCombination
from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.repositories.interfaces.commands.beatmap_leaderboards import (
    BeatmapLeaderboardUserBestScope,
    BeatmapLeaderboardUserProjectionSlice,
    BeatmapLeaderboardUserScope,
    UpsertBeatmapLeaderboardUserBest,
)
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.scores import (
    ProcessScoreSubmissionUseCase,
    ScoreSubmissionAuthorizer,
)
from osu_server.services.commands.scores.authorization import AuthorizationContext
from osu_server.transports.stable.web_legacy.mappers import (
    StableScoreSubmitMapper,
)
from osu_server.transports.stable.web_legacy.score_submit import ScoreSubmitHandler

if TYPE_CHECKING:
    from starlette.requests import Request

    from osu_server.domain.beatmaps import BeatmapResolveOptions


def _resolved_beatmap() -> Beatmap:
    """Score submitで解決済みとみなすranked beatmapを作成する.

    Returns:
        Beatmap: fixed checksumとranked statusを持つtest beatmap.
    """
    return Beatmap(
        id=1,
        beatmapset_id=10,
        checksum_md5="0123456789abcdef0123456789abcdef",
        mode=BeatmapMode.OSU,
        version="Test",
        total_length=None,
        hit_length=None,
        max_combo=None,
        bpm=None,
        cs=None,
        od=None,
        ar=None,
        hp=None,
        difficulty_rating=None,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        local_status_override=None,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=BeatmapFileState.MISSING,
        file_attachment=None,
        last_fetched_at=None,
        next_refresh_at=None,
    )


def _eligible_result() -> BeatmapResolveResult:
    """Score受理を許可するbeatmap resolve resultを作成する.

    Returns:
        BeatmapResolveResult: ranked beatmapとleaderboard適格eligibilityを持つ解決結果.
    """
    return BeatmapResolveResult(
        beatmap=_resolved_beatmap(),
        beatmapset=None,
        eligibility=BeatmapEligibility(
            accepts_scores=True,
            has_leaderboard=True,
            awards_ranked_pp=True,
            awards_loved_pp=False,
            requires_osu_file_for_pp=True,
            is_officially_verified=True,
            is_mirror_derived=False,
            accepts_failed_scores=True,
            failed_scores_have_leaderboard=False,
            failed_scores_update_best_score=False,
            failed_scores_award_ranked_pp=False,
            failed_scores_award_loved_pp=False,
            denial_reason=None,
        ),
        metadata_status=BeatmapFetchState.FRESH,
        file_status=BeatmapFileState.MISSING,
        source=BeatmapMetadataSource.OFFICIAL,
        verified=True,
        last_fetched_at=None,
        next_refresh_at=None,
        reason=None,
    )


class MockAuthService:
    """常に認可成功を返すscore submission authorization fake."""

    async def authorize_submission(
        self, password_md5: str, payload_username: str, payload_user_id: int
    ) -> AuthorizationContext:
        """Password値に関係なくpayload identityを認可済みとして返す.

        Args:
            password_md5 (str): stable requestから渡されるMD5 password, fakeでは使用しない.
            payload_username (str): payload内のuser名.
            payload_user_id (int): payload内のuser識別子.

        Returns:
            AuthorizationContext: session, password, payload identityがすべてvalidの認可結果.
        """
        _ = password_md5
        return AuthorizationContext(
            user_id=payload_user_id,
            username=payload_username,
            session_valid=True,
            password_valid=True,
            payload_identity_match=True,
        )


class MockBeatmapResolver:
    """常にeligibleなbeatmap解決結果を返すresolver fake."""

    async def resolve_by_beatmap_id(
        self, beatmap_id: int, options: BeatmapResolveOptions | None = None
    ) -> BeatmapResolveResult:
        """Beatmap識別子の解決を固定eligible resultで模擬する.

        Args:
            beatmap_id (int): 解決要求されたbeatmap識別子, fakeでは使用しない.
            options (BeatmapResolveOptions | None): 解決option, fakeでは使用しない.

        Returns:
            BeatmapResolveResult: score受理を許可する固定解決結果.
        """
        _ = beatmap_id, options
        return _eligible_result()

    async def resolve_by_checksum(
        self, checksum_md5: str, options: BeatmapResolveOptions | None = None
    ) -> BeatmapResolveResult:
        """Beatmap checksumの解決を固定eligible resultで模擬する.

        Args:
            checksum_md5 (str): 解決要求されたMD5 checksum, fakeでは使用しない.
            options (BeatmapResolveOptions | None): 解決option, fakeでは使用しない.

        Returns:
            BeatmapResolveResult: score受理を許可する固定解決結果.
        """
        _ = checksum_md5, options
        return _eligible_result()


class MockRequest:
    """Handlerへ直接渡す最小Starlette request fake.

    Attributes:
        headers (Headers): multipart content typeを持つrequest header.
        _body (bytes): body()が返すrequest body bytes.
    """

    headers: Headers
    _body: bytes

    def __init__(self, body_data: bytes, content_type: str) -> None:
        """Multipart bodyとcontent type headerを設定する.

        Args:
            body_data (bytes): body()で返すraw multipart bytes.
            content_type (str): request headerへ設定するmultipart content type.
        """
        self.headers = Headers({"content-type": content_type})
        self._body = body_data

    async def body(self) -> bytes:
        """設定済みのraw request bodyを返す.

        Returns:
            bytes: handlerがmultipartとして解析するbody bytes.
        """
        return self._body


def _request(body_data: bytes, content_type: str) -> Request:
    """MockRequestをhandler引数として扱うRequest型へcastする.

    Args:
        body_data (bytes): request fakeへ設定するraw multipart bytes.
        content_type (str): request fakeへ設定するmultipart content type.

    Returns:
        Request: ScoreSubmitHandlerへ渡すための構造互換request.
    """
    return cast("Request", cast("object", MockRequest(body_data, content_type)))


def _create_valid_multipart_body(
    *,
    encrypted_payload: bytes = b"test_encrypted_payload",
    replay_data: bytes = b"test_replay_data",
    client_hash: bytes = b"client_hash_example",
) -> tuple[bytes, str]:
    """有効なstable multipart request bodyを作る.

    Args:
        encrypted_payload (bytes): score fieldへ入れる暗号化済みpayloadのdummy bytes.
        replay_data (bytes): replay fieldへ入れるbytes.
        client_hash (bytes): stable client hash fieldへ入れるbytes.

    Returns:
        tuple[bytes, str]: multipart bodyとContent-Type header value.

    Notes:
        encrypted_payloadはbase64 encodeしてbodyへ入れ,
        復号内容はdecoder fakeのpayload_decryptorが決める.
    """
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    content_type = f"multipart/form-data; boundary={boundary}"

    # Valid encrypted payload that decrypts to a real score
    # Format: user_id:username:checksum:online_checksum:ruleset:...
    encrypted_payload = base64.b64encode(encrypted_payload)
    iv = base64.b64encode(b"0" * 32)

    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="score"\r\n\r\n').encode()
    body += encrypted_payload + b"\r\n"

    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="iv"\r\n\r\n').encode()
    body += iv + b"\r\n"

    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="pass"\r\n\r\n'
    body += fixed_test_password_md5().encode("ascii") + b"\r\n"
    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="x"\r\n\r\n'
    body += client_hash + b"\r\n"
    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="ft"\r\n\r\n'
    body += b"0\r\n"
    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="osuver"\r\n\r\n'
    body += b"20241201\r\n"
    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="score"\r\n\r\n'
    body += replay_data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()

    return body, content_type


def _make_process_score_submission_use_case(
    *, auth_service: ScoreSubmissionAuthorizer
) -> ProcessScoreSubmissionUseCase:
    """In-memory依存を使うscore submission processing use-caseを構築する.

    Args:
        auth_service (ScoreSubmissionAuthorizer): submitterを認可する実装またはfake.

    Returns:
        ProcessScoreSubmissionUseCase: handlerがscore, replay, projectionを処理するuse-case.
    """
    uow_factory = InMemoryUnitOfWorkFactory()
    return ProcessScoreSubmissionUseCase(
        submit_score_use_case=make_submit_score_use_case(uow_factory),
        replay_blob_storage=StubBlobStorageService(),
        auth_service=auth_service,
        beatmap_resolver=MockBeatmapResolver(),
    )


def _leaderboard_scope() -> BeatmapLeaderboardUserBestScope:
    """Test userのno-mod global user bestを検索するscopeを作成する.

    Returns:
        BeatmapLeaderboardUserBestScope: fixed beatmap, user, ruleset, playstyleを持つscope.
    """
    return BeatmapLeaderboardUserBestScope(
        beatmap_id=1,
        beatmap_checksum="0123456789abcdef0123456789abcdef",
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        user_id=1000,
        mods=ModCombination.none(),
    )


async def _get_leaderboard_best_score_id(
    uow_factory: InMemoryUnitOfWorkFactory,
) -> int | None:
    """Test userのglobal leaderboard best score識別子を取得する.

    Args:
        uow_factory (InMemoryUnitOfWorkFactory): global user bestを読むin-memory factory.

    Returns:
        int | None: 現在のbest score識別子, projection未作成時はNone.
    """
    async with uow_factory() as uow:
        best = await uow.beatmap_leaderboards.get_global_user_best(
            BeatmapLeaderboardUserScope(
                beatmap_id=1,
                beatmap_checksum="0123456789abcdef0123456789abcdef",
                ruleset=Ruleset.OSU,
                playstyle=Playstyle.VANILLA,
                user_id=1000,
            )
        )
        return best.score_id if best is not None else None


async def _replace_projection_with_score(
    uow_factory: InMemoryUnitOfWorkFactory,
    *,
    score_id: int,
) -> None:
    """Test userのprojectionを既存scoreへ戻してsnapshot検証を準備する.

    Args:
        uow_factory (InMemoryUnitOfWorkFactory): scoreとprojectionを読み書きするfactory.
        score_id (int): replacement projectionに設定する既存score識別子.

    Returns:
        None: projection sliceを置換してcommitした後に値を返さない.

    Raises:
        AssertionError: score_idに対応するscoreが存在しない場合.
    """
    async with uow_factory() as uow:
        score = await uow.scores.get_by_id(score_id)
        assert score is not None
        await uow.beatmap_leaderboards.replace_projection_slice(
            BeatmapLeaderboardUserProjectionSlice(user_id=1000),
            (
                UpsertBeatmapLeaderboardUserBest(
                    scope=_leaderboard_scope(),
                    score_id=score_id,
                    rank_key=ScoreRankKey(
                        score=score.score,
                        submitted_at=score.submitted_at,
                        score_id=score_id,
                    ),
                ),
            ),
        )
        await uow.commit()


@pytest.mark.asyncio
async def test_e2e_score_submit_completed_response() -> None:
    """実multipart POSTがcompleted stable responseを返すことを検証する.

    Returns:
        None: response statusとstable chart bodyをassertして終了する.

    Raises:
        AssertionError: response statusまたはstable chart bodyが期待と異なる場合.

    Notes:
        requestはhandlerへ直接渡し, network I/Oは使わない.
    """
    # Arrange
    auth_service = MockAuthService()

    service = _make_process_score_submission_use_case(auth_service=auth_service)
    handler = ScoreSubmitHandler(
        service,
        decoder=make_stable_score_submit_decoder(
            payload="1000:test_user:0123456789abcdef0123456789abcdef:e2e_score_submit:0:0:100:10:5:0:0:2:500000:99:1:1"
        ),
        mapper=StableScoreSubmitMapper(stable_web_base_url="https://osu.athena.localhost"),
    )

    body, content_type = _create_valid_multipart_body()
    request = _request(body, content_type)

    # Act
    response = await handler(request)

    # Assert
    assert response.status_code == 200
    response_body = bytes(response.body)
    assert response_body.startswith(
        b"beatmapId:1|beatmapSetId:0|beatmapPlaycount:1|beatmapPasscount:1|approvedDate:\n"
    )
    assert (
        b"chartId:beatmap|chartUrl:https://osu.athena.localhost/b/1|chartName:Beatmap Ranking|"
    ) in response_body
    assert (
        b"chartId:overall|chartUrl:https://osu.athena.localhost/u/1000|chartName:Overall Ranking|"
    ) in response_body


@pytest.mark.asyncio
async def test_e2e_score_submit_updates_projection_and_retry_returns_saved_snapshot() -> None:
    """Stable submitがprojectionを更新し同一retryが保存済みsnapshotを返すことを検証する.

    Returns:
        None: 2件のpersonal best更新とretry response snapshotをassertして終了する.

    Raises:
        AssertionError: leaderboard projectionまたはretry responseが期待と異なる場合.

    Notes:
        同一request bodyのretryは再計算せず, 初回response bodyと同じ内容を返す.
    """
    uow_factory = InMemoryUnitOfWorkFactory()

    def decrypt_payload(
        encrypted: bytes,
        _iv: bytes,
        _osu_version: str | None,
    ) -> DecryptedPayload:
        """暗号化payload markerに対応するstable score plaintextを返す.

        Args:
            encrypted (bytes): multipart score fieldから渡される暗号化payload marker.
            _iv (bytes): decoderから渡されるinitialization vector, fakeでは使用しない.
            _osu_version (str | None): decoderから渡されるclient version, fakeでは使用しない.

        Returns:
            DecryptedPayload: previousまたはnew personal bestを表すchecksum検証済みplaintext.
        """
        if encrypted == b"previous_best_payload":
            payload = (
                "1000:test_user:0123456789abcdef0123456789abcdef:"
                "e2e_lb_prev:0:0:100:10:5:0:0:2:400000:99:1:1"
            )
        else:
            payload = (
                "1000:test_user:0123456789abcdef0123456789abcdef:e2e_lb_new:0:"
                f"{int(Mod.DOUBLE_TIME)}:100:10:5:0:0:2:500000:99:1:1"
            )
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    service = ProcessScoreSubmissionUseCase(
        submit_score_use_case=make_submit_score_use_case(uow_factory),
        replay_blob_storage=StubBlobStorageService(),
        auth_service=MockAuthService(),
        beatmap_resolver=MockBeatmapResolver(),
    )
    handler = ScoreSubmitHandler(
        service,
        decoder=make_stable_score_submit_decoder(
            payload_decryptor=StubScorePayloadDecryptor(factory=decrypt_payload)
        ),
    )

    previous_body, previous_content_type = _create_valid_multipart_body(
        encrypted_payload=b"previous_best_payload",
        replay_data=b"previous_best_replay",
        client_hash=b"previous_hash",
    )
    previous_response = await handler(_request(previous_body, previous_content_type))

    assert previous_response.status_code == 200
    previous_response_body = bytes(previous_response.body)
    assert b"rankedScoreBefore:0|rankedScoreAfter:400000|" in previous_response_body
    previous_best_score_id = await _get_leaderboard_best_score_id(uow_factory)
    assert previous_best_score_id is not None

    new_body, new_content_type = _create_valid_multipart_body(
        encrypted_payload=b"new_best_payload",
        replay_data=b"new_best_replay",
        client_hash=b"new_hash",
    )
    new_response = await handler(_request(new_body, new_content_type))

    assert new_response.status_code == 200
    new_response_body = bytes(new_response.body)
    assert b"rankedScoreBefore:400000|rankedScoreAfter:500000|" in new_response_body
    new_best_score_id = await _get_leaderboard_best_score_id(uow_factory)
    assert new_best_score_id is not None
    assert new_best_score_id != previous_best_score_id

    await _replace_projection_with_score(uow_factory, score_id=previous_best_score_id)

    retry_response = await handler(_request(new_body, new_content_type))

    assert retry_response.status_code == 200
    assert bytes(retry_response.body) == new_response_body
    assert await _get_leaderboard_best_score_id(uow_factory) == previous_best_score_id


@pytest.mark.asyncio
async def test_e2e_score_submit_terminal_reject_format() -> None:
    """認可failureがterminal reject formatを返すことを検証する.

    Returns:
        None: HTTP statusとstable legacy error bodyをassertして終了する.

    Raises:
        AssertionError: response statusまたはbodyが期待と異なる場合.

    Notes:
        認可失敗でもstable legacy responseはHTTP 200と`error: no`を返す.
    """

    # Arrange
    # Mock auth service that always fails
    class FailingAuthService:
        """常にsessionとpasswordをinvalidとして返すauthorization fake."""

        async def authorize_submission(
            self, password_md5: str, payload_username: str, payload_user_id: int
        ) -> AuthorizationContext:
            """Payload値に関係なく認可失敗のcontextを返す.

            Args:
                password_md5 (str): stable requestから渡されるMD5 password, fakeでは使用しない.
                payload_username (str): payload内のuser名, fakeでは使用しない.
                payload_user_id (int): payload内のuser識別子, fakeでは使用しない.

            Returns:
                AuthorizationContext: すべての認可flagがFalseのterminal reject用context.
            """
            _ = password_md5, payload_username, payload_user_id
            return AuthorizationContext(
                user_id=0,
                username="",
                session_valid=False,
                password_valid=False,
                payload_identity_match=False,
            )

    service = _make_process_score_submission_use_case(auth_service=FailingAuthService())
    handler = ScoreSubmitHandler(
        service,
        decoder=make_stable_score_submit_decoder(
            payload="1000:test_user:0123456789abcdef0123456789abcdef:e2e_score_submit:0:0:100:10:5:0:0:2:500000:99:1:1"
        ),
    )

    body, content_type = _create_valid_multipart_body()
    request = _request(body, content_type)

    # Act
    response = await handler(request)

    # Assert
    assert response.status_code == 200
    assert response.body == b"error: no"
