"""Exercise internal service/actor authentication and HTTP-only public ingress."""

import json
import sys

import grpc
from openlet_api.letfs.v1 import letfs_pb2 as pb
from openlet_api.letfs.v1 import letfs_pb2_grpc as rpc

request = json.load(sys.stdin)
metadata = [
    ("authorization", "Bearer " + request["service_token"]),
    ("x-openlet-user-id", request["actor_id"]),
]
with grpc.insecure_channel("letfs:9090") as channel:
    client = rpc.FilesystemServiceStub(channel)
    context = pb.PathContext(
        mounts=[pb.Mount(path="/files", filesystem_id=request["filesystem_id"])]
    )
    node = pb.GetNodeRequest(
        filesystem_id=request["filesystem_id"],
        node_id=request["node_id"],
        path_context=context,
    )
    if request["allowed"]:
        result = client.GetNode(node, metadata=metadata, timeout=10)
        assert result.node.id == request["node_id"]
        assert result.node.filesystem_id == request["filesystem_id"]
        # Internal listeners reject duplicate actor identity instead of choosing one.
        forged = metadata + [("x-openlet-user-id", request["foreign_user_id"])]
        try:
            client.GetNode(node, metadata=forged, timeout=10)
        except grpc.RpcError as error:
            assert error.code() == grpc.StatusCode.UNAUTHENTICATED
        else:
            raise AssertionError("duplicate actor identity was accepted")
    else:
        try:
            client.GetNode(node, metadata=metadata, timeout=10)
        except grpc.RpcError as error:
            assert error.code() in (
                grpc.StatusCode.PERMISSION_DENIED,
                grpc.StatusCode.NOT_FOUND,
            )
        else:
            raise AssertionError("revoked caller retained native filesystem access")
    for call, payload in [
        (
            rpc.StorageAdministrationServiceStub(channel).CreateBucket,
            pb.CreateBucketRequest(),
        ),
        (rpc.IngestServiceStub(channel).PrepareParse, pb.PrepareParseRequest()),
    ]:
        try:
            call(payload, metadata=metadata, timeout=10)
        except grpc.RpcError as error:
            assert error.code() == grpc.StatusCode.PERMISSION_DENIED
        else:
            raise AssertionError("filesystem caller reached a private RPC")
    try:
        client.GetNode(
            node, metadata=[("authorization", "Bearer " + request["token"])], timeout=10
        )
    except grpc.RpcError as error:
        assert error.code() == grpc.StatusCode.UNAUTHENTICATED
    else:
        raise AssertionError("public JWT was accepted as a service credential")
with grpc.insecure_channel("envoy:8080") as channel:
    try:
        rpc.FilesystemServiceStub(channel).GetNode(
            node, metadata=[("authorization", "Bearer " + request["token"])], timeout=10
        )
    except grpc.RpcError as error:
        assert error.code() == grpc.StatusCode.UNIMPLEMENTED
    else:
        raise AssertionError("public ingress exposed internal gRPC")
print("native filesystem and private method isolation passed")
