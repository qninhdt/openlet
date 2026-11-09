import argparse
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from openlet.errors import AppError
from openlet.httpapi import problem_json
from openlet.identity import GatewayAuthenticationError, authenticate_gateway
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from leta.config import Settings
from leta.http import agents, boxes, events, history, messages, requests, schedules
from leta.lifespan import resources


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config = settings or Settings.from_env()
        async with resources(config) as owned:
            app.state.settings = config
            app.state.resources = owned
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    def error_response(error: Exception):
        status, headers, body = problem_json(error)
        return JSONResponse(body, status_code=status, headers=headers)

    @app.exception_handler(AppError)
    async def application_error(_request: Request, error: AppError):
        return error_response(error)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, error):
        fields = [".".join(map(str, item["loc"])) for item in error.errors()]
        return error_response(
            AppError(
                "invalid request fields: " + ", ".join(fields),
                reason="VALIDATION",
                kind="invalid",
                retryable=False,
            )
        )

    for router in (
        events.router,
        agents.router,
        boxes.router,
        messages.router,
        history.router,
        requests.router,
        schedules.router,
    ):
        app.include_router(router)

    @app.middleware("http")
    async def gateway(request: Request, call_next):
        if request.url.path == "/v1" or request.url.path.startswith("/v1/"):
            headers = {
                key: request.headers.getlist(key) for key in request.headers.keys()
            }
            try:
                request.state.principal = authenticate_gateway(
                    headers, request.app.state.settings.gateway_token
                )
            except GatewayAuthenticationError:
                return error_response(
                    AppError(
                        "gateway authentication required",
                        reason="UNAUTHENTICATED",
                        kind="unauthenticated",
                        retryable=False,
                    )
                )
        response = await call_next(request)
        if request.url.path.startswith("/v1/"):
            response.headers["cache-control"] = "no-store"
        return response

    @app.get("/live")
    async def live():
        return {"status": "ok"}

    @app.get("/ready")
    async def ready(request: Request):
        try:
            await request.app.state.resources.check()
        except Exception:
            return error_response(
                AppError(
                    "required dependency unavailable",
                    reason="DEPENDENCY_UNAVAILABLE",
                    kind="unavailable",
                )
            )
        return {"status": "ok"}

    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls="/live,/ready",
        http_capture_headers_server_request=[],
        http_capture_headers_server_response=[],
    )
    return app


if __name__ == "__main__":
    argparse.ArgumentParser(description="Run the Leta HTTP API").parse_args()
    config = Settings.from_env()
    address = urlsplit("//" + config.listen_addr)
    uvicorn.run(create_app(config), host=address.hostname, port=address.port)
