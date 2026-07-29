"""score performance calculation の domain model,状態,policy を定義する."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import TYPE_CHECKING

from osu_server.domain.beatmaps import BeatmapRankStatus
from osu_server.domain.scores.mods import Mod
from osu_server.domain.scores.score import Playstyle
from osu_server.shared.checksums import MD5_HEX_LENGTH, is_lowercase_md5_hexdigest

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from osu_server.domain.scores.score import Score


class PerformanceCalculationState(Enum):
    """一件の performance calculation attempt の lifecycle state を表す.

    Attributes:
        QUEUED (PerformanceCalculationState): 計算要求を受理し worker 実行待ちの状態.
        FETCHING_FILE (PerformanceCalculationState): 必要な beatmap file を取得中の状態.
        CALCULATING (PerformanceCalculationState): calculator が PP と star rating を計算中の状態.
        COMPLETED (PerformanceCalculationState): PP と star rating を取得して正常完了した状態.
        UNAVAILABLE (PerformanceCalculationState): 入力または calculator が利用不能で完了した状態.
        SUPERSEDED (PerformanceCalculationState): current calculation から置換済みの履歴状態.
    """

    QUEUED = "queued"
    FETCHING_FILE = "fetching_file"
    CALCULATING = "calculating"
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"
    SUPERSEDED = "superseded"

    @classmethod
    def pending_states(cls) -> frozenset[PerformanceCalculationState]:
        """完了 payload を持たない active lifecycle state の集合を返す.

        Returns:
            frozenset[PerformanceCalculationState]: QUEUED,FETCHING_FILE,CALCULATING の集合.
        """
        return frozenset({cls.QUEUED, cls.FETCHING_FILE, cls.CALCULATING})

    @classmethod
    def terminal_states(cls) -> frozenset[PerformanceCalculationState]:
        """計算実行として終了した lifecycle state の集合を返す.

        Returns:
            frozenset[PerformanceCalculationState]: COMPLETED と UNAVAILABLE の集合.

        Notes:
            SUPERSEDED は履歴管理上の状態であり,この集合には含めない.
        """
        return frozenset({cls.COMPLETED, cls.UNAVAILABLE})

    @property
    def is_pending(self) -> bool:
        """この state が active な計算待ちまたは計算中か判定する.

        Returns:
            bool: state が pending_states() に含まれる場合は True.
        """
        return self in self.pending_states()

    @property
    def is_terminal(self) -> bool:
        """この state が正常または unavailable で終了しているか判定する.

        Returns:
            bool: state が terminal_states() に含まれる場合は True.
        """
        return self in self.terminal_states()

    @property
    def is_historical(self) -> bool:
        """この state が current calculation ではない履歴状態か判定する.

        Returns:
            bool: state が SUPERSEDED の場合は True.
        """
        return self is self.SUPERSEDED


class PerformanceRecalculationBatchStatus(Enum):
    """永続的な recalculation batch の operator-visible lifecycle を表す.

    Attributes:
        PENDING (PerformanceRecalculationBatchStatus): batch を作成し work item 実行待ちの状態.
        RUNNING (PerformanceRecalculationBatchStatus): one or more work item を処理中の状態.
        COMPLETED (PerformanceRecalculationBatchStatus): 全 work item が terminal になった状態.
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"


class PerformanceRecalculationWorkItemState(Enum):
    """一件の永続的 recalculation work item の lifecycle state を表す.

    Attributes:
        PENDING (PerformanceRecalculationWorkItemState): worker claim を待つ状態.
        CLAIMED (PerformanceRecalculationWorkItemState): worker が一時的な処理権を保持する状態.
        COMPLETED (PerformanceRecalculationWorkItemState): calculation を完了して終了した状態.
        UNAVAILABLE (PerformanceRecalculationWorkItemState): unavailable で終了した状態.
    """

    PENDING = "pending"
    CLAIMED = "claimed"
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"

    @classmethod
    def terminal_states(cls) -> frozenset[PerformanceRecalculationWorkItemState]:
        """Work item 処理として終了した lifecycle state の集合を返す.

        Returns:
            frozenset[PerformanceRecalculationWorkItemState]: COMPLETED と UNAVAILABLE の集合.
        """
        return frozenset({cls.COMPLETED, cls.UNAVAILABLE})

    @property
    def is_terminal(self) -> bool:
        """この work item state が terminal か判定する.

        Returns:
            bool: state が terminal_states() に含まれる場合は True.
        """
        return self in self.terminal_states()


