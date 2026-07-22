"""スコア submission の command workflow 全体を編成する use-case."""

import hashlib
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Never, Protocol

import structlog

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapRankStatus,
    BeatmapResolveOptions,
    BeatmapResolveResult,
)
from osu_server.domain.scores.mods import Mod, ModCombination
from osu_server.domain.scores.payload_parser import ParsedScore
from osu_server.domain.scores.personal_best import PersonalBestDelta
from osu_server.domain.scores.score import Playstyle, PlayTimeSource, Ruleset, Score
from osu_server.domain.scores.user_stats import UserCurrentStats
from osu_server.domain.scores.validator import (
    ValidationError,
    ValidationResult,
    validate_hit_counts,
)
from osu_server.domain.storage.blobs import BlobStoreResult
from osu_server.services.commands.beatmaps import (
    BeatmapFileWarmupEntrance,
    BeatmapFileWarmupRequest,
    BeatmapFileWarmupResult,
)
from osu_server.services.commands.scores.authorization import (
    AuthorizationContext,
)
from osu_server.services.commands.scores.performance import (
    RequestPerformanceCalculationCommand,
    RequestPerformanceCalculationOutcome,
    RequestPerformanceCalculationResult,
)
from osu_server.services.commands.scores.submit_score import (
    SubmitScoreCommand,
    SubmitScoreCommandOutcome,
    SubmitScoreCommandResult,
    SubmitScoreUseCase,
)
from osu_server.services.queries.scores import (
    BeatmapPersonalBestRankQueryInput,
    BeatmapPersonalBestRankQueryResult,
    CurrentUserStatsQueryInput,
    CurrentUserStatsQueryResult,
    PerformanceSubmitResponse,
    PerformanceSubmitResponseQuery,
    PerformanceSubmitResponseState,
)

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]

_REPLAY_CONTENT_TYPE = "application/octet-stream"
_PERFORMANCE_RESPONSE_AVAILABLE_OUTCOMES = frozenset(
    {
        RequestPerformanceCalculationOutcome.CREATED,
        RequestPerformanceCalculationOutcome.CREATED_REPLACEMENT,
        RequestPerformanceCalculationOutcome.REUSED_PENDING,
        RequestPerformanceCalculationOutcome.REUSED_REPLACEMENT_PENDING,
        RequestPerformanceCalculationOutcome.ALREADY_CURRENT,
    }
)


class _FingerprintHasher(Protocol):
    """スコア提出用fingerprintを増分更新するhash objectのinterface."""

    def update(self, data: bytes, /) -> None:
        """ハッシュstateへbinary dataを追加する.

        Args:
            data (bytes): fingerprintへ順序どおりに追加するbinary data.

        Returns:
            None: hash stateを更新し,呼び出し側へ値を返さずに完了する.
        """
        ...


def _update_fingerprint_bytes(hasher: _FingerprintHasher, label: bytes, value: bytes) -> None:
    """長さを含むbinary fieldをsubmission fingerprintへ追加する.

    Args:
        hasher (_FingerprintHasher): 更新対象のSHA-256互換hash object.
        label (bytes): fieldを識別するASCII label.
        value (bytes): 長さを記録して追加するfield値.

    Returns:
        None: labelとvalueをNUL区切りのlength-prefixed形式で追加して完了する.
    """
    hasher.update(label)
    hasher.update(b"\0")
    hasher.update(str(len(value)).encode())
    hasher.update(b"\0")
    hasher.update(value)
    hasher.update(b"\0")


def _update_fingerprint_text(hasher: _FingerprintHasher, label: str, value: str) -> None:
    """文字列fieldをUTF-8へ符号化してsubmission fingerprintへ追加する.

    Args:
        hasher (_FingerprintHasher): 更新対象のSHA-256互換hash object.
        label (str): fieldを識別するASCII label.
        value (str): UTF-8へ符号化するfield値.

    Returns:
        None: textをbinary fieldとしてhash objectへ追加して完了する.
    """
    _update_fingerprint_bytes(hasher, label.encode(), value.encode())


