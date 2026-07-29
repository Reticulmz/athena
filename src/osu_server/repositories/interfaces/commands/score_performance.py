"""Score performance lifecycle の command-side repository 契約."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime
    from decimal import Decimal

    from osu_server.domain.scores.performance import (
        FormulaProfile,
        PerformanceCalculation,
        PerformanceCalculationState,
        PerformanceRecalculationBatch,
        PerformanceRecalculationWorkItem,
        RecalculationCandidateReason,
    )


class ScorePerformanceCommandConflictError(RuntimeError):
    """並行した command persistence を再試行すべき場合の例外."""


_ALLOWED_PENDING_STATE_TRANSITIONS = {
    "queued": frozenset({"fetching_file"}),
    "fetching_file": frozenset({"calculating"}),
    "calculating": frozenset[str](),
}


@dataclass(frozen=True, slots=True)
class CreateScorePerformanceCalculation:
    """Current または replacement performance calculation row を要求する command.

    Attributes:
        score_id (int): 計算対象 Score ID.
        calculator_name (str): 使用する performance calculator の名前.
        calculator_version (str): 使用する calculator version.
        formula_profile (FormulaProfile): 計算に適用する formula profile.
        requested_at (datetime): 計算を要求した日時.
    """

    score_id: int
    calculator_name: str
    calculator_version: str
    formula_profile: FormulaProfile
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class ScorePerformanceCalculationRequestResult:
    """Calculation request を作成または再利用した結果.

    Attributes:
        calculation (PerformanceCalculation): 作成または再利用した calculation row.
        created (bool): 新規 row を作成した場合は True.
        is_replacement (bool): Current calculation を置換する request の場合は True.
        requires_commit (bool): Durable outcome にするため Unit of Work の commit が必要な場合は
            True.
    """

    calculation: PerformanceCalculation
    created: bool
    is_replacement: bool
    requires_commit: bool = False


@dataclass(frozen=True, slots=True)
class ClaimScorePerformanceCalculation:
    """1件の pending calculation row の ownership を要求する command.

    Attributes:
        calculation_id (int): Claim する calculation の識別子.
        owner (str): Claim を保持する worker identity.
        claimed_at (datetime): Claim を取得した日時.
        claim_expires_at (datetime): Claim を stale とみなす日時.
    """

    calculation_id: int
    owner: str
    claimed_at: datetime
    claim_expires_at: datetime


@dataclass(frozen=True, slots=True)
class ScorePerformanceCalculationClaimResult:
    """成功した pending calculation claim の metadata.

    Attributes:
        calculation (PerformanceCalculation): Claim に成功した calculation row.
        owner (str): Claim を保持する worker identity.
        expires_at (datetime): Claim の有効期限.
        attempt_count (int): Calculation に対する claim 試行回数.
    """

    calculation: PerformanceCalculation
    owner: str
    expires_at: datetime
    attempt_count: int


@dataclass(frozen=True, slots=True)
class UpdateScorePerformanceCalculationState:
    """Pending calculation を expected state から次の pending state へ進める command.

    Attributes:
        calculation_id (int): 遷移する calculation の正の識別子.
        expected_state (PerformanceCalculationState): Compare-and-set に使う現在の pending state.
        state (PerformanceCalculationState): 記録する次の pending state.
        transitioned_at (datetime): State 遷移日時.
    """

    calculation_id: int
    expected_state: PerformanceCalculationState
    state: PerformanceCalculationState
    transitioned_at: datetime

    def __post_init__(self) -> None:
        """Pending calculation state の前進遷移を検証する.

        Returns:
            None: State 遷移が pending lifecycle の制約を満たすことを示す.

        Raises:
            ValueError: calculation_id が正でない場合,両 state が pending でない場合,
                または state が許可された次状態へ進まない場合に送出する.
        """
        if self.calculation_id <= 0:
            msg = "calculation_id must be positive"
            raise ValueError(msg)
        if not self.expected_state.is_pending:
            msg = "score performance calculation expected state must be pending"
            raise ValueError(msg)
        if not self.state.is_pending:
            msg = "score performance calculation state update must stay pending"
            raise ValueError(msg)
        allowed_next_states = _ALLOWED_PENDING_STATE_TRANSITIONS[self.expected_state.value]
        if self.state.value not in allowed_next_states:
            msg = "score performance calculation state update must advance"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class CompleteScorePerformanceCalculation:
    """PP と star rating を伴う calculation の完了を記録する command.

    Attributes:
        calculation_id (int): 完了する calculation の識別子.
        pp (Decimal): 計算された performance point.
        star_rating (Decimal): 計算された star rating.
        calculator_name (str): 使用した performance calculator の名前.
        calculator_version (str): 使用した calculator version.
        formula_profile (FormulaProfile): 使用した formula profile.
        beatmap_file_attachment_id (int): 計算に使った Beatmap file attachment ID.
        beatmap_file_checksum_md5 (str): 計算に使った Beatmap file の MD5 checksum.
        calculated_at (datetime): 計算完了日時.
    """

    calculation_id: int
    pp: Decimal
    star_rating: Decimal
    calculator_name: str
    calculator_version: str
    formula_profile: FormulaProfile
    beatmap_file_attachment_id: int
    beatmap_file_checksum_md5: str
    calculated_at: datetime


@dataclass(frozen=True, slots=True)
class MarkScorePerformanceCalculationUnavailable:
    """Operator-visible reason とともに calculation を unavailable として完了する command.

    Attributes:
        calculation_id (int): Unavailable にする calculation の識別子.
        calculator_name (str): 使用を試みた performance calculator の名前.
        calculator_version (str): 使用を試みた calculator version.
        formula_profile (FormulaProfile): 使用を試みた formula profile.
        beatmap_file_attachment_id (int | None): 使用を試みた file attachment ID.未取得時は None.
        beatmap_file_checksum_md5 (str | None): 使用を試みた file の MD5 checksum.未取得時は None.
        reason (str): Operator が確認できる unavailable reason.
        calculated_at (datetime): Unavailable を確定した日時.
    """

    calculation_id: int
    calculator_name: str
    calculator_version: str
    formula_profile: FormulaProfile
    beatmap_file_attachment_id: int | None
    beatmap_file_checksum_md5: str | None
    reason: str
    calculated_at: datetime


@dataclass(frozen=True, slots=True)
class CreateScorePerformanceRecalculationWorkItem:
    """再計算 batch へ永続化する1件の候補.

    Attributes:
        score_id (int): 再計算対象の Score ID.
        reason (RecalculationCandidateReason): 候補へ選定された閉集合理由.

    Notes:
        Reason は domain の RecalculationCandidateReason で表現する.
    """

    score_id: int
    reason: RecalculationCandidateReason


@dataclass(frozen=True, slots=True)
class CreateScorePerformanceRecalculationBatch:
    """再計算 batch と work item を永続化する command.

    Attributes:
        filters (Mapping[str, object]): 候補選択に使用した filter snapshot.
        reason_counts (Mapping[RecalculationCandidateReason, int]): 理由別候補件数.
        target_calculator_version (str): 再計算先の calculator version.
        target_formula_profile (FormulaProfile): 再計算先の formula profile.
        work_items (tuple[CreateScorePerformanceRecalculationWorkItem, ...]): 永続化対象.
        created_at (datetime): Batch と work item の作成日時.

    Notes:
        Reason は domain Enum のまま repository へ渡し,adapter が永続化値へ変換する.
    """

    filters: Mapping[str, object]
    reason_counts: Mapping[RecalculationCandidateReason, int]
    target_calculator_version: str
    target_formula_profile: FormulaProfile
    work_items: tuple[CreateScorePerformanceRecalculationWorkItem, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ClaimScorePerformanceRecalculationWork:
    """Pending または stale recalculation work の上限付き chunk を claim する command.

    Attributes:
        batch_id (int): Claim 対象 batch の識別子.
        owner (str): Claim を保持する worker identity.
        claimed_at (datetime): Claim を取得した日時.
        claim_expires_at (datetime): Claim を stale とみなす日時.
        limit (int): 1回の claim で取得する最大 work item 数.
    """

    batch_id: int
    owner: str
    claimed_at: datetime
    claim_expires_at: datetime
    limit: int


@dataclass(frozen=True, slots=True)
class CompleteScorePerformanceRecalculationWork:
    """1件の recalculation work item を completed として記録する command.

    Attributes:
        work_item_id (int): Completed にする work item の識別子.
        owner (str): Work item を claim している worker identity.
        calculation_id (int): 完了した performance calculation の識別子.
        completed_at (datetime): Completion を記録する日時.
    """

    work_item_id: int
    owner: str
    calculation_id: int
    completed_at: datetime


@dataclass(frozen=True, slots=True)
class MarkScorePerformanceRecalculationWorkUnavailable:
    """1件の recalculation work item を unavailable として記録する command.

    Attributes:
        work_item_id (int): Unavailable にする work item の識別子.
        owner (str): Work item を claim している worker identity.
        calculation_id (int): Unavailable で完了した calculation の識別子.
        reason (str): Operator が確認できる unavailable reason.
        completed_at (datetime): Unavailable completion を記録する日時.
    """

    work_item_id: int
    owner: str
    calculation_id: int
    reason: str
    completed_at: datetime


@dataclass(frozen=True, slots=True)
class MarkScorePerformanceRecalculationWorkFailed:
    """1件の retryable recalculation work failure を記録する command.

    Attributes:
        work_item_id (int): 失敗を記録する work item の識別子.
        owner (str): Work item を claim している worker identity.
        error (str): Retry 判断と operator 調査に使う failure detail.
        failed_at (datetime): Failure を記録する日時.
    """

    work_item_id: int
    owner: str
    error: str
    failed_at: datetime


class ScorePerformanceCalculationLifecycleRepository(Protocol):
    """1件の score performance calculation lifecycle の mutation port.

    Notes:
        Runtime 実装は command Unit of Work から取得する.各操作は同じ Unit of Work が
        所有する transaction に参加し,この repository 自身は commit または rollback を
        実行しない.
    """

    async def create_or_reuse_calculation(
        self,
        command: CreateScorePerformanceCalculation,
    ) -> ScorePerformanceCalculationRequestResult:
        """Current または replacement calculation request を作成または再利用する.

        Args:
            command (CreateScorePerformanceCalculation): 作成または再利用する request の入力.

        Returns:
            ScorePerformanceCalculationRequestResult: Calculation と作成結果を表す値.

        Raises:
            ScorePerformanceCommandConflictError: 永続化時の IntegrityError が command conflict に
                変換され,command を再試行すべき場合に送出する.
        """
        ...

    async def claim_pending_calculation(
        self,
        command: ClaimScorePerformanceCalculation,
    ) -> ScorePerformanceCalculationClaimResult | None:
        """Pending calculation を claim し,一時的な競合時は None を返す.

        Args:
            command (ClaimScorePerformanceCalculation): Claim の owner と期限を含む入力.

        Returns:
            ScorePerformanceCalculationClaimResult | None: 成功した claim の metadata.一時的な
                conflict,未存在,または claim 不可の state の場合は None.

        Raises:
            ScorePerformanceCommandConflictError: 永続化時の IntegrityError が command conflict に
                変換され,command を再試行すべき場合に送出する.
        """
        ...

    async def update_pending_calculation_state(
        self,
        command: UpdateScorePerformanceCalculationState,
    ) -> PerformanceCalculation | None:
        """Operator-visible pending lifecycle state を永続化する.

        Args:
            command (UpdateScorePerformanceCalculationState): Compare-and-set state 遷移の入力.

        Returns:
            PerformanceCalculation | None: 遷移後の calculation.Expected state が一致しない場合
                または対象が存在しない場合は None.

        Raises:
            ScorePerformanceCommandConflictError: 永続化時の IntegrityError が command conflict に
                変換され,command を再試行すべき場合に送出する.
        """
        ...

    async def mark_completed(
        self,
        command: CompleteScorePerformanceCalculation,
    ) -> PerformanceCalculation | None:
        """Pending calculation を completed として完了する.

        Args:
            command (CompleteScorePerformanceCalculation): Completion の値を含む入力.

        Returns:
            PerformanceCalculation | None: 完了後の calculation.対象が完了可能でない場合は None.

        Raises:
            ScorePerformanceCommandConflictError: 永続化時の IntegrityError が command conflict に
                変換され,command を再試行すべき場合に送出する.
        """
        ...

    async def mark_unavailable(
        self,
        command: MarkScorePerformanceCalculationUnavailable,
    ) -> PerformanceCalculation | None:
        """Pending calculation を unavailable として完了する.

        Args:
            command (MarkScorePerformanceCalculationUnavailable): Unavailable completion の入力.

        Returns:
            PerformanceCalculation | None: 完了後の calculation.対象が完了可能でない場合は None.

        Raises:
            ScorePerformanceCommandConflictError: 永続化時の IntegrityError が command conflict に
                変換され,command を再試行すべき場合に送出する.
        """
        ...

    async def get_by_id(self, calculation_id: int) -> PerformanceCalculation | None:
        """Identifier から1件の calculation を返す.

        Args:
            calculation_id (int): 取得する calculation の識別子.

        Returns:
            PerformanceCalculation | None: 一致する calculation.存在しない場合は None.
        """
        ...

    async def get_current_for_score(self, score_id: int) -> PerformanceCalculation | None:
        """Score に対する current calculation を返す.

        Args:
            score_id (int): Current calculation を取得する Score ID.

        Returns:
            PerformanceCalculation | None: Score の current calculation.存在しない場合は None.
        """
        ...


class ScorePerformanceRecalculationWorkRepository(Protocol):
    """Durable recalculation batch work の mutation port.

    Notes:
        Runtime 実装は command Unit of Work から取得する.各操作は同じ Unit of Work が
        所有する transaction に参加し,この repository 自身は commit または rollback を
        実行しない.
    """

    async def create_recalculation_batch(
        self,
        command: CreateScorePerformanceRecalculationBatch,
    ) -> PerformanceRecalculationBatch:
        """選定済み work item 全件を持つ recalculation batch を作成する.

        Args:
            command (CreateScorePerformanceRecalculationBatch): Batch と work item の作成入力.

        Returns:
            PerformanceRecalculationBatch: 永続化後の recalculation batch.

        Raises:
            ScorePerformanceCommandConflictError: 永続化時の IntegrityError が command conflict に
                変換され,command を再試行すべき場合に送出する.
        """
        ...

    async def claim_recalculation_work(
        self,
        command: ClaimScorePerformanceRecalculationWork,
    ) -> tuple[PerformanceRecalculationWorkItem, ...]:
        """Pending または stale recalculation work item を上限付き chunk で claim する.

        Args:
            command (ClaimScorePerformanceRecalculationWork): Claim の batch,owner,期限,上限を
                含む入力.

        Returns:
            tuple[PerformanceRecalculationWorkItem, ...]: Claim に成功した work item 群.対象が
                ない場合は空 tuple.

        Raises:
            ValueError: command.limit が 0 以下の場合に送出する.
            ScorePerformanceCommandConflictError: 永続化時の IntegrityError が command conflict に
                変換され,command を再試行すべき場合に送出する.

        Notes:
            command.limit は 0 より大きくなければならない.
        """
        ...

    async def mark_recalculation_work_completed(
        self,
        command: CompleteScorePerformanceRecalculationWork,
    ) -> PerformanceRecalculationWorkItem | None:
        """1件の recalculation work item を completed にし batch progress を更新する.

        Args:
            command (CompleteScorePerformanceRecalculationWork): Completion の owner と calculation
                を含む入力.

        Returns:
            PerformanceRecalculationWorkItem | None: 更新後の work item.対象が更新可能でない
                場合は None.

        Raises:
            ScorePerformanceCommandConflictError: 永続化時の IntegrityError が command conflict に
                変換され,command を再試行すべき場合に送出する.
        """
        ...

    async def mark_recalculation_work_unavailable(
        self,
        command: MarkScorePerformanceRecalculationWorkUnavailable,
    ) -> PerformanceRecalculationWorkItem | None:
        """1件の recalculation work item を unavailable にし batch progress を更新する.

        Args:
            command (MarkScorePerformanceRecalculationWorkUnavailable): Unavailable completion の
                owner,calculation,reason を含む入力.

        Returns:
            PerformanceRecalculationWorkItem | None: 更新後の work item.対象が更新可能でない
                場合は None.

        Raises:
            ScorePerformanceCommandConflictError: 永続化時の IntegrityError が command conflict に
                変換され,command を再試行すべき場合に送出する.
        """
        ...

    async def mark_recalculation_work_failed(
        self,
        command: MarkScorePerformanceRecalculationWorkFailed,
    ) -> PerformanceRecalculationWorkItem | None:
        """Retryable work item failure を記録し,再試行は claim timeout へ委ねる.

        Args:
            command (MarkScorePerformanceRecalculationWorkFailed): Failure の owner と detail を
                含む入力.

        Returns:
            PerformanceRecalculationWorkItem | None: 更新後の work item.対象が更新可能でない
                場合は None.

        Raises:
            ScorePerformanceCommandConflictError: 永続化時の IntegrityError が command conflict に
                変換され,command を再試行すべき場合に送出する.
        """
        ...

    async def get_recalculation_batch_by_id(
        self,
        batch_id: int,
    ) -> PerformanceRecalculationBatch | None:
        """Operator-visible recalculation batch progress を返す.

        Args:
            batch_id (int): 取得する recalculation batch の識別子.

        Returns:
            PerformanceRecalculationBatch | None: 一致する batch progress.存在しない場合は None.
        """
        ...

    async def get_recalculation_work_item_by_id(
        self,
        work_item_id: int,
    ) -> PerformanceRecalculationWorkItem | None:
        """Identifier から1件の recalculation work item を返す.

        Args:
            work_item_id (int): 取得する work item の識別子.

        Returns:
            PerformanceRecalculationWorkItem | None: 一致する work item.存在しない場合は None.
        """
        ...


class ScorePerformanceCommandRepository(
    ScorePerformanceCalculationLifecycleRepository,
    ScorePerformanceRecalculationWorkRepository,
    Protocol,
):
    """Score performance adapter が実装する composite mutation port.

    Notes:
        Runtime 実装は calculation lifecycle と recalculation work の両 contract を同じ command
        Unit of Work transaction 内で提供する.Repository 自身は commit または rollback を
        実行しない.
    """


__all__ = [
    "ClaimScorePerformanceCalculation",
    "ClaimScorePerformanceRecalculationWork",
    "CompleteScorePerformanceCalculation",
    "CompleteScorePerformanceRecalculationWork",
    "CreateScorePerformanceCalculation",
    "CreateScorePerformanceRecalculationBatch",
    "CreateScorePerformanceRecalculationWorkItem",
    "MarkScorePerformanceCalculationUnavailable",
    "MarkScorePerformanceRecalculationWorkFailed",
    "MarkScorePerformanceRecalculationWorkUnavailable",
    "ScorePerformanceCalculationClaimResult",
    "ScorePerformanceCalculationLifecycleRepository",
    "ScorePerformanceCalculationRequestResult",
    "ScorePerformanceCommandConflictError",
    "ScorePerformanceCommandRepository",
    "ScorePerformanceRecalculationWorkRepository",
    "UpdateScorePerformanceCalculationState",
]
