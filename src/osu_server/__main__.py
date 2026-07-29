"""`python -m osu_server` の実行エントリーポイントを提供する.

環境設定を読み込み,ASGI applicationをUvicornで起動する.
"""

import uvicorn

from osu_server.config import load_config


def main() -> None:
    """環境設定に従ってUvicornを起動する.

    Returns:
        None: `uvicorn.run()`の終了後に値を返さないことを示す.

    Notes:
        development環境では`src`を監視してreloadを有効にする.
    """
    config = load_config()
    reload_enabled = config.environment == "development"
    uvicorn.run(
        "osu_server.app:app",
        host=config.server_host,
        port=config.server_port,
        reload=reload_enabled,
        reload_dirs=["src"] if reload_enabled else None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
