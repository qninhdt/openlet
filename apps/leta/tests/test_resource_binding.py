import asyncio
import subprocess
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid7

import grpc
import pytest
from grpc_health.v1 import health_pb2 as health
from grpc_health.v1 import health_pb2_grpc as health_rpc
from openlet.errors import AppError
from openlet.rpc import Actor, Principal, RpcClient, decode_error
from openlet_api.leta.v1 import leta_pb2 as pb
from openlet_api.leta.v1 import leta_pb2_grpc as leta_rpc
from test_domain import box_input, root_input

from leta.transport import grpc as transport


@pytest.mark.integration
async def test_canonical_binding_wire_and_scope(settings, store):
    config = replace(settings, rpc_listen_addr="127.0.0.1:0")
    root = root_input()
    await store.create_leta(root)
    check = AsyncMock()
    async with transport.serve(config, store, check) as port:
        address = f"127.0.0.1:{port}"
        async with RpcClient(
            address, settings.workspace_service_token, allow_plaintext=True
        ) as client:
            stub = leta_rpc.LetaServiceStub(client.channel)
            request = pb.GetLetaBindingRequest(leta_id=str(root.id))
            for status in ("initializing", "active", "deleting", "archived"):
                if status == "active":
                    await store.activate_leta(root.id)
                    box = box_input(root.id)
                    await store.create_box(box)
                    with pytest.raises(AppError) as captured:
                        await client.invoke(
                            stub.GetLetaBinding,
                            pb.GetLetaBindingRequest(leta_id=str(box.letis[0].id)),
                        )
                    assert captured.value.reason == "NOT_FOUND"
                elif status == "deleting":
                    await store.begin_delete(root.id)
                elif status == "archived":
                    await store.archive(root.id)
                response = await client.invoke(stub.GetLetaBinding, request)
                assert response == pb.GetLetaBindingResponse(
                    leta_id=str(root.id),
                    kind="leta",
                    workspace_id=str(root.workspace_id),
                    created_by_user_id=str(root.created_by_user_id),
                    home_scope_id=str(root.home_scope_id),
                    status=status,
                )

            for invalid in ("", "not-a-uuid", str(UUID(int=0))):
                with pytest.raises(AppError) as captured:
                    await client.invoke(
                        stub.GetLetaBinding, pb.GetLetaBindingRequest(leta_id=invalid)
                    )
                assert captured.value.reason == "VALIDATION"
            with pytest.raises(AppError) as captured:
                await client.invoke(
                    stub.GetLetaBinding, pb.GetLetaBindingRequest(leta_id=str(uuid7()))
                )
            assert captured.value.reason == "NOT_FOUND"

            for kind in ("user", "leta"):
                with pytest.raises(AppError) as captured:
                    await client.invoke(
                        stub.GetLetaBinding, request, actor=Actor(kind, uuid7())
                    )
                assert captured.value.kind == "forbidden"

            headers = (("authorization", f"Bearer {config.workspace_service_token}"),)
            for metadata in (
                (),
                (("authorization", f"Bearer {config.service_token}"),),
                headers + headers,
                headers + (("x-openlet-service", "workspace"),),
            ):
                with pytest.raises(grpc.aio.AioRpcError) as captured:
                    await stub.GetLetaBinding(request, metadata=metadata, timeout=2)
                assert captured.value.code() == grpc.StatusCode.UNAUTHENTICATED

            health_stub = health_rpc.HealthStub(client.channel)
            for service in ("", transport.SERVICE):
                assert (
                    await health_stub.Check(
                        health.HealthCheckRequest(service=service), timeout=2
                    )
                ).status == health.HealthCheckResponse.SERVING
            check.side_effect = RuntimeError("sensitive readiness detail")
            assert (
                await health_stub.Check(health.HealthCheckRequest(), timeout=2)
            ).status == health.HealthCheckResponse.NOT_SERVING
            # Binding reads must work while Workspace awaits dependency readiness.
            assert (
                await client.invoke(stub.GetLetaBinding, request)
            ).status == "archived"
            with pytest.raises(grpc.aio.AioRpcError) as captured:
                await health_stub.Check(
                    health.HealthCheckRequest(service="foreign"), timeout=2
                )
            assert captured.value.code() == grpc.StatusCode.NOT_FOUND
            call = health_stub.Watch(health.HealthCheckRequest(), timeout=2)
            with pytest.raises(grpc.aio.AioRpcError) as captured:
                await call.read()
            assert captured.value.code() == grpc.StatusCode.UNAUTHENTICATED

    assert set(pb.GetLetaBindingResponse.DESCRIPTOR.fields_by_name) == {
        "leta_id",
        "kind",
        "workspace_id",
        "created_by_user_id",
        "home_scope_id",
        "status",
    }


