package filesystem

import (
	"context"
	"strconv"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/rpc"
	"google.golang.org/grpc/codes"
)

type Download struct {
	MIME, Filename, ETag string
	SizeBytes            int64
	InlineContent        []byte
	SignedURL            string
}

func (s *Store) GetDownload(ctx context.Context, fs uuid.UUID, mounts []Mount, id uuid.UUID, revision *int64) (Download, error) {
	if _, err := s.authorize(ctx, fs, "filesystem", authz.ContentRead); err != nil {
		return Download{}, err
	}
	session, err := s.openSession(ctx, fs, false)
	if err != nil {
		return Download{}, err
	}
	defer session.tx.Rollback(ctx)
	node, err := session.resolveOne(ctx, mounts, Locator{NodeID: &id})
	if err != nil {
		return Download{}, err
	}
	if node.Kind != "file" {
		return Download{}, rpc.Fault(codes.Aborted, "NOT_FILE", "file required")
	}
	if revision != nil {
		if err := node.revision(revision); err != nil {
			return Download{}, err
		}
	}
	result := Download{MIME: "application/octet-stream", Filename: node.Name, ETag: `"` + strconv.FormatInt(node.Revision, 10) + `"`, SizeBytes: node.SizeBytes}
	if node.MediaType != nil {
		result.MIME = *node.MediaType
	}
	var kind string
	var key *string
	err = session.tx.QueryRow(ctx, `SELECT storage_kind,inline_bytes,object_key FROM files WHERE node_id=$1`, node.ID).
		Scan(&kind, &result.InlineContent, &key)
	if err != nil {
		return Download{}, databaseError(err)
	}
	switch kind {
	case "inline":
		if result.InlineContent == nil || int64(len(result.InlineContent)) != result.SizeBytes {
			return Download{}, rpc.Fault(codes.Internal, "INTERNAL", "invalid stored content")
		}
	case "object":
		if key == nil || s.Storage == nil {
			return Download{}, rpc.Fault(codes.Unavailable, "DEPENDENCY_UNAVAILABLE", "object storage unavailable")
		}
	default:
		return Download{}, rpc.Fault(codes.Unavailable, "DEPENDENCY_UNAVAILABLE", "object storage unavailable")
	}
	// Sign only after closing the metadata snapshot; storage never holds a SQL transaction.
	if err = session.tx.Commit(ctx); err != nil {
		return Download{}, databaseError(err)
	}
	if kind == "object" {
		result.SignedURL, err = s.Storage.DownloadURL(ctx, *key, result.Filename, s.DownloadLifetime)
		if err != nil {
			if contextErr := ctx.Err(); contextErr != nil {
				return Download{}, contextErr
			}
			return Download{}, rpc.Fault(codes.Unavailable, "DEPENDENCY_UNAVAILABLE", "object storage unavailable")
		}
	}
	return result, nil
}
