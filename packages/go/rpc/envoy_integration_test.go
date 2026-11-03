//go:build integration

package rpc

import (
	"bytes"
	"context"
	"crypto"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"io"
	"math/big"
	"net"
	"net/url"
	"os"
	"strconv"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/wait"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	letfsv1 "openlet/packages/go/gen/openlet_api/letfs/v1"
)

func TestIntegrationEnvoyPublicIdentityAndPrivateRPCIsolation(t *testing.T) {
	backend, f := transportServer(t, "127.0.0.1:0")
	address, key := envoyProof(t, backend.URL)
	connection, err := grpc.NewClient(address, grpc.WithTransportCredentials(insecure.NewCredentials()))
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, connection.Close()) })
	client := letfsv1.NewFilesystemServiceClient(connection)
	ctx, cancel := context.WithTimeout(t.Context(), 15*time.Second)
	defer cancel()
	jwt := fixtureJWT(t, key, transportActor)
	verified := metadata.NewOutgoingContext(ctx, metadata.Pairs("authorization", "Bearer "+jwt))
	response, err := client.GetDownload(verified, &letfsv1.GetDownloadRequest{FilesystemId: "drive", NodeId: "node"})
	require.NoError(t, err)
	require.Equal(t, transportBytes, response.Download.GetInlineContent())

	spoofed := metadata.NewOutgoingContext(ctx, metadata.Pairs("authorization", "Bearer "+jwt,
		"x-openlet-user-id", "019a3b66-0000-7000-8000-000000000099", "x-openlet-user-id", "invalid",
		"x-openlet-service", "workspace", "x-gateway-token", "spoofed"))
	_, err = client.GetNode(spoofed, &letfsv1.GetNodeRequest{FilesystemId: "drive", NodeId: "node"})
	require.NoError(t, err, "gateway must replace spoofed headers with the verified JWT actor")
	_, err = client.GetNode(ctx, &letfsv1.GetNodeRequest{FilesystemId: "drive", NodeId: "node"})
	require.Equal(t, codes.Unauthenticated, status.Code(err))
	withoutActor := metadata.NewOutgoingContext(ctx, metadata.Pairs("authorization", "Bearer "+fixtureJWT(t, key, ""), "x-openlet-user-id", transportActor))
	_, err = client.GetNode(withoutActor, &letfsv1.GetNodeRequest{FilesystemId: "drive", NodeId: "node"})
	require.Equal(t, codes.PermissionDenied, status.Code(err), "spoofed header cannot repair a missing JWT claim")
	_, err = letfsv1.NewStorageAdministrationServiceClient(connection).CreateBucket(verified, &letfsv1.CreateBucketRequest{BucketId: "private"})
	require.Equal(t, codes.Unimplemented, status.Code(err), "private native method must not have an ingress route")
	_, err = letfsv1.NewIngestServiceClient(connection).PrepareParse(verified, &letfsv1.PrepareParseRequest{})
	require.Equal(t, codes.Unimplemented, status.Code(err), "ingest native method must not have an ingress route")
	archive, err := client.StreamArchive(verified, &letfsv1.StreamArchiveRequest{FilesystemId: "drive", NodeId: "node"})
	require.NoError(t, err)
	frame, err := archive.Recv()
	require.NoError(t, err)
	require.Equal(t, "application/zip", frame.GetMetadata().Mime)
	for {
		_, err = archive.Recv()
		if err != nil {
			require.ErrorIs(t, err, io.EOF)
			break
		}
	}
	_, err = client.GetNode(verified, &letfsv1.GetNodeRequest{FilesystemId: "foreign", NodeId: "node"})
	require.Equal(t, codes.NotFound, status.Code(err))

	cancelable, stop := context.WithCancel(verified)
	defer stop()
	result := make(chan error, 1)
	go func() {
		_, err := client.GetDownload(cancelable, &letfsv1.GetDownloadRequest{FilesystemId: "drive", NodeId: "slow"})
		result <- err
	}()
	select {
	case <-f.slowStarted:
	case <-ctx.Done():
		t.Fatal("Envoy did not forward native RPC")
	}
	stop()
	require.Equal(t, codes.Canceled, status.Code(<-result))
	select {
	case <-f.slowStopped:
	case <-ctx.Done():
		t.Fatal("Envoy swallowed stream cancellation")
	}
}

func fixtureJWT(t *testing.T, key *rsa.PrivateKey, actor string) string {
	t.Helper()
	encode := func(value any) string {
		data, err := json.Marshal(value)
		require.NoError(t, err)
		return base64.RawURLEncoding.EncodeToString(data)
	}
	claims := map[string]any{"iss": "https://issuer.example.test", "aud": "openlet-proof", "sub": "fixture-user", "exp": time.Now().Add(time.Minute).Unix()}
	if actor != "" {
		claims["openlet_user_id"] = actor
	}
	unsigned := encode(map[string]string{"alg": "RS256", "typ": "JWT", "kid": "proof"}) + "." + encode(claims)
	hash := sha256.Sum256([]byte(unsigned))
	signature, err := rsa.SignPKCS1v15(rand.Reader, key, crypto.SHA256, hash[:])
	require.NoError(t, err)
	return unsigned + "." + base64.RawURLEncoding.EncodeToString(signature)
}