@pytest.mark.parametrize(
    "caller",
    [
        Principal("letfs"),
        Principal("workspace", Actor("user", uuid7())),
        Principal("workspace", gateway=True),
    ],
)
async def test_binding_rechecks_actor_free_workspace_before_store(monkeypatch, caller):
    store = SimpleNamespace(get_binding=AsyncMock())
    monkeypatch.setattr(transport, "principal", lambda: caller)
    with pytest.raises(AppError) as captured:
        await transport.LetaService(store).GetLetaBinding(
            pb.GetLetaBindingRequest(leta_id=str(uuid7())), None
        )
    assert captured.value.kind == "forbidden"
    store.get_binding.assert_not_called()


async def test_binding_deadline_cancels_work_and_errors_are_safe(settings):
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def blocked(_):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    store = SimpleNamespace(get_binding=AsyncMock(side_effect=blocked))
    config = replace(settings, rpc_listen_addr="127.0.0.1:0")
    async with transport.serve(config, store, AsyncMock()) as port:
        async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
            stub = leta_rpc.LetaServiceStub(channel)
            request = pb.GetLetaBindingRequest(leta_id=str(uuid7()))
            metadata = (("authorization", f"Bearer {config.workspace_service_token}"),)
            call = stub.GetLetaBinding(request, metadata=metadata, timeout=2)
            async with asyncio.timeout(3):
                await entered.wait()
                call.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await call
                await cancelled.wait()
                entered.clear()
                cancelled.clear()
                call = stub.GetLetaBinding(request, metadata=metadata, timeout=0.2)
                await entered.wait()
                with pytest.raises(grpc.aio.AioRpcError) as captured:
                    await call
                assert captured.value.code() == grpc.StatusCode.DEADLINE_EXCEEDED
                await cancelled.wait()
            store.get_binding.side_effect = RuntimeError("sensitive SQL detail")
            with pytest.raises(grpc.aio.AioRpcError) as captured:
                await stub.GetLetaBinding(request, metadata=metadata, timeout=2)
            assert captured.value.code() == grpc.StatusCode.INTERNAL
            assert "sensitive" not in str(decode_error(captured.value))


async def test_tls_listener_and_shutdown(settings, tmp_path):
    certificate, key = tmp_path / "server.crt", tmp_path / "server.key"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-keyout",
            str(key),
            "-out",
            str(certificate),
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
        timeout=10,
    )
    config = replace(
        settings,
        rpc_listen_addr="127.0.0.1:0",
        allow_plaintext=False,
        rpc_certificate_path=certificate,
        rpc_private_key_path=key,
    )
    async with transport.serve(config, None, AsyncMock()) as port:
        address = f"127.0.0.1:{port}"
        async with grpc.aio.secure_channel(
            address,
            grpc.ssl_channel_credentials(root_certificates=certificate.read_bytes()),
        ) as channel:
            stub = health_rpc.HealthStub(channel)
            assert (
                await stub.Check(health.HealthCheckRequest(), timeout=2)
            ).status == health.HealthCheckResponse.SERVING
        async with grpc.aio.insecure_channel(address) as channel:
            with pytest.raises(grpc.aio.AioRpcError) as captured:
                await health_rpc.HealthStub(channel).Check(
                    health.HealthCheckRequest(), timeout=1
                )
            assert captured.value.code() == grpc.StatusCode.UNAVAILABLE
    async with grpc.aio.secure_channel(
        address,
        grpc.ssl_channel_credentials(root_certificates=certificate.read_bytes()),
    ) as channel:
        with pytest.raises(grpc.aio.AioRpcError) as captured:
            await health_rpc.HealthStub(channel).Check(
                health.HealthCheckRequest(), timeout=1
            )
        assert captured.value.code() == grpc.StatusCode.UNAVAILABLE

    certificate.unlink()
    with pytest.raises(ValueError, match="^RPC TLS certificate unavailable$"):
        async with transport.serve(config, None, AsyncMock()):
            pytest.fail("missing TLS certificate admitted")
