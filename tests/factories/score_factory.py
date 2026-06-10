"""Score test data factory."""

from datetime import UTC, datetime


def make_score_data(
    *,
    beatmap_checksum: str = "8119fb28af74b9445f4a685f8b09eec2",
    username: str = "PlayerOne",
    password_md5: str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    score: int = 552,
    max_combo: int = 2,
    count_300: int = 1,
    count_100: int = 1066,
    count_50: int = 53,
    count_geki: int = 4,
    count_katu: int = 943904,
    count_miss: int = 0,
    perfect: bool = False,
    grade: str = "D",
    mods: int = 0,
    passed: bool = True,
) -> dict[str, int | str | bool]:
    """Create valid score data for testing."""
    return {
        "beatmap_checksum": beatmap_checksum,
        "username": username,
        "password_md5": password_md5,
        "score": score,
        "max_combo": max_combo,
        "count_300": count_300,
        "count_100": count_100,
        "count_50": count_50,
        "count_geki": count_geki,
        "count_katu": count_katu,
        "count_miss": count_miss,
        "perfect": perfect,
        "grade": grade,
        "mods": mods,
        "passed": passed,
    }
