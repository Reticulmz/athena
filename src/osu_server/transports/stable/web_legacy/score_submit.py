"""Stable score submit requestをcommand workflowへ適合させるhandlerを提供する."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP
from typing import TYPE_CHECKING, Protocol, cast

import structlog
from starlette.responses import Response

from osu_server.domain.events.scores import CurrentUserStatsUpdated
from osu_server.domain.scores import Playstyle, Ruleset
from osu_server.services.commands.scores import SubmissionOutcome
from osu_server.services.queries.scores import (
    CurrentUserStatsQueryInput,
    CurrentUserStatsQueryResult,
)
from osu_server.transports.stable.web_legacy.mappers import (
    MultipartParseError,
    StableScoreSubmitDecodeError,
    StableScoreSubmitDecoder,
    StableScoreSubmitMapper,
    StableScoreSubmitOverallStats,
)

if TYPE_CHECKING:
    from starlette.requests import Request

    from osu_server.domain.scores.user_stats import UserCurrentStats
    from osu_server.infrastructure.messaging.local import LocalEventBus
    from osu_server.infrastructure.parsers.multipart_parser import MultipartLimits
    from osu_server.services.commands.scores import ParsedSubmissionInput, SubmissionResult

logger: structlog.stdlib.BoundLogger = cast(
    "structlog.stdlib.BoundLogger",
    structlog.get_logger(__name__),
)


class ScoreSubmissionCommand(Protocol):
    """正規化済みscore submission inputを処理するcommand boundaryを表す."""

    async def execute(self, input_data: ParsedSubmissionInput) -> SubmissionResult:
        """Score submission inputを処理して結果を返す.

        Args:
            input_data (ParsedSubmissionInput): transportで正規化済みのscore submission input.

        Returns:
            SubmissionResult: stable response選択に使うsubmission処理結果.
        """
        ...


class CurrentUserStatsQueryPort(Protocol):
    """Completed score response用のcurrent user statsを取得するquery boundaryを表す."""

    async def execute(
        self,
        input_data: CurrentUserStatsQueryInput,
    ) -> CurrentUserStatsQueryResult:
        """指定userのrulesetとplaystyleに対応するcurrent statsを取得する.

        Args:
            input_data (CurrentUserStatsQueryInput): user ID, ruleset, playstyleを指定するquery
                input.

        Returns:
            CurrentUserStatsQueryResult: 指定userの取得済みcurrent stats.
        """
        ...


class ScoreSubmitHandler:
    """Stable `POST /web/osu-submit-modular-selector.php`を処理するhandler.

    Stable clientのmultipart score submissionをrequest mappingへ変換し, decoderでcommand
    input化してscore submission command workflowへ渡す.

    Attributes:
        _submit_score_command (ScoreSubmissionCommand): 正規化済みsubmission inputを
            処理するcommand.
        _decoder (StableScoreSubmitDecoder): stable request mappingをcommand inputへ変換
            するdecoder.
        _mapper (StableScoreSubmitMapper): stable requestとresponseを変換するmapper.
        _current_user_stats_query (CurrentUserStatsQueryPort | None): completed response用statsを
            補完するquery.
        _event_bus (LocalEventBus | None): current stats update eventを発火するbus.
    """

    def __init__(
        self,
        submit_score_command: ScoreSubmissionCommand,
        decoder: StableScoreSubmitDecoder,
        limits: MultipartLimits | None = None,
        mapper: StableScoreSubmitMapper | None = None,
        current_user_stats_query: CurrentUserStatsQueryPort | None = None,
        event_bus: LocalEventBus | None = None,
    ) -> None:
        """Handlerのcommand, decoder, mapper, side-effect境界を設定する.

        Args:
            submit_score_command (ScoreSubmissionCommand): 正規化済みinputを処理するscore
                submission command.
            decoder (StableScoreSubmitDecoder): stable encrypted payloadをParsedSubmissionInputへ
                変換するdecoder.
            limits (MultipartLimits | None): mapper省略時に使うmultipart parser制限.
            mapper (StableScoreSubmitMapper | None): stable request/response mapper.
                Noneならlimitsから生成する.
            current_user_stats_query (CurrentUserStatsQueryPort | None):
                completed response用statsを補完するquery.
            event_bus (LocalEventBus | None): completed後にcurrent stats update eventを発火するbus.

        Notes:
            handlerはtransport adaptationに閉じ, repositoryやDB sessionを直接扱わない.
        """
        self._submit_score_command: ScoreSubmissionCommand = submit_score_command
        self._decoder: StableScoreSubmitDecoder = decoder
        self._mapper: StableScoreSubmitMapper = mapper or StableScoreSubmitMapper(limits)
        self._current_user_stats_query: CurrentUserStatsQueryPort | None = current_user_stats_query
        self._event_bus: LocalEventBus | None = event_bus

    async def __call__(self, request: Request) -> Response:
        """Stable score submit requestをcommand workflowへ適用する.

        Args:
            request (Request): stable clientから届いたmultipart HTTP request.

        Returns:
            Response: stable client互換のscore submit response.

        Notes:
            multipart parseとdecoder失敗はterminal responseへ変換する. retryableとpending結果も
            stable response bodyへ変換する. 復号済みpayload, password-md5, replay binary, opaque
            metadataの生値はloggingせず, current stats補完とevent発火の失敗はresponseを
            失敗扱いにしない.
        """
        try:
            body = await request.body()
            content_type = request.headers.get("content-type", "")
            request_mapping = self._mapper.to_request_mapping(
                body=body,
                content_type=content_type,
                submitted_at=datetime.now(UTC),
            )
        except MultipartParseError as exc:
            logger.warning(
                "score_submission_failed",
                reason="multipart_parse_failed",
                error=str(exc),
            )
            return Response(b"error: no", status_code=200)

        try:
            command_mapping = self._decoder.to_command_mapping(request_mapping)
        except StableScoreSubmitDecodeError as exc:
            logger.warning(
                "score_submission_failed",
                reason=exc.reason,
                request_hash=exc.request_hash,
                opaque_fields=exc.opaque_field_hashes or None,
                error=exc.error,
            )
            return self._mapper.to_response(exc.result)

        logger.debug(
            "score_submission_multipart_parsed",
            score_field_count=command_mapping.score_field_count,
            replay_present=command_mapping.replay_present,
            replay_byte_size=command_mapping.replay_byte_size,
            fail_time_ms=command_mapping.fail_time_ms,
            submit_exit_classification=command_mapping.submit_exit_classification,
            osu_version=command_mapping.osu_version,
        )

        input_data = command_mapping.input_data
        result = await self._submit_score_command.execute(input_data)

        if result.outcome == SubmissionOutcome.COMPLETED:
            current_stats = await self._current_user_stats_after_submit(result)
            overall_stats = (
                _score_submit_overall_stats(current_stats)
                if result.overall_stats_after is None
                else None
            )
            return self._mapper.to_response(
                result,
                overall_stats=overall_stats,
            )
        if result.outcome == SubmissionOutcome.RETRYABLE:
            logger.info(
                "score_submission_retryable_response",
                error_reason=result.error_reason,
            )
            return self._mapper.to_response(result)
        if result.outcome == SubmissionOutcome.ACCEPTED_PENDING:
            logger.info(
                "score_submission_pending_response",
                error_reason=result.error_reason,
            )
            return self._mapper.to_response(result)
        logger.warning(
            "score_submission_terminal_response",
            error_reason=result.error_reason,
        )
        return self._mapper.to_response(result)

    async def _current_user_stats_after_submit(
        self,
        result: SubmissionResult,
    ) -> UserCurrentStats | None:
        """Completed submission後のcurrent user statsを取得してupdate eventを発火する.

        Args:
            result (SubmissionResult): completed submissionのuser, ruleset, playstyle, statsを
                持つ結果.

        Returns:
            UserCurrentStats | None: responseへ使うcurrent stats. userまたはstatsが得られない
                場合はNone.

        Notes:
            stats queryまたはevent発火の失敗は記録して抑制し, submission responseを変えない.
        """
        if result.user_id is None:
            return None

        try:
            ruleset = result.ruleset or Ruleset.OSU
            playstyle = result.playstyle or Playstyle.VANILLA
            current_stats = result.overall_stats_after
            if current_stats is None:
                if self._current_user_stats_query is None:
                    return None
                stats_result = await self._current_user_stats_query.execute(
                    CurrentUserStatsQueryInput(
                        user_ids=(result.user_id,),
                        ruleset=ruleset,
                        playstyle=playstyle,
                    )
                )
                current_stats = stats_result.get(result.user_id)
                if current_stats is None:
                    return None
        except Exception:
            logger.exception(
                "score_submission_current_stats_query_failed",
                user_id=result.user_id,
                score_id=result.score_id,
            )
            return None

        if self._event_bus is not None:
            try:
                await self._event_bus.fire(
                    CurrentUserStatsUpdated(
                        user_id=result.user_id,
                        ruleset=ruleset,
                        playstyle=playstyle,
                        current_stats=current_stats,
                    )
                )
            except Exception:
                logger.exception(
                    "score_submission_current_stats_event_failed",
                    user_id=result.user_id,
                    score_id=result.score_id,
                )
        return current_stats


def _score_submit_overall_stats(
    current_stats: UserCurrentStats | None,
) -> StableScoreSubmitOverallStats | None:
    """Domain current statsをstable overall chart用の値へ変換する.

    Args:
        current_stats (UserCurrentStats | None): completed submission後に取得したdomain stats.

    Returns:
        StableScoreSubmitOverallStats | None: stable chart用の丸め済みstats. inputがNoneならNone.
    """
    if current_stats is None:
        return None
    return StableScoreSubmitOverallStats(
        rank=current_stats.global_rank,
        ranked_score=current_stats.ranked_score,
        total_score=current_stats.total_score,
        max_combo=current_stats.max_combo,
        accuracy=current_stats.accuracy,
        stable_pp=int(current_stats.pp.to_integral_value(rounding=ROUND_HALF_UP)),
    )
