"""ProcessScoreSubmissionUseCaseのplaystyle検証契約を確認する unit test module."""

from dataclasses import dataclass, replace

import pytest

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapEligibility,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapResolveOptions,
    BeatmapResolveResult,
    BeatmapSourceVerification,
)
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.scores import (
    ParsedSubmissionInput,
    ProcessScoreSubmissionUseCase,
    SubmissionOutcome,
)
from tests.support.credentials import fixed_test_password_md5
from tests.support.fakes import (
    StubBlobStorageService,
    make_score_authorization_service,
    make_submit_score_use_case,
    make_test_parsed_score,
    make_test_submission_input,
)

# Mod bit constants (from osu! stable protocol)
RELAX = 1 << 7  # 128
AUTOPILOT = 1 << 13  # 8192


def _eligible_beatmap() -> BeatmapEligibility:
    """Score submissionを受理するranked beatmap用eligibilityを作成する.

    Returns:
        BeatmapEligibility: vanilla scoreを受理しranked PPを付与するbeatmapのeligibility.
    """
    return BeatmapEligibility(
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
    )


def _resolved_beatmap() -> Beatmap:
    """playstyle検証で解決済みとして返すranked beatmapを作成する.

    Returns:
        Beatmap: file未取得だがsubmission可否を判定できるosu! modeのranked beatmap.
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


@dataclass(slots=True)
class FakeBeatmapResolver:
    """playstyle検証用に一定のbeatmap解決結果を返すfake resolver.

    Attributes:
        eligibility (BeatmapEligibility | None): checksum解決結果へ含めるsubmission eligibility.
    """

    eligibility: BeatmapEligibility | None = None

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        """Beatmap IDによる解決要求へmetadataのみの結果を返す.

        Args:
            beatmap_id (int): 呼び出し側が指定するbeatmap ID. fakeでは結果を変えない.
            options (BeatmapResolveOptions | None): 解決option. fakeでは使用しない.

        Returns:
            BeatmapResolveResult: beatmap本体を含まず,設定済みeligibilityを含むfreshな解決結果.
        """
        del beatmap_id, options
        return BeatmapResolveResult(
            beatmap=None,
            beatmapset=None,
            eligibility=self.eligibility,
            metadata_status=BeatmapFetchState.FRESH,
            file_status=BeatmapFileState.MISSING,
            source=BeatmapMetadataSource.OFFICIAL,
            verified=True,
            last_fetched_at=None,
            next_refresh_at=None,
            reason=None,
        )

    async def resolve_by_checksum(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        """checksumによる解決要求へranked beatmapを含む結果を返す.

        Args:
            checksum_md5 (str): 呼び出し側が指定するbeatmap checksum MD5. fakeでは結果を変えない.
            options (BeatmapResolveOptions | None): 解決option. fakeでは使用しない.

        Returns:
            BeatmapResolveResult: 設定済みeligibilityと固定ranked beatmapを含むfreshな解決結果.
        """
        del checksum_md5, options
        return BeatmapResolveResult(
            beatmap=_resolved_beatmap(),
            beatmapset=None,
            eligibility=self.eligibility,
            metadata_status=BeatmapFetchState.FRESH,
            file_status=BeatmapFileState.MISSING,
            source=BeatmapMetadataSource.OFFICIAL,
            verified=True,
            last_fetched_at=None,
            next_refresh_at=None,
            reason=None,
        )


@pytest.fixture
def uow_factory() -> InMemoryUnitOfWorkFactory:
    """Submission testで共有するin-memory Unit of Work factoryを提供する fixture.

    Returns:
        InMemoryUnitOfWorkFactory: score保存を外部DBなしで検証するfactory.
    """
    return InMemoryUnitOfWorkFactory()


@pytest.fixture
def beatmap_resolver() -> FakeBeatmapResolver:
    """score受理可能なbeatmapを返すresolverを提供する fixture.

    Returns:
        FakeBeatmapResolver: ranked vanilla scoreを受理するeligibilityを返すresolver.
    """
    return FakeBeatmapResolver(_eligible_beatmap())


@pytest.fixture
def service(
    uow_factory: InMemoryUnitOfWorkFactory,
    beatmap_resolver: FakeBeatmapResolver,
) -> ProcessScoreSubmissionUseCase:
    """playstyle検証に必要なin-memory依存を持つsubmission use-caseを提供する fixture.

    Args:
        uow_factory (InMemoryUnitOfWorkFactory): score状態を保持するin-memory Unit of Work factory.
        beatmap_resolver (FakeBeatmapResolver): submission可否を返すfake beatmap resolver.

    Returns:
        ProcessScoreSubmissionUseCase: credential, storage, beatmap解決をtest doubleへ接続した
            use-case.
    """
    auth_service = make_score_authorization_service()
    return ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        StubBlobStorageService(),
        auth_service,
        beatmap_resolver,
    )


@pytest.fixture
def valid_input() -> ParsedSubmissionInput:
    """Vanilla playstyleの成功submissionを表す正規化済みinputを提供する fixture.

    Returns:
        ParsedSubmissionInput: 有効なcredentialとscore payloadを含むsubmission input.
    """
    return make_test_submission_input(password_md5=fixed_test_password_md5())


@pytest.mark.asyncio
async def test_relax_mod_terminal_reject(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
) -> None:
    """Relax mod付きsubmissionをterminalに拒否するplaystyle契約を検証する.

    有効なscore inputへRelax bitを設定し,
    score保存前にterminal rejectionとplaystyle由来の理由が返ることを確認する.

    Args:
        service (ProcessScoreSubmissionUseCase): playstyle検証を実行するsubmission use-case.
        valid_input (ParsedSubmissionInput): 正常なvanilla submissionを表す基準input.

    Returns:
        None: Relax submissionの拒否結果を検証して完了し,呼び出し側へ値を返さない.
    """
    input_data = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            f"1000:test_user:0123456789abcdef0123456789abcdef:online_rx:0:{RELAX}:100:10:5:0:0:2:500000:99:1:1"
        ),
    )

    result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result.error_reason is not None
    assert "relax" in result.error_reason.lower() or "playstyle" in result.error_reason.lower()


@pytest.mark.asyncio
async def test_autopilot_mod_terminal_reject(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
) -> None:
    """Autopilot mod付きsubmissionをterminalに拒否するplaystyle契約を検証する.

    有効なscore inputへAutopilot bitを設定し,
    score保存前にterminal rejectionとplaystyle由来の理由が返ることを確認する.

    Args:
        service (ProcessScoreSubmissionUseCase): playstyle検証を実行するsubmission use-case.
        valid_input (ParsedSubmissionInput): 正常なvanilla submissionを表す基準input.

    Returns:
        None: Autopilot submissionの拒否結果を検証して完了し,呼び出し側へ値を返さない.
    """
    input_data = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            f"1000:test_user:0123456789abcdef0123456789abcdef:online_ap:0:{AUTOPILOT}:100:10:5:0:0:2:500000:99:1:1"
        ),
    )

    result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result.error_reason is not None
    assert "autopilot" in result.error_reason.lower() or "playstyle" in result.error_reason.lower()


@pytest.mark.asyncio
async def test_relax_and_autopilot_combined_terminal_reject(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
) -> None:
    """RelaxとAutopilotを併用したsubmissionをterminalに拒否する契約を検証する.

    2つの禁止playstyle bitを同時に設定し,
    単独の検出結果ではなくplaystyle不正としてterminal rejectionになることを確認する.

    Args:
        service (ProcessScoreSubmissionUseCase): playstyle検証を実行するsubmission use-case.
        valid_input (ParsedSubmissionInput): 正常なvanilla submissionを表す基準input.

    Returns:
        None: 併用modの拒否結果を検証して完了し,呼び出し側へ値を返さない.
    """
    combined_mods = RELAX | AUTOPILOT
    input_data = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            f"1000:test_user:0123456789abcdef0123456789abcdef:online_both:0:{combined_mods}:100:10:5:0:0:2:500000:99:1:1"
        ),
    )

    result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result.error_reason is not None
    assert "playstyle" in result.error_reason.lower()


@pytest.mark.asyncio
async def test_vanilla_mod_accepted(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
) -> None:
    """modなしのvanilla submissionを受理するplaystyle契約を検証する.

    mod bitを0にした有効inputを実行し,
    completed outcomeとscore IDが返り拒否理由を持たないことを確認する.

    Args:
        service (ProcessScoreSubmissionUseCase): playstyle検証を実行するsubmission use-case.
        valid_input (ParsedSubmissionInput): 正常なvanilla submissionを表す基準input.

    Returns:
        None: vanilla submissionの受理結果を検証して完了し,呼び出し側へ値を返さない.
    """
    input_data = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            "1000:test_user:0123456789abcdef0123456789abcdef:online_vanilla:0:0:100:10:5:0:0:2:500000:99:1:1"
        ),
    )

    result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.score_id is not None
    assert result.error_reason is None


@pytest.mark.asyncio
async def test_other_mods_accepted(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
) -> None:
    """RelaxとAutopilot以外のmodを含むsubmissionを受理する契約を検証する.

    HD, HR, DTのbitを組み合わせた有効inputを実行し,
    completed outcomeとscore IDが返り拒否理由を持たないことを確認する.

    Args:
        service (ProcessScoreSubmissionUseCase): playstyle検証を実行するsubmission use-case.
        valid_input (ParsedSubmissionInput): 正常なvanilla submissionを表す基準input.

    Returns:
        None: 許可modを含むsubmissionの受理結果を検証して完了し,呼び出し側へ値を返さない.
    """
    other_mods = 8 | 16 | 64
    input_data = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            f"1000:test_user:0123456789abcdef0123456789abcdef:online_other:0:{other_mods}:100:10:5:0:0:2:500000:99:1:1"
        ),
    )

    result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.score_id is not None
    assert result.error_reason is None
