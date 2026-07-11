"""Score domain models."""

from osu_server.domain.scores.decryption import DecryptedPayload
from osu_server.domain.scores.leaderboards import (
    NO_MOD_FILTER_KEY,
    LeaderboardModFilter,
    LeaderboardScope,
    ScoreRankKey,
    filter_from_mod_combination,
    score_beats_current,
    score_matches_selected_mod_filter,
    selected_mod_filter_keys_for_score,
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
from osu_server.domain.scores.submission import ScoreSubmission
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
    "NO_MOD_FILTER_KEY",
    "DecryptedPayload",
    "FormulaProfile",
    "FormulaProfilePolicy",
    "Grade",
    "LeaderboardCategory",
    "LeaderboardModFilter",
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
    "filter_from_mod_combination",
    "friends_leaderboard_is_available",
    "score_beats_current",
    "score_beats_personal_best",
    "score_matches_selected_mod_filter",
    "selected_mod_filter_keys_for_score",
    "validate_hit_counts",
]
