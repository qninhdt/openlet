//go:build integration

package rpc

import (
	"context"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/identity"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

const fixtureGateway = "isolated-public-gateway-credential-12345"
const fixtureService = "isolated-owner-service-credential-12345"

func TestIntegrationPythonWheelRPC(t *testing.T) {
	ctx, cancel := context.WithTimeout(t.Context(), 90*time.Second)
	defer cancel()
	root, err := filepath.Abs("../../..")
	require.NoError(t, err)
	scratch := t.TempDir()
	run := func(directory, name string, args ...string) string {
		t.Helper()
		cmd := exec.CommandContext(ctx, name, args...)
		cmd.Dir = directory
		for _, item := range os.Environ() {
			if !strings.HasPrefix(item, "PYTHONPATH=") {
				cmd.Env = append(cmd.Env, item)
			}
		}
		output, err := cmd.CombinedOutput()
		require.NoError(t, err, "%s: %s", name, output)
		return string(output)
	}
	run(root, "uv", "build", "--package", "openlet-python", "--wheel", "--out-dir", scratch)
	wheels, err := filepath.Glob(filepath.Join(scratch, "openlet_python-*.whl"))
	require.NoError(t, err)
	require.Len(t, wheels, 1)
	environment := filepath.Join(scratch, "environment")
	run(scratch, "uv", "venv", "--python", "3.13", environment)
	python := filepath.Join(environment, "bin", "python")
	run(scratch, "uv", "pip", "install", "--python", python, wheels[0])
	authentication, err := NewAuthenticator([]Credential{
		{Service: "gateway", Token: fixtureGateway, Gateway: true, Methods: []string{letfsv1.FilesystemService_GetNode_FullMethodName}},
		{Service: "workspace", Token: fixtureService, Methods: []string{letfsv1.StorageAdministrationService_CreateBucket_FullMethodName}},
	})
	require.NoError(t, err)
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	server := grpc.NewServer(grpc.UnaryInterceptor(authentication.Unary()))
	letfsv1.RegisterFilesystemServiceServer(server, &nodeFixture{})
	letfsv1.RegisterStorageAdministrationServiceServer(server, &letfsv1.UnimplementedStorageAdministrationServiceServer{})
	done := make(chan error, 1)
	go func() { done <- server.Serve(listener) }()
	t.Cleanup(func() { server.Stop(); require.NoError(t, <-done) })
	output := run(scratch, python, "-I", "-c", `
import sys
import grpc
from openlet_api.letfs.v1 import letfs_pb2 as pb, letfs_pb2_grpc as rpc
with grpc.insecure_channel(sys.argv[1]) as channel:
    client = rpc.FilesystemServiceStub(channel)
    actor = '019a3b66-0000-7000-8000-000000000001'
    metadata = [('authorization', 'Bearer ' + sys.argv[2]), ('x-openlet-user-id', actor)]
    request = pb.GetNodeRequest(filesystem_id='drive', node_id='node')
    response = client.GetNode(request, metadata=metadata, timeout=5)
    assert response.node.id == 'node'
    assert response.node.name == 'report.pdf'
    assert response.node.revision == 9223372036854775807
    assert not response.node.HasField('media_type')
    for supplied, expected in [([], grpc.StatusCode.UNAUTHENTICATED),
            (metadata + [('x-openlet-user-id', actor)], grpc.StatusCode.UNAUTHENTICATED)]:
        try:
            client.GetNode(request, metadata=supplied, timeout=5)
            raise AssertionError('unauthorized call succeeded')
        except grpc.RpcError as error:
            assert error.code() == expected, error
    admin = rpc.StorageAdministrationServiceStub(channel)
    try:
        admin.CreateBucket(pb.CreateBucketRequest(bucket_id='bucket'), metadata=metadata, timeout=5)
        raise AssertionError('public caller reached administration')
    except grpc.RpcError as error:
        assert error.code() == grpc.StatusCode.PERMISSION_DENIED, error
print('independent shared wheel completed authenticated Go RPC')
`, listener.Addr().String(), fixtureGateway)
	require.Contains(t, output, "independent shared wheel completed authenticated Go RPC")
}

type nodeFixture struct {
	letfsv1.UnimplementedFilesystemServiceServer
}

func (*nodeFixture) GetNode(ctx context.Context, request *letfsv1.GetNodeRequest) (*letfsv1.GetNodeResponse, error) {
	principal, ok := identity.FromContext(ctx)
	if !ok || principal.ActorID == uuid.Nil {
		return nil, status.Error(codes.Unauthenticated, "missing verified actor")
	}
	if request.FilesystemId != "drive" || request.NodeId != "node" {
		return nil, status.Error(codes.NotFound, "node not found")
	}
	return &letfsv1.GetNodeResponse{Node: &letfsv1.Node{Id: "node", Name: "report.pdf", Revision: 9223372036854775807}}, nil
}
