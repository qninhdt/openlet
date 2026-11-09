package config

import (
	"errors"
	"fmt"
	"net"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/qninhdt/openlet/apps/letfs/internal/clients/search"
	"github.com/qninhdt/openlet/apps/letfs/internal/clients/storage"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	sharedconfig "github.com/qninhdt/openlet/packages/go/config"
)

type Config struct {
	AI                                                         search.AIConfig
	QdrantURL, QdrantKey                                       string
	TemporalAddress, TemporalNamespace                         string
	Listen, RPCListen, DatabaseURL, SpiceDBAddress, SpiceDBKey string
	GatewayToken, WorkspaceToken, IngestToken, LetaToken       string
	RPCCertificatePath, RPCPrivateKeyPath                      string
	AllowPlaintextRPC                                          bool
	Storage                                                    storage.Config
	MaxNodes, MaxCopyNodes, InlineLimit, MaxFileBytes          int64
	MaxOutstanding, MaxCleanupBacklog                          int64
	MultipartThreshold, MultipartPartBytes                     int64
	DownloadLifetime, UploadLifetime, UploadTransferGrace      time.Duration
	ProcessingMaxOutputs, ProcessingMaxOutputBytes             int64
	IndexSpace                                                 filesystem.VectorSpace
	Archive                                                    filesystem.ArchiveConfig
	ArchiveMaxConcurrent                                       int64
}