class RecalculationCandidateReason(Enum):
    """PP再計算候補になったoperator-visible reasonを表す閉集合.

    Attributes:
        UNCALCULATED (RecalculationCandidateReason): current calculation が存在しない理由.
        STALE (RecalculationCandidateReason): beatmap file または計算結果が stale な理由.
        CALCULATOR_VERSION_MISMATCH (RecalculationCandidateReason): version 不一致の理由.
        FORMULA_PROFILE_MISMATCH (RecalculationCandidateReason): profile 不一致の理由.
        UNAVAILABLE (RecalculationCandidateReason): 既存計算が unavailable で再試行対象になる理由.

    Notes:
        domain/use-case 境界では enum member を使い,永続化境界だけで文字列値へ変換する.
    """

    UNCALCULATED = "uncalculated"
    STALE = "stale"
    CALCULATOR_VERSION_MISMATCH = "calculator_version_mismatch"
    FORMULA_PROFILE_MISMATCH = "formula_profile_mismatch"
    UNAVAILABLE = "unavailable"


class FormulaProfile(Enum):
    """playstyle ごとの performance formula profile key を表す.

    Attributes:
        LEGACY_VANILLA_RANKED (FormulaProfile): 旧版 vanilla ranked formula profile.
        VANILLA_RANKED (FormulaProfile): 現行の vanilla ranked formula profile.
    """

    LEGACY_VANILLA_RANKED = "vanilla_ranked_legacy"
    VANILLA_RANKED = "vanilla_ranked_v1"


_DEFAULT_FORMULA_PROFILES_BY_PLAYSTYLE: Mapping[Playstyle, FormulaProfile] = MappingProxyType(
    {Playstyle.VANILLA: FormulaProfile.VANILLA_RANKED}
)


@dataclass(slots=True, frozen=True)
class PerformanceCalculation:
    """一つの score に対する PP calculation attempt または結果を表す.

    Attributes:
        id (int | None): 永続化後の calculation ID. 未永続化時は None.
        score_id (int): calculation 対象となる正の score ID.
        state (PerformanceCalculationState): calculation の lifecycle state.
        is_current (bool): score に対する現在採用中の calculation なら True.
        pp (Decimal | None): COMPLETED 時の非負 PP. それ以外では state に従い None.
        star_rating (Decimal | None): COMPLETED 時の非負 star rating. それ以外は state に従う.
        calculator_name (str): calculation を実行した calculator の空でない識別名.
        calculator_version (str): calculation を実行した calculator の空でない version.
        formula_profile (FormulaProfile): calculation に使用した formula profile.
        beatmap_file_attachment_id (int | None): 入力 file attachment の正の ID. 未保持時は None.
        beatmap_file_checksum_md5 (str | None): 入力 file の lowercase MD5 checksum.
        unavailable_reason (str | None): UNAVAILABLE 時の空でない理由. それ以外は state に従う.
        calculated_at (datetime | None): calculation の終了日時. state により None となる.

    Notes:
        pending state は pp,star_rating,unavailable_reason,calculated_at を保持できない.
        COMPLETED は pp,star_rating,calculated_at を必要とし,UNAVAILABLE は空でない
        unavailable_reason と calculated_at を必要とする. SUPERSEDED は current ではない.
    """

    id: int | None
    score_id: int
    state: PerformanceCalculationState
    is_current: bool
    pp: Decimal | None
    star_rating: Decimal | None
    calculator_name: str
    calculator_version: str
    formula_profile: FormulaProfile
    beatmap_file_attachment_id: int | None
    beatmap_file_checksum_md5: str | None
    unavailable_reason: str | None
    calculated_at: datetime | None

    def __post_init__(self) -> None:
        """Calculation の identity,provenance,state payload を検証する.

        Returns:
            None: calculation がすべての domain invariant を満たすことを示す.

        Raises:
            ValueError: ID,provenance,checksum,または state 固有 payload が不正な場合.
        """
        _validate_identity(self)
        _validate_provenance(self)
        _validate_state_payload(self)