class BeatmapEligibilityResolver(Protocol):
    """スコア submission用のbeatmapとeligibilityを解決するquery interface."""

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        """指定したbeatmap IDからsubmission可否を含む解決結果を取得する.

        Args:
            beatmap_id (int): 解決対象のbeatmap ID.
            options (BeatmapResolveOptions | None): fetch待機などを制御する任意のoption.

        Returns:
            BeatmapResolveResult: beatmap,metadata,eligibilityを含む解決結果.
        """
        ...

    async def resolve_by_checksum(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        """指定したchecksum MD5からsubmission可否を含む解決結果を取得する.

        Args:
            checksum_md5 (str): stable score payloadに含まれるbeatmap checksum MD5.
            options (BeatmapResolveOptions | None): fetch待機などを制御する任意のoption.

        Returns:
            BeatmapResolveResult: beatmap,metadata,eligibilityを含む解決結果.
        """
        ...


class ScoreSubmissionAuthorizer(Protocol):
    """スコア submissionのcredential,session,identityを照合するinterface."""

    async def authorize_submission(
        self,
        password_md5: str,
        payload_username: str,
        payload_user_id: int,
    ) -> AuthorizationContext:
        """スコア submissionを認可するための照合結果を取得する.

        Args:
            password_md5 (str): stable clientが送信したpassword MD5 hex値.
            payload_username (str): 復号済みpayloadのユーザー名.
            payload_user_id (int): 復号済みpayloadのuser ID.未送信時は0.

        Returns:
            AuthorizationContext: credential,session,payload identityの照合結果.
        """
        ...


class ReplayBlobStorage(Protocol):
    """スコアに添付されたreplay binaryをblob storageへ永続化するinterface."""

    async def put_bytes(
        self,
        data: bytes,
        *,
        content_type: str,
    ) -> BlobStoreResult:
        """指定されたbinary dataをcontent type付きで保存する.

        Args:
            data (bytes): 保存するreplay binary.
            content_type (str): 保存するblobのMIME content type.

        Returns:
            BlobStoreResult: 保存済みblobの識別情報を含む結果.
        """
        ...


class BeatmapFileWarmupUseCase(Protocol):
    """スコア submit時に必要なbeatmap fileを事前取得するuse-case interface."""

    async def execute(
        self,
        request: BeatmapFileWarmupRequest,
    ) -> BeatmapFileWarmupResult:
        """指定entranceのbeatmap file warmupを実行する.

        Args:
            request (BeatmapFileWarmupRequest): warmup対象とentry pointを表すrequest.

        Returns:
            BeatmapFileWarmupResult: warmup実行結果.
        """
        ...


class PerformanceCalculationRequestUseCase(Protocol):
    """スコアのperformance calculationを要求するuse-case interface."""

    async def execute(
        self,
        command: RequestPerformanceCalculationCommand,
    ) -> RequestPerformanceCalculationResult:
        """計算requestを作成または再利用する.

        Args:
            command (RequestPerformanceCalculationCommand): scoreとcalculatorを指定するcommand.

        Returns:
            RequestPerformanceCalculationResult: requestの作成または再利用結果.
        """
        ...


class PerformanceCalculatorIdentity(Protocol):
    """計算用calculatorの永続的identityを提供するinterface."""

    def calculator_name(self) -> str:
        """計算用calculatorの名前を返す.

        Returns:
            str: calculation requestを識別するcalculator名.
        """
        ...

    def calculator_version(self) -> str:
        """計算用calculatorのversionを返す.

        Returns:
            str: calculation requestを識別するcalculator version.
        """
        ...


class PerformanceSubmitResponseUseCase(Protocol):
    """安定版score submit response用のperformance結果を取得するinterface."""

    async def wait_for_submit_response(
        self,
        query: PerformanceSubmitResponseQuery,
    ) -> PerformanceSubmitResponse:
        """計算結果が利用可能になるまで待機して取得する.

        Args:
            query (PerformanceSubmitResponseQuery): 対象scoreを指定するquery.

        Returns:
            PerformanceSubmitResponse: 利用可能になったperformance submit response.
        """
        ...

    async def get_submit_response(
        self,
        query: PerformanceSubmitResponseQuery,
    ) -> PerformanceSubmitResponse:
        """待機せずに現在のperformance submit responseを取得する.

        Args:
            query (PerformanceSubmitResponseQuery): 対象scoreを指定するquery.

        Returns:
            PerformanceSubmitResponse: 現時点のperformance submit response.
        """
        ...


class CurrentUserStatsQueryUseCase(Protocol):
    """現在のuser statsをscore submit response用に取得するquery interface."""

    async def execute(
        self,
        input_data: CurrentUserStatsQueryInput,
    ) -> CurrentUserStatsQueryResult:
        """指定したrulesetとplaystyleでuser statsを取得する.

        Args:
            input_data (CurrentUserStatsQueryInput): user IDsとscore scopeを表すquery input.

        Returns:
            CurrentUserStatsQueryResult: user IDごとの現在statsを含む結果.
        """
        ...


class BeatmapPersonalBestRankQueryUseCase(Protocol):
    """beatmap personal best順位をscore submit response用に取得するinterface."""

    async def execute(
        self,
        input_data: BeatmapPersonalBestRankQueryInput,
    ) -> BeatmapPersonalBestRankQueryResult:
        """指定score scopeにおけるuserのbeatmap順位を取得する.

        Args:
            input_data (BeatmapPersonalBestRankQueryInput): rank対象を指定するquery input.

        Returns:
            BeatmapPersonalBestRankQueryResult: 指定scopeでのpersonal best rank結果.
        """
        ...


class SubmissionOutcome(Enum):
    """スコア submission workflowの最終outcomeを表す.

    Attributes:
        COMPLETED (SubmissionOutcome): score submissionが完了しresponseを返せる状態.
        TERMINAL_REJECTED (SubmissionOutcome): 再送しても受理しないterminal rejection状態.
        RETRYABLE (SubmissionOutcome): 後続処理の再試行または再照会が必要な状態.
        ACCEPTED_PENDING (SubmissionOutcome): scoreは受理済みで後続結果を待つ状態.
    """

    COMPLETED = "completed"
    TERMINAL_REJECTED = "terminal_rejected"
    RETRYABLE = "retryable"
    ACCEPTED_PENDING = "accepted_pending"


@dataclass(frozen=True, slots=True)
class BeatmapRankDelta:
    """安定版submit responseに載せるbeatmap leaderboard順位差分を表す.

    Attributes:
        before (int | None): score submission前のpersonal best順位.未取得時はNone.
        after (int | None): score submission後のpersonal best順位.未取得時はNone.
    """

    before: int | None
    after: int | None


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    """転送層へ返すscore submissionの処理結果を表す.

    Attributes:
        outcome (SubmissionOutcome): workflowの最終outcome.
        user_id (int | None): 認証済みuser ID.認可前のrejectionではNoneまたは0相当となる.
        ruleset (Ruleset | None): 提出scoreのruleset.
        playstyle (Playstyle | None): 提出scoreのplaystyle.
        score_id (int | None): 永続化済みscore ID.未作成時はNone.
        beatmap_id (int | None): 解決済みbeatmap ID.
        beatmapset_id (int | None): 解決済みbeatmapset ID.
        score (int | None): 提出score値.
        max_combo (int | None): 提出した最大combo.
        accuracy (float | None): server側で検証したaccuracy.
        passed (bool | None): scoreがclear扱いか.
        beatmap_playcount (int | None): score反映後のbeatmap play count.
        beatmap_passcount (int | None): score反映後のbeatmap pass count.
        beatmap_approved_at (datetime | None): beatmapが承認状態になった時刻.
        error_reason (str | None): rejectionまたはretryable outcomeのmachine-readable理由.
        stable_pp (int | None): stable responseへ返す最終PP値.
        stable_pp_before (int | None): personal best更新前のPP値.
        stable_pp_after (int | None): personal best更新後のPP値.
        personal_best_delta (PersonalBestDelta | None): personal best scoreの更新差分.
        beatmap_rank_delta (BeatmapRankDelta | None): beatmap personal best順位の更新差分.
        overall_stats_before (UserCurrentStats | None): score反映前のoverall stats.
        overall_stats_after (UserCurrentStats | None): score反映後のoverall stats.
    """

    outcome: SubmissionOutcome
    user_id: int | None = None
    ruleset: Ruleset | None = None
    playstyle: Playstyle | None = None
    score_id: int | None = None
    beatmap_id: int | None = None
    beatmapset_id: int | None = None
    score: int | None = None
    max_combo: int | None = None
    accuracy: float | None = None
    passed: bool | None = None
    beatmap_playcount: int | None = None
    beatmap_passcount: int | None = None
    beatmap_approved_at: datetime | None = None
    error_reason: str | None = None
    stable_pp: int | None = None
    stable_pp_before: int | None = None
    stable_pp_after: int | None = None
    personal_best_delta: PersonalBestDelta | None = None
    beatmap_rank_delta: BeatmapRankDelta | None = None
    overall_stats_before: UserCurrentStats | None = None
    overall_stats_after: UserCurrentStats | None = None


@dataclass(frozen=True, slots=True)
class ParsedSubmissionInput:
    """安定版score submitをcommand境界へ渡す正規化済み入力を表す.

    Attributes:
        parsed_score (ParsedScore): transportで復号してparse済みのcanonical score値.
        request_hash (str): idempotencyと診断に使うstable request hash.
        opaque_field_hashes (Mapping[str, str]): tokenなどのopaque metadataをSHA-256化した値.
        decrypt_latency_ms (float): transport側の復号処理時間をmillisecondで表した値.
        replay_data (bytes | None): 添付replay binary.未送信時はNone.
        password_md5 (str): stable clientが送るpassword-md5 credential.記録しない.
        fail_time_ms (int | None): stable clientのfail time.未送信時はNone.
        osu_version (str | None): stable client version.未送信時はNone.
        submitted_at (datetime): serverがrequestを受け取った時刻.
        beatmap_id (int | None): form field由来のbeatmap ID.未送信時はNone.
        submit_exit_classification (str | None): client終了種別の診断値.未送信時はNone.

    Notes:
        stable multipart,暗号化済みpayload,transport wire型を含めない.credentialとreplayは
        loggingせず,opaque metadataはhash済み値だけを保持する.
    """

    parsed_score: ParsedScore
    request_hash: str
    opaque_field_hashes: Mapping[str, str]
    decrypt_latency_ms: float
    replay_data: bytes | None
    password_md5: str
    fail_time_ms: int | None
    osu_version: str | None
    submitted_at: datetime
    beatmap_id: int | None = None
    submit_exit_classification: str | None = None


def _grade_discrepancy(client_grade: str | None, server_grade: str) -> dict[str, str] | None:
    """クライアントとserverのgradeが実質的に異なる場合に診断用差分を返す.

    Args:
        client_grade (str | None): stable clientが送信したgrade.未送信時はNone.
        server_grade (str): server側validationが算出したgrade.

    Returns:
        dict[str, str] | None: 差分のclient_gradeとserver_grade.空または同一ならNone.
    """
    if client_grade is None:
        return None

    normalized_client_grade = client_grade.strip().upper()
    if not normalized_client_grade or normalized_client_grade == server_grade:
        return None

    return {
        "client_grade": client_grade,
        "server_grade": server_grade,
    }


def generate_submission_fingerprint(
    *,
    user_id: int,
    beatmap_checksum: str,
    submitted_timestamp: str | None,
    request_hash: str,
) -> str:
    """冪等性判定に使うsubmission fingerprintを生成する.

    Args:
        user_id (int): 認可済みuser ID.
        beatmap_checksum (str): 提出scoreのbeatmap checksum MD5.
        submitted_timestamp (str | None): clientが送信した提出時刻.未送信時はNone.
        request_hash (str): transportが作成したrequest固有hash.

    Returns:
        str: field名,長さ,値を順序どおりSHA-256化したhex fingerprint.
    """
    hasher = hashlib.sha256()
    _update_fingerprint_text(hasher, "user_id", str(user_id))
    _update_fingerprint_text(hasher, "beatmap_checksum", beatmap_checksum)
    _update_fingerprint_text(hasher, "submitted_timestamp", submitted_timestamp or "")
    _update_fingerprint_text(hasher, "request_hash", request_hash)
    return hasher.hexdigest()


def _valid_non_negative(value: int | None) -> int | None:
    """非負整数だけを保持し,それ以外をNoneへ正規化する.

    Args:
        value (int | None): 正規化する任意の整数値.

    Returns:
        int | None: 0以上の入力値.Noneまたは負値の場合はNone.
    """
    if value is None or value < 0:
        return None
    return value


def _derive_score_timing(
    *,
    passed: bool,
    fail_time_ms: int | None,
    beatmap_total_length: int | None,
) -> tuple[int | None, int | None, PlayTimeSource | None]:
    """提出scoreのfail timeとplay timeを提出状態から導出する.

    Args:
        passed (bool): scoreがclear扱いか.
        fail_time_ms (int | None): clientが送信したfail timeをmillisecondで表した値.
        beatmap_total_length (int | None): beatmapの総再生時間をsecondで表した値.

    Returns:
        tuple[int | None, int | None, PlayTimeSource | None]: 正規化済みfail time,play time,
            導出元をこの順で含むtuple.
    """
    normalized_fail_time_ms = _valid_non_negative(fail_time_ms)
    if not passed:
        if normalized_fail_time_ms is None:
            return None, None, None
        return (
            normalized_fail_time_ms,
            normalized_fail_time_ms // 1000,
            PlayTimeSource.FAIL_TIME,
        )

    normalized_total_length = _valid_non_negative(beatmap_total_length)
    if normalized_total_length is None:
        return normalized_fail_time_ms, None, None
    return (
        normalized_fail_time_ms,
        normalized_total_length,
        PlayTimeSource.BEATMAP_TOTAL_LENGTH,
    )


def _submission_result_from_command(
    result: SubmitScoreCommandResult,
    *,
    beatmap_rank_delta: BeatmapRankDelta | None = None,
    overall_stats_before: UserCurrentStats | None = None,
    overall_stats_after: UserCurrentStats | None = None,
) -> SubmissionResult:
    """提出commandの結果をtransport用submission resultへ変換する.

    Args:
        result (SubmitScoreCommandResult): 永続化commandが返したscore submission結果.
        beatmap_rank_delta (BeatmapRankDelta | None): responseへ含めるbeatmap順位差分.
        overall_stats_before (UserCurrentStats | None): score反映前のoverall stats.
        overall_stats_after (UserCurrentStats | None): score反映後のoverall stats.

    Returns:
        SubmissionResult: command結果と任意のresponse差分を集約したtransport境界の結果.
    """
    return SubmissionResult(
        outcome=SubmissionOutcome(result.outcome.value),
        user_id=result.user_id,
        ruleset=result.ruleset,
        playstyle=result.playstyle,
        score_id=result.score_id,
        beatmap_id=result.beatmap_id,
        beatmapset_id=result.beatmapset_id,
        score=result.score,
        max_combo=result.max_combo,
        accuracy=result.accuracy,
        passed=result.passed,
        beatmap_playcount=result.beatmap_playcount,
        beatmap_passcount=result.beatmap_passcount,
        beatmap_approved_at=result.beatmap_approved_at,
        error_reason=result.error_reason,
        personal_best_delta=result.personal_best_delta,
        beatmap_rank_delta=beatmap_rank_delta,
        overall_stats_before=overall_stats_before,
        overall_stats_after=overall_stats_after,
    )


def _score_submit_approved_at(beatmap: Beatmap) -> datetime | None:
    """スコア submission時点で適用するbeatmap承認時刻を返す.

    Args:
        beatmap (Beatmap): local overrideと公式metadataを持つ解決済みbeatmap.

    Returns:
        datetime | None: local status overrideの変更時刻.未設定時は公式更新時刻.
    """
    if (
        beatmap.local_status_override is not None
        and beatmap.local_status_override_changed_at is not None
    ):
        return beatmap.local_status_override_changed_at
    return beatmap.official_last_updated_at


class _SubmissionStoppedError(Exception):
    """処理workflowをSubmissionResultで早期停止する内部control-flow exception.

    Attributes:
        result (SubmissionResult): executeが呼び出し元へ返す停止結果.
    """

    def __init__(self, result: SubmissionResult) -> None:
        """停止時に返すsubmission resultを保持する.

        Args:
            result (SubmissionResult): terminalまたはretryable outcomeを持つ停止結果.
        """
        super().__init__(result.error_reason)
        self.result: SubmissionResult = result


def _stop_submission(result: SubmissionResult) -> Never:
    """送信結果を伴う内部停止例外を送出する.

    Args:
        result (SubmissionResult): execute境界へ返す停止結果.

    Raises:
        _SubmissionStoppedError: workflowを直ちに中断してresultをexecuteへ伝える場合.
    """
    raise _SubmissionStoppedError(result)


@dataclass(frozen=True, slots=True)
class _SubmissionAttempt:
    """一回のscore submission処理で共有するrequest状態を表す.

    Attributes:
        input_data (ParsedSubmissionInput): transport境界で正規化済みの入力.
        start_time (float): 処理開始時のmonotonic clock値.
        request_hash (str): idempotencyと診断に使うrequest hash.
        opaque_field_hashes (Mapping[str, str]): 記録可能なopaque metadataのhash値.
    """

    input_data: ParsedSubmissionInput
    start_time: float
    request_hash: str
    opaque_field_hashes: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class _AuthorizedSubmission:
    """認可済みscore submissionのpayloadとidentityを表す.

    Attributes:
        parsed (ParsedScore): 認可対象として処理するparse済みscore.
        auth_ctx (AuthorizationContext): credential,session,identityの照合結果.
        fingerprint (str): 永続化commandを識別するsubmission fingerprint.
    """

    parsed: ParsedScore
    auth_ctx: AuthorizationContext
    fingerprint: str


@dataclass(frozen=True, slots=True)
class _ResolvedBeatmapSubmission:
    """解決済みbeatmapと測定したlatencyを表す.

    Attributes:
        result (BeatmapResolveResult): eligibilityを含む元のbeatmap解決結果.
        beatmap (Beatmap): 存在を確認済みの解決済みbeatmap.
        latency_ms (float): beatmap解決に要した時間をmillisecondで表した値.
    """

    result: BeatmapResolveResult
    beatmap: Beatmap
    latency_ms: float


@dataclass(frozen=True, slots=True)
class _AcceptedBeatmapSubmission:
    """スコア submissionで受理したbeatmap由来のsnapshotを表す.

    Attributes:
        result (BeatmapResolveResult): 元のbeatmap解決結果.
        resolved_beatmap_id (int): scoreへ永続化するbeatmap ID.
        resolved_beatmapset_id (int): scoreへ永続化するbeatmapset ID.未解決時は0.
        score_ruleset (Ruleset): parse済みscoreから決めたruleset.
        score_playstyle (Playstyle): このworkflowが許可するplaystyle.
        beatmap_status_at_submission (str): 送信時点の有効beatmap rank status.
        beatmap_approved_at (datetime | None): 送信時点で適用する承認時刻.
        leaderboard_eligible_at_submission (bool): leaderboard更新対象として扱うか.
        fail_time_ms (int | None): 正規化済みfail timeをmillisecondで表した値.
        play_time_seconds (int | None): 導出済みplay timeをsecondで表した値.
        play_time_source (PlayTimeSource | None): play timeの導出元.
        latency_ms (float): beatmap解決に要した時間をmillisecondで表した値.
    """

    result: BeatmapResolveResult
    resolved_beatmap_id: int
    resolved_beatmapset_id: int
    score_ruleset: Ruleset
    score_playstyle: Playstyle
    beatmap_status_at_submission: str
    beatmap_approved_at: datetime | None
    leaderboard_eligible_at_submission: bool
    fail_time_ms: int | None
    play_time_seconds: int | None
    play_time_source: PlayTimeSource | None
    latency_ms: float


@dataclass(frozen=True, slots=True)
class _ValidatedSubmission:
    """提出scoreのvalidation結果とgrade差分を表す.

    Attributes:
        result (ValidationResult): hit count validationが算出したcanonical結果.
        grade_discrepancy (dict[str, str] | None): clientとserverのgrade差分.差分なしはNone.
    """

    result: ValidationResult
    grade_discrepancy: dict[str, str] | None


@dataclass(frozen=True, slots=True)
class _ReplayBlobReference:
    """スコア submissionに関連付けるreplay blobのsnapshotを表す.

    Attributes:
        replay_data (bytes | None): 元のreplay binary.未送信時はNone.
        replay_checksum (str | None): replay binaryのSHA-256 hex値.未送信時はNone.
        replay_byte_size (int | None): replay binaryのbyte数.未送信時はNone.
        replay_blob_id (int | None): 永続化済みblob ID.未送信時はNone.
    """

    replay_data: bytes | None
    replay_checksum: str | None
    replay_byte_size: int | None
    replay_blob_id: int | None


@dataclass(frozen=True, slots=True)
class _SubmitScoreBaseline:
    """永続化前に取得したscore submit response用baselineを表す.

    Attributes:
        overall_stats_before (UserCurrentStats | None): score反映前のoverall stats.
        beatmap_rank_before (int | None): score反映前のbeatmap personal best順位.
    """

    overall_stats_before: UserCurrentStats | None
    beatmap_rank_before: int | None


@dataclass(frozen=True, slots=True)
class _SubmitResponseDeltas:
    """永続化後に取得したscore submit response用差分を表す.

    Attributes:
        overall_stats_after (UserCurrentStats | None): score反映後のoverall stats.
        beatmap_rank_after (int | None): score反映後のbeatmap personal best順位.
    """

    overall_stats_after: UserCurrentStats | None
    beatmap_rank_after: int | None


def _accepted_beatmap_submission(
    attempt: _SubmissionAttempt,
    authorized: _AuthorizedSubmission,
    resolved: _ResolvedBeatmapSubmission,
) -> _AcceptedBeatmapSubmission:
    """解決済みbeatmapからscore永続化用のaccepted snapshotを作る.

    Args:
        attempt (_SubmissionAttempt): request時刻とform fieldを持つ処理状態.
        authorized (_AuthorizedSubmission): 認可済みpayloadとsubmission fingerprint.
        resolved (_ResolvedBeatmapSubmission): 存在を確認済みのbeatmap解決結果.

    Returns:
        _AcceptedBeatmapSubmission: score永続化とleaderboard判定に使うbeatmap snapshot.
    """
    parsed = authorized.parsed
    beatmap_result = resolved.result
    beatmap = resolved.beatmap
    eligibility = beatmap_result.eligibility
    score_ruleset = Ruleset(parsed.ruleset)
    fail_time_ms, play_time_seconds, play_time_source = _derive_score_timing(
        passed=parsed.passed,
        fail_time_ms=attempt.input_data.fail_time_ms,
        beatmap_total_length=beatmap.total_length,
    )
    return _AcceptedBeatmapSubmission(
        result=beatmap_result,
        resolved_beatmap_id=attempt.input_data.beatmap_id or beatmap.id,
        resolved_beatmapset_id=(
            beatmap_result.beatmapset.id if beatmap_result.beatmapset is not None else 0
        ),
        score_ruleset=score_ruleset,
        score_playstyle=Playstyle.VANILLA,
        beatmap_status_at_submission=beatmap.effective_status.value,
        beatmap_approved_at=_score_submit_approved_at(beatmap),
        leaderboard_eligible_at_submission=(
            parsed.passed and eligibility is not None and eligibility.has_leaderboard
        ),
        fail_time_ms=fail_time_ms,
        play_time_seconds=play_time_seconds,
        play_time_source=play_time_source,
        latency_ms=resolved.latency_ms,
    )


def _build_score(
    attempt: _SubmissionAttempt,
    authorized: _AuthorizedSubmission,
    accepted_beatmap: _AcceptedBeatmapSubmission,
    validated: _ValidatedSubmission,
) -> Score:
    """認可,beatmap,validationのsnapshotからdomain scoreを組み立てる.

    Args:
        attempt (_SubmissionAttempt): transport入力と提出時刻を持つ処理状態.
        authorized (_AuthorizedSubmission): 認可済みpayloadとuser identity.
        accepted_beatmap (_AcceptedBeatmapSubmission): scoreへ記録するbeatmap snapshot.
        validated (_ValidatedSubmission): server側validation結果とgrade差分.

    Returns:
        Score: SubmitScoreCommandへ渡す永続化前のdomain score.
    """
    parsed = authorized.parsed
    return Score(
        id=None,
        user_id=authorized.auth_ctx.user_id,
        beatmap_id=accepted_beatmap.resolved_beatmap_id,
        beatmap_checksum=parsed.beatmap_checksum,
        online_checksum=parsed.online_checksum,
        ruleset=accepted_beatmap.score_ruleset,
        playstyle=accepted_beatmap.score_playstyle,
        mods=parsed.mods,
        n300=parsed.n300,
        n100=parsed.n100,
        n50=parsed.n50,
        geki=parsed.geki,
        katu=parsed.katu,
        miss=parsed.miss,
        score=parsed.score,
        max_combo=parsed.max_combo,
        accuracy=validated.result.accuracy,
        grade=validated.result.grade,
        passed=parsed.passed,
        perfect=parsed.perfect,
        client_version=attempt.input_data.osu_version or "unknown",
        submitted_at=attempt.input_data.submitted_at,
        beatmap_status_at_submission=BeatmapRankStatus(
            accepted_beatmap.beatmap_status_at_submission
        ),
        leaderboard_eligible_at_submission=accepted_beatmap.leaderboard_eligible_at_submission,
        fail_time_ms=accepted_beatmap.fail_time_ms,
        play_time_seconds=accepted_beatmap.play_time_seconds,
        play_time_source=accepted_beatmap.play_time_source,
        submit_exit_classification=attempt.input_data.submit_exit_classification,
    )


def _completed_submit_command(
    *,
    attempt: _SubmissionAttempt,
    authorized: _AuthorizedSubmission,
    accepted_beatmap: _AcceptedBeatmapSubmission,
    validated: _ValidatedSubmission,
    replay: _ReplayBlobReference,
    score: Score,
) -> SubmitScoreCommand:
    """完了scoreを永続化するSubmitScoreCommandを組み立てる.

    Args:
        attempt (_SubmissionAttempt): request hashとopaque metadataを持つ処理状態.
        authorized (_AuthorizedSubmission): 認可済みpayloadとfingerprint.
        accepted_beatmap (_AcceptedBeatmapSubmission): 永続化するbeatmap snapshot.
        validated (_ValidatedSubmission): validation結果とgrade差分.
        replay (_ReplayBlobReference): 関連付けるreplay blobのsnapshot.
        score (Score): 永続化するdomain score.

    Returns:
        SubmitScoreCommand: completed outcomeを永続化するcommand.
    """
    return SubmitScoreCommand(
        fingerprint=authorized.fingerprint,
        user_id=authorized.auth_ctx.user_id,
        beatmap_checksum=authorized.parsed.beatmap_checksum,
        submitted_at=attempt.input_data.submitted_at,
        outcome=SubmitScoreCommandOutcome.COMPLETED,
        score=score,
        beatmap_id=accepted_beatmap.resolved_beatmap_id,
        beatmapset_id=accepted_beatmap.resolved_beatmapset_id,
        beatmap_approved_at=accepted_beatmap.beatmap_approved_at,
        replay_blob_id=replay.replay_blob_id,
        replay_checksum_sha256=replay.replay_checksum,
        replay_byte_size=replay.replay_byte_size,
        grade_discrepancy=validated.grade_discrepancy,
        opaque_field_hashes=attempt.opaque_field_hashes,
        include_personal_best_delta=accepted_beatmap.leaderboard_eligible_at_submission,
        update_personal_best=accepted_beatmap.leaderboard_eligible_at_submission,
    )


def _log_submission_completed(
    *,
    attempt: _SubmissionAttempt,
    authorized: _AuthorizedSubmission,
    accepted_beatmap: _AcceptedBeatmapSubmission,
    replay: _ReplayBlobReference,
    command_result: SubmitScoreCommandResult,
    decrypt_latency_ms: float,
    db_latency_ms: float,
) -> None:
    """完了したscore submissionの診断用structured logを記録する.

    Args:
        attempt (_SubmissionAttempt): 処理開始時刻とrequest metadataを持つ状態.
        authorized (_AuthorizedSubmission): 認可済みuserとfingerprint.
        accepted_beatmap (_AcceptedBeatmapSubmission): beatmap解決latencyを含むsnapshot.
        replay (_ReplayBlobReference): replay添付の有無とsizeを含むsnapshot.
        command_result (SubmitScoreCommandResult): 永続化commandの完了結果.
        decrypt_latency_ms (float): transport側復号に要した時間をmillisecondで表した値.
        db_latency_ms (float): score永続化に要した時間をmillisecondで表した値.

    Returns:
        None: raw credentialやreplay内容を含めずに完了logを記録して完了する.
    """
    logger.info(
        "score_submission_completed",
        duration_ms=(time.perf_counter() - attempt.start_time) * 1000,
        decrypt_latency_ms=decrypt_latency_ms,
        beatmap_latency_ms=accepted_beatmap.latency_ms,
        db_latency_ms=db_latency_ms,
        fingerprint=authorized.fingerprint,
        user_id=authorized.auth_ctx.user_id,
        beatmap_id=accepted_beatmap.resolved_beatmap_id,
        score_id=command_result.score_id,
        replay_attachment_id=command_result.replay_attachment_id,
        replay_present=replay.replay_data is not None,
        replay_byte_size=replay.replay_byte_size,
        passed=authorized.parsed.passed,
        fail_time_ms=attempt.input_data.fail_time_ms,
        beatmap_status_at_submission=accepted_beatmap.beatmap_status_at_submission,
        opaque_fields=attempt.opaque_field_hashes or None,
    )


def _beatmap_rank_delta_for_submit_response(
    *,
    before: int | None,
    after: int | None,
    include_beatmap_rank_delta: bool,
) -> BeatmapRankDelta | None:
    """指定時だけresponseへ含めるbeatmap順位差分を作る.

    Args:
        before (int | None): score反映前のbeatmap personal best順位.
        after (int | None): score反映後のbeatmap personal best順位.
        include_beatmap_rank_delta (bool): stable responseへ順位差分を載せるか.

    Returns:
        BeatmapRankDelta | None: 表示対象の順位差分.非表示の場合はNone.
    """
    if not include_beatmap_rank_delta:
        return None
    return BeatmapRankDelta(before=before, after=after)


def _performance_pending_submission_result(
    command_result: SubmitScoreCommandResult,
    *,
    overall_stats_before: UserCurrentStats | None,
    stable_pp_before: int | None = None,
    personal_best_delta: PersonalBestDelta | None = None,
) -> SubmissionResult:
    """計算待ちを表すretryable submission resultを作る.

    Args:
        command_result (SubmitScoreCommandResult): 永続化済みscore submissionの結果.
        overall_stats_before (UserCurrentStats | None): score反映前のoverall stats.
        stable_pp_before (int | None): personal best更新前のPP値.
        personal_best_delta (PersonalBestDelta | None): personal best scoreの更新差分.

    Returns:
        SubmissionResult: scoreを受理済みとしつつperformance計算待ちを示す結果.
    """
    return SubmissionResult(
        outcome=SubmissionOutcome.RETRYABLE,
        user_id=command_result.user_id,
        ruleset=command_result.ruleset,
        playstyle=command_result.playstyle,
        score_id=command_result.score_id,
        beatmap_id=command_result.beatmap_id,
        beatmapset_id=command_result.beatmapset_id,
        score=command_result.score,
        max_combo=command_result.max_combo,
        accuracy=command_result.accuracy,
        passed=command_result.passed,
        beatmap_playcount=command_result.beatmap_playcount,
        beatmap_passcount=command_result.beatmap_passcount,
        beatmap_approved_at=command_result.beatmap_approved_at,
        error_reason="performance_calculation_pending",
        stable_pp_before=stable_pp_before,
        personal_best_delta=personal_best_delta,
        overall_stats_before=overall_stats_before,
    )


def _completed_submit_response_result(
    command_result: SubmitScoreCommandResult,
    *,
    stable_pp: int | None,
    stable_pp_before: int | None = None,
    personal_best_delta: PersonalBestDelta | None = None,
    beatmap_rank_delta: BeatmapRankDelta | None,
    overall_stats_before: UserCurrentStats | None,
    overall_stats_after: UserCurrentStats | None,
) -> SubmissionResult:
    """計算結果を含むcompleted submission resultを作る.

    Args:
        command_result (SubmitScoreCommandResult): 永続化済みscore submissionの結果.
        stable_pp (int | None): stable responseへ返す最終PP値.
        stable_pp_before (int | None): personal best更新前のPP値.
        personal_best_delta (PersonalBestDelta | None): personal best scoreの更新差分.
        beatmap_rank_delta (BeatmapRankDelta | None): beatmap順位の更新差分.
        overall_stats_before (UserCurrentStats | None): score反映前のoverall stats.
        overall_stats_after (UserCurrentStats | None): score反映後のoverall stats.

    Returns:
        SubmissionResult: completed outcomeとstable response用差分を含む結果.
    """
    return SubmissionResult(
        outcome=SubmissionOutcome.COMPLETED,
        user_id=command_result.user_id,
        ruleset=command_result.ruleset,
        playstyle=command_result.playstyle,
        score_id=command_result.score_id,
        beatmap_id=command_result.beatmap_id,
        beatmapset_id=command_result.beatmapset_id,
        score=command_result.score,
        max_combo=command_result.max_combo,
        accuracy=command_result.accuracy,
        passed=command_result.passed,
        beatmap_playcount=command_result.beatmap_playcount,
        beatmap_passcount=command_result.beatmap_passcount,
        beatmap_approved_at=command_result.beatmap_approved_at,
        stable_pp=stable_pp,
        stable_pp_before=stable_pp_before,
        stable_pp_after=stable_pp,
        personal_best_delta=personal_best_delta,
        beatmap_rank_delta=beatmap_rank_delta,
        overall_stats_before=overall_stats_before,
        overall_stats_after=overall_stats_after,
    )


class ProcessScoreSubmissionUseCase:
    """スコア submissionのcommand workflowを編成するuse-case.

    Attributes:
        _submit_score_use_case (SubmitScoreUseCase): score outcomeとsnapshotを永続化するuse-case.
        _replay_blob_storage (ReplayBlobStorage): replay binaryを保存するblob storage.
        _auth_service (ScoreSubmissionAuthorizer): credential,session,identityを照合するservice.
        _beatmap_resolver (BeatmapEligibilityResolver): beatmap eligibilityを解決するquery.
        _beatmap_file_warmup_use_case (BeatmapFileWarmupUseCase | None): 任意の
            beatmap file warmup use-case.
        _performance_calculation_request (PerformanceCalculationRequestUseCase | None): 任意の
            PP calculation request use-case.
        _performance_calculator_identity (PerformanceCalculatorIdentity | None): 任意の
            performance calculator identity provider.
        _performance_response_query (PerformanceSubmitResponseUseCase | None): 任意の
            performance submit response query.
        _current_user_stats_query (CurrentUserStatsQueryUseCase | None): overall statsを読むquery.
        _beatmap_personal_best_rank_query (BeatmapPersonalBestRankQueryUseCase | None):
            beatmap personal best順位を読む任意のquery.

    Notes:
        authorization,beatmap eligibility,validation,replay保存,score永続化,performance要求を
        このuse-caseの内側で順に編成する.
    """

    def __init__(
        self,
        submit_score_use_case: SubmitScoreUseCase,
        replay_blob_storage: ReplayBlobStorage,
        auth_service: ScoreSubmissionAuthorizer,
        beatmap_resolver: BeatmapEligibilityResolver,
        beatmap_file_warmup_use_case: BeatmapFileWarmupUseCase | None = None,
        performance_calculation_request: PerformanceCalculationRequestUseCase | None = None,
        performance_calculator_identity: PerformanceCalculatorIdentity | None = None,
        performance_response_query: PerformanceSubmitResponseUseCase | None = None,
        current_user_stats_query: CurrentUserStatsQueryUseCase | None = None,
        beatmap_personal_best_rank_query: BeatmapPersonalBestRankQueryUseCase | None = None,
    ) -> None:
        """スコア submission workflowの依存use-caseとadapterを設定する.

        Args:
            submit_score_use_case (SubmitScoreUseCase): score outcomeを永続化するuse-case.
            replay_blob_storage (ReplayBlobStorage): replay binaryを保存するblob storage.
            auth_service (ScoreSubmissionAuthorizer): score submissionを認可するservice.
            beatmap_resolver (BeatmapEligibilityResolver): beatmap eligibilityを解決するquery.
            beatmap_file_warmup_use_case (BeatmapFileWarmupUseCase | None): 任意のbeatmap file
                warmup use-case.
            performance_calculation_request (PerformanceCalculationRequestUseCase | None): PP計算を
                要求する任意のuse-case.
            performance_calculator_identity (PerformanceCalculatorIdentity | None): PP calculatorを
                識別する任意のprovider.
            performance_response_query (PerformanceSubmitResponseUseCase | None): 任意の
                performance response query.
            current_user_stats_query (CurrentUserStatsQueryUseCase | None): overall statsを取得する
                任意のquery.
            beatmap_personal_best_rank_query (BeatmapPersonalBestRankQueryUseCase | None): 任意の
                beatmap personal best rank query.

        Notes:
            performance関連の依存はすべて揃う場合だけ計算要求と待機を行い,未設定時は即時responseを返す.
        """
        self._submit_score_use_case: SubmitScoreUseCase = submit_score_use_case
        self._replay_blob_storage: ReplayBlobStorage = replay_blob_storage
        self._auth_service: ScoreSubmissionAuthorizer = auth_service
        self._beatmap_resolver: BeatmapEligibilityResolver = beatmap_resolver
        self._beatmap_file_warmup_use_case: BeatmapFileWarmupUseCase | None = (
            beatmap_file_warmup_use_case
        )
        self._performance_calculation_request: PerformanceCalculationRequestUseCase | None = (
            performance_calculation_request
        )
        self._performance_calculator_identity: PerformanceCalculatorIdentity | None = (
            performance_calculator_identity
        )
        self._performance_response_query: PerformanceSubmitResponseUseCase | None = (
            performance_response_query
        )
        self._current_user_stats_query: CurrentUserStatsQueryUseCase | None = (
            current_user_stats_query
        )
        self._beatmap_personal_best_rank_query: BeatmapPersonalBestRankQueryUseCase | None = (
            beatmap_personal_best_rank_query
        )

    async def execute(self, input_data: ParsedSubmissionInput) -> SubmissionResult:
        """提出scoreを検証し,durable stateとreplay blobへ反映する.

        Args:
            input_data (ParsedSubmissionInput): transportで復号とparseを完了したscore submit入力.

        Returns:
            SubmissionResult: durable stateへの反映結果とstable responseに必要な差分情報.

        Notes:
            fingerprint生成,authorization,beatmap eligibility,hit count validation,replay保存,
            score永続化,performance calculation requestの順に処理する.内部停止例外はこの境界で
            SubmissionResultへ変換する.transport adapterは再送識別用のrequest hashを生成する.
        """
        attempt = _SubmissionAttempt(
            input_data=input_data,
            start_time=time.perf_counter(),
            request_hash=input_data.request_hash,
            opaque_field_hashes=input_data.opaque_field_hashes,
        )

        try:
            authorized = await self._authorize_submission(attempt, input_data.parsed_score)
            await self._reject_unsupported_playstyle(attempt, authorized)
            accepted_beatmap = await self._resolve_accepted_beatmap(attempt, authorized)
            validated = await self._validate_submission(attempt, authorized)

            await self._request_score_submit_fallback_warmup(
                user_id=authorized.auth_ctx.user_id,
                beatmap_id=accepted_beatmap.resolved_beatmap_id,
                checksum_md5=authorized.parsed.beatmap_checksum,
            )
            replay = await self._store_replay_blob(attempt, authorized)

            return await self._persist_completed_submission(
                attempt=attempt,
                authorized=authorized,
                accepted_beatmap=accepted_beatmap,
                validated=validated,
                replay=replay,
                decrypt_latency_ms=input_data.decrypt_latency_ms,
            )
        except _SubmissionStoppedError as stopped:
            return stopped.result

    async def _authorize_submission(
        self,
        attempt: _SubmissionAttempt,
        parsed: ParsedScore,
    ) -> _AuthorizedSubmission:
        """入力payloadのidentityを照合し,永続化用submission fingerprintを作る.

        Args:
            attempt (_SubmissionAttempt): credential,提出時刻,request metadataを持つ処理状態.
            parsed (ParsedScore): 認可対象のparse済みscore payload.

        Returns:
            _AuthorizedSubmission: 認可context,parse済みscore,fingerprintを含む状態.

        Raises:
            _SubmissionStoppedError: 認可条件のいずれかが不一致の場合.
        """
        auth_ctx = await self._auth_service.authorize_submission(
            attempt.input_data.password_md5,
            parsed.username,
            parsed.user_id,
        )

        fingerprint = generate_submission_fingerprint(
            user_id=auth_ctx.user_id,
            beatmap_checksum=parsed.beatmap_checksum,
            submitted_timestamp=parsed.client_submitted_at,
            request_hash=attempt.request_hash,
        )

        if not auth_ctx.authorized:
            password_hash = hashlib.sha256(attempt.input_data.password_md5.encode()).hexdigest()
            logger.warning(
                "score_submission_failed",
                reason="authorization_failed",
                fingerprint=fingerprint,
                password_hash=password_hash,
                username=parsed.username,
                user_id=auth_ctx.user_id,
                password_valid=auth_ctx.password_valid,
                session_valid=auth_ctx.session_valid,
                identity_match=auth_ctx.payload_identity_match,
            )
            result = await self._record_terminal_reject(
                fingerprint=fingerprint,
                user_id=auth_ctx.user_id,
                beatmap_checksum=parsed.beatmap_checksum,
                submitted_at=attempt.input_data.submitted_at,
                error_reason=self._format_auth_error(auth_ctx),
                opaque_field_hashes=attempt.opaque_field_hashes,
            )
            _stop_submission(result)
        return _AuthorizedSubmission(parsed=parsed, auth_ctx=auth_ctx, fingerprint=fingerprint)

    async def _reject_unsupported_playstyle(
        self,
        attempt: _SubmissionAttempt,
        authorized: _AuthorizedSubmission,
    ) -> None:
        """許可しないRelaxまたはAutopilotを含むsubmissionをterminal rejectする.

        Args:
            attempt (_SubmissionAttempt): 提出時刻とopaque metadataを持つ処理状態.
            authorized (_AuthorizedSubmission): 認可済みscoreとfingerprint.

        Returns:
            None: 許可playstyleでは何もせずに完了する.

        Raises:
            _SubmissionStoppedError: scoreがRelaxまたはAutopilot modを含む場合.
        """
        if self._is_relax_or_autopilot(authorized.parsed.mods):
            error_reason = "playstyle_not_supported: relax_or_autopilot"
            logger.warning(
                "score_submission_failed",
                reason="playstyle_not_supported",
                fingerprint=authorized.fingerprint,
                mods=authorized.parsed.mods.to_persistence_bitmask(),
                user_id=authorized.auth_ctx.user_id,
            )
            result = await self._record_terminal_reject(
                fingerprint=authorized.fingerprint,
                user_id=authorized.auth_ctx.user_id,
                beatmap_checksum=authorized.parsed.beatmap_checksum,
                submitted_at=attempt.input_data.submitted_at,
                error_reason=error_reason,
                opaque_field_hashes=attempt.opaque_field_hashes,
            )
            _stop_submission(result)

    async def _resolve_accepted_beatmap(
        self,
        attempt: _SubmissionAttempt,
        authorized: _AuthorizedSubmission,
    ) -> _AcceptedBeatmapSubmission:
        """解決済みbeatmapをscore submission用snapshotへ変換する.

        Args:
            attempt (_SubmissionAttempt): request時刻とform fieldを持つ処理状態.
            authorized (_AuthorizedSubmission): 認可済みscoreとfingerprint.

        Returns:
            _AcceptedBeatmapSubmission: eligibility確認済みのbeatmap submission snapshot.

        Raises:
            _SubmissionStoppedError: beatmap取得中またはscore submissionを受理できない場合.
        """
        resolved = await self._resolve_beatmap_or_retry(attempt, authorized)
        await self._reject_ineligible_beatmap(attempt, authorized, resolved)
        return _accepted_beatmap_submission(attempt, authorized, resolved)

    async def _resolve_beatmap_or_retry(
        self,
        attempt: _SubmissionAttempt,
        authorized: _AuthorizedSubmission,
    ) -> _ResolvedBeatmapSubmission:
        """提出scoreのchecksumからbeatmapを解決し,未取得ならretryable outcomeで停止する.

        Args:
            attempt (_SubmissionAttempt): 提出時刻とopaque metadataを持つ処理状態.
            authorized (_AuthorizedSubmission): 認可済みscoreとfingerprint.

        Returns:
            _ResolvedBeatmapSubmission: 存在を確認済みのbeatmapと解決latency.

        Raises:
            _SubmissionStoppedError: beatmapが未取得でfetch完了待ちの場合.
        """
        beatmap_start = time.perf_counter()
        beatmap_result = await self._beatmap_resolver.resolve_by_checksum(
            authorized.parsed.beatmap_checksum,
            BeatmapResolveOptions(wait_timeout_seconds=5),
        )
        beatmap_latency_ms = (time.perf_counter() - beatmap_start) * 1000

        beatmap = beatmap_result.beatmap
        if beatmap is None:
            error_reason = "beatmap_fetch_in_progress"
            logger.info(
                "score_submission_retryable",
                reason=error_reason,
                fingerprint=authorized.fingerprint,
                beatmap_checksum=authorized.parsed.beatmap_checksum,
                opaque_fields=attempt.opaque_field_hashes or None,
            )
            result = await self._record_retryable(
                fingerprint=authorized.fingerprint,
                user_id=authorized.auth_ctx.user_id,
                beatmap_checksum=authorized.parsed.beatmap_checksum,
                submitted_at=attempt.input_data.submitted_at,
                error_reason=error_reason,
                opaque_field_hashes=attempt.opaque_field_hashes,
            )
            _stop_submission(result)
        return _ResolvedBeatmapSubmission(
            result=beatmap_result,
            beatmap=beatmap,
            latency_ms=beatmap_latency_ms,
        )

    async def _reject_ineligible_beatmap(
        self,
        attempt: _SubmissionAttempt,
        authorized: _AuthorizedSubmission,
        resolved: _ResolvedBeatmapSubmission,
    ) -> None:
        """提出scoreのpass状態に応じてbeatmap eligibilityを検査する.

        Args:
            attempt (_SubmissionAttempt): form fieldと提出時刻を持つ処理状態.
            authorized (_AuthorizedSubmission): 認可済みscoreとfingerprint.
            resolved (_ResolvedBeatmapSubmission): eligibilityを含むbeatmap解決結果.

        Returns:
            None: beatmapがscoreを受理できる場合に値を返さず完了する.

        Raises:
            _SubmissionStoppedError: passedまたはfailed scoreをbeatmapが受理しない場合.
        """
        eligibility = resolved.result.eligibility
        accepts_submission = False
        if eligibility is not None:
            accepts_submission = (
                eligibility.accepts_scores
                if authorized.parsed.passed
                else eligibility.accepts_failed_scores
            )
        if not accepts_submission:
            denial_reason = eligibility.denial_reason if eligibility is not None else None
            error_reason = f"beatmap_ineligible: {denial_reason or 'not_accepting_scores'}"
            logger.warning(
                "score_submission_failed",
                reason="beatmap_ineligible",
                fingerprint=authorized.fingerprint,
                beatmap_id=attempt.input_data.beatmap_id,
                beatmap_checksum=authorized.parsed.beatmap_checksum,
                denial_reason=denial_reason,
                passed=authorized.parsed.passed,
            )
            result = await self._record_terminal_reject(
                fingerprint=authorized.fingerprint,
                user_id=authorized.auth_ctx.user_id,
                beatmap_checksum=authorized.parsed.beatmap_checksum,
                submitted_at=attempt.input_data.submitted_at,
                error_reason=error_reason,
                opaque_field_hashes=attempt.opaque_field_hashes,
            )
            _stop_submission(result)

    async def _validate_submission(
        self,
        attempt: _SubmissionAttempt,
        authorized: _AuthorizedSubmission,
    ) -> _ValidatedSubmission:
        """添付replayとhit countsを検証してcanonical validation結果を返す.

        Args:
            attempt (_SubmissionAttempt): replayと提出時刻を持つ処理状態.
            authorized (_AuthorizedSubmission): 認可済みscoreとfingerprint.

        Returns:
            _ValidatedSubmission: server側validation結果とclient gradeとの差分.

        Raises:
            _SubmissionStoppedError: replayが空,またはhit count validationに失敗した場合.
        """
        parsed = authorized.parsed
        if attempt.input_data.replay_data == b"":
            error_reason = "empty_replay_data"
            logger.warning(
                "score_submission_failed",
                reason="empty_replay_data",
                fingerprint=authorized.fingerprint,
                passed=parsed.passed,
                fail_time_ms=attempt.input_data.fail_time_ms,
            )
            result = await self._record_terminal_reject(
                fingerprint=authorized.fingerprint,
                user_id=authorized.auth_ctx.user_id,
                beatmap_checksum=parsed.beatmap_checksum,
                submitted_at=attempt.input_data.submitted_at,
                error_reason=error_reason,
                opaque_field_hashes=attempt.opaque_field_hashes,
            )
            _stop_submission(result)

        try:
            validation = validate_hit_counts(parsed)
        except ValidationError as e:
            error_reason = f"validation_failed: {e}"
            logger.warning(
                "score_submission_failed",
                reason="validation_failed",
                fingerprint=authorized.fingerprint,
                error=str(e),
            )
            result = await self._record_terminal_reject(
                fingerprint=authorized.fingerprint,
                user_id=authorized.auth_ctx.user_id,
                beatmap_checksum=parsed.beatmap_checksum,
                submitted_at=attempt.input_data.submitted_at,
                error_reason=error_reason,
                opaque_field_hashes=attempt.opaque_field_hashes,
            )
            _stop_submission(result)

        grade_discrepancy = _grade_discrepancy(parsed.client_grade, validation.grade.value)
        if grade_discrepancy is not None:
            logger.info(
                "score_grade_discrepancy",
                fingerprint=authorized.fingerprint,
                user_id=authorized.auth_ctx.user_id,
                beatmap_checksum=parsed.beatmap_checksum,
                client_grade=grade_discrepancy["client_grade"],
                server_grade=grade_discrepancy["server_grade"],
            )
        return _ValidatedSubmission(result=validation, grade_discrepancy=grade_discrepancy)

    async def _store_replay_blob(
        self,
        attempt: _SubmissionAttempt,
        authorized: _AuthorizedSubmission,
    ) -> _ReplayBlobReference:
        """添付replayを保存し,scoreへ関連付けるblob snapshotを返す.

        Args:
            attempt (_SubmissionAttempt): replay,提出時刻,opaque metadataを持つ処理状態.
            authorized (_AuthorizedSubmission): 認可済みscoreとfingerprint.

        Returns:
            _ReplayBlobReference: replayのSHA-256,byte数,保存済みblob IDを含むsnapshot.

        Raises:
            _SubmissionStoppedError: replay blob storageへの保存に失敗した場合.

        Notes:
            replayが未送信の場合はblob storageを呼ばず,すべてNoneのreferenceを返す.
        """
        replay_data = attempt.input_data.replay_data
        replay_byte_size = len(replay_data) if replay_data is not None else None
        replay_checksum = None
        if replay_data is not None:
            replay_checksum = hashlib.sha256(replay_data).hexdigest()

        if replay_data is None:
            return _ReplayBlobReference(
                replay_data=None,
                replay_checksum=None,
                replay_byte_size=None,
                replay_blob_id=None,
            )

        try:
            replay_blob_result = await self._replay_blob_storage.put_bytes(
                replay_data,
                content_type=_REPLAY_CONTENT_TYPE,
            )
        except Exception as exc:
            logger.warning(
                "score_submission_retryable",
                reason="replay_blob_store_failed",
                fingerprint=authorized.fingerprint,
                error=type(exc).__name__,
            )
            result = await self._record_retryable(
                fingerprint=authorized.fingerprint,
                user_id=authorized.auth_ctx.user_id,
                beatmap_checksum=authorized.parsed.beatmap_checksum,
                submitted_at=attempt.input_data.submitted_at,
                error_reason="replay_blob_store_failed",
                opaque_field_hashes=attempt.opaque_field_hashes,
            )
            _stop_submission(result)

        return _ReplayBlobReference(
            replay_data=replay_data,
            replay_checksum=replay_checksum,
            replay_byte_size=replay_byte_size,
            replay_blob_id=replay_blob_result.blob.id,
        )

    async def _submit_score_baseline(
        self,
        authorized: _AuthorizedSubmission,
        accepted_beatmap: _AcceptedBeatmapSubmission,
    ) -> _SubmitScoreBaseline:
        """反映前のscoreに対応するoverall statsとbeatmap順位を取得する.

        Args:
            authorized (_AuthorizedSubmission): 認可済みuserとscore scope.
            accepted_beatmap (_AcceptedBeatmapSubmission): leaderboard可否を含むbeatmap snapshot.

        Returns:
            _SubmitScoreBaseline: score反映前に取得したresponse用baseline.
        """
        overall_stats_before = await self._current_user_stats_for_submit_response(
            user_id=authorized.auth_ctx.user_id,
            ruleset=accepted_beatmap.score_ruleset,
            playstyle=accepted_beatmap.score_playstyle,
            phase="before",
        )
        beatmap_rank_before = (
            await self._beatmap_rank_for_submit_response(
                user_id=authorized.auth_ctx.user_id,
                beatmap_id=accepted_beatmap.resolved_beatmap_id,
                beatmap_checksum=authorized.parsed.beatmap_checksum,
                ruleset=accepted_beatmap.score_ruleset,
                playstyle=accepted_beatmap.score_playstyle,
                phase="before",
            )
            if accepted_beatmap.leaderboard_eligible_at_submission
            else None
        )
        return _SubmitScoreBaseline(
            overall_stats_before=overall_stats_before,
            beatmap_rank_before=beatmap_rank_before,
        )

    async def _submit_completed_score(
        self,
        command: SubmitScoreCommand,
    ) -> tuple[SubmitScoreCommandResult, float]:
        """完了scoreを永続化し,database処理時間を測定する.

        Args:
            command (SubmitScoreCommand): completed outcomeを永続化するcommand.

        Returns:
            tuple[SubmitScoreCommandResult, float]: command結果とdatabase latencyをmillisecondで
                この順に含むtuple.
        """
        db_start = time.perf_counter()
        command_result = await self._submit_score_use_case.execute(command)
        return command_result, (time.perf_counter() - db_start) * 1000

    async def _persist_completed_submission(
        self,
        *,
        attempt: _SubmissionAttempt,
        authorized: _AuthorizedSubmission,
        accepted_beatmap: _AcceptedBeatmapSubmission,
        validated: _ValidatedSubmission,
        replay: _ReplayBlobReference,
        decrypt_latency_ms: float,
    ) -> SubmissionResult:
        """検証済みscoreを永続化し,stable response用の結果を組み立てる.

        Args:
            attempt (_SubmissionAttempt): request時刻とopaque metadataを持つ処理状態.
            authorized (_AuthorizedSubmission): 認可済みscoreとfingerprint.
            accepted_beatmap (_AcceptedBeatmapSubmission): scoreへ記録するbeatmap snapshot.
            validated (_ValidatedSubmission): hit count validation結果とgrade差分.
            replay (_ReplayBlobReference): 関連付けるreplay blobのsnapshot.
            decrypt_latency_ms (float): transport側復号に要した時間をmillisecondで表した値.

        Returns:
            SubmissionResult: persistence outcomeとperformance,stats,rank差分を含む結果.
        """
        score = _build_score(attempt, authorized, accepted_beatmap, validated)
        baseline = await self._submit_score_baseline(authorized, accepted_beatmap)

        command_result, db_latency_ms = await self._submit_completed_score(
            _completed_submit_command(
                attempt=attempt,
                authorized=authorized,
                accepted_beatmap=accepted_beatmap,
                validated=validated,
                replay=replay,
                score=score,
            )
        )

        if command_result.outcome != SubmitScoreCommandOutcome.COMPLETED:
            logger.warning(
                "score_submission_failed",
                reason=command_result.error_reason,
                fingerprint=authorized.fingerprint,
                user_id=authorized.auth_ctx.user_id,
                beatmap_checksum=authorized.parsed.beatmap_checksum,
            )
            return _submission_result_from_command(
                command_result,
                beatmap_rank_delta=(
                    BeatmapRankDelta(before=baseline.beatmap_rank_before, after=None)
                    if accepted_beatmap.leaderboard_eligible_at_submission
                    else None
                ),
                overall_stats_before=baseline.overall_stats_before,
            )

        performance_response_available = command_result.existing_submission
        if not command_result.existing_submission:
            performance_response_available = await self._request_performance_calculation(
                score_id=command_result.score_id,
                requested_at=attempt.input_data.submitted_at,
            )

        _log_submission_completed(
            attempt=attempt,
            authorized=authorized,
            accepted_beatmap=accepted_beatmap,
            replay=replay,
            command_result=command_result,
            decrypt_latency_ms=decrypt_latency_ms,
            db_latency_ms=db_latency_ms,
        )

        return await self._build_accepted_submission_result(
            command_result,
            beatmap_checksum=authorized.parsed.beatmap_checksum,
            beatmap_rank_before=baseline.beatmap_rank_before,
            include_beatmap_rank_delta=accepted_beatmap.leaderboard_eligible_at_submission,
            overall_stats_before=baseline.overall_stats_before,
            wait_for_performance=performance_response_available,
        )

    async def _request_performance_calculation(
        self,
        *,
        score_id: int | None,
        requested_at: datetime,
    ) -> bool:
        """必要な依存がそろう場合にscoreのperformance calculationを要求する.

        Args:
            score_id (int | None): 永続化済みscore ID.未作成時はNone.
            requested_at (datetime): performance calculationを要求したserver時刻.

        Returns:
            bool: submit responseを待機できるcalculation outcomeの場合はTrue.

        Notes:
            score IDまたはperformance依存がない場合,要求実行の例外が起きた場合はFalseを返す.
        """
        if (
            score_id is None
            or self._performance_calculation_request is None
            or self._performance_calculator_identity is None
        ):
            return False

        try:
            result = await self._performance_calculation_request.execute(
                RequestPerformanceCalculationCommand(
                    score_id=score_id,
                    calculator_name=self._performance_calculator_identity.calculator_name(),
                    calculator_version=self._performance_calculator_identity.calculator_version(),
                    requested_at=requested_at,
                )
            )
        except Exception as exc:
            logger.warning(
                "score_performance_calculation_request_failed",
                score_id=score_id,
                error=type(exc).__name__,
            )
            return False

        logger.info(
            "score_performance_calculation_requested",
            score_id=score_id,
            outcome=result.outcome.value,
            calculation_id=None if result.calculation is None else result.calculation.id,
            worker_wake_requested=result.worker_wake_requested,
            worker_wake_failed=result.worker_wake_failed,
        )
        return result.outcome in _PERFORMANCE_RESPONSE_AVAILABLE_OUTCOMES

    async def _submit_response_deltas(
        self,
        command_result: SubmitScoreCommandResult,
        *,
        beatmap_checksum: str,
        include_beatmap_rank_delta: bool,
    ) -> _SubmitResponseDeltas:
        """反映後のscoreに対応するoverall statsとbeatmap順位を取得する.

        Args:
            command_result (SubmitScoreCommandResult): score永続化後の結果とscore scope.
            beatmap_checksum (str): beatmap順位queryに渡すbeatmap checksum MD5.
            include_beatmap_rank_delta (bool): beatmap順位を取得してresponseへ含めるか.

        Returns:
            _SubmitResponseDeltas: score反映後に取得したresponse用差分.
        """
        return _SubmitResponseDeltas(
            overall_stats_after=await self._current_user_stats_for_submit_response(
                user_id=command_result.user_id,
                ruleset=command_result.ruleset,
                playstyle=command_result.playstyle,
                phase="after",
            ),
            beatmap_rank_after=await self._beatmap_rank_after_for_submit_response(
                command_result,
                beatmap_checksum=beatmap_checksum,
                include_beatmap_rank_delta=include_beatmap_rank_delta,
            ),
        )

    async def _wait_for_submit_performance_response(
        self,
        score_id: int,
    ) -> PerformanceSubmitResponse:
        """指定scoreのperformance submit responseが利用可能になるまで待機する.

        Args:
            score_id (int): performance calculationを待機する永続化済みscore ID.

        Returns:
            PerformanceSubmitResponse: 利用可能になったperformance calculation結果.

        Notes:
            呼び出し経路はperformance response queryが設定済みであることを保証する.
        """
        assert self._performance_response_query is not None
        return await self._performance_response_query.wait_for_submit_response(
            PerformanceSubmitResponseQuery(score_id=score_id)
        )

    async def _build_accepted_submission_result(
        self,
        command_result: SubmitScoreCommandResult,
        *,
        beatmap_checksum: str,
        beatmap_rank_before: int | None,
        include_beatmap_rank_delta: bool,
        overall_stats_before: UserCurrentStats | None,
        wait_for_performance: bool,
    ) -> SubmissionResult:
        """受理済みscoreからperformanceとresponse差分を含む結果を組み立てる.

        Args:
            command_result (SubmitScoreCommandResult): completed scoreの永続化結果.
            beatmap_checksum (str): beatmap順位queryに渡すbeatmap checksum MD5.
            beatmap_rank_before (int | None): score反映前のbeatmap personal best順位.
            include_beatmap_rank_delta (bool): beatmap順位差分をresponseへ含めるか.
            overall_stats_before (UserCurrentStats | None): score反映前のoverall stats.
            wait_for_performance (bool): performance結果が利用可能になるまで待機するか.

        Returns:
            SubmissionResult: performance,stats,beatmap順位を反映したcompleted result.

        Raises:
            _SubmissionStoppedError: 待機したperformance responseがretryable状態の場合.
        """
        if (
            not wait_for_performance
            or command_result.score_id is None
            or self._performance_response_query is None
        ):
            deltas = await self._submit_response_deltas(
                command_result,
                beatmap_checksum=beatmap_checksum,
                include_beatmap_rank_delta=include_beatmap_rank_delta,
            )
            return _submission_result_from_command(
                command_result,
                beatmap_rank_delta=_beatmap_rank_delta_for_submit_response(
                    before=beatmap_rank_before,
                    after=deltas.beatmap_rank_after,
                    include_beatmap_rank_delta=include_beatmap_rank_delta,
                ),
                overall_stats_before=overall_stats_before,
                overall_stats_after=deltas.overall_stats_after,
            )

        personal_best_delta = command_result.personal_best_delta
        if personal_best_delta is not None:
            return await self._build_personal_best_submission_result(
                command_result,
                personal_best_delta,
                beatmap_checksum=beatmap_checksum,
                beatmap_rank_before=beatmap_rank_before,
                include_beatmap_rank_delta=include_beatmap_rank_delta,
                overall_stats_before=overall_stats_before,
            )

        response = await self._wait_for_submit_performance_response(command_result.score_id)
        if response.state is PerformanceSubmitResponseState.RETRYABLE:
            _stop_submission(
                _performance_pending_submission_result(
                    command_result,
                    overall_stats_before=overall_stats_before,
                )
            )

        deltas = await self._submit_response_deltas(
            command_result,
            beatmap_checksum=beatmap_checksum,
            include_beatmap_rank_delta=include_beatmap_rank_delta,
        )
        return _completed_submit_response_result(
            command_result,
            stable_pp=response.stable_pp,
            beatmap_rank_delta=_beatmap_rank_delta_for_submit_response(
                before=beatmap_rank_before,
                after=deltas.beatmap_rank_after,
                include_beatmap_rank_delta=include_beatmap_rank_delta,
            ),
            overall_stats_before=overall_stats_before,
            overall_stats_after=deltas.overall_stats_after,
        )

    async def _personal_best_pp_delta(
        self,
        command_result: SubmitScoreCommandResult,
        personal_best_delta: PersonalBestDelta,
        *,
        overall_stats_before: UserCurrentStats | None,
    ) -> tuple[int, int]:
        """更新前後のpersonal bestに対応するstable PPを取得する.

        Args:
            command_result (SubmitScoreCommandResult): 永続化済みscoreとpersonal best更新結果.
            personal_best_delta (PersonalBestDelta): 更新前後のscore IDを表す差分.
            overall_stats_before (UserCurrentStats | None): retryable resultに含める更新前stats.

        Returns:
            tuple[int, int]: personal best更新前と更新後のstable PPをこの順に含むtuple.

        Raises:
            _SubmissionStoppedError: 新しいpersonal bestのperformance responseがretryableの場合.

        Notes:
            command_resultはscore_idを持つcompleted resultであることを呼び出し経路が保証する.
        """
        assert command_result.score_id is not None

        pp_before = await self._stable_pp_without_wait(personal_best_delta.before_score_id)

        if personal_best_delta.after_score_id == command_result.score_id:
            response = await self._wait_for_submit_performance_response(command_result.score_id)
            if response.state is PerformanceSubmitResponseState.RETRYABLE:
                _stop_submission(
                    _performance_pending_submission_result(
                        command_result,
                        overall_stats_before=overall_stats_before,
                        stable_pp_before=pp_before,
                        personal_best_delta=personal_best_delta,
                    )
                )
            return pp_before, response.stable_pp or 0

        if personal_best_delta.after_score_id == personal_best_delta.before_score_id:
            return pp_before, pp_before

        pp_after = await self._stable_pp_without_wait(personal_best_delta.after_score_id)
        return pp_before, pp_after

    async def _build_personal_best_submission_result(
        self,
        command_result: SubmitScoreCommandResult,
        personal_best_delta: PersonalBestDelta,
        *,
        beatmap_checksum: str,
        beatmap_rank_before: int | None,
        include_beatmap_rank_delta: bool,
        overall_stats_before: UserCurrentStats | None,
    ) -> SubmissionResult:
        """更新済みpersonal bestを含むcompleted submission resultを組み立てる.

        Args:
            command_result (SubmitScoreCommandResult): completed scoreの永続化結果.
            personal_best_delta (PersonalBestDelta): 更新前後のpersonal best score差分.
            beatmap_checksum (str): beatmap順位queryに渡すbeatmap checksum MD5.
            beatmap_rank_before (int | None): score反映前のbeatmap personal best順位.
            include_beatmap_rank_delta (bool): beatmap順位差分をresponseへ含めるか.
            overall_stats_before (UserCurrentStats | None): score反映前のoverall stats.

        Returns:
            SubmissionResult: personal best PP,stats,beatmap順位を反映したcompleted result.

        Raises:
            _SubmissionStoppedError: 新しいpersonal bestのperformance responseがretryableの場合.
        """
        pp_before, pp_after = await self._personal_best_pp_delta(
            command_result,
            personal_best_delta,
            overall_stats_before=overall_stats_before,
        )
        deltas = await self._submit_response_deltas(
            command_result,
            beatmap_checksum=beatmap_checksum,
            include_beatmap_rank_delta=include_beatmap_rank_delta,
        )
        return _completed_submit_response_result(
            command_result,
            stable_pp=pp_after,
            stable_pp_before=pp_before,
            personal_best_delta=personal_best_delta,
            beatmap_rank_delta=_beatmap_rank_delta_for_submit_response(
                before=beatmap_rank_before,
                after=deltas.beatmap_rank_after,
                include_beatmap_rank_delta=include_beatmap_rank_delta,
            ),
            overall_stats_before=overall_stats_before,
            overall_stats_after=deltas.overall_stats_after,
        )

    async def _beatmap_rank_after_for_submit_response(
        self,
        command_result: SubmitScoreCommandResult,
        *,
        beatmap_checksum: str,
        include_beatmap_rank_delta: bool,
    ) -> int | None:
        """反映後のscoreに対応するbeatmap personal best順位を必要時だけ取得する.

        Args:
            command_result (SubmitScoreCommandResult): score反映後のuser,beatmap,score scope.
            beatmap_checksum (str): beatmap順位queryに渡すbeatmap checksum MD5.
            include_beatmap_rank_delta (bool): beatmap順位を取得してresponseへ含めるか.

        Returns:
            int | None: score反映後のbeatmap順位.非表示または未取得時はNone.
        """
        if not include_beatmap_rank_delta:
            return None
        return await self._beatmap_rank_for_submit_response(
            user_id=command_result.user_id,
            beatmap_id=command_result.beatmap_id,
            beatmap_checksum=beatmap_checksum,
            ruleset=command_result.ruleset,
            playstyle=command_result.playstyle,
            phase="after",
        )

    async def _beatmap_rank_for_submit_response(
        self,
        *,
        user_id: int | None,
        beatmap_id: int | None,
        beatmap_checksum: str,
        ruleset: Ruleset | None,
        playstyle: Playstyle | None,
        phase: str,
    ) -> int | None:
        """安定版submit response用のbeatmap personal best順位を取得する.

        Args:
            user_id (int | None): 順位を取得するuser ID.未確定時はNone.
            beatmap_id (int | None): 順位を取得するbeatmap ID.未確定時はNone.
            beatmap_checksum (str): query scopeを固定するbeatmap checksum MD5.
            ruleset (Ruleset | None): 順位queryのruleset.未確定時はosu!を使う.
            playstyle (Playstyle | None): 順位queryのplaystyle.未確定時はvanillaを使う.
            phase (str): beforeまたはafterを表すdiagnostic phase.

        Returns:
            int | None: queryできたpersonal best順位.依存未設定またはquery失敗時はNone.
        """
        if user_id is None or beatmap_id is None or self._beatmap_personal_best_rank_query is None:
            return None

        query_ruleset = ruleset or Ruleset.OSU
        query_playstyle = playstyle or Playstyle.VANILLA
        try:
            result = await self._beatmap_personal_best_rank_query.execute(
                BeatmapPersonalBestRankQueryInput(
                    user_id=user_id,
                    beatmap_id=beatmap_id,
                    beatmap_checksum=beatmap_checksum,
                    ruleset=query_ruleset,
                    playstyle=query_playstyle,
                )
            )
        except Exception:
            logger.exception(
                "score_submission_beatmap_rank_query_failed",
                user_id=user_id,
                beatmap_id=beatmap_id,
                ruleset=query_ruleset.value,
                playstyle=query_playstyle.value,
                phase=phase,
            )
            return None
        return result.rank

    async def _current_user_stats_for_submit_response(
        self,
        *,
        user_id: int | None,
        ruleset: Ruleset | None,
        playstyle: Playstyle | None,
        phase: str,
    ) -> UserCurrentStats | None:
        """安定版submit response用の現在overall statsを取得する.

        Args:
            user_id (int | None): statsを取得するuser ID.未確定時はNone.
            ruleset (Ruleset | None): stats queryのruleset.未確定時はosu!を使う.
            playstyle (Playstyle | None): stats queryのplaystyle.未確定時はvanillaを使う.
            phase (str): beforeまたはafterを表すdiagnostic phase.

        Returns:
            UserCurrentStats | None: queryできた現在stats.依存未設定またはquery失敗時はNone.
        """
        if user_id is None or self._current_user_stats_query is None:
            return None

        query_ruleset = ruleset or Ruleset.OSU
        query_playstyle = playstyle or Playstyle.VANILLA
        try:
            result = await self._current_user_stats_query.execute(
                CurrentUserStatsQueryInput(
                    user_ids=(user_id,),
                    ruleset=query_ruleset,
                    playstyle=query_playstyle,
                )
            )
        except Exception:
            logger.exception(
                "score_submission_overall_stats_query_failed",
                user_id=user_id,
                ruleset=query_ruleset.value,
                playstyle=query_playstyle.value,
                phase=phase,
            )
            return None
        return result.get(user_id)

    async def _stable_pp_without_wait(self, score_id: int | None) -> int:
        """待機せずにscoreのstable PPを取得し,未確定値を0へ正規化する.

        Args:
            score_id (int | None): performance responseを取得するscore ID.未確定時はNone.

        Returns:
            int: 現時点のstable PP.score IDまたはPPがない場合は0.

        Notes:
            score IDがある呼び出し経路はperformance response queryが設定済みであることを保証する.
        """
        if score_id is None:
            return 0
        assert self._performance_response_query is not None
        response = await self._performance_response_query.get_submit_response(
            PerformanceSubmitResponseQuery(score_id=score_id)
        )
        return response.stable_pp or 0

    async def _request_score_submit_fallback_warmup(
        self,
        *,
        user_id: int,
        beatmap_id: int,
        checksum_md5: str,
    ) -> None:
        """安定版score submitのfallbackとしてbeatmap file warmupを要求する.

        Args:
            user_id (int): warmupを要求した認可済みuser ID.
            beatmap_id (int): warmup対象の解決済みbeatmap ID.
            checksum_md5 (str): warmup対象を照合するbeatmap checksum MD5.

        Returns:
            None: 任意warmupを実行または失敗を記録し,score workflowを継続して完了する.

        Notes:
            warmup use-caseが未設定の場合とwarmup失敗時はscore submissionを停止しない.
        """
        if self._beatmap_file_warmup_use_case is None:
            return

        try:
            _ = await self._beatmap_file_warmup_use_case.execute(
                BeatmapFileWarmupRequest(
                    entrance=BeatmapFileWarmupEntrance.STABLE_SCORE_SUBMIT_FALLBACK,
                    user_id=user_id,
                    beatmap_id=beatmap_id,
                    checksum_md5=checksum_md5,
                )
            )
        except Exception:
            logger.exception(
                "score_submit_beatmap_file_warmup_failed",
                user_id=user_id,
                beatmap_id=beatmap_id,
                has_checksum=checksum_md5 != "",
            )

    async def _record_terminal_reject(
        self,
        *,
        fingerprint: str,
        user_id: int,
        beatmap_checksum: str,
        submitted_at: datetime,
        error_reason: str,
        opaque_field_hashes: Mapping[str, str] | None = None,
    ) -> SubmissionResult:
        """最終拒否outcomeを永続化してtransport用結果へ変換する.

        Args:
            fingerprint (str): 再送を同一submissionとして識別するfingerprint.
            user_id (int): rejectionを関連付ける認可済みuser ID.
            beatmap_checksum (str): rejectionを関連付けるbeatmap checksum MD5.
            submitted_at (datetime): serverがscore submitを受け取った時刻.
            error_reason (str): rejectionを分類するmachine-readable理由.
            opaque_field_hashes (Mapping[str, str] | None): 記録可能なopaque metadataのhash値.

        Returns:
            SubmissionResult: 永続化済みterminal rejectionを表すtransport境界の結果.
        """
        result = await self._submit_score_use_case.execute(
            SubmitScoreCommand(
                fingerprint=fingerprint,
                user_id=user_id,
                beatmap_checksum=beatmap_checksum,
                submitted_at=submitted_at,
                outcome=SubmitScoreCommandOutcome.TERMINAL_REJECTED,
                error_reason=error_reason,
                opaque_field_hashes=opaque_field_hashes,
            )
        )
        return _submission_result_from_command(result)

    async def _record_retryable(
        self,
        *,
        fingerprint: str,
        user_id: int,
        beatmap_checksum: str,
        submitted_at: datetime,
        error_reason: str,
        opaque_field_hashes: Mapping[str, str] | None = None,
    ) -> SubmissionResult:
        """再試行可能outcomeを永続化してtransport用結果へ変換する.

        Args:
            fingerprint (str): 再送を同一submissionとして識別するfingerprint.
            user_id (int): retryable outcomeを関連付ける認可済みuser ID.
            beatmap_checksum (str): retryable outcomeを関連付けるbeatmap checksum MD5.
            submitted_at (datetime): serverがscore submitを受け取った時刻.
            error_reason (str): retryable状態を分類するmachine-readable理由.
            opaque_field_hashes (Mapping[str, str] | None): 記録可能なopaque metadataのhash値.

        Returns:
            SubmissionResult: 永続化済みretryable outcomeを表すtransport境界の結果.
        """
        result = await self._submit_score_use_case.execute(
            SubmitScoreCommand(
                fingerprint=fingerprint,
                user_id=user_id,
                beatmap_checksum=beatmap_checksum,
                submitted_at=submitted_at,
                outcome=SubmitScoreCommandOutcome.RETRYABLE,
                error_reason=error_reason,
                opaque_field_hashes=opaque_field_hashes,
            )
        )
        return _submission_result_from_command(result)

    def _format_auth_error(self, ctx: AuthorizationContext) -> str:
        """認証情報を露出せずauthorization error reasonを整形する.

        Args:
            ctx (AuthorizationContext): credential,session,identityの照合結果.

        Returns:
            str: 最初に不一致だった認可条件を表すmachine-readable error reason.
        """
        if not ctx.password_valid:
            return "authorization_failed: invalid_password"
        if not ctx.session_valid:
            return "authorization_failed: no_active_session"
        if not ctx.payload_identity_match:
            return "authorization_failed: identity_mismatch"
        return "authorization_failed: unknown"

    def _is_relax_or_autopilot(self, mods: ModCombination) -> bool:
        """提出scoreがRelaxまたはAutopilot modを含むかを判定する.

        Args:
            mods (ModCombination): 提出scoreに適用されたcanonical mod組み合わせ.

        Returns:
            bool: RelaxまたはAutopilotのいずれかを含む場合はTrue.
        """
        return mods.has(Mod.RELAX) or mods.has(Mod.AUTOPILOT)
