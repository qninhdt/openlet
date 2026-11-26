from __future__ import annotations

import uvicorn
from openlet_sdk.config import load

from ..observability import setup_observability
from .app import create_app


def main() -> None:
    cfg = load()
    shutdown, lf = setup_observability("openlet-leta-api", cfg)
    listen = cfg["services"]["leta"]["http_listen"]
    host, port_str = listen.rsplit(":", 1)
    try:
        uvicorn.run(
            create_app(langfuse=lf),
            host=host,
            port=int(port_str),
            log_level=cfg["runtime"]["log_level"].lower(),
        )
    finally:
        shutdown()


if __name__ == "__main__":
    main()
