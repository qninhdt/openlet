package grpc

import (
	"context"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/identity"
	"github.com/qninhdt/openlet/packages/go/rpc"
	"google.golang.org/grpc/codes"
)

type Ingest struct {
	letfsv1.UnimplementedIngestServiceServer
	Store *filesystem.Store
}

func processingGenerationInput(ctx context.Context, input *letfsv1.ProcessingGeneration) (filesystem.Generation, error) {
	if err := ingestAuthority(ctx); err != nil {
		return filesystem.Generation{}, err
	}
	id, err := parseID(input.GetFileId())
	if err != nil {
		return filesystem.Generation{}, err
	}
	if input.GetGeneration() <= 0 {
		return filesystem.Generation{}, rpc.Fault(codes.InvalidArgument, "VALIDATION", "invalid processing generation")
	}
	return filesystem.Generation{FileID: id, Generation: input.Generation}, nil
}

func (s *Ingest) PrepareIndex(ctx context.Context, input *letfsv1.PrepareIndexRequest) (*letfsv1.PrepareIndexResponse, error) {
	source, err := processingGenerationInput(ctx, input.GetSource())
	if err != nil {
		return nil, err
	}
	value, err := s.Store.PrepareIndex(ctx, source)
	if err != nil {
		return nil, err
	}
	if value.Complete {
		return &letfsv1.PrepareIndexResponse{Result: &letfsv1.PrepareIndexResponse_Complete{Complete: &letfsv1.IndexComplete{SourceId: source.FileID.String()}}}, nil
	}
	result := &letfsv1.IndexInput{FilesystemId: value.FilesystemID.String(), ScopeId: value.ScopeID.String(), SourceId: source.FileID.String(), Generation: source.Generation,
		Nodes: inventoryMessages(value.Nodes), VectorSpace: &letfsv1.VectorSpace{Model: value.VectorSpace.Model, Collection: value.VectorSpace.Collection, Dimension: value.VectorSpace.Dimension}, MaxOutputBytes: s.Store.ProcessingMaxOutputBytes}
	return &letfsv1.PrepareIndexResponse{Result: &letfsv1.PrepareIndexResponse_Input{Input: result}}, nil
}

func (s *Ingest) CompleteIndex(ctx context.Context, input *letfsv1.CompleteIndexRequest) (*letfsv1.CompleteIndexResponse, error) {
	source, err := processingGenerationInput(ctx, input.GetSource())
	if err != nil {
		return nil, err
	}
	if err = s.Store.CompleteIndex(ctx, source); err != nil {
		return nil, err
	}
	return &letfsv1.CompleteIndexResponse{SourceId: source.FileID.String()}, nil
}

func (s *Ingest) FailIndex(ctx context.Context, input *letfsv1.FailIndexRequest) (*letfsv1.FailIndexResponse, error) {
	source, err := processingGenerationInput(ctx, input.GetSource())
	if err != nil {
		return nil, err
	}
	if err = s.Store.FailIndex(ctx, source, input.GetErrorCode()); err != nil {
		return nil, err
	}
	return &letfsv1.FailIndexResponse{}, nil
}

func ingestAuthority(ctx context.Context) error {
	p, ok := identity.FromContext(ctx)
	if !ok || p.Gateway || p.Service != "ingest" {
		return rpc.Fault(codes.PermissionDenied, "FORBIDDEN", "ingest service authority required")
	}
	return nil
}

func outputScopeInput(ctx context.Context, input *letfsv1.OutputUploadScope) (filesystem.OutputScope, error) {
	a, err := processingGenerationInput(ctx, input.GetSource())
	if err != nil {
		return filesystem.OutputScope{}, err
	}
	id, err := parseID(input.GetUploadId())
	if err != nil {
		return filesystem.OutputScope{}, err
	}
	if input.GetStage() != "parse" && input.GetStage() != "enrichment" {
		return filesystem.OutputScope{}, rpc.Fault(codes.InvalidArgument, "VALIDATION", "invalid output stage")
	}
	return filesystem.OutputScope{Source: a, UploadID: id, Stage: input.Stage}, nil
}

