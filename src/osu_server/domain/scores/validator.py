"""Score validator."""

from dataclasses import dataclass

from osu_server.domain.scores.payload_parser import ParsedScore
from osu_server.domain.scores.score import Grade, Ruleset

# Grade thresholds (osu! specification)
_GRADE_SS_ACCURACY = 1.0
_GRADE_S_ACCURACY = 0.9
_GRADE_A_ACCURACY = 0.8
_GRADE_B_ACCURACY = 0.7
_GRADE_C_ACCURACY = 0.6
_CATCH_GRADE_S_ACCURACY = 0.98
_CATCH_GRADE_A_ACCURACY = 0.94
_CATCH_GRADE_B_ACCURACY = 0.90
_CATCH_GRADE_C_ACCURACY = 0.85
_MANIA_GRADE_S_ACCURACY = 0.95
_MANIA_GRADE_A_ACCURACY = 0.90
_MANIA_GRADE_B_ACCURACY = 0.80
_MANIA_GRADE_C_ACCURACY = 0.70


class ValidationError(Exception):
    """Raised when score validation fails."""


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Validation result with calculated accuracy and grade."""

    valid: bool
    accuracy: float
    grade: Grade


def validate_hit_counts(parsed: ParsedScore) -> ValidationResult:
    """Validate hit counts and calculate accuracy/grade.

    Args:
        parsed: Parsed score data

    Returns:
        ValidationResult with accuracy and grade

    Raises:
        ValidationError: If hit counts are invalid
    """
    # Validate ruleset
    try:
        ruleset = Ruleset(parsed.ruleset)
    except ValueError as e:
        raise ValidationError(f"Invalid ruleset: {parsed.ruleset}") from e

    # Validate non-negative hit counts
    if any(
        count < 0
        for count in [
            parsed.n300,
            parsed.n100,
            parsed.n50,
            parsed.geki,
            parsed.katu,
            parsed.miss,
        ]
    ):
        raise ValidationError("Hit counts cannot be negative")

    # Calculate total hits based on ruleset
    total_hits = _calculate_total_hits(ruleset, parsed)

    # Validate non-zero total
    if total_hits == 0:
        raise ValidationError("Total hit count cannot be zero")

    # Calculate accuracy
    accuracy = _calculate_accuracy(ruleset, parsed, total_hits)

    # Calculate grade
    grade = _calculate_grade(ruleset, parsed, accuracy)

    return ValidationResult(valid=True, accuracy=accuracy, grade=grade)


def _calculate_total_hits(ruleset: Ruleset, parsed: ParsedScore) -> int:
    """Calculate total hits based on ruleset."""
    match ruleset:
        case Ruleset.OSU:
            return parsed.n300 + parsed.n100 + parsed.n50 + parsed.miss
        case Ruleset.TAIKO:
            return parsed.n300 + parsed.n100 + parsed.miss
        case Ruleset.CATCH:
            return parsed.n300 + parsed.n100 + parsed.n50 + parsed.katu + parsed.miss
        case Ruleset.MANIA:
            return parsed.n300 + parsed.n100 + parsed.n50 + parsed.geki + parsed.katu + parsed.miss


def _calculate_accuracy(ruleset: Ruleset, parsed: ParsedScore, total_hits: int) -> float:
    """Calculate accuracy based on ruleset."""
    match ruleset:
        case Ruleset.OSU:
            weighted = (parsed.n300 * 300 + parsed.n100 * 100 + parsed.n50 * 50) / (
                total_hits * 300
            )
        case Ruleset.TAIKO:
            weighted = (parsed.n300 * 300 + parsed.n100 * 150) / (total_hits * 300)
        case Ruleset.CATCH:
            weighted = (parsed.n300 + parsed.n100 + parsed.n50) / total_hits
        case Ruleset.MANIA:
            weighted = (
                parsed.geki * 300
                + parsed.n300 * 300
                + parsed.katu * 200
                + parsed.n100 * 100
                + parsed.n50 * 50
            ) / (total_hits * 300)

    return max(0.0, min(1.0, weighted))


def _calculate_grade(ruleset: Ruleset, parsed: ParsedScore, accuracy: float) -> Grade:
    """Calculate grade based on ruleset and accuracy."""
    match ruleset:
        case Ruleset.OSU:
            return _calculate_osu_grade(parsed, accuracy)
        case Ruleset.TAIKO:
            return _calculate_taiko_grade(parsed, accuracy)
        case Ruleset.CATCH:
            return _calculate_catch_grade(accuracy)
        case Ruleset.MANIA:
            return _calculate_mania_grade(accuracy)


def _calculate_osu_grade(parsed: ParsedScore, accuracy: float) -> Grade:
    """Calculate osu! standard grade."""
    if (
        accuracy >= _GRADE_SS_ACCURACY
        and parsed.miss == 0
        and parsed.n100 == 0
        and parsed.n50 == 0
    ):
        return Grade.X
    if accuracy > _GRADE_S_ACCURACY and parsed.miss == 0:
        return Grade.S
    if accuracy > _GRADE_A_ACCURACY:
        return Grade.A
    if accuracy > _GRADE_B_ACCURACY:
        return Grade.B
    if accuracy > _GRADE_C_ACCURACY:
        return Grade.C
    return Grade.D


def _calculate_taiko_grade(parsed: ParsedScore, accuracy: float) -> Grade:
    """Calculate taiko grade."""
    if accuracy >= _GRADE_SS_ACCURACY and parsed.miss == 0 and parsed.n100 == 0:
        return Grade.X
    if accuracy > _GRADE_S_ACCURACY and parsed.miss == 0:
        return Grade.S
    if accuracy > _GRADE_A_ACCURACY:
        return Grade.A
    if accuracy > _GRADE_B_ACCURACY:
        return Grade.B
    if accuracy > _GRADE_C_ACCURACY:
        return Grade.C
    return Grade.D


def _calculate_catch_grade(accuracy: float) -> Grade:
    """Calculate catch grade."""
    if accuracy >= _GRADE_SS_ACCURACY:
        return Grade.X
    if accuracy > _CATCH_GRADE_S_ACCURACY:
        return Grade.S
    if accuracy > _CATCH_GRADE_A_ACCURACY:
        return Grade.A
    if accuracy > _CATCH_GRADE_B_ACCURACY:
        return Grade.B
    if accuracy > _CATCH_GRADE_C_ACCURACY:
        return Grade.C
    return Grade.D


def _calculate_mania_grade(accuracy: float) -> Grade:
    """Calculate mania grade."""
    if accuracy >= _GRADE_SS_ACCURACY:
        return Grade.X
    if accuracy > _MANIA_GRADE_S_ACCURACY:
        return Grade.S
    if accuracy > _MANIA_GRADE_A_ACCURACY:
        return Grade.A
    if accuracy > _MANIA_GRADE_B_ACCURACY:
        return Grade.B
    if accuracy > _MANIA_GRADE_C_ACCURACY:
        return Grade.C
    return Grade.D
