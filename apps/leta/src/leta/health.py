"""Container probe uses the existing native readiness check."""

import asyncio
import os

from grpc_health.v1 import health_pb2, health_pb2_grpc
from openlet.config import required, secret
from openlet.rpc import RpcClient


async def main():
    port = required("RPC_LISTEN_ADDR").rsplit(":", 1)[1]
    async with RpcClient(
        f"localhost:{port}",
        secret("LETA_SERVICE_TOKEN"),
        allow_plaintext=os.getenv("ALLOW_PLAINTEXT_RPC") == "true",
    ) as rpc:
        result = await rpc.invoke(
            health_pb2_grpc.HealthStub(rpc.channel).Check,
            health_pb2.HealthCheckRequest(),
            timeout=4,
        )
        if result.status != health_pb2.HealthCheckResponse.SERVING:
            raise RuntimeError("Leta dependencies are not ready")


if __name__ == "__main__":
    asyncio.run(main())
