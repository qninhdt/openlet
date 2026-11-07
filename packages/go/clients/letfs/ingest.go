package letfs

import (
	"context"

	"github.com/google/uuid"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/rpc"
)

type IngestClient struct{ API letfsv1.IngestServiceClient }
type Generation struct {
	FileID uuid.UUID
	Number int64
}
type ParseInput struct {
	SourceID                                                                         uuid.UUID
	Format                                                                           string
	SizeBytes, InlineLimitBytes, MultipartThresholdBytes, MaxOutputs, MaxOutputBytes int64
	InlineContent                                                                    *[]byte
	SignedURL                                                                        *string
}
type ParseAdmission struct {
	Input     *ParseInput
	Completed bool
}
type OutputDescription struct {
	Path, Storage string
	SizeBytes     *int64
	ContentMD5    *string
}
type InventoryNode struct {
	ID                                     uuid.UUID
	ParentID                               *uuid.UUID
	Path, Name, Kind                       string
	SizeBytes                              int64
	MediaType, Title, Description, Context *string
	InlineContent                          *[]byte
	SignedURL                              *string
}
type EnrichmentInput struct {
	SourceID                                                  uuid.UUID
	Nodes                                                     []InventoryNode
	InlineLimitBytes, MultipartThresholdBytes, MaxOutputBytes int64
}
type EnrichmentAdmission struct {
	Input     *EnrichmentInput
	Completed bool
}
type SemanticMetadata struct{ Title, Description, SemanticType, Context string }
type EnrichmentUpdate struct {
	ID       uuid.UUID
	Path     string
	Metadata *SemanticMetadata
	UploadID *uuid.UUID
}
type VectorSpace struct {
	Model, Collection string
	Dimension         int32
}
type IndexInput struct {
	FilesystemID, ScopeID, SourceID uuid.UUID
	Generation                      int64
	Nodes                           []InventoryNode
	VectorSpace                     VectorSpace
	MaxOutputBytes                  int64
}
type IndexAdmission struct {
	Input     *IndexInput
	Completed bool
}
type OutputScope struct {
	Source   Generation
	Stage    string
	UploadID uuid.UUID
}

func generation(value Generation) *letfsv1.ProcessingGeneration {
	return &letfsv1.ProcessingGeneration{FileId: value.FileID.String(), Generation: value.Number}
}
func outputDescription(value OutputDescription) *letfsv1.OutputDescription {
	return &letfsv1.OutputDescription{Path: value.Path, Storage: value.Storage, SizeBytes: value.SizeBytes, ContentMd5: value.ContentMD5}
}
func outputScope(value OutputScope) *letfsv1.OutputUploadScope {
	return &letfsv1.OutputUploadScope{Source: generation(value.Source), Stage: value.Stage, UploadId: value.UploadID.String()}
}
func nativeInventory(values []*letfsv1.InventoryNode) ([]InventoryNode, error) {
	out := make([]InventoryNode, len(values))
	for i, value := range values {
		id, err := parseID(value.GetId())
		if err != nil {
			return nil, err
		}
		item := InventoryNode{ID: id, Path: value.GetPath(), Name: value.GetName(), Kind: value.GetKind(), SizeBytes: value.GetSizeBytes(), MediaType: value.MediaType, Title: value.Title, Description: value.Description, Context: value.Context}
		switch source := value.GetContent().(type) {
		case *letfsv1.InventoryNode_InlineContent:
			content := source.InlineContent
			item.InlineContent = &content
		case *letfsv1.InventoryNode_SignedUrl:
			url := source.SignedUrl
			item.SignedURL = &url
		}
		if value.ParentId != nil {
			parent, err := parseID(value.GetParentId())
			if err != nil {
				return nil, err
			}
			item.ParentID = &parent
		}
		out[i] = item
	}
	return out, nil
}

func (c IngestClient) PrepareParse(ctx context.Context, value Generation) (ParseAdmission, error) {
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.PrepareParse(ctx, &letfsv1.PrepareParseRequest{FileId: value.FileID.String(), Generation: value.Number})
	if err != nil {
		return ParseAdmission{}, rpc.DecodeError(err)
	}
	if response.GetComplete() != nil {
		return ParseAdmission{Completed: true}, nil
	}
	input := response.GetInput()
	if input == nil {
		return ParseAdmission{}, scopeError()
	}
	source, err := parseID(input.GetSourceId())
	if err != nil || source != value.FileID {
		return ParseAdmission{}, scopeError()
	}
	out := &ParseInput{SourceID: source, Format: input.GetFormat(), SizeBytes: input.GetSizeBytes(), InlineLimitBytes: input.GetInlineLimitBytes(), MultipartThresholdBytes: input.GetMultipartThresholdBytes(), MaxOutputs: input.GetMaxOutputs(), MaxOutputBytes: input.GetMaxOutputBytes()}
	switch source := input.GetSource().(type) {
	case *letfsv1.ParseInput_InlineContent:
		content := source.InlineContent
		out.InlineContent = &content
	case *letfsv1.ParseInput_SignedUrl:
		url := source.SignedUrl
		out.SignedURL = &url
	default:
		return ParseAdmission{}, scopeError()
	}
	return ParseAdmission{Input: out}, nil
}