@dataclass(slots=True, frozen=True)
class PerformanceRecalculationBatch:
    """operator が作成した永続的な recalculation work set を表す.

    Attributes:
        id (int | None): 永続化後の batch ID. 未永続化時は None.
        status (PerformanceRecalculationBatchStatus): batch 全体の lifecycle state.
        filters (Mapping[str, object]): 候補選択に使用した filter snapshot.
        reason_counts (Mapping[RecalculationCandidateReason, int]): 理由別の候補件数.
        target_calculator_version (str): 再計算先の空でない calculator version.
        target_formula_profile (FormulaProfile): 再計算先の formula profile.
        candidate_count (int): batch へ登録した候補総数.
        completed_count (int): 正常完了した work item 数.
        unavailable_count (int): unavailable で完了した work item 数.
        last_error (str | None): 最新の batch error. 未発生時は None.
        created_at (datetime): batch 作成日時.
        updated_at (datetime): batch 最終更新日時.

    Raises:
        ValueError: ID,件数,進捗,version,error が domain invariant を満たさない場合.
    """

    id: int | None
    status: PerformanceRecalculationBatchStatus
    filters: Mapping[str, object]
    reason_counts: Mapping[RecalculationCandidateReason, int]
    target_calculator_version: str
    target_formula_profile: FormulaProfile
    candidate_count: int
    completed_count: int
    unavailable_count: int
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        """Recalculation batch の identity,進捗,reason count を検証する.

        Returns:
            None: batch が domain invariant を満たすことを示す.

        Raises:
            ValueError: ID,version,件数,進捗,error,reason count が不正な場合.
        """
        _validate_recalculation_batch(self)


@dataclass(slots=True, frozen=True)
class PerformanceRecalculationWorkItem:
    """durable な recalculation batch に含まれる一件の score 処理状態を表す.

    Attributes:
        id (int | None): 永続化後の work item ID. 未永続化時は None.
        batch_id (int): 所属する正の recalculation batch ID.
        score_id (int): 再計算対象の正の score ID.
        reason (RecalculationCandidateReason): 候補へ選定された理由.
        state (PerformanceRecalculationWorkItemState): 処理 lifecycle state.
        calculation_id (int | None): 起動または完了した正の calculation ID. 未作成時は None.
        claim_owner (str | None): 処理権を保持する空でない worker 識別子. 未 claim 時は None.
        claim_expires_at (datetime | None): claim の有効期限. 未 claim 時は None.
        attempt_count (int): claim された非負の処理回数.
        last_error (str | None): 直近の operator-visible error. 未発生時は None.
        created_at (datetime): work item を作成した日時.
        updated_at (datetime): work item を最後に更新した日時.

    Notes:
        CLAIMED では claim_owner と claim_expires_at を同時に設定する. terminal state では
        calculation_id が必須となり,active claim は保持しない.
    """

    id: int | None
    batch_id: int
    score_id: int
    reason: RecalculationCandidateReason
    state: PerformanceRecalculationWorkItemState
    calculation_id: int | None
    claim_owner: str | None
    claim_expires_at: datetime | None
    attempt_count: int
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        """Recalculation work item の identity,claim,terminal payload を検証する.

        Returns:
            None: work item が domain invariant を満たすことを示す.

        Raises:
            ValueError: ID,claim metadata,attempt count,error,state 固有 payload が不正な場合.
        """
        _validate_recalculation_work_item(self)


