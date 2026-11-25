package storage

import (
	"context"
	"time"

	az "github.com/authzed/authzed-go/proto/authzed/api/v1"
	authzed "github.com/authzed/authzed-go/v1"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/openai/openai-go/v3"
	"github.com/qdrant/go-client/qdrant"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"go.temporal.io/sdk/client"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

type Settings struct {
	GRPCListen                  string       `yaml:"grpc_listen"`
	GRPCTarget                  string       `yaml:"grpc_target"`
	Database                    sdk.Database `yaml:"database"`
	MaxTextBytes                int64        `yaml:"max_text_bytes"`
	MaxBlobBytes                int64        `yaml:"max_blob_bytes"`
	MultipartThresholdBytes     int64        `yaml:"multipart_threshold_bytes"`
	MultipartPartBytes          int64        `yaml:"multipart_part_bytes"`
	UploadURLTTLSeconds         int          `yaml:"upload_url_ttl_seconds"`
	DownloadURLTTLSeconds       int          `yaml:"download_url_ttl_seconds"`
	IdempotencyRetentionSeconds int          `yaml:"idempotency_retention_seconds"`
	SemanticSearch              struct {
		CandidateLimit uint64 `yaml:"candidate_limit"`
		ResultLimit    uint64 `yaml:"result_limit"`
	} `yaml:"semantic_search"`
	Processing struct {
		MaxArtifacts              int   `yaml:"max_artifacts"`
		MaxManifestTextBytes      int64 `yaml:"max_manifest_text_bytes"`
		MaxArtifactBlobBytes      int64 `yaml:"max_artifact_blob_bytes"`
		ParseTimeoutSeconds       int   `yaml:"parse_timeout_seconds"`
		EnrichIndexTimeoutSeconds int   `yaml:"enrich_index_timeout_seconds"`
	} `yaml:"processing"`
	Maintenance struct {
		IntervalSeconds      int `yaml:"interval_seconds"`
		ObjectGCGraceSeconds int `yaml:"object_gc_grace_seconds"`
	} `yaml:"maintenance"`
}
type Server struct {
	DB                  *pgxpool.Pool
	Graph               *authzed.Client
	S3                  *s3.Client
	Presign             *s3.PresignClient
	ProcessingPresign   *s3.PresignClient
	Bucket              string
	Temporal            client.Client
	Queues              sdk.Queues
	Settings            Settings
	FileTypes           sdk.FileTypes
	Qdrant              *qdrant.Client
	Collection          string
	Models              openai.Client
	EmbeddingModel      string
	EmbeddingDimensions int64
	RerankingModel      string
}

var _ pb.LetFSServiceServer = (*Server)(nil)
var _ pb.LetFSInternalServiceServer = (*Server)(nil)

type queryer interface {
	Query(context.Context, string, ...any) (pgx.Rows, error)
	QueryRow(context.Context, string, ...any) pgx.Row
	Exec(context.Context, string, ...any) (pgconn.CommandTag, error)
}

func permissionDenied() error {
	return status.Error(codes.PermissionDenied, "storage permission denied")
}
func invalid(message string) error { return status.Error(codes.InvalidArgument, message) }
func notFound() error {
	return status.Error(codes.NotFound, "node not found within live storage/mount")
}
func conflict(message string) error { return status.Error(codes.Aborted, message) }
func (s *Server) check(ctx context.Context, kind, id, permission string) (sdk.Actor, error) {
	a, err := sdk.ActorFromContext(ctx)
	if err != nil {
		return a, err
	}
	r, err := s.Graph.CheckPermission(ctx, &az.CheckPermissionRequest{Resource: sdk.Object(kind, id), Permission: permission, Subject: sdk.Subject(a), Consistency: sdk.Consistency(ctx)})
	if err != nil {
		return a, err
	}
	if r.Permissionship != az.CheckPermissionResponse_PERMISSIONSHIP_HAS_PERMISSION {
		return a, permissionDenied()
	}
	return a, nil
}
func (s *Server) quota(ctx context.Context, tx pgx.Tx, workspace string, delta int64) error {
	if delta == 0 {
		return nil
	}
	tag, err := tx.Exec(ctx, `UPDATE workspace_storage SET used_bytes=used_bytes+$2 WHERE workspace_id=$1 AND used_bytes+$2 BETWEEN 0 AND quota_bytes`, workspace, delta)
	if err != nil {
		return err
	}
	if tag.RowsAffected() != 1 {
		return status.Error(codes.ResourceExhausted, "workspace storage quota exceeded")
	}
	return nil
}
func (s *Server) ttl() time.Duration {
	return time.Duration(s.Settings.IdempotencyRetentionSeconds) * time.Second
}
func pageSize(n int32) int {
	if n == 0 {
		return 50
	}
	return int(n)
}
func nilString(v string) any {
	if v == "" {
		return nil
	}
	return v
}
func writable(r resolved) error {
	if r.Node.Readonly {
		return status.Error(codes.FailedPrecondition, "generated artifacts are readonly")
	}
	return nil
}
func directory(r resolved) error {
	if err := writable(r); err != nil {
		return err
	}
	if r.Node.Kind != pb.NodeKind_NODE_KIND_DIRECTORY {
		return status.Error(codes.FailedPrecondition, "parent must be a directory")
	}
	return nil
}
