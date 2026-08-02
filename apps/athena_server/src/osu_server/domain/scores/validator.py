"""parsed score の hit count,accuracy,grade を検証する domain policy を定義する."""

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
    """score validation の入力が domain 条件を満たさない場合の例外を表す."""


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """検証済み hit count から計算した accuracy と grade を表す.

    Attributes:
        valid (bool): validation が成功した場合は True.
        accuracy (float): ruleset ごとの式で計算し 0.0 から 1.0 に収めた accuracy ratio.
        grade (Grade): ruleset ごとの grade 判定結果.
    """

    valid: bool
    accuracy: float
    grade: Grade


def validate_hit_counts(parsed: ParsedScore) -> ValidationResult:
    """Hit count を検証し ruleset 別の accuracy と grade を計算する.

    Args:
        parsed (ParsedScore): client payload を mapping した score 入力.

    Returns:
        ValidationResult: valid=True と計算済みの accuracy,grade を持つ結果.

    Raises:
        ValidationError: ruleset が不明,hit count が負,または ruleset 上の総 hit 数が 0 の場合.

    Notes:
        client_grade は信頼せず,この関数が hit count だけから grade を再計算する.
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
    """Ruleset の accuracy denominator に含める総 hit 数を計算する.

    Args:
        ruleset (Ruleset): hit count を解釈する ruleset.
        parsed (ParsedScore): 集計する hit count を持つ score 入力.

    Returns:
        int: ruleset が採用する判定数と miss 数の合計.

    Notes:
        TAIKO は n50 を,CATCH は geki を,OSU は geki と katu を集計に含めない.
    """
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
    """Ruleset 別の重みで accuracy ratio を計算する.

    Args:
        ruleset (Ruleset): accuracy 式を選ぶ ruleset.
        parsed (ParsedScore): 重み付けする hit count を持つ score 入力.
        total_hits (int): ruleset に対応する正の総 hit 数.

    Returns:
        float: 0.0 から 1.0 の範囲に収めた accuracy ratio.

    Raises:
        ZeroDivisionError: total_hits が 0 のまま呼び出された場合.

    Notes:
        呼び出し元の `validate_hit_counts()` は total_hits が 0 でないことを先に検証する.
    """
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
    """Ruleset と accuracy から grade を選択する.

    Args:
        ruleset (Ruleset): grade 閾値を選ぶ ruleset.
        parsed (ParsedScore): miss と hit count を参照する score 入力.
        accuracy (float): ruleset 別に計算済みの accuracy ratio.

    Returns:
        Grade: ruleset 固有の閾値で決めた grade.
    """
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
    """Osu! standard の grade を計算する.

    Args:
        parsed (ParsedScore): SS と S の miss/hit 条件を参照する score 入力.
        accuracy (float): 0.0 から 1.0 の accuracy ratio.

    Returns:
        Grade: X,S,A,B,C,D のいずれか.

    Notes:
        X は miss,n100,n50 がすべて 0 の完全 accuracy に限る. S 以下の閾値比較は厳密な
        `>` を使う.
    """
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
    """osu!taiko の grade を計算する.

    Args:
        parsed (ParsedScore): X と S の miss/n100 条件を参照する score 入力.
        accuracy (float): 0.0 から 1.0 の accuracy ratio.

    Returns:
        Grade: X,S,A,B,C,D のいずれか.

    Notes:
        X は miss と n100 が 0 の完全 accuracy に限る. S 以下の閾値比較は厳密な `>` を使う.
    """
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
    """osu!catch の accuracy 閾値から grade を計算する.

    Args:
        accuracy (float): 0.0 から 1.0 の accuracy ratio.

    Returns:
        Grade: X,S,A,B,C,D のいずれか.

    Notes:
        X は完全 accuracy,S/A/B/C の閾値はそれぞれ 0.98/0.94/0.90/0.85 より厳密に大きい値を使う.
    """
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
    """osu!mania の accuracy 閾値から grade を計算する.

    Args:
        accuracy (float): 0.0 から 1.0 の accuracy ratio.

    Returns:
        Grade: X,S,A,B,C,D のいずれか.

    Notes:
        X は完全 accuracy,S/A/B/C の閾値はそれぞれ 0.95/0.90/0.80/0.70 より厳密に大きい値を使う.
    """
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