@dataclass(slots=True, frozen=True)
class PerformanceEligibilityDecision:
    """ranked PP scope へ score を採用するかの判定結果を表す.

    Attributes:
        is_eligible (bool): score が対象 scope に採用できる場合は True.
        reason (str | None): 採用しない場合の machine-readable 理由. 採用時は None.
    """

    is_eligible: bool
    reason: str | None


class PerformanceEligibilityPolicy:
    """score が ranked PP scope に入るか判定する policy を表す."""

    def evaluate(self, score: Score) -> PerformanceEligibilityDecision:
        """Score が ranked PP calculation の対象か判定する.

        Args:
            score (Score): submit 時点の status,playstyle,mod を保持する accepted score.

        Returns:
            PerformanceEligibilityDecision: eligible 結果,または最初に検出した
                machine-readable 除外理由.

        Raises:
            ValueError: score の beatmap_status_at_submission が BeatmapRankStatus として
                無効な場合.

        Notes:
            passed な VANILLA score だけを対象とし,RELAX/AUTOPILOT を除外する. beatmap status は
            RANKED または APPROVED だけを対象とする.
        """
        if not score.passed:
            return PerformanceEligibilityDecision(False, "score_failed")
        if score.playstyle is not Playstyle.VANILLA:
            return PerformanceEligibilityDecision(False, "playstyle_out_of_scope")
        if score.mods.has(Mod.RELAX) or score.mods.has(Mod.AUTOPILOT):
            return PerformanceEligibilityDecision(False, "playstyle_out_of_scope")
        status = _score_status(score)
        if status is None:
            return PerformanceEligibilityDecision(False, "beatmap_status_missing")
        if status not in _RANKED_PP_STATUSES:
            return PerformanceEligibilityDecision(False, "beatmap_status_out_of_scope")
        return PerformanceEligibilityDecision(True, None)

    def evaluate_best_candidate(self, score: Score) -> PerformanceEligibilityDecision:
        """Score が PP best 集計に採用できるか判定する.

        Args:
            score (Score): submit 時点の leaderboard eligibility を保持する accepted score.

        Returns:
            PerformanceEligibilityDecision: score_not_eligible,または `evaluate()` の判定結果.

        Raises:
            ValueError: score の beatmap_status_at_submission が BeatmapRankStatus として
                無効な場合.

        Notes:
            leaderboard_eligible_at_submission が False の score は ranked PP 条件を満たしていても
            除外する.
        """
        if not score.leaderboard_eligible_at_submission:
            return PerformanceEligibilityDecision(False, "score_not_eligible")
        return self.evaluate(score)


class FormulaProfilePolicy:
    """playstyle ごとに一つの active formula profile を解決する policy を表す."""

    def __init__(
        self,
        profiles_by_playstyle: Mapping[Playstyle, FormulaProfile] | None = None,
    ) -> None:
        """Playstyle から active formula profile への不変な対応表を作成する.

        Args:
            profiles_by_playstyle (Mapping[Playstyle, FormulaProfile] | None): 指定する対応表.
                None の場合は VANILLA の既定対応表を使う.

        Raises:
            ValueError: 対応表に VANILLA の profile が存在しない場合.

        Notes:
            入力 mapping は copy して MappingProxyType で公開する. 構築後の外部変更は反映しない.
        """
        profiles = dict(
            _DEFAULT_FORMULA_PROFILES_BY_PLAYSTYLE
            if profiles_by_playstyle is None
            else profiles_by_playstyle
        )
        if Playstyle.VANILLA not in profiles:
            msg = "vanilla formula profile is required"
            raise ValueError(msg)
        self._profiles_by_playstyle: Mapping[Playstyle, FormulaProfile] = MappingProxyType(
            profiles
        )

    @property
    def profiles_by_playstyle(self) -> Mapping[Playstyle, FormulaProfile]:
        """現在の active formula profile 対応表を返す.

        Returns:
            Mapping[Playstyle, FormulaProfile]: policy 構築時に固定した読み取り専用対応表.
        """
        return self._profiles_by_playstyle

    def active_profile_for(self, playstyle: object) -> FormulaProfile:
        """指定 playstyle の active formula profile を返す.

        Args:
            playstyle (object): runtime で受け取った playstyle 値.

        Returns:
            FormulaProfile: 指定 playstyle に対応する active profile.

        Raises:
            ValueError: playstyle が Playstyle instance でない,または対応 profile がない場合.
        """
        if isinstance(playstyle, Playstyle):
            profile = self._profiles_by_playstyle.get(playstyle)
            if profile is not None:
                return profile
        msg = f"unsupported playstyle for performance calculation: {playstyle!r}"
        raise ValueError(msg)