func outputDescriptionInput(input *letfsv1.OutputDescription) (filesystem.ProcessingOutput, error) {
	if input == nil {
		return filesystem.ProcessingOutput{}, rpc.Fault(codes.InvalidArgument, "VALIDATION", "output description required")
	}
	return filesystem.ProcessingOutput{Path: input.Path, Storage: input.Storage, SizeBytes: input.SizeBytes, ContentMD5: input.ContentMd5}, nil
}

func outputReceiptMessage(value filesystem.Upload) *letfsv1.UploadReceipt {
	return &letfsv1.UploadReceipt{Id: value.ID.String(), Status: value.State, SizeBytes: value.SizeBytes}
}

func outputUploadMessage(value filesystem.Upload) *letfsv1.Upload {
	result := uploadMessage(value)
	if value.State == "finalized" {
		result.Result = &letfsv1.Upload_Receipt{Receipt: outputReceiptMessage(value)}
	}
	return result
}

func (s *Ingest) PrepareParse(ctx context.Context, input *letfsv1.PrepareParseRequest) (*letfsv1.PrepareParseResponse, error) {
	a, err := processingGenerationInput(ctx, &letfsv1.ProcessingGeneration{FileId: input.GetFileId(), Generation: input.GetGeneration()})
	if err != nil {
		return nil, err
	}
	value, err := s.Store.PrepareParse(ctx, a)
	if err != nil {
		return nil, err
	}
	if value.Complete {
		return &letfsv1.PrepareParseResponse{Result: &letfsv1.PrepareParseResponse_Complete{Complete: &letfsv1.ParseComplete{SourceId: value.SourceID.String()}}}, nil
	}
	result := &letfsv1.ParseInput{SourceId: value.SourceID.String(), Format: value.Format, SizeBytes: value.SizeBytes, InlineLimitBytes: s.Store.InlineLimit, MultipartThresholdBytes: s.Store.MultipartThreshold, MaxOutputs: s.Store.ProcessingMaxOutputs, MaxOutputBytes: s.Store.ProcessingMaxOutputBytes}
	if value.SignedURL != "" {
		result.Source = &letfsv1.ParseInput_SignedUrl{SignedUrl: value.SignedURL}
	} else {
		result.Source = &letfsv1.ParseInput_InlineContent{InlineContent: value.InlineContent}
	}
	return &letfsv1.PrepareParseResponse{Result: &letfsv1.PrepareParseResponse_Input{Input: result}}, nil
}

func (s *Ingest) PrepareParseOutput(ctx context.Context, input *letfsv1.PrepareParseOutputRequest) (*letfsv1.PrepareParseOutputResponse, error) {
	a, err := processingGenerationInput(ctx, input.GetSource())
	if err != nil {
		return nil, err
	}
	output, err := outputDescriptionInput(input.GetOutput())
	if err != nil {
		return nil, err
	}
	value, err := s.Store.PrepareParseOutput(ctx, a, output)
	if err != nil {
		return nil, err
	}
	return &letfsv1.PrepareParseOutputResponse{Upload: outputUploadMessage(value)}, nil
}

func (s *Ingest) CompleteParse(ctx context.Context, input *letfsv1.CompleteParseRequest) (*letfsv1.CompleteParseResponse, error) {
	a, err := processingGenerationInput(ctx, input.GetSource())
	if err != nil {
		return nil, err
	}
	if int64(len(input.GetUploads())) > s.Store.ProcessingMaxOutputs || int64(len(input.GetDirectories())) > s.Store.ProcessingMaxOutputs {
		return nil, rpc.Fault(codes.Aborted, "RESOURCE_LIMIT", "output manifest exceeds limit")
	}
	ids := make([]uuid.UUID, len(input.Uploads))
	for i, raw := range input.Uploads {
		id, err := parseID(raw)
		if err != nil {
			return nil, err
		}
		ids[i] = id
	}
	if err = s.Store.CompleteParse(ctx, a, filesystem.ParseManifest{Uploads: ids, Directories: input.Directories}); err != nil {
		return nil, err
	}
	return &letfsv1.CompleteParseResponse{SourceId: a.FileID.String()}, nil
}

