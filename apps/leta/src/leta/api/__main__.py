from __future__ import annotations

import logging

import uvicorn
from openlet_sdk.config import load

from .app import create_app


def main() -> None:
    cfg = load()
    listen = cfg["services"]["leta"]["http_listen"]
    host, port_str = listen.rsplit(":", 1)
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        create_app(),
        host=host,
        port=int(port_str),
        log_level=cfg["runtime"]["log_level"].lower(),
    )


if __name__ == "__main__":
    main()
