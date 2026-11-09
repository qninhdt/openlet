package config

import (
	"fmt"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

func values() map[string]string {
	return map[string]string{
		"TEMPORAL_ADDRESS": "localhost:7233", "TEMPORAL_NAMESPACE": "openlet",
		"DATABASE_URL":    "postgres://letfs:isolated-password@localhost:5432/letfs",
		"SPICEDB_ADDRESS": "localhost:50051", "SPICEDB_GRPC_PRESHARED_KEY": strings.Repeat("s", 32),
		"GATEWAY_TOKEN": strings.Repeat("g", 32), "WORKSPACE_SERVICE_TOKEN": strings.Repeat("w", 32), "INGEST_SERVICE_TOKEN": strings.Repeat("i", 32), "LETA_SERVICE_TOKEN": strings.Repeat("l", 32), "ALLOW_PLAINTEXT_RPC": "true",
		"S3_ENDPOINT": "https://s3.example.test", "S3_BUCKET": "private", "S3_REGION": "auto", "S3_ACCESS_KEY_ID": "isolated-access", "S3_SECRET_ACCESS_KEY": "isolated-secret",
		"QDRANT_API_KEY":     "isolated-qdrant-token",
		"OPENROUTER_API_KEY": "isolated-provider-token",
	}
}
func TestParseStorageLimitsAndTrustBoundaries(t *testing.T) {
	input := values()
	cfg, err := Parse(func(key string) string { return input[key] })
	require.NoError(t, err)
	require.Equal(t, ":9090", cfg.RPCListen)
	require.EqualValues(t, 104857600, cfg.MaxFileBytes)
	require.Equal(t, 300*time.Second, cfg.DownloadLifetime)
	require.EqualValues(t, 512, cfg.ProcessingMaxOutputs)
	require.EqualValues(t, 268435456, cfg.ProcessingMaxOutputBytes)
	require.Equal(t, "openai/text-embedding-3-small", cfg.IndexSpace.Model)
	require.Equal(t, "files", cfg.IndexSpace.Collection)
	require.EqualValues(t, 1536, cfg.IndexSpace.Dimension)
	require.EqualValues(t, 10000, cfg.Archive.MaxEntries)
	require.EqualValues(t, 2, cfg.ArchiveMaxConcurrent)
	require.Equal(t, 1200*time.Second, cfg.Archive.Runtime)
	for _, change := range []map[string]string{
		{"ALLOW_PLAINTEXT_RPC": "1"}, {"ALLOW_PLAINTEXT_RPC": "false"}, {"RPC_TLS_CERT_PATH": "cert"},
		{"RPC_LISTEN_ADDR": ":0"}, {"SPICEDB_ADDRESS": ":50051"}, {"DATABASE_URL": "postgres://letfs@localhost/letfs"},
		{"TEMPORAL_ADDRESS": ""}, {"TEMPORAL_ADDRESS": ":7233"}, {"TEMPORAL_ADDRESS": "localhost:0"},
		{"TEMPORAL_NAMESPACE": ""}, {"TEMPORAL_NAMESPACE": "openlet\n"},
		{"LETA_SERVICE_TOKEN": ""}, {"LETA_SERVICE_TOKEN": strings.Repeat("w", 32)}, {"INGEST_SERVICE_TOKEN": ""}, {"INGEST_SERVICE_TOKEN": strings.Repeat("w", 32)}, {"INGEST_SERVICE_TOKEN": "invalid-token"},
		{"GATEWAY_TOKEN": strings.Repeat("w", 32)}, {"SPICEDB_GRPC_PRESHARED_KEY": "bad\nkey"},
		{"S3_ENDPOINT": "http://localhost:9000"}, {"S3_ENDPOINT": "https://user:password@s3.example.test"},
		{"S3_SIGNING_ENDPOINT": "https://s3.example.test?bad"}, {"ALLOW_LOCAL_S3": "1"},
		{"ARCHIVE_MAX_ENTRIES": "100001"}, {"ARCHIVE_MAX_SOURCE_BYTES": "0"}, {"ARCHIVE_MAX_OUTPUT_BYTES": "10000000001"}, {"ARCHIVE_MAX_CONCURRENT": "9"}, {"ARCHIVE_RUNTIME_SECONDS": "1801"},
		{"MAX_NODES": "0"}, {"MAX_COPY_NODES": "-1"}, {"MAX_FILE_BYTES": "9223372036854775807"},
		{"PROCESSING_MAX_OUTPUTS": "0"}, {"PROCESSING_MAX_OUTPUT_BYTES": "-1"},
		{"OPENROUTER_EMBEDDING_MODEL": " "}, {"QDRANT_COLLECTION": "../files"},
		{"EMBEDDING_DIMENSION": "0"}, {"EMBEDDING_DIMENSION": "65537"}, {"EMBEDDING_DIMENSION": "4294967297"},
		{"QDRANT_API_KEY": ""}, {"QDRANT_URL": "http://user:password@qdrant:6333"}, {"QDRANT_URL": "http://qdrant:6333?invalid"},
		{"OPENROUTER_API_KEY": ""}, {"OPENROUTER_URL": "http://provider.test"}, {"OPENROUTER_RERANK_MODEL": " "}, {"ALLOW_LOCAL_AI": "1"},
		{"INLINE_LIMIT_BYTES": "1048577"}, {"DOWNLOAD_URL_TTL_SECONDS": "601"}, {"UPLOAD_URL_TTL_SECONDS": "3601"},
		{"UPLOAD_TRANSFER_GRACE_SECONDS": "86401"}, {"MULTIPART_PART_BYTES": "5242879"},
		{"MULTIPART_PART_BYTES": "5368709121"}, {"MULTIPART_THRESHOLD_BYTES": "5242880"},
	} {
		t.Run(fmt.Sprint(change), func(t *testing.T) {
			input := values()
			for key, value := range change {
				input[key] = value
			}
			_, err := Parse(func(key string) string { return input[key] })
			require.Error(t, err)
		})
	}
	input = values()
	input["ALLOW_LOCAL_S3"] = "true"
	input["S3_ENDPOINT"] = "http://localhost:9000"
	input["S3_SIGNING_ENDPOINT"] = "http://127.0.0.1:18202"
	_, err = Parse(func(key string) string { return input[key] })
	require.NoError(t, err)
}
func TestLoadDoesNotFallBackFromAnUnreadableSecretFile(t *testing.T) {
	for key, value := range values() {
		t.Setenv(key, value)
	}
	t.Setenv("DATABASE_URL_FILE", filepath.Join(t.TempDir(), "missing"))
	_, err := Load()
	require.ErrorContains(t, err, "DATABASE_URL")
	require.NotContains(t, err.Error(), "isolated-password")
}
