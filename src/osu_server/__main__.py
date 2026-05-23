"""Entry point for ``python -m osu_server``."""

import uvicorn

from osu_server.config import load_config


def main() -> None:
    """Launch uvicorn with settings from AppConfig."""
    config = load_config()
    uvicorn.run(
        "osu_server.app:app",
        host=config.server_host,
        port=config.server_port,
        reload=config.environment == "development",
        access_log=False,
    )


if __name__ == "__main__":
    main()