func Load() (Config, error) { return Parse(sharedconfig.Secret) }
func Parse(get func(string) string) (Config, error) {
	c := Config{Listen: get("LISTEN_ADDR"), RPCListen: get("RPC_LISTEN_ADDR"), DatabaseURL: get("DATABASE_URL"), SpiceDBAddress: get("SPICEDB_ADDRESS"), SpiceDBKey: get("SPICEDB_GRPC_PRESHARED_KEY"), GatewayToken: get("GATEWAY_TOKEN"), WorkspaceToken: get("WORKSPACE_SERVICE_TOKEN"), IngestToken: get("INGEST_SERVICE_TOKEN"), RPCCertificatePath: get("RPC_TLS_CERT_PATH"), RPCPrivateKeyPath: get("RPC_TLS_KEY_PATH"), TemporalAddress: get("TEMPORAL_ADDRESS"), TemporalNamespace: get("TEMPORAL_NAMESPACE")}
	c.LetaToken = get("LETA_SERVICE_TOKEN")
	boolean := func(key string) (bool, error) {
		value := get(key)
		if value != "" && value != "true" && value != "false" {
			return false, fmt.Errorf("%s must be true or false", key)
		}
		return value == "true", nil
	}
	var err error
	c.AllowPlaintextRPC, err = boolean("ALLOW_PLAINTEXT_RPC")
	if err != nil {
		return c, err
	}
	if !c.AllowPlaintextRPC && (c.RPCCertificatePath == "" || c.RPCPrivateKeyPath == "") {
		return c, errors.New("RPC TLS certificate and key required")
	}
	if c.AllowPlaintextRPC && (c.RPCCertificatePath != "" || c.RPCPrivateKeyPath != "") {
		return c, errors.New("RPC TLS and plaintext configuration conflict")
	}
	if c.Listen == "" {
		c.Listen = ":8080"
	}
	if c.RPCListen == "" {
		c.RPCListen = ":9090"
	}
	for key, address := range map[string]string{"LISTEN_ADDR": c.Listen, "RPC_LISTEN_ADDR": c.RPCListen, "SPICEDB_ADDRESS": c.SpiceDBAddress, "TEMPORAL_ADDRESS": c.TemporalAddress} {
		host, port, e := net.SplitHostPort(address)
		number, numberErr := strconv.Atoi(port)
		if e != nil || numberErr != nil || number < 1 || number > 65535 || key != "RPC_LISTEN_ADDR" && key != "LISTEN_ADDR" && host == "" {
			return c, fmt.Errorf("invalid %s", key)
		}
	}
	if c.TemporalNamespace == "" || len(c.TemporalNamespace) > 255 || strings.IndexFunc(c.TemporalNamespace, func(r rune) bool { return r <= 32 || r == 127 }) >= 0 {
		return c, errors.New("invalid Temporal namespace")
	}
	u, err := url.Parse(c.DatabaseURL)
	if err != nil || u.Hostname() == "" || u.User == nil || u.Path == "" || u.Path == "/" || (u.Scheme != "postgres" && u.Scheme != "postgresql") {
		return c, errors.New("invalid DATABASE_URL")
	}
	if password, ok := u.User.Password(); !ok || password == "" || u.User.Username() == "" {
		return c, errors.New("DATABASE_URL credentials required")
	}
	seen := map[string]bool{}
	for _, token := range []string{c.GatewayToken, c.WorkspaceToken, c.IngestToken, c.LetaToken, c.SpiceDBKey} {
		if len(token) < 32 || strings.IndexFunc(token, func(r rune) bool {
			return !(r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '-' || r == '_')
		}) >= 0 || seen[token] {
			return c, errors.New("distinct valid service tokens required")
		}
		seen[token] = true
	}
	c.Storage = storage.Config{Endpoint: get("S3_ENDPOINT"), SigningEndpoint: get("S3_SIGNING_ENDPOINT"), Region: get("S3_REGION"), Bucket: get("S3_BUCKET"), AccessKey: get("S3_ACCESS_KEY_ID"), SecretKey: get("S3_SECRET_ACCESS_KEY")}
	c.Storage.AllowHTTP, err = boolean("ALLOW_LOCAL_S3")
	if err != nil {
		return c, err
	}
	if _, err = storage.New(c.Storage); err != nil {
		return c, err
	}
	c.MaxNodes, c.MaxCopyNodes, c.InlineLimit, c.MaxFileBytes = 1000000, 10000, 262144, 104857600
	c.MaxOutstanding, c.MaxCleanupBacklog = 16, 10000
	c.MultipartThreshold, c.MultipartPartBytes = 16777216, 8388608
	c.ProcessingMaxOutputs, c.ProcessingMaxOutputBytes = 512, 268435456
	c.IndexSpace = filesystem.VectorSpace{Model: "openai/text-embedding-3-small", Collection: "files", Dimension: 1536}
	if value := get("OPENROUTER_EMBEDDING_MODEL"); value != "" {
		c.IndexSpace.Model = value
	}
	if value := get("QDRANT_COLLECTION"); value != "" {
		c.IndexSpace.Collection = value
	}
	if value := get("EMBEDDING_DIMENSION"); value != "" {
		dimension, err := strconv.ParseInt(value, 10, 32)
		if err != nil {
			return c, errors.New("invalid EMBEDDING_DIMENSION")
		}
		c.IndexSpace.Dimension = int32(dimension)
	}
	if err = c.IndexSpace.Validate(); err != nil {
		return c, errors.New("invalid vector space configuration")
	}
	c.QdrantURL, c.QdrantKey = get("QDRANT_URL"), get("QDRANT_API_KEY")
	if c.QdrantURL == "" {
		c.QdrantURL = "http://qdrant:6333"
	}
	if _, err = search.New(c.QdrantURL, c.QdrantKey); err != nil {
		return c, errors.New("invalid Qdrant configuration")
	}
	c.AI = search.AIConfig{URL: get("OPENROUTER_URL"), Key: get("OPENROUTER_API_KEY"), RerankModel: get("OPENROUTER_RERANK_MODEL")}
	if c.AI.URL == "" {
		c.AI.URL = "https://openrouter.ai/api/v1"
	}
	if c.AI.RerankModel == "" {
		c.AI.RerankModel = "cohere/rerank-v3.5"
	}
	c.AI.AllowLocal, err = boolean("ALLOW_LOCAL_AI")
	if err != nil {
		return c, err
	}
	if _, err = search.NewAI(c.AI); err != nil {
		return c, errors.New("invalid AI search configuration")
	}
	c.Archive = filesystem.ArchiveConfig{MaxEntries: 10000, MaxSourceBytes: 1073741824, MaxOutputBytes: 1107296256}
	c.ArchiveMaxConcurrent = 2
	archiveRuntime := int64(1200)
	download, upload, grace := int64(300), int64(900), int64(3600)
	for key, target := range map[string]*int64{
		"ARCHIVE_MAX_ENTRIES": &c.Archive.MaxEntries, "ARCHIVE_MAX_SOURCE_BYTES": &c.Archive.MaxSourceBytes,
		"ARCHIVE_MAX_OUTPUT_BYTES": &c.Archive.MaxOutputBytes, "ARCHIVE_MAX_CONCURRENT": &c.ArchiveMaxConcurrent, "ARCHIVE_RUNTIME_SECONDS": &archiveRuntime,
		"MAX_NODES": &c.MaxNodes, "MAX_COPY_NODES": &c.MaxCopyNodes, "INLINE_LIMIT_BYTES": &c.InlineLimit, "MAX_FILE_BYTES": &c.MaxFileBytes,
		"PROCESSING_MAX_OUTPUTS": &c.ProcessingMaxOutputs, "PROCESSING_MAX_OUTPUT_BYTES": &c.ProcessingMaxOutputBytes,
		"MAX_OUTSTANDING_STORAGE": &c.MaxOutstanding, "MAX_CLEANUP_BACKLOG": &c.MaxCleanupBacklog,
		"MULTIPART_THRESHOLD_BYTES": &c.MultipartThreshold, "MULTIPART_PART_BYTES": &c.MultipartPartBytes,
		"DOWNLOAD_URL_TTL_SECONDS": &download, "UPLOAD_URL_TTL_SECONDS": &upload, "UPLOAD_TRANSFER_GRACE_SECONDS": &grace,
	} {
		if value := get(key); value != "" {
			parsed, e := strconv.ParseInt(value, 10, 64)
			if e != nil || parsed <= 0 || key != "MAX_NODES" && parsed > 10000000000 {
				return c, fmt.Errorf("invalid %s", key)
			}
			*target = parsed
		}
	}
	if c.InlineLimit > 1048576 || download > 600 || upload > 3600 || grace > 86400 || c.MultipartPartBytes < 5242880 || c.MultipartPartBytes > 5368709120 || c.MultipartThreshold < c.MultipartPartBytes || c.MaxFileBytes > c.MultipartPartBytes*10000 {
		return c, errors.New("invalid storage limits")
	}
	if c.ArchiveMaxConcurrent > 8 || archiveRuntime > 1800 {
		return c, errors.New("invalid archive resource limits")
	}
	c.Archive.Runtime = time.Duration(archiveRuntime) * time.Second
	if c.Archive.Validate() != nil {
		return c, errors.New("invalid archive resource limits")
	}
	c.DownloadLifetime = time.Duration(download) * time.Second
	c.UploadLifetime = time.Duration(upload) * time.Second
	c.UploadTransferGrace = time.Duration(grace) * time.Second
	return c, nil
}
