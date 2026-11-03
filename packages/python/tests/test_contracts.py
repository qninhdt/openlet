from openlet_api.account.v1 import account_pb2, account_pb2_grpc
from openlet_api.letfs.v1 import letfs_pb2, letfs_pb2_grpc


def test_generated_messages_preserve_presence_and_large_counters():
    node = letfs_pb2.Node(id="node", revision=2**63 - 1)
    assert not node.HasField("media_type")
    node.media_type = ""
    decoded = letfs_pb2.Node.FromString(node.SerializeToString())
    assert decoded.revision == 2**63 - 1
    assert decoded.HasField("media_type")
    assert decoded.media_type == ""


def test_client_and_server_interfaces_are_packaged():
    for module, service in [
        (account_pb2_grpc, "AccountService"),
        (letfs_pb2_grpc, "FilesystemService"),
        (letfs_pb2_grpc, "StorageAdministrationService"),
        (letfs_pb2_grpc, "IngestService"),
    ]:
        assert getattr(module, service + "Stub")
        assert getattr(module, service + "Servicer")
        assert callable(getattr(module, "add_" + service + "Servicer_to_server"))
    assert account_pb2.GetUserSummariesRequest(ids=["user"]).ids == ["user"]