_RANKED_PP_STATUSES = frozenset({BeatmapRankStatus.RANKED, BeatmapRankStatus.APPROVED})


def _score_status(score: Score) -> BeatmapRankStatus | None:
    """Score に記録した submit 時点の beatmap status を canonical enum へ変換する.

    Args:
        score (Score): beatmap_status_at_submission を持つ accepted score.

    Returns:
        BeatmapRankStatus | None: 記録済み status,または status が未記録であることを表す None.

    Raises:
        ValueError: 記録された値が BeatmapRankStatus の定義値へ変換できない場合.
    """
    raw_status = score.beatmap_status_at_submission
    if raw_status is None:
        return None
    return BeatmapRankStatus(raw_status)


def _validate_identity(calculation: PerformanceCalculation) -> None:
    """Performance calculation の identity に関する invariant を検証する.

    Args:
        calculation (PerformanceCalculation): ID と score ID を検証する calculation.

    Returns:
        None: calculation ID が未設定または正で,score_id が正であることを示す.

    Raises:
        ValueError: calculation ID が 0 以下,または score_id が 0 以下の場合.
    """
    if calculation.id is not None and calculation.id <= 0:
        msg = "performance calculation id must be positive"
        raise ValueError(msg)
    if calculation.score_id <= 0:
        msg = "score_id must be positive"
        raise ValueError(msg)


def _validate_provenance(calculation: PerformanceCalculation) -> None:
    """Performance calculation の calculator と beatmap file provenance を検証する.

    Args:
        calculation (PerformanceCalculation): provenance を検証する calculation.

    Returns:
        None: provenance 情報が domain invariant を満たすことを示す.

    Raises:
        ValueError: calculator 名または version が空,attachment ID が 0 以下,または checksum が
            lowercase 32 文字 MD5 hexadecimal string ではない場合.
    """
    if calculation.calculator_name == "":
        msg = "calculator_name is required"
        raise ValueError(msg)
    if calculation.calculator_version == "":
        msg = "calculator_version is required"
        raise ValueError(msg)
    attachment_id = calculation.beatmap_file_attachment_id
    if attachment_id is not None and attachment_id <= 0:
        msg = "beatmap_file_attachment_id must be positive"
        raise ValueError(msg)
    checksum = calculation.beatmap_file_checksum_md5
    if checksum is not None and not is_lowercase_md5_hexdigest(checksum):
        msg = (
            f"beatmap_file_checksum_md5 must be a {MD5_HEX_LENGTH}-character "
            "lowercase hexadecimal string"
        )
        raise ValueError(msg)


def _validate_state_payload(calculation: PerformanceCalculation) -> None:
    """Lifecycle state に対応する performance payload invariant を検証する.

    Args:
        calculation (PerformanceCalculation): state payload を検証する calculation.

    Returns:
        None: state 固有の payload 条件を満たすことを示す.

    Raises:
        ValueError: state に対応しない payload,または current SUPERSEDED state の場合.
    """
    if calculation.state.is_pending:
        _validate_pending_payload(calculation)
        return
    if calculation.state is PerformanceCalculationState.COMPLETED:
        _validate_completed_payload(calculation)
        return
    if calculation.state is PerformanceCalculationState.UNAVAILABLE:
        _validate_unavailable_payload(calculation)
        return
    if calculation.state is PerformanceCalculationState.SUPERSEDED and calculation.is_current:
        msg = "superseded calculation cannot be current"
        raise ValueError(msg)


