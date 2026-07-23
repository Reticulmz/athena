"""legacy score submission用の有効なscore data factoryを提供する."""


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
    """Score submission testに渡すdefault有効score dataを作る.

    Args:
        beatmap_checksum (str): score対象beatmapのMD5 checksum.
        username (str): scoreを送信するuser名.
        password_md5 (str): user passwordのMD5 digest.
        score (int): 記録したscore値.
        max_combo (int): 最大combo.
        count_300 (int): 300判定数.
        count_100 (int): 100判定数.
        count_50 (int): 50判定数.
        count_geki (int): geki判定数.
        count_katu (int): katu判定数.
        count_miss (int): miss判定数.
        perfect (bool): full comboか.
        grade (str): grade文字列.
        mods (int): stable mod bitmask.
        passed (bool): beatmapをpassしたか.

    Returns:
        dict[str, int | str | bool]: legacy score formへ変換する入力mapping.
    """
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
