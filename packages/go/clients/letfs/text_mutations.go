package letfs

import (
	"context"
	"unicode/utf8"

	"github.com/google/uuid"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/rpc"
)

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

func nativeTextTarget(value TextTarget) (*letfsv1.TextTarget, error) {
	if value.Create != nil {
		if value.Locator != (Locator{}) || value.Revision != 0 || value.Fingerprint != nil {
			return nil, scopeError()
		}
		c := value.Create
		parent, err := nativeLocator(c.Parent)
		if err != nil {
			return nil, err
		}
		var id *string
		if c.NodeID != nil {
			v := c.NodeID.String()
			id = &v
		}
		return &letfsv1.TextTarget{Target: &letfsv1.TextTarget_Create{Create: &letfsv1.TextCreation{Parent: parent, Name: c.Name, MediaType: c.MediaType, IdempotencyKey: c.Key.String(), NodeId: id}}}, nil
	}
	loc, err := nativeLocator(value.Locator)
	if err != nil {
		return nil, err
	}
	return &letfsv1.TextTarget{Target: &letfsv1.TextTarget_Existing{Existing: &letfsv1.ExistingText{Locator: loc, Revision: value.Revision, ExpectedFingerprint: value.Fingerprint}}}, nil
}

func nativeTextMutation(value *letfsv1.TextMutation, scope uuid.UUID, target TextTarget) (TextMutationResult, error) {
	if value == nil {
		return TextMutationResult{}, scopeError()
	}
	var loc *Locator
	if target.Create == nil {
		loc = &target.Locator
	}
	stat, err := nativeStat(value.Stat, scope, loc)
	if err != nil {
		return TextMutationResult{}, err
	}
	if stat.StorageKind != "text" || stat.RepresentationKind != "text" || stat.NewlineCount == nil || stat.SHA256 == nil {
		return TextMutationResult{}, scopeError()
	}
	if target.Create != nil {
		if value.BeforeRevision != 0 || value.BeforeFingerprint != "" || target.Create.NodeID != nil && stat.Node.ID != *target.Create.NodeID {
			return TextMutationResult{}, scopeError()
		}
	} else if value.BeforeRevision != target.Revision || value.BeforeFingerprint == "" || stat.Node.Revision < target.Revision || target.Fingerprint != nil && value.BeforeFingerprint != *target.Fingerprint {
		return TextMutationResult{}, scopeError()
	}
	return TextMutationResult{Stat: stat, BeforeRevision: value.BeforeRevision, BeforeFingerprint: value.BeforeFingerprint}, nil
}

func (c FilesystemClient) WriteText(ctx context.Context, fs, scope uuid.UUID, target TextTarget, content []byte) (TextMutationResult, error) {
	t, err := nativeTextTarget(target)
	if err != nil {
		return TextMutationResult{}, err
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.WriteText(ctx, &letfsv1.WriteTextRequest{FilesystemId: fs.String(), ScopeId: scope.String(), Target: t, Content: content})
	if err != nil {
		return TextMutationResult{}, rpc.DecodeError(err)
	}
	return nativeTextMutation(response.GetResult(), scope, target)
}
func (c FilesystemClient) AppendText(ctx context.Context, fs, scope uuid.UUID, target TextTarget, content []byte) (TextMutationResult, error) {
	t, err := nativeTextTarget(target)
	if err != nil {
		return TextMutationResult{}, err
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.AppendText(ctx, &letfsv1.AppendTextRequest{FilesystemId: fs.String(), ScopeId: scope.String(), Target: t, Content: content})
	if err != nil {
		return TextMutationResult{}, rpc.DecodeError(err)
	}
	return nativeTextMutation(response.GetResult(), scope, target)
}
func (c FilesystemClient) PatchText(ctx context.Context, fs, scope uuid.UUID, target TextTarget, patch TextPatch) (TextMutationResult, error) {
	t, err := nativeTextTarget(target)
	if err != nil {
		return TextMutationResult{}, err
	}
	request := &letfsv1.PatchTextRequest{FilesystemId: fs.String(), ScopeId: scope.String(), Target: t}
	if (patch.Offset == nil) == (patch.OldText == nil) || patch.Offset != nil && patch.ReplaceAll {
		return TextMutationResult{}, scopeError()
	}
	if patch.Offset != nil {
		request.Patch = &letfsv1.PatchTextRequest_Bytes{Bytes: &letfsv1.ByteOverwrite{Offset: *patch.Offset, Content: patch.Content}}
	} else {
		if !utf8.Valid(patch.Content) {
			return TextMutationResult{}, scopeError()
		}
		request.Patch = &letfsv1.PatchTextRequest_Literal{Literal: &letfsv1.LiteralReplacement{OldText: *patch.OldText, NewText: string(patch.Content), ReplaceAll: patch.ReplaceAll}}
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.PatchText(ctx, request)
	if err != nil {
		return TextMutationResult{}, rpc.DecodeError(err)
	}
	return nativeTextMutation(response.GetResult(), scope, target)
}
func (c FilesystemClient) TruncateText(ctx context.Context, fs, scope uuid.UUID, target TextTarget, length int64, noCreate bool) (TextMutationResult, error) {
	t, err := nativeTextTarget(target)
	if err != nil {
		return TextMutationResult{}, err
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.TruncateText(ctx, &letfsv1.TruncateTextRequest{FilesystemId: fs.String(), ScopeId: scope.String(), Target: t, Length: length, NoCreate: noCreate})
	if err != nil {
		return TextMutationResult{}, rpc.DecodeError(err)
	}
	return nativeTextMutation(response.GetResult(), scope, target)
}
