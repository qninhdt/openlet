package filesystem

import (
	"bytes"
	"context"
	"math"
	"strings"
	"unicode/utf8"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"github.com/qninhdt/openlet/packages/go/authz"
)

// Creation and an observed existing target are mutually exclusive.
type TextTarget struct {
	Locator     Locator
	Revision    int64
	Fingerprint *string
	Create      *TextCreation
}

type TextCreation struct {
	Key             uuid.UUID
	Parent          Locator
	Name, MediaType string
	NodeID          *uuid.UUID
}

type TextMutationResult struct {
	Stat              FileStat
	BeforeRevision    int64
	BeforeFingerprint string
}

type TextPatch struct {
	Offset     *int64
	OldText    *string
	Content    []byte
	ReplaceAll bool
}

type textMutation struct {
	kind           string
	content        []byte
	offset, length int64
	old            string
	all            bool
}

func invalidText() error {
	return apperr.New(apperr.Invalid, "VALIDATION", "valid UTF-8 text without NUL required")
}
func unsupportedText() error {
	return apperr.New(apperr.Invalid, "NOT_SUPPORTED", "text growth with zero padding is not supported")
}
func textTooLarge() error {
	return apperr.New(apperr.Limit, "REQUEST_LIMIT", "inline content exceeds limit")
}

func (m textMutation) validate(limit int64) error {
	if int64(len(m.content)) > limit {
		return textTooLarge()
	}
	if !utf8.Valid(m.content) || bytes.IndexByte(m.content, 0) >= 0 {
		return invalidText()
	}
	switch m.kind {
	case "write", "append":
	case "offset":
		if m.offset < 0 || m.offset > math.MaxInt64-int64(len(m.content)) {
			return apperr.New(apperr.Invalid, "VALIDATION", "invalid byte offset")
		}
	case "literal":
		if m.old == "" || !utf8.ValidString(m.old) || strings.ContainsRune(m.old, 0) || int64(len(m.old)) > limit {
			return apperr.New(apperr.Invalid, "VALIDATION", "nonempty bounded old text required")
		}
	case "truncate":
		if m.length < 0 {
			return apperr.New(apperr.Invalid, "VALIDATION", "negative text length")
		}
	default:
		return apperr.New(apperr.Invalid, "VALIDATION", "invalid text mutation")
	}
	return nil
}

func (m textMutation) apply(before []byte, limit int64) ([]byte, error) {
	if err := m.validate(limit); err != nil {
		return nil, err
	}
	var body []byte
	size := int64(len(before))
	switch m.kind {
	case "write":
		body = m.content
	case "append":
		if int64(len(m.content)) > limit-size {
			return nil, textTooLarge()
		}
		body = append(bytes.Clone(before), m.content...)
	case "offset":
		if m.offset > size {
			return nil, unsupportedText()
		}
		end := m.offset + int64(len(m.content))
		if max(size, end) > limit {
			return nil, textTooLarge()
		}
		body = make([]byte, max(size, end))
		copy(body, before)
		copy(body[m.offset:], m.content)
	case "literal":
		count := bytes.Count(before, []byte(m.old))
		if count == 0 {
			return nil, apperr.New(apperr.Conflict, "NO_MATCH", "old text not found")
		}
		if count > 1 && !m.all {
			return nil, apperr.New(apperr.Conflict, "AMBIGUOUS_MATCH", "multiple matches require replace_all")
		}
		final := size + int64(count)*int64(len(m.content)-len(m.old))
		if final > limit {
			return nil, textTooLarge()
		}
		body = bytes.ReplaceAll(before, []byte(m.old), m.content)
	case "truncate":
		if m.length > size {
			return nil, unsupportedText()
		}
		body = before[:m.length]
	}
	if !utf8.Valid(body) || bytes.IndexByte(body, 0) >= 0 {
		return nil, invalidText()
	}
	return body, nil
}

func (s *Store) WriteText(ctx context.Context, scope uuid.UUID, target TextTarget, content []byte) (TextMutationResult, error) {
	return s.mutateText(ctx, scope, target, textMutation{kind: "write", content: content})
}
func (s *Store) AppendText(ctx context.Context, scope uuid.UUID, target TextTarget, content []byte) (TextMutationResult, error) {
	return s.mutateText(ctx, scope, target, textMutation{kind: "append", content: content})
}
func (s *Store) PatchText(ctx context.Context, scope uuid.UUID, target TextTarget, patch TextPatch) (TextMutationResult, error) {
	if (patch.Offset == nil) == (patch.OldText == nil) || patch.Offset != nil && patch.ReplaceAll {
		return TextMutationResult{}, apperr.New(apperr.Invalid, "VALIDATION", "exactly one patch kind required")
	}
	m := textMutation{content: patch.Content, all: patch.ReplaceAll}
	if patch.Offset != nil {
		m.kind, m.offset = "offset", *patch.Offset
	} else {
		m.kind, m.old = "literal", *patch.OldText
	}
	return s.mutateText(ctx, scope, target, m)
}
func (s *Store) TruncateText(ctx context.Context, scope uuid.UUID, target TextTarget, length int64, noCreate bool) (TextMutationResult, error) {
	if noCreate && target.Create != nil {
		return TextMutationResult{}, apperr.New(apperr.Missing, "NOT_FOUND", "file required")
	}
	return s.mutateText(ctx, scope, target, textMutation{kind: "truncate", length: length})
}

