"""Entry point for ``python -m osu_server``."""

import uvicorn

from osu_server.config import load_config


def main() -> None:
    """Launch uvicorn with settings from AppConfig."""
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
