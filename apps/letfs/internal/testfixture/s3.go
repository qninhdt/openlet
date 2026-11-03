//go:build integration

package testfixture

import (
	"context"
	"net"
	"net/http"
	"os/exec"
	"path/filepath"
	"runtime"
	"testing"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/stretchr/testify/require"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/wait"
)

// S3 owns a disposable provider and bucket; it never reads development credentials.
func S3(t *testing.T) string {
	t.Helper()
	build, cancelBuild := context.WithTimeout(t.Context(), 10*time.Minute)
	_, source, _, ok := runtime.Caller(0)
	require.True(t, ok)
	directory := filepath.Join(filepath.Dir(source), "../../../../infra/minio")
	const image = "openlet-minio:RELEASE.2025-10-15T17-29-55Z"
	output, err := exec.CommandContext(build, "docker", "build", "--tag", image, directory).CombinedOutput()
	cancelBuild()
	require.NoError(t, err, "MinIO image build: %s", output)
	ctx, cancel := context.WithTimeout(t.Context(), time.Minute)
	defer cancel()
	server, err := testcontainers.GenericContainer(ctx, testcontainers.GenericContainerRequest{Started: true, ContainerRequest: testcontainers.ContainerRequest{
		Image:        image,
		Env:          map[string]string{"MINIO_ROOT_USER": "integration", "MINIO_ROOT_PASSWORD": "isolated-testcontainers-secret"},
		ExposedPorts: []string{"9000/tcp"},
		WaitingFor:   wait.ForHTTP("/minio/health/ready").WithPort("9000/tcp").WithStatusCodeMatcher(func(code int) bool { return code == http.StatusOK }).WithStartupTimeout(45 * time.Second),
	}})
	if server != nil {
		testcontainers.CleanupContainer(t, server)
	}
	require.NoError(t, err)
	host, err := server.Host(ctx)
	require.NoError(t, err)
	port, err := server.MappedPort(ctx, "9000/tcp")
	require.NoError(t, err)
	endpoint := "http://" + net.JoinHostPort(host, port.Port())
	client := s3.New(s3.Options{Region: "us-east-1", BaseEndpoint: &endpoint, UsePathStyle: true, Credentials: aws.CredentialsProviderFunc(func(context.Context) (aws.Credentials, error) {
		return aws.Credentials{AccessKeyID: "integration", SecretAccessKey: "isolated-testcontainers-secret"}, nil
	})})
	_, err = client.CreateBucket(ctx, &s3.CreateBucketInput{Bucket: aws.String("openlet-integration")})
	require.NoError(t, err)
	return endpoint
}