func (c IngestClient) CompleteParse(ctx context.Context, value Generation, uploads, directories []uuid.UUID) error {
	rawUploads := make([]string, len(uploads))
	for i, id := range uploads {
		rawUploads[i] = id.String()
	}
	rawDirectories := make([]string, len(directories))
	for i, id := range directories {
		rawDirectories[i] = id.String()
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.CompleteParse(ctx, &letfsv1.CompleteParseRequest{Source: generation(value), Uploads: rawUploads, Directories: rawDirectories})
	if err != nil {
		return rpc.DecodeError(err)
	}
	id, err := parseID(response.GetSourceId())
	if err != nil || id != value.FileID {
		return scopeError()
	}
	return nil
}

func (c IngestClient) AbortParse(ctx context.Context, value Generation, code string) error {
	ctx, cancel := bounded(ctx)
	defer cancel()
	_, err := c.API.AbortParse(ctx, &letfsv1.AbortParseRequest{Source: generation(value), ErrorCode: code})
	return rpc.DecodeError(err)
}
func (c IngestClient) PrepareParseOutput(ctx context.Context, value Generation, output OutputDescription) (Upload, error) {
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.PrepareParseOutput(ctx, &letfsv1.PrepareParseOutputRequest{Source: generation(value), Output: outputDescription(output)})
	if err != nil {
		return Upload{}, rpc.DecodeError(err)
	}
	return nativeUpload(response.GetUpload())
}
func (c IngestClient) PrepareEnrichment(ctx context.Context, value Generation) (EnrichmentAdmission, error) {
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.PrepareEnrichment(ctx, &letfsv1.PrepareEnrichmentRequest{Source: generation(value)})
	if err != nil {
		return EnrichmentAdmission{}, rpc.DecodeError(err)
	}
	if response.GetComplete() != nil {
		return EnrichmentAdmission{Completed: true}, nil
	}
	input := response.GetInput()
	if input == nil {
		return EnrichmentAdmission{}, scopeError()
	}
	source, err := parseID(input.GetSourceId())
	if err != nil || source != value.FileID {
		return EnrichmentAdmission{}, scopeError()
	}
	nodes, err := nativeInventory(input.GetNodes())
	if err != nil {
		return EnrichmentAdmission{}, err
	}
	return EnrichmentAdmission{Input: &EnrichmentInput{SourceID: source, Nodes: nodes, InlineLimitBytes: input.GetInlineLimitBytes(), MultipartThresholdBytes: input.GetMultipartThresholdBytes(), MaxOutputBytes: input.GetMaxOutputBytes()}}, nil
}
func (c IngestClient) PrepareEnrichmentOutput(ctx context.Context, value Generation, output OutputDescription) (Upload, error) {
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.PrepareEnrichmentOutput(ctx, &letfsv1.PrepareEnrichmentOutputRequest{Source: generation(value), Output: outputDescription(output)})
	if err != nil {
		return Upload{}, rpc.DecodeError(err)
	}
	return nativeUpload(response.GetUpload())
}
func (c IngestClient) CompleteEnrichment(ctx context.Context, value Generation, updates []EnrichmentUpdate) error {
	items := make([]*letfsv1.EnrichmentUpdate, len(updates))
	for i, update := range updates {
		item := &letfsv1.EnrichmentUpdate{Id: update.ID.String(), Path: update.Path}
		if update.Metadata != nil {
			item.Metadata = &letfsv1.SemanticMetadata{Title: update.Metadata.Title, Description: update.Metadata.Description, SemanticType: update.Metadata.SemanticType, Context: update.Metadata.Context}
		}
		if update.UploadID != nil {
			raw := update.UploadID.String()
			item.UploadId = &raw
		}
		items[i] = item
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.CompleteEnrichment(ctx, &letfsv1.CompleteEnrichmentRequest{Source: generation(value), Nodes: items})
	if err != nil {
		return rpc.DecodeError(err)
	}
	id, err := parseID(response.GetSourceId())
	if err != nil || id != value.FileID {
		return scopeError()
	}
	return nil
}
func (c IngestClient) FailEnrichment(ctx context.Context, value Generation, code string) error {
	ctx, cancel := bounded(ctx)
	defer cancel()
	_, err := c.API.FailEnrichment(ctx, &letfsv1.FailEnrichmentRequest{Source: generation(value), ErrorCode: code})
	return rpc.DecodeError(err)
}
func (c IngestClient) PrepareIndex(ctx context.Context, value Generation) (IndexAdmission, error) {
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.PrepareIndex(ctx, &letfsv1.PrepareIndexRequest{Source: generation(value)})
	if err != nil {
		return IndexAdmission{}, rpc.DecodeError(err)
	}
	if response.GetComplete() != nil {
		return IndexAdmission{Completed: true}, nil
	}
	input := response.GetInput()
	if input == nil {
		return IndexAdmission{}, scopeError()
	}
	source, err := parseID(input.GetSourceId())
	if err != nil || source != value.FileID || input.GetGeneration() != value.Number {
		return IndexAdmission{}, scopeError()
	}
	filesystem, err := parseID(input.GetFilesystemId())
	if err != nil {
		return IndexAdmission{}, err
	}
	scope, err := parseID(input.GetScopeId())
	if err != nil {
		return IndexAdmission{}, err
	}
	nodes, err := nativeInventory(input.GetNodes())
	if err != nil {
		return IndexAdmission{}, err
	}
	space := input.GetVectorSpace()
	if space == nil {
		return IndexAdmission{}, scopeError()
	}
	return IndexAdmission{Input: &IndexInput{FilesystemID: filesystem, ScopeID: scope, SourceID: source, Generation: input.GetGeneration(), Nodes: nodes, VectorSpace: VectorSpace{Model: space.GetModel(), Collection: space.GetCollection(), Dimension: space.GetDimension()}, MaxOutputBytes: input.GetMaxOutputBytes()}}, nil
}

func (c IngestClient) CompleteIndex(ctx context.Context, value Generation) error {
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.CompleteIndex(ctx, &letfsv1.CompleteIndexRequest{Source: generation(value)})
	if err != nil {
		return rpc.DecodeError(err)
	}
	id, err := parseID(response.GetSourceId())
	if err != nil || id != value.FileID {
		return scopeError()
	}
	return nil
}

func (c IngestClient) FailIndex(ctx context.Context, value Generation, code string) error {
	ctx, cancel := bounded(ctx)
	defer cancel()
	_, err := c.API.FailIndex(ctx, &letfsv1.FailIndexRequest{Source: generation(value), ErrorCode: code})
	return rpc.DecodeError(err)
}
func (c IngestClient) GetOutputUpload(ctx context.Context, scope OutputScope) (Upload, error) {
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.GetOutputUpload(ctx, &letfsv1.GetOutputUploadRequest{Scope: outputScope(scope)})
	if err != nil {
		return Upload{}, rpc.DecodeError(err)
	}
	value, err := nativeUpload(response.GetUpload())
	if err != nil || value.ID != scope.UploadID {
		return Upload{}, scopeError()
	}
	return value, nil
}
func (c IngestClient) GetOutputUploadParts(ctx context.Context, scope OutputScope, numbers []int32) ([]UploadPart, error) {
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.GetOutputUploadParts(ctx, &letfsv1.GetOutputUploadPartsRequest{Scope: outputScope(scope), Numbers: numbers})
	if err != nil {
		return nil, rpc.DecodeError(err)
	}
	items := make([]UploadPart, len(response.GetItems()))
	for i, item := range response.GetItems() {
		if item.GetTransfer() == nil {
			return nil, scopeError()
		}
		items[i] = UploadPart{Number: item.GetPartNumber(), Transfer: *nativeSigned(item.GetTransfer())}
	}
	return items, nil
}
func (c IngestClient) CompleteOutputUpload(ctx context.Context, scope OutputScope, parts []PartReceipt) (UploadReceipt, error) {
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.CompleteOutputUpload(ctx, &letfsv1.CompleteOutputUploadRequest{Scope: outputScope(scope), Parts: receipts(parts)})
	if err != nil {
		return UploadReceipt{}, rpc.DecodeError(err)
	}
	value, err := nativeReceipt(response.GetReceipt())
	if err != nil || value == nil || value.ID != scope.UploadID {
		return UploadReceipt{}, scopeError()
	}
	return *value, nil
}
func (c IngestClient) WriteOutputBytes(ctx context.Context, scope OutputScope, content []byte) (UploadReceipt, error) {
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.WriteOutputBytes(ctx, &letfsv1.WriteOutputBytesRequest{Scope: outputScope(scope), Content: content})
	if err != nil {
		return UploadReceipt{}, rpc.DecodeError(err)
	}
	value, err := nativeReceipt(response.GetReceipt())
	if err != nil || value == nil || value.ID != scope.UploadID {
		return UploadReceipt{}, scopeError()
	}
	return *value, nil
}
