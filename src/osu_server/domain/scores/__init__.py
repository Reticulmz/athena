"""Score domain models."""

from osu_server.domain.scores.decryption import DecryptedPayload
from osu_server.domain.scores.leaderboards import (
    LeaderboardScope,
    ScoreRankKey,
    score_beats_current,
)
from osu_server.domain.scores.mods import Mod, ModCombination
from osu_server.domain.scores.payload_parser import ParsedScore, ParseError
from osu_server.domain.scores.performance import (
    FormulaProfile,
    FormulaProfilePolicy,
    PerformanceCalculation,
    PerformanceCalculationState,
    PerformanceEligibilityDecision,
    PerformanceEligibilityPolicy,
    PerformanceRecalculationBatch,
    PerformanceRecalculationBatchStatus,
    PerformanceRecalculationWorkItem,
    PerformanceRecalculationWorkItemState,
)
from osu_server.domain.scores.personal_best import (
    LeaderboardCategory,
    PersonalBest,
    PersonalBestDelta,
    PersonalBestScope,
    country_leaderboard_is_available,
    friends_leaderboard_is_available,
    score_beats_personal_best,
)
from osu_server.domain.scores.replay import Replay
from osu_server.domain.scores.score import Grade, Playstyle, PlayTimeSource, Ruleset, Score
from osu_server.domain.scores.submission import ScoreSubmission, ScoreSubmissionState
from osu_server.domain.scores.user_stats import (
    UserCurrentStats,
    UserPerformanceBest,
    UserStatsHitTotals,
    UserStatsPerformanceTotals,
    UserStatsPolicy,
    UserStatsProjection,
    UserStatsScope,
)
from osu_server.domain.scores.validator import (
    ValidationError,
    ValidationResult,
    validate_hit_counts,
)

__all__ = [
    "DecryptedPayload",
    "FormulaProfile",
    "FormulaProfilePolicy",
    "Grade",
    "LeaderboardCategory",
    "LeaderboardScope",
    "Mod",
    "ModCombination",
    "ParseError",
    "ParsedScore",
    "PerformanceCalculation",
    "PerformanceCalculationState",
    "PerformanceEligibilityDecision",
    "PerformanceEligibilityPolicy",
    "PerformanceRecalculationBatch",
    "PerformanceRecalculationBatchStatus",
    "PerformanceRecalculationWorkItem",
    "PerformanceRecalculationWorkItemState",
    "PersonalBest",
    "PersonalBestDelta",
    "PersonalBestScope",
    "PlayTimeSource",
    "Playstyle",
    "Replay",
    "Ruleset",
    "Score",
    "ScoreRankKey",
    "ScoreSubmission",
    "ScoreSubmissionState",
    "UserCurrentStats",
    "UserPerformanceBest",
    "UserStatsHitTotals",
    "UserStatsPerformanceTotals",
    "UserStatsPolicy",
    "UserStatsProjection",
    "UserStatsScope",
    "ValidationError",
    "ValidationResult",
    "country_leaderboard_is_available",
    "friends_leaderboard_is_available",
    "score_beats_current",
    "score_beats_personal_best",
    "validate_hit_counts",
]
