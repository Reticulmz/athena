"""アプリケーション横断で使用する例外型を定義する."""


class AppError(Exception):
    """アプリケーション固有の例外を表す基底型です.

    Notes:
        呼び出し元は組み込み例外だけを捕捉する代わりにこの型を捕捉できる.
    """


class DecryptionError(AppError):
    """score payload の復号に失敗したことを表す例外です.

    Notes:
        復号失敗を通常の入力検証失敗と区別して上位層へ伝えるために使用する.
    """
