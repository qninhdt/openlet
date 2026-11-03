"""Exercise the public Envoy HTTP/2 route with the installed generated client."""

import json
import sys

import grpc
from openlet_api.letfs.v1 import letfs_pb2 as pb
from openlet_api.letfs.v1 import letfs_pb2_grpc as rpc

request = json.load(sys.stdin)
metadata = [("authorization", "Bearer " + request["token"])]
with grpc.insecure_channel("envoy:8080") as channel:
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
        # The gateway replaces both forged and duplicate trusted identity fields.
        forged = metadata + [
            ("x-openlet-user-id", request["foreign_user_id"]),
            ("x-openlet-user-id", request["foreign_user_id"]),
            ("x-gateway-token", "forged"),
        ]
        assert (
            client.GetNode(node, metadata=forged, timeout=10).node.id == result.node.id
        )
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
            assert error.code() in (
                grpc.StatusCode.UNIMPLEMENTED,
                grpc.StatusCode.PERMISSION_DENIED,
            )
        else:
            raise AssertionError("public caller reached a private RPC")
print("native filesystem and private method isolation passed")