func (s *Store) mutateText(ctx context.Context, scope uuid.UUID, target TextTarget, m textMutation) (TextMutationResult, error) {
	limit := min(s.InlineLimit, s.MaxFileBytes)
	if err := m.validate(limit); err != nil {
		return TextMutationResult{}, err
	}
	if target.Create != nil {
		if target.Revision != 0 || target.Fingerprint != nil || target.Locator != (Locator{}) {
			return TextMutationResult{}, apperr.New(apperr.Invalid, "VALIDATION", "ambiguous text target")
		}
		if m.kind == "literal" {
			return TextMutationResult{}, apperr.New(apperr.Missing, "NOT_FOUND", "file required")
		}
		body, err := m.apply(nil, limit)
		if err != nil {
			return TextMutationResult{}, err
		}
		c := target.Create
		input := CreateNode{Parent: c.Parent, Name: c.Name, NodeID: c.NodeID, File: &InlineFile{Content: body, MediaType: c.MediaType}}
		// Native text creation does not infer storage from a filename or MIME type.
		node, err := s.createNode(ctx, scope, c.Key, input, true)
		if err != nil {
			return TextMutationResult{}, err
		}
		payload := textPayload(body)
		stat, _, err := representation(fileMetadata{Node: node, Storage: "text", LF: payload.NewlineCount, SHA: payload.SHA256}, nil)
		return TextMutationResult{Stat: stat}, err
	}
	if target.Revision <= 0 {
		return TextMutationResult{}, apperr.New(apperr.Precondition, "PRECONDITION_REQUIRED", "positive observed revision required")
	}
	if target.Fingerprint != nil && (len(*target.Fingerprint) == 0 || len(*target.Fingerprint) > 256) {
		return TextMutationResult{}, apperr.New(apperr.Invalid, "VALIDATION", "invalid fingerprint")
	}
	if _, err := s.authorize(ctx, scope, "scope", authz.ScopeWrite); err != nil {
		return TextMutationResult{}, err
	}
	session, err := s.openSession(ctx, scope, true)
	if err != nil {
		return TextMutationResult{}, err
	}
	defer session.tx.Rollback(ctx)
	node, err := session.resolveOne(ctx, target.Locator)
	if err != nil {
		return TextMutationResult{}, err
	}
	if target.Locator.ExpectedNodeID != nil && *target.Locator.ExpectedNodeID != node.ID {
		return TextMutationResult{}, apperr.New(apperr.Precondition, "TARGET_MISMATCH", "target mismatch")
	}
	if err = guard(target.Locator, node.ID, false); err != nil {
		return TextMutationResult{}, err
	}
	if err = node.writable(); err != nil {
		return TextMutationResult{}, err
	}
	if err = node.revision(&target.Revision); err != nil {
		return TextMutationResult{}, err
	}
	if node.Kind != "file" {
		return TextMutationResult{}, apperr.New(apperr.Conflict, "NOT_FILE", "file required")
	}
	metadata, err := session.metadata(ctx, node)
	if err != nil {
		return TextMutationResult{}, err
	}
	if metadata.Storage != "text" {
		return TextMutationResult{}, apperr.New(apperr.Invalid, "NOT_SUPPORTED", "blob content cannot be edited as text")
	}
	before, _, err := representation(metadata, nil)
	if err != nil {
		return TextMutationResult{}, err
	}
	if target.Fingerprint != nil && *target.Fingerprint != before.Fingerprint {
		return TextMutationResult{}, apperr.New(apperr.Precondition, "CONTENT_CHANGED", "file representation changed")
	}
	var body []byte
	if err = session.tx.QueryRow(ctx, `SELECT convert_to(text_content,'UTF8') FROM files WHERE node_id=$1`, node.ID).Scan(&body); err != nil {
		return TextMutationResult{}, databaseError(err)
	}
	content, err := m.apply(body, limit)
	if err != nil {
		return TextMutationResult{}, err
	}
	if err = session.validateInlineText(content); err != nil {
		return TextMutationResult{}, err
	}
	result := TextMutationResult{Stat: before, BeforeRevision: node.Revision, BeforeFingerprint: before.Fingerprint}
	if bytes.Equal(body, content) {
		return result, nil
	}
	if err = session.usage(ctx, int64(len(content))-node.SizeBytes); err != nil {
		return TextMutationResult{}, err
	}
	if err = session.invalidate(ctx, node.ID); err != nil {
		return TextMutationResult{}, err
	}
	payload := textPayload(content)
	_, err = session.tx.Exec(ctx, `UPDATE files SET text_content=$2,newline_count=$3,text_sha256=$4 WHERE node_id=$1`, node.ID, payload.Text, payload.NewlineCount, payload.SHA256)
	if err != nil {
		return TextMutationResult{}, databaseError(err)
	}
	_, err = session.tx.Exec(ctx, `UPDATE nodes SET size_bytes=$2 WHERE id=$1`, node.ID, len(content))
	if err != nil {
		return TextMutationResult{}, databaseError(err)
	}
	if err = session.bump(ctx, node.ID); err != nil {
		return TextMutationResult{}, err
	}
	node, err = session.fetch(ctx, node.ID)
	if err != nil {
		return TextMutationResult{}, err
	}
	if err = session.recordIntent(ctx, node); err != nil {
		return TextMutationResult{}, err
	}
	result.Stat, _, err = representation(fileMetadata{Node: node, Storage: "text", LF: payload.NewlineCount, SHA: payload.SHA256}, nil)
	if err != nil {
		return TextMutationResult{}, err
	}
	return result, databaseError(session.tx.Commit(ctx))
}
