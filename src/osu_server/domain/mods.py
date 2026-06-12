"""osu! mod flags"""

from enum import IntFlag


class Mods(IntFlag):
    """osu! mod bit flags (stable & lazer compatible)"""

    NONE = 0
    NO_FAIL = 1 << 0  # 1
    EASY = 1 << 1  # 2
    TOUCH_DEVICE = 1 << 2  # 4
    HIDDEN = 1 << 3  # 8
    HARD_ROCK = 1 << 4  # 16
    SUDDEN_DEATH = 1 << 5  # 32
    DOUBLE_TIME = 1 << 6  # 64
    RELAX = 1 << 7  # 128
    HALF_TIME = 1 << 8  # 256
    NIGHTCORE = 1 << 9  # 512
    FLASHLIGHT = 1 << 10  # 1024
    AUTOPLAY = 1 << 11  # 2048
    SPUN_OUT = 1 << 12  # 4096
    AUTOPILOT = 1 << 13  # 8192
    PERFECT = 1 << 14  # 16384
    KEY4 = 1 << 15  # 32768
    KEY5 = 1 << 16  # 65536
    KEY6 = 1 << 17  # 131072
    KEY7 = 1 << 18  # 262144
    KEY8 = 1 << 19  # 524288
    FADE_IN = 1 << 20  # 1048576
    RANDOM = 1 << 21  # 2097152
    CINEMA = 1 << 22  # 4194304
    TARGET_PRACTICE = 1 << 23  # 8388608
    KEY9 = 1 << 24  # 16777216
    KEY_COOP = 1 << 25  # 33554432
    KEY1 = 1 << 26  # 67108864
    KEY3 = 1 << 27  # 134217728
    KEY2 = 1 << 28  # 268435456
    SCORE_V2 = 1 << 29  # 536870912
    MIRROR = 1 << 30  # 1073741824