def _validate_pending_payload(calculation: PerformanceCalculation) -> None:
    """Pending calculation が完了または unavailable payload を持たないことを検証する.

    Args:
        calculation (PerformanceCalculation): pending state の calculation.

    Returns:
        None: pp,star_rating,unavailable_reason,calculated_at がすべて None であることを示す.

    Raises:
        ValueError: pending calculation が完了または unavailable の payload を保持する場合.
    """
    if calculation.pp is not None or calculation.star_rating is not None:
        msg = "pending calculation cannot have pp or star rating"
        raise ValueError(msg)
    if calculation.unavailable_reason is not None:
        msg = "pending calculation cannot have unavailable reason"
        raise ValueError(msg)
    if calculation.calculated_at is not None:
        msg = "pending calculation cannot have calculated timestamp"
        raise ValueError(msg)


def _validate_completed_payload(calculation: PerformanceCalculation) -> None:
    """Completed calculation の result payload を検証する.

    Args:
        calculation (PerformanceCalculation): COMPLETED state の calculation.

    Returns:
        None: PP と star rating が非負で,calculated_at があり reason がないことを示す.

    Raises:
        ValueError: result payload の必須値不足,負の値,または unavailable reason がある場合.
    """
    if calculation.pp is None or calculation.star_rating is None:
        msg = "completed calculation requires pp and star rating"
        raise ValueError(msg)
    if calculation.pp < Decimal("0") or calculation.star_rating < Decimal("0"):
        msg = "completed calculation pp and star rating must be non-negative"
        raise ValueError(msg)
    if calculation.unavailable_reason is not None:
        msg = "completed calculation cannot have unavailable reason"
        raise ValueError(msg)
    if calculation.calculated_at is None:
        msg = "completed calculation requires calculated timestamp"
        raise ValueError(msg)


def _validate_unavailable_payload(calculation: PerformanceCalculation) -> None:
    """Unavailable calculation の failure payload を検証する.

    Args:
        calculation (PerformanceCalculation): UNAVAILABLE state の calculation.

    Returns:
        None: PP/star rating が None で,空でない reason と calculated_at があることを示す.

    Raises:
        ValueError: result payload,unavailable reason,または calculated_at が不正な場合.
    """
    if calculation.pp is not None or calculation.star_rating is not None:
        msg = "unavailable calculation cannot have pp or star rating"
        raise ValueError(msg)
    if calculation.unavailable_reason is None or calculation.unavailable_reason == "":
        msg = "unavailable calculation requires unavailable reason"
        raise ValueError(msg)
    if calculation.calculated_at is None:
        msg = "unavailable calculation requires calculated timestamp"
        raise ValueError(msg)


def _validate_recalculation_batch(batch: PerformanceRecalculationBatch) -> None:
    """Recalculation batch の identity と進捗 invariant を検証する.

    Args:
        batch (PerformanceRecalculationBatch): 件数,status,error,reason count を検証する batch.

    Returns:
        None: batch が有効な再計算進捗を表すことを示す.

    Raises:
        ValueError: batch の ID,version,count,progress,error,reason count が不正な場合.

    Notes:
        COMPLETED batch の terminal item 数は candidate_count と等しい.
    """
    if batch.id is not None and batch.id <= 0:
        msg = "recalculation batch id must be positive"
        raise ValueError(msg)
    if batch.target_calculator_version == "":
        msg = "target_calculator_version is required"
        raise ValueError(msg)
    if batch.candidate_count < 0:
        msg = "candidate_count must be non-negative"
        raise ValueError(msg)
    if batch.completed_count < 0 or batch.unavailable_count < 0:
        msg = "recalculation progress counts must be non-negative"
        raise ValueError(msg)
    if batch.completed_count + batch.unavailable_count > batch.candidate_count:
        msg = "recalculation progress cannot exceed candidate_count"
        raise ValueError(msg)
    if batch.status is PerformanceRecalculationBatchStatus.COMPLETED and (
        batch.completed_count + batch.unavailable_count != batch.candidate_count
    ):
        msg = "completed recalculation batch requires all work to be terminal"
        raise ValueError(msg)
    if batch.last_error == "":
        msg = "last_error cannot be empty"
        raise ValueError(msg)
    for count in batch.reason_counts.values():
        if count < 0:
            msg = "recalculation reason counts must be non-negative"
            raise ValueError(msg)