func (s *Ingest) AbortParse(ctx context.Context, input *letfsv1.AbortParseRequest) (*letfsv1.AbortParseResponse, error) {
	a, err := processingGenerationInput(ctx, input.GetSource())
	if err != nil {
		return nil, err
	}
	if err = s.Store.AbortParse(ctx, a, input.GetErrorCode()); err != nil {
		return nil, err
	}
	return &letfsv1.AbortParseResponse{}, nil
}

func (s *Ingest) GetOutputUpload(ctx context.Context, input *letfsv1.GetOutputUploadRequest) (*letfsv1.GetOutputUploadResponse, error) {
	scope, err := outputScopeInput(ctx, input.GetScope())
	if err != nil {
		return nil, err
	}
	value, err := s.Store.GetOutputUpload(ctx, scope)
	if err != nil {
		return nil, err
	}
	return &letfsv1.GetOutputUploadResponse{Upload: outputUploadMessage(value)}, nil
}

func (s *Ingest) GetOutputUploadParts(ctx context.Context, input *letfsv1.GetOutputUploadPartsRequest) (*letfsv1.GetOutputUploadPartsResponse, error) {
	scope, err := outputScopeInput(ctx, input.GetScope())
	if err != nil {
		return nil, err
	}
	value, err := s.Store.GetOutputUploadParts(ctx, scope, input.GetNumbers())
	if err != nil {
		return nil, err
	}
	return &letfsv1.GetOutputUploadPartsResponse{Items: uploadPartsMessage(value)}, nil
}

func (s *Ingest) CompleteOutputUpload(ctx context.Context, input *letfsv1.CompleteOutputUploadRequest) (*letfsv1.CompleteOutputUploadResponse, error) {
	scope, err := outputScopeInput(ctx, input.GetScope())
	if err != nil {
		return nil, err
	}
	parts, err := partReceiptsInput(input.GetParts())
	if err != nil {
		return nil, err
	}
	value, err := s.Store.CompleteOutputUpload(ctx, scope, parts)
	if err != nil {
		return nil, err
	}
	return &letfsv1.CompleteOutputUploadResponse{Receipt: outputReceiptMessage(value)}, nil
}

func (s *Ingest) WriteOutputBytes(ctx context.Context, input *letfsv1.WriteOutputBytesRequest) (*letfsv1.WriteOutputBytesResponse, error) {
	scope, err := outputScopeInput(ctx, input.GetScope())
	if err != nil {
		return nil, err
	}
	value, err := s.Store.WriteOutputBytes(ctx, scope, input.GetContent())
	if err != nil {
		return nil, err
	}
	return &letfsv1.WriteOutputBytesResponse{Receipt: outputReceiptMessage(value)}, nil
}

func inventoryMessages(nodes []filesystem.ProcessingNode) []*letfsv1.InventoryNode {
	result := make([]*letfsv1.InventoryNode, len(nodes))
	for i, node := range nodes {
		value := &letfsv1.InventoryNode{Id: node.ID.String(), Path: node.Path, Name: node.Name, Kind: node.Kind, SizeBytes: node.SizeBytes, MediaType: node.MediaType, Title: node.Title, Description: node.Description, Context: node.Context}
		if node.ParentID != nil {
			parent := node.ParentID.String()
			value.ParentId = &parent
		}
		if content := node.Content; content != nil {
			if content.SignedURL != "" {
				value.Content = &letfsv1.InventoryNode_SignedUrl{SignedUrl: content.SignedURL}
			} else {
				value.Content = &letfsv1.InventoryNode_InlineContent{InlineContent: content.InlineContent}
			}
		}
		result[i] = value
	}
	return result
}

