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
	"github.com/qninhdt/openlet/packages/go/identity"
	"io"
	"math/big"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"

	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/stretchr/testify/require"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/wait"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

func TestIntegrationEnvoyPublicHTTPAndPrivateRPCIsolation(t *testing.T) {
	started, stopped := make(chan struct{}), make(chan struct{})
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		principal, err := identity.AuthenticateGateway(r.Header, fixtureGateway, false)
		if err != nil || principal.ActorID.String() != transportActor {
			w.WriteHeader(401)
			return
		}
		if strings.HasSuffix(r.URL.Path, "/slow") {
			close(started)
			<-r.Context().Done()
			close(stopped)
			return
		}
		_, _ = w.Write(transportBytes)
	}))
	t.Cleanup(backend.Close)
	address, key := envoyProof(t, backend.URL)
	ctx, cancel := context.WithTimeout(t.Context(), 15*time.Second)
	defer cancel()
	jwt := fixtureJWT(t, key, transportActor)
	get := func(token string, spoof bool) *http.Response {
		request, err := http.NewRequestWithContext(ctx, "GET", "http://"+address+"/v1/filesystems/drive/nodes/node", nil)
		require.NoError(t, err)
		if token != "" {
			request.Header.Set("Authorization", "Bearer "+token)
		}
		if spoof {
			request.Header.Add("X-Openlet-Account-ID", "invalid")
			request.Header.Add("X-Openlet-Account-ID", "019a3b66-0000-7000-8000-000000000099")
			request.Header.Set("X-Gateway-Token", "spoofed")
			request.Header.Set("X-Openlet-Service", "workspace")
		}
		response, err := http.DefaultClient.Do(request)
		require.NoError(t, err)
		t.Cleanup(func() { _ = response.Body.Close() })
		return response
	}
	for _, spoof := range []bool{false, true} {
		response := get(jwt, spoof)
		require.Equal(t, 200, response.StatusCode)
		data, err := io.ReadAll(response.Body)
		require.NoError(t, err)
		require.Equal(t, transportBytes, data, "gateway replaces untrusted identity and credentials")
	}
	require.Equal(t, 401, get("", false).StatusCode)
	require.Equal(t, 403, get(fixtureJWT(t, key, ""), true).StatusCode, "headers cannot repair a missing JWT claim")
	connection, err := grpc.NewClient(address, grpc.WithTransportCredentials(insecure.NewCredentials()))
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, connection.Close()) })
	verified := metadata.NewOutgoingContext(ctx, metadata.Pairs("authorization", "Bearer "+jwt))
	_, err = letfsv1.NewFilesystemServiceClient(connection).GetNode(verified, &letfsv1.GetNodeRequest{})
	require.Equal(t, codes.Unimplemented, status.Code(err), "file gRPC has no public ingress")
	_, err = letfsv1.NewStorageAdministrationServiceClient(connection).CreateFilesystem(verified, &letfsv1.CreateFilesystemRequest{})
	require.Equal(t, codes.Unimplemented, status.Code(err))
	_, err = letfsv1.NewIngestServiceClient(connection).PrepareParse(verified, &letfsv1.PrepareParseRequest{})
	require.Equal(t, codes.Unimplemented, status.Code(err))
	cancelable, stop := context.WithCancel(ctx)
	defer stop()
	request, err := http.NewRequestWithContext(cancelable, "GET", "http://"+address+"/v1/filesystems/drive/nodes/slow", nil)
	require.NoError(t, err)
	request.Header.Set("Authorization", "Bearer "+jwt)
	result := make(chan error, 1)
	go func() {
		response, err := http.DefaultClient.Do(request)
		if response != nil {
			_ = response.Body.Close()
		}
		result <- err
	}()
	select {
	case <-started:
	case <-ctx.Done():
		t.Fatal("HTTP request never reached service")
	}
	stop()
	require.Error(t, <-result)
	select {
	case <-stopped:
	case <-ctx.Done():
		t.Fatal("HTTP cancellation never reached service")
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
		claims["openlet_account_id"] = actor
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
	host["request_headers_to_add"].([]any)[0].(map[string]any)["header"].(map[string]any)["value"] = fixtureGateway
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
	clusters := []any{}
	for _, name := range []string{"letfs", "account", "workspace"} {
		clusters = append(clusters, map[string]any{"name": name, "type": "STRICT_DNS", "connect_timeout": "3s",
			"load_assignment": map[string]any{"cluster_name": name, "endpoints": []any{map[string]any{"lb_endpoints": []any{map[string]any{
				"endpoint": map[string]any{"address": map[string]any{"socket_address": map[string]any{"address": testcontainers.HostInternal, "port_value": port}}},
			}}}}}})
	}
	resources["clusters"] = clusters
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