def _validate_recalculation_work_item(item: PerformanceRecalculationWorkItem) -> None:
    """Recalculation work item の identity,claim,state invariant を検証する.

    Args:
        item (PerformanceRecalculationWorkItem): identity と state payload を検証する item.

    Returns:
        None: work item が state に対応する処理状態を表すことを示す.

    Raises:
        ValueError: ID,attempt,error,claim,CLAIMED payload,terminal payload が不正な場合.
    """
    if item.id is not None and item.id <= 0:
        msg = "recalculation work item id must be positive"
        raise ValueError(msg)
    if item.batch_id <= 0:
        msg = "recalculation work item batch_id must be positive"
        raise ValueError(msg)
    if item.score_id <= 0:
        msg = "recalculation work item score_id must be positive"
        raise ValueError(msg)
    if item.calculation_id is not None and item.calculation_id <= 0:
        msg = "recalculation work item calculation_id must be positive"
        raise ValueError(msg)
    if item.attempt_count < 0:
        msg = "recalculation work item attempt_count must be non-negative"
        raise ValueError(msg)
    if item.last_error == "":
        msg = "recalculation work item last_error cannot be empty"
        raise ValueError(msg)
    if (item.claim_owner is None) != (item.claim_expires_at is None):
        msg = "recalculation work item claim owner and expiry must be set together"
        raise ValueError(msg)
    if item.claim_owner == "":
        msg = "recalculation work item claim_owner cannot be empty"
        raise ValueError(msg)
    if item.state is PerformanceRecalculationWorkItemState.CLAIMED:
        _validate_claimed_recalculation_work_item(item)
    if item.state.is_terminal:
        _validate_terminal_recalculation_work_item(item)


def _validate_claimed_recalculation_work_item(
    item: PerformanceRecalculationWorkItem,
) -> None:
    """CLAIMED work item が active claim metadata を持つことを検証する.

    Args:
        item (PerformanceRecalculationWorkItem): CLAIMED state の work item.

    Returns:
        None: claim owner,claim expiry,正の attempt count があることを示す.

    Raises:
        ValueError: claim metadata がない,または attempt_count が 0 以下の場合.
    """
    if item.claim_owner is None or item.claim_expires_at is None:
        msg = "claimed recalculation work item requires claim metadata"
        raise ValueError(msg)
    if item.attempt_count <= 0:
        msg = "claimed recalculation work item requires a positive attempt_count"
        raise ValueError(msg)


def _validate_terminal_recalculation_work_item(
    item: PerformanceRecalculationWorkItem,
) -> None:
    """Terminal work item が calculation を参照し active claim を持たないことを検証する.

    Args:
        item (PerformanceRecalculationWorkItem): COMPLETED または UNAVAILABLE state の work item.

    Returns:
        None: calculation_id が存在し,claim metadata がないことを示す.

    Raises:
        ValueError: calculation_id がない,または active claim metadata が残っている場合.
    """
    if item.calculation_id is None:
        msg = "terminal recalculation work item requires calculation_id"
        raise ValueError(msg)
    if item.claim_owner is not None or item.claim_expires_at is not None:
        msg = "terminal recalculation work item cannot keep an active claim"
        raise ValueError(msg)


__all__ = [
    "FormulaProfile",
    "FormulaProfilePolicy",
    "PerformanceCalculation",
    "PerformanceCalculationState",
    "PerformanceEligibilityDecision",
    "PerformanceEligibilityPolicy",
    "PerformanceRecalculationBatch",
    "PerformanceRecalculationBatchStatus",
    "PerformanceRecalculationWorkItem",
    "PerformanceRecalculationWorkItemState",
    "RecalculationCandidateReason",
]
