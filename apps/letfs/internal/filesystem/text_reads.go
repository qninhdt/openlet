package filesystem

import (
	"bytes"
	"context"
	"crypto/md5"
	"crypto/sha1"
	"crypto/sha512"
	"encoding/hex"
	"hash"
	"math"
	"strings"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"github.com/qninhdt/openlet/packages/go/authz"
)

type TextSelection struct {
	Kind      string
	Offset    int64
	Length    *int64
	StartLine int64
	LineCount int64
}

type TextRead struct {
	Stat           FileStat
	Content        []byte
	Offset, Length int64
}

func (v TextSelection) validate() error {
	invalid := apperr.New(apperr.Invalid, "VALIDATION", "invalid text selection")
	switch v.Kind {
	case "whole":
	case "bytes":
		if v.Offset < 0 || v.Length != nil && (*v.Length < 0 || *v.Length > math.MaxInt64-v.Offset) {
			return invalid
		}
	case "lines":
		if v.StartLine < 1 || v.LineCount < 0 || v.LineCount > math.MaxInt64-v.StartLine {
			return invalid
		}
	case "head", "tail":
		if v.LineCount < 0 {
			return invalid
		}
	default:
		return invalid
	}
	return nil
}

func selectText(body []byte, v TextSelection) (content []byte, offset int64) {
	n := int64(len(body))
	switch v.Kind {
	case "bytes":
		start := min(v.Offset, n)
		end := n
		if v.Length != nil {
			end = min(start+*v.Length, n)
		}
		return body[start:end], start
	case "head", "lines":
		line := int64(1)
		if v.Kind == "lines" {
			line = v.StartLine
		}
		start := 0
		for i := int64(1); i < line && start < len(body); i++ {
			at := bytes.IndexByte(body[start:], '\n')
			if at < 0 {
				start = len(body)
			} else {
				start += at + 1
			}
		}
		end := start
		for i := int64(0); i < v.LineCount && end < len(body); i++ {
			at := bytes.IndexByte(body[end:], '\n')
			if at < 0 {
				end = len(body)
			} else {
				end += at + 1
			}
		}
		return body[start:end], int64(start)
	case "tail":
		if v.LineCount == 0 {
			return body[len(body):], n
		}
		end := len(body)
		if end > 0 && body[end-1] == '\n' {
			end--
		}
		start := 0
		for i := int64(0); i < v.LineCount; i++ {
			at := bytes.LastIndexByte(body[:end], '\n')
			if at < 0 {
				start = 0
				break
			}
			start = at + 1
			end = at
		}
		return body[start:], int64(start)
	default:
		return body, 0
	}
}

func (s *Store) ReadText(ctx context.Context, scopeID uuid.UUID, locator Locator, selection TextSelection, expected *string) (TextRead, error) {
	if err := selection.validate(); err != nil {
		return TextRead{}, err
	}
	if expected != nil && (len(*expected) == 0 || len(*expected) > 256) {
		return TextRead{}, apperr.New(apperr.Invalid, "VALIDATION", "invalid fingerprint")
	}
	if _, err := s.authorize(ctx, scopeID, "scope", authz.ScopeReadContent); err != nil {
		return TextRead{}, err
	}
	session, err := s.openSession(ctx, scopeID, false)
	if err != nil {
		return TextRead{}, err
	}
	defer session.tx.Rollback(ctx)
	node, err := session.resolveOne(ctx, locator)
	if err != nil {
		return TextRead{}, err
	}
	if locator.ExpectedNodeID != nil && *locator.ExpectedNodeID != node.ID {
		return TextRead{}, apperr.New(apperr.Conflict, "TARGET_MISMATCH", "target mismatch")
	}
	if node.Kind != "file" {
		return TextRead{}, apperr.New(apperr.Conflict, "NOT_FILE", "file required")
	}
	stat, body, err := session.fileRepresentation(ctx, node)
	if err != nil {
		return TextRead{}, err
	}
	if expected != nil && *expected != stat.Fingerprint {
		return TextRead{}, apperr.New(apperr.Conflict, "CONTENT_CHANGED", "file representation changed")
	}
	if stat.StorageKind == "text" {
		err = session.tx.QueryRow(ctx, `SELECT convert_to(text_content,'UTF8') FROM files WHERE node_id=$1`, node.ID).Scan(&body)
		if err != nil {
			return TextRead{}, databaseError(err)
		}
	}
	if int64(len(body)) != stat.ReadableSize || len(body) > MaxReadBytes {
		return TextRead{}, readLimit()
	}
	content, offset := selectText(body, selection)
	return TextRead{Stat: stat, Content: content, Offset: offset, Length: int64(len(content))}, nil
}

type TextMetric struct {
	Stat              FileStat
	Algorithm, Digest string
	Supported         bool
}

func (s *Store) TextMetrics(ctx context.Context, scopeID uuid.UUID, locator Locator, algorithm string) (TextMetric, error) {
	if len(algorithm) > 32 {
		return TextMetric{}, apperr.New(apperr.Invalid, "VALIDATION", "invalid digest algorithm")
	}
	result := TextMetric{Algorithm: strings.ToLower(algorithm)}
	var h hash.Hash
	switch result.Algorithm {
	case "md5":
		h = md5.New()
	case "sha1":
		h = sha1.New()
	case "sha256":
		// The maintained representation digest needs no TEXT payload read.
	case "sha384":
		h = sha512.New384()
	case "sha512":
		h = sha512.New()
	}
	if h == nil {
		stat, err := s.Stat(ctx, scopeID, locator, true)
		if err != nil {
			return TextMetric{}, err
		}
		if stat.Node.Kind != "file" {
			return TextMetric{}, apperr.New(apperr.Conflict, "NOT_FILE", "file required")
		}
		result.Stat = stat
		if result.Algorithm == "sha256" && stat.SHA256 != nil {
			result.Digest, result.Supported = *stat.SHA256, true
		}
		return result, nil
	}
	read, err := s.ReadText(ctx, scopeID, locator, TextSelection{Kind: "whole"}, nil)
	if err != nil {
		return TextMetric{}, err
	}
	result.Stat = read.Stat
	_, _ = h.Write(read.Content)
	result.Digest = hex.EncodeToString(h.Sum(nil))
	result.Supported = true
	return result, nil
}
