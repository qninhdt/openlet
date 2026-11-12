package storage

import (
	"context"
	"sort"
	"strings"
	"time"
	"unicode/utf8"

	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"
)

func (s *Server) validateText(text string) error {
	if !utf8.ValidString(text) || strings.ContainsRune(text, 0) {
		return invalid("text must be UTF-8 without NUL")
	}
	if int64(len(text)) > s.Settings.MaxTextBytes {
		return status.Error(codes.ResourceExhausted, "text exceeds configured limit")
	}
	return nil
}
func textLines(text string) []string {
	if text == "" {
		return nil
	}
	lines := strings.SplitAfter(text, "\n")
	if lines[len(lines)-1] == "" {
		lines = lines[:len(lines)-1]
	}
	return lines
}
func selectText(text string, r *pb.ReadTextRequest) (string, error) {
	lines := textLines(text)
	switch v := r.Selection.(type) {
	case *pb.ReadTextRequest_Bytes:
		start, end := min(v.Bytes.Offset, int64(len(text))), int64(len(text))
		if v.Bytes.Length != nil {
			end = start + min(*v.Bytes.Length, end-start)
		}
		part := text[start:end]
		if !utf8.ValidString(part) {
			return "", invalid("byte range splits a UTF-8 character")
		}
		return part, nil
	case *pb.ReadTextRequest_Lines:
		start := min(int(v.Lines.First)-1, len(lines))
		end := start + min(int(v.Lines.Count), len(lines)-start)
		return strings.Join(lines[start:end], ""), nil
	case *pb.ReadTextRequest_HeadLines:
		n := min(int(v.HeadLines), len(lines))
		return strings.Join(lines[:n], ""), nil
	case *pb.ReadTextRequest_TailLines:
		n := min(int(v.TailLines), len(lines))
		return strings.Join(lines[len(lines)-n:], ""), nil
	default:
		return text, nil
	}
}
func (s *Server) ReadText(ctx context.Context, r *pb.ReadTextRequest) (*pb.ReadTextResponse, error) {
	if _, err := s.check(ctx, "storage", r.StorageId, "read"); err != nil {
		return nil, err
	}
	v, err := oneResolved(ctx, s.DB, r.WorkspaceId, r.StorageId, r.Target, true, false)
	if err != nil {
		return nil, err
	}
	if v.Text == nil {
		return nil, status.Error(codes.FailedPrecondition, "node is not a text file")
	}
	content, err := selectText(*v.Text, r)
	if err != nil {
		return nil, err
	}
	out := &pb.ReadTextResponse{Content: content, Version: v.Node.File.Version}
	if r.IncludeMetrics {
		out.Metrics = &pb.TextMetrics{Bytes: int64(len(*v.Text)), Lines: int64(len(textLines(*v.Text)))}
	}
	return out, nil
}
func applyText(text string, r *pb.MutateTextRequest) (string, error) {
	switch m := r.Mutation.(type) {
	case *pb.MutateTextRequest_Replace:
		return m.Replace, nil
	case *pb.MutateTextRequest_Append:
		return text + m.Append, nil
	case *pb.MutateTextRequest_Overwrite:
		if m.Overwrite.Offset > int64(len(text)) {
			return "", invalid("overwrite cannot create a hole")
		}
		end := m.Overwrite.Offset + min(int64(len(m.Overwrite.Content)), int64(len(text))-m.Overwrite.Offset)
		out := text[:m.Overwrite.Offset] + m.Overwrite.Content + text[end:]
		if !utf8.ValidString(out) {
			return "", invalid("overwrite splits a UTF-8 character")
		}
		return out, nil
	case *pb.MutateTextRequest_LiteralReplace:
		n := strings.Count(text, m.LiteralReplace.OldText)
		if n == 0 || (n > 1 && !m.LiteralReplace.ReplaceAll) {
			return "", conflict("replacement must match once, or set replace_all")
		}
		return strings.ReplaceAll(text, m.LiteralReplace.OldText, m.LiteralReplace.NewText), nil
	case *pb.MutateTextRequest_TruncateBytes:
		if m.TruncateBytes < 0 || m.TruncateBytes > int64(len(text)) {
			return "", invalid("truncate size is outside text")
		}
		out := text[:m.TruncateBytes]
		if !utf8.ValidString(out) {
			return "", invalid("truncate splits UTF-8 character")
		}
		return out, nil
	case *pb.MutateTextRequest_Patch:
		edits := append([]*pb.TextEdit(nil), m.Patch.Edits...)
		sort.SliceStable(edits, func(i, j int) bool { return edits[i].StartByte < edits[j].StartByte })
		var b strings.Builder
		var last int64
		for _, edit := range edits {
			if edit.StartByte < last || edit.EndByte < edit.StartByte || edit.EndByte > int64(len(text)) {
				return "", invalid("patch edits overlap or exceed text")
			}
			prefix := text[last:edit.StartByte]
			if !utf8.ValidString(prefix) || !utf8.ValidString(text[edit.StartByte:edit.EndByte]) {
				return "", invalid("patch splits UTF-8 character")
			}
			b.WriteString(prefix)
			b.WriteString(edit.Replacement)
			last = edit.EndByte
		}
		b.WriteString(text[last:])
		return b.String(), nil
	default:
		return "", invalid("text mutation is required")
	}
}
func (s *Server) MutateText(ctx context.Context, r *pb.MutateTextRequest) (*pb.Node, error) {
	a, err := s.check(ctx, "storage", r.StorageId, "write")
	if err != nil {
		return nil, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	out := new(pb.Node)
	duplicate, err := sdk.Claim(ctx, tx, a.String(), "MutateText", r.RequestId, r, out, s.ttl())
	if err != nil {
		return nil, err
	}
	if duplicate {
		return out, tx.Commit(ctx)
	}
	current, err := oneResolved(ctx, tx, r.WorkspaceId, r.StorageId, r.Target, true, true)
	if err != nil {
		return nil, err
	}
	if err = writable(current); err != nil {
		return nil, err
	}
	if current.Text == nil {
		return nil, status.Error(codes.FailedPrecondition, "node is not a text file")
	}
	if r.ExpectedVersion != nil && *r.ExpectedVersion != current.Node.File.Version {
		return nil, conflict("content version changed")
	}
	text, err := applyText(*current.Text, r)
	if err != nil {
		return nil, err
	}
	if err = s.validateText(text); err != nil {
		return nil, err
	}
	out = current.Node
	if text != *current.Text {
		var updated time.Time
		err = tx.QueryRow(ctx, `WITH changed AS (UPDATE files SET text_content=$2,size_bytes=octet_length($2),version=version+1 WHERE node_id=$1 RETURNING version,size_bytes),touched AS (UPDATE nodes SET updated_at=now() WHERE id=$1 RETURNING updated_at) SELECT c.version,c.size_bytes,t.updated_at FROM changed c CROSS JOIN touched t`, out.Id, text).Scan(&out.File.Version, &out.File.SizeBytes, &updated)
		if err != nil {
			return nil, err
		}
		out.UpdatedAt = timestamppb.New(updated)
		if err = s.quota(ctx, tx, r.WorkspaceId, int64(len(text)-len(*current.Text))); err != nil {
			return nil, err
		}
	}
	if err = sdk.Finish(ctx, tx, a.String(), "MutateText", r.RequestId, out); err != nil {
		return nil, err
	}
	return out, tx.Commit(ctx)
}
