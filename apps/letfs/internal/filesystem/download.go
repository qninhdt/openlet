package filesystem

import (
	"context"
	"strconv"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"github.com/qninhdt/openlet/packages/go/authz"
)

type Download struct {
	MIME, Filename, ETag string
	SizeBytes            int64
	InlineContent        []byte
	SignedURL            string
}

func (s *Store) GetDownload(ctx context.Context, scopeID uuid.UUID, id uuid.UUID, revision *int64) (Download, error) {
	if _, err := s.authorize(ctx, scopeID, "scope", authz.ScopeReadContent); err != nil {
		return Download{}, err
	}
	session, err := s.openSession(ctx, scopeID, false)
	if err != nil {
		return Download{}, err
	}
	defer session.tx.Rollback(ctx)
	node, err := session.resolveOne(ctx, Locator{NodeID: &id})
	if err != nil {
		return Download{}, err
	}
	if node.Kind != "file" {
		return Download{}, apperr.New(apperr.Conflict, "NOT_FILE", "file required")
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
			return Download{}, apperr.New(apperr.Internal, "INTERNAL", "invalid stored content")
		}
	case "object":
		if key == nil || s.Storage == nil {
			return Download{}, apperr.New(apperr.Unavailable, "DEPENDENCY_UNAVAILABLE", "object storage unavailable")
		}
	default:
		return Download{}, apperr.New(apperr.Unavailable, "DEPENDENCY_UNAVAILABLE", "object storage unavailable")
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
			return Download{}, apperr.New(apperr.Unavailable, "DEPENDENCY_UNAVAILABLE", "object storage unavailable")
		}
	}
	return result, nil
}