// Reuse the current JWT/header/RBAC chain; only proof routes and dependency addresses differ.
func envoyProof(t *testing.T, backendURL string) (string, *rsa.PrivateKey) {
	t.Helper()
	ctx, cancel := context.WithTimeout(t.Context(), time.Minute)
	defer cancel()
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	require.NoError(t, err)
	data, err := os.ReadFile("../../../infra/config/envoy.template.json")
	require.NoError(t, err)
	var config map[string]any
	require.NoError(t, json.Unmarshal(data, &config))
	resources := config["static_resources"].(map[string]any)
	listener := resources["listeners"].([]any)[0].(map[string]any)
	manager := listener["filter_chains"].([]any)[0].(map[string]any)["filters"].([]any)[0].(map[string]any)["typed_config"].(map[string]any)
	host := manager["route_config"].(map[string]any)["virtual_hosts"].([]any)[0].(map[string]any)
	host["request_headers_to_add"] = []any{map[string]any{"header": map[string]any{"key": "authorization", "value": "Bearer " + fixtureGateway}, "append_action": "OVERWRITE_IF_EXISTS_OR_ADD"}}
	routes := []any{}
	for _, method := range []string{letfsv1.FilesystemService_GetNode_FullMethodName, letfsv1.FilesystemService_GetDownload_FullMethodName, letfsv1.FilesystemService_StreamArchive_FullMethodName} {
		routes = append(routes, map[string]any{"match": map[string]any{"path": method}, "route": map[string]any{"cluster": "letfs", "timeout": "10s"}})
	}
	host["routes"] = append(routes,
		map[string]any{"match": map[string]any{"prefix": "/v1/filesystems/"}, "route": map[string]any{"cluster": "letfs", "timeout": "10s"}},
		map[string]any{"match": map[string]any{"prefix": "/"}, "direct_response": map[string]any{"status": 404}})
	for _, value := range manager["http_filters"].([]any) {
		filter := value.(map[string]any)
		typed := filter["typed_config"].(map[string]any)
		switch filter["name"] {
		case "envoy.filters.http.header_mutation":
			mutations := typed["mutations"].(map[string]any)
			mutations["request_mutations"] = append(mutations["request_mutations"].([]any), map[string]any{"remove": "x-openlet-service"})
		case "envoy.filters.http.jwt_authn":
			provider := typed["providers"].(map[string]any)["clerk"].(map[string]any)
			delete(provider, "remote_jwks")
			jwks, err := json.Marshal(map[string]any{"keys": []any{map[string]any{"kty": "RSA", "alg": "RS256", "use": "sig", "kid": "proof",
				"n": base64.RawURLEncoding.EncodeToString(key.N.Bytes()), "e": base64.RawURLEncoding.EncodeToString(big.NewInt(int64(key.E)).Bytes())}}})
			require.NoError(t, err)
			provider["issuer"], provider["audiences"], provider["local_jwks"] = "https://issuer.example.test", []string{"openlet-proof"}, map[string]any{"inline_string": string(jwks)}
		}
	}
	backend, err := url.Parse(backendURL)
	require.NoError(t, err)
	port, err := strconv.Atoi(backend.Port())
	require.NoError(t, err)
	resources["clusters"] = []any{map[string]any{"name": "letfs", "type": "STRICT_DNS", "connect_timeout": "3s", "http2_protocol_options": map[string]any{},
		"load_assignment": map[string]any{"cluster_name": "letfs", "endpoints": []any{map[string]any{"lb_endpoints": []any{map[string]any{
			"endpoint": map[string]any{"address": map[string]any{"socket_address": map[string]any{"address": testcontainers.HostInternal, "port_value": port}}},
		}}}}}}}
	encoded, err := json.Marshal(config)
	require.NoError(t, err)
	proxy, err := testcontainers.GenericContainer(ctx, testcontainers.GenericContainerRequest{Started: true, ContainerRequest: testcontainers.ContainerRequest{
		Image:        "envoyproxy/envoy:v1.37.0@sha256:d9b4a70739d92b3e28cd407f106b0e90d55df453d7d87773efd22b4429777fe8",
		ExposedPorts: []string{"8080/tcp"}, Cmd: []string{"-c", "/tmp/proof-envoy.json", "--concurrency", "1", "--log-level", "error"},
		Files:           []testcontainers.ContainerFile{{Reader: bytes.NewReader(encoded), ContainerFilePath: "/tmp/proof-envoy.json", FileMode: 0o644}},
		HostAccessPorts: []int{port},
		WaitingFor:      wait.ForListeningPort("8080/tcp").WithStartupTimeout(30 * time.Second),
	}})
	if proxy != nil {
		testcontainers.CleanupContainer(t, proxy)
	}
	require.NoError(t, err)
	proxyHost, err := proxy.Host(ctx)
	require.NoError(t, err)
	proxyPort, err := proxy.MappedPort(ctx, "8080/tcp")
	require.NoError(t, err)
	return net.JoinHostPort(proxyHost, proxyPort.Port()), key
}
