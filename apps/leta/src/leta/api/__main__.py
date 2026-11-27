"""CLI entrypoint for launching the Leta HTTP + internal gRPC server."""

from __future__ import annotations

import uvicorn
from openlet_sdk.config import load

from leta.api.app import create_app
from leta.observability import setup_observability


def main() -> None:
    """Initialize observability and serve the Leta FastAPI application."""
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
