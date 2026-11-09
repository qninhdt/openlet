package grpc

import (
	"context"

	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	"github.com/qninhdt/openlet/packages/go/apperr"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
)

func textTargetInput(input *letfsv1.TextTarget) (filesystem.TextTarget, error) {
	var result filesystem.TextTarget
	switch v := input.GetTarget().(type) {
	case *letfsv1.TextTarget_Existing:
		if v.Existing == nil {
			break
		}
		locator, err := locatorInput(v.Existing.Locator)
		if err != nil {
			return result, err
		}
		return filesystem.TextTarget{Locator: locator, Revision: v.Existing.Revision, Fingerprint: v.Existing.ExpectedFingerprint}, nil
	case *letfsv1.TextTarget_Create:
		if v.Create == nil {
			break
		}
		parent, err := locatorInput(v.Create.Parent)
		if err != nil {
			return result, err
		}
		key, err := parseID(v.Create.IdempotencyKey)
		if err != nil {
			return result, err
		}
		id, err := optionalID(v.Create.NodeId)
		if err != nil {
			return result, err
		}
		result.Create = &filesystem.TextCreation{Key: key, Parent: parent, Name: v.Create.Name, MediaType: v.Create.MediaType, NodeID: id}
		return result, nil
	}
	return result, apperr.New(apperr.Invalid, "VALIDATION", "text target required")
}

func textMutationMessage(value filesystem.TextMutationResult) *letfsv1.TextMutation {
	return &letfsv1.TextMutation{Stat: statMessage(value.Stat), BeforeRevision: value.BeforeRevision, BeforeFingerprint: value.BeforeFingerprint}
}

func (s *Filesystem) WriteText(ctx context.Context, input *letfsv1.WriteTextRequest) (*letfsv1.WriteTextResponse, error) {
	scope, err := s.scopeInput(ctx, input.GetFilesystemId(), input.GetScopeId())
	if err != nil {
		return nil, err
	}
	target, err := textTargetInput(input.GetTarget())
	if err != nil {
		return nil, err
	}
	result, err := s.Service.WriteText(ctx, scope, target, input.Content)
	if err != nil {
		return nil, err
	}
	return &letfsv1.WriteTextResponse{Result: textMutationMessage(result)}, nil
}
func (s *Filesystem) AppendText(ctx context.Context, input *letfsv1.AppendTextRequest) (*letfsv1.AppendTextResponse, error) {
	scope, err := s.scopeInput(ctx, input.GetFilesystemId(), input.GetScopeId())
	if err != nil {
		return nil, err
	}
	target, err := textTargetInput(input.GetTarget())
	if err != nil {
		return nil, err
	}
	result, err := s.Service.AppendText(ctx, scope, target, input.Content)
	if err != nil {
		return nil, err
	}
	return &letfsv1.AppendTextResponse{Result: textMutationMessage(result)}, nil
}
func (s *Filesystem) PatchText(ctx context.Context, input *letfsv1.PatchTextRequest) (*letfsv1.PatchTextResponse, error) {
	scope, err := s.scopeInput(ctx, input.GetFilesystemId(), input.GetScopeId())
	if err != nil {
		return nil, err
	}
	target, err := textTargetInput(input.GetTarget())
	if err != nil {
		return nil, err
	}
	var patch filesystem.TextPatch
	switch v := input.Patch.(type) {
	case *letfsv1.PatchTextRequest_Bytes:
		if v.Bytes != nil {
			patch.Offset = &v.Bytes.Offset
			patch.Content = v.Bytes.Content
		}
	case *letfsv1.PatchTextRequest_Literal:
		if v.Literal != nil {
			patch.OldText = &v.Literal.OldText
			patch.Content = []byte(v.Literal.NewText)
			patch.ReplaceAll = v.Literal.ReplaceAll
		}
	}
	result, err := s.Service.PatchText(ctx, scope, target, patch)
	if err != nil {
		return nil, err
	}
	return &letfsv1.PatchTextResponse{Result: textMutationMessage(result)}, nil
}
func (s *Filesystem) TruncateText(ctx context.Context, input *letfsv1.TruncateTextRequest) (*letfsv1.TruncateTextResponse, error) {
	scope, err := s.scopeInput(ctx, input.GetFilesystemId(), input.GetScopeId())
	if err != nil {
		return nil, err
	}
	target, err := textTargetInput(input.GetTarget())
	if err != nil {
		return nil, err
	}
	result, err := s.Service.TruncateText(ctx, scope, target, input.Length, input.NoCreate)
	if err != nil {
		return nil, err
	}
	return &letfsv1.TruncateTextResponse{Result: textMutationMessage(result)}, nil
}