func (s *Ingest) PrepareEnrichment(ctx context.Context, input *letfsv1.PrepareEnrichmentRequest) (*letfsv1.PrepareEnrichmentResponse, error) {
	a, err := processingGenerationInput(ctx, input.GetSource())
	if err != nil {
		return nil, err
	}
	value, err := s.Store.PrepareEnrichment(ctx, a)
	if err != nil {
		return nil, err
	}
	if value.Complete {
		return &letfsv1.PrepareEnrichmentResponse{Result: &letfsv1.PrepareEnrichmentResponse_Complete{Complete: &letfsv1.EnrichmentComplete{SourceId: value.SourceID.String()}}}, nil
	}
	result := &letfsv1.EnrichmentInput{SourceId: value.SourceID.String(), Nodes: inventoryMessages(value.Nodes), InlineLimitBytes: s.Store.InlineLimit, MultipartThresholdBytes: s.Store.MultipartThreshold, MaxOutputBytes: s.Store.ProcessingMaxOutputBytes}
	return &letfsv1.PrepareEnrichmentResponse{Result: &letfsv1.PrepareEnrichmentResponse_Input{Input: result}}, nil
}

func (s *Ingest) PrepareEnrichmentOutput(ctx context.Context, input *letfsv1.PrepareEnrichmentOutputRequest) (*letfsv1.PrepareEnrichmentOutputResponse, error) {
	a, err := processingGenerationInput(ctx, input.GetSource())
	if err != nil {
		return nil, err
	}
	output, err := outputDescriptionInput(input.GetOutput())
	if err != nil {
		return nil, err
	}
	value, err := s.Store.PrepareEnrichmentOutput(ctx, a, output)
	if err != nil {
		return nil, err
	}
	return &letfsv1.PrepareEnrichmentOutputResponse{Upload: outputUploadMessage(value)}, nil
}

func (s *Ingest) CompleteEnrichment(ctx context.Context, input *letfsv1.CompleteEnrichmentRequest) (*letfsv1.CompleteEnrichmentResponse, error) {
	a, err := processingGenerationInput(ctx, input.GetSource())
	if err != nil {
		return nil, err
	}
	if int64(len(input.GetNodes())) > s.Store.ProcessingMaxOutputs+1 {
		return nil, rpc.Fault(codes.Aborted, "RESOURCE_LIMIT", "enrichment manifest exceeds limit")
	}
	updates := make([]filesystem.EnrichmentUpdate, len(input.Nodes))
	for i, node := range input.Nodes {
		id, err := parseID(node.GetId())
		if err != nil {
			return nil, err
		}
		update := filesystem.EnrichmentUpdate{ID: id, Path: node.GetPath()}
		if metadata := node.GetMetadata(); metadata != nil {
			update.Metadata = &filesystem.SemanticMetadata{Title: metadata.Title, Description: metadata.Description, SemanticType: metadata.SemanticType, Context: metadata.Context}
		}
		if node.UploadId != nil {
			id, err := parseID(*node.UploadId)
			if err != nil {
				return nil, err
			}
			update.UploadID = &id
		}
		updates[i] = update
	}
	if err = s.Store.CompleteEnrichment(ctx, a, filesystem.EnrichmentManifest{Nodes: updates}); err != nil {
		return nil, err
	}
	return &letfsv1.CompleteEnrichmentResponse{SourceId: a.FileID.String()}, nil
}

func (s *Ingest) FailEnrichment(ctx context.Context, input *letfsv1.FailEnrichmentRequest) (*letfsv1.FailEnrichmentResponse, error) {
	a, err := processingGenerationInput(ctx, input.GetSource())
	if err != nil {
		return nil, err
	}
	if err = s.Store.FailEnrichment(ctx, a, input.GetErrorCode()); err != nil {
		return nil, err
	}
	return &letfsv1.FailEnrichmentResponse{}, nil
}
