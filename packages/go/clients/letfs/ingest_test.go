package letfs

import (
	"context"
	"testing"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/apperr"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc"
)

type fakeIngest struct {
	letfsv1.IngestServiceClient
	enrichment func(context.Context, *letfsv1.PrepareEnrichmentRequest) (*letfsv1.PrepareEnrichmentResponse, error)
	write      func(context.Context, *letfsv1.WriteOutputBytesRequest) (*letfsv1.WriteOutputBytesResponse, error)
	complete   func(context.Context, *letfsv1.CompleteEnrichmentRequest) (*letfsv1.CompleteEnrichmentResponse, error)
}

func (f fakeIngest) PrepareEnrichment(ctx context.Context, in *letfsv1.PrepareEnrichmentRequest, _ ...grpc.CallOption) (*letfsv1.PrepareEnrichmentResponse, error) {
	return f.enrichment(ctx, in)
}
func (f fakeIngest) WriteOutputBytes(ctx context.Context, in *letfsv1.WriteOutputBytesRequest, _ ...grpc.CallOption) (*letfsv1.WriteOutputBytesResponse, error) {
	return f.write(ctx, in)
}
func (f fakeIngest) CompleteEnrichment(ctx context.Context, in *letfsv1.CompleteEnrichmentRequest, _ ...grpc.CallOption) (*letfsv1.CompleteEnrichmentResponse, error) {
	return f.complete(ctx, in)
}

func TestIngestConversionsPreserveGenerationAndScope(t *testing.T) {
	file, node, upload := uuid.New(), uuid.New(), uuid.New()
	generation := Generation{FileID: file, Number: 4}
	client := IngestClient{API: fakeIngest{
		enrichment: func(_ context.Context, in *letfsv1.PrepareEnrichmentRequest) (*letfsv1.PrepareEnrichmentResponse, error) {
			require.Equal(t, int64(4), in.GetSource().GetGeneration())
			return &letfsv1.PrepareEnrichmentResponse{Result: &letfsv1.PrepareEnrichmentResponse_Input{Input: &letfsv1.EnrichmentInput{SourceId: file.String(), Nodes: []*letfsv1.InventoryNode{{Id: node.String(), Path: "/x", Name: "x", Kind: "file"}}}}}, nil
		},
		write: func(_ context.Context, in *letfsv1.WriteOutputBytesRequest) (*letfsv1.WriteOutputBytesResponse, error) {
			require.Equal(t, "parse", in.GetScope().GetStage())
			require.Equal(t, []byte("body"), in.GetContent())
			return &letfsv1.WriteOutputBytesResponse{Receipt: &letfsv1.UploadReceipt{Id: upload.String(), Status: "uploaded", SizeBytes: 4}}, nil
		},
	}}
	admission, err := client.PrepareEnrichment(t.Context(), generation)
	require.NoError(t, err)
	require.Equal(t, node, admission.Input.Nodes[0].ID)
	receipt, err := client.WriteOutputBytes(t.Context(), OutputScope{Source: generation, Stage: "parse", UploadID: upload}, []byte("body"))
	require.NoError(t, err)
	require.Equal(t, upload, receipt.ID)
}

func TestIngestRejectsForeignSource(t *testing.T) {
	file := uuid.New()
	client := IngestClient{API: fakeIngest{enrichment: func(context.Context, *letfsv1.PrepareEnrichmentRequest) (*letfsv1.PrepareEnrichmentResponse, error) {
		return &letfsv1.PrepareEnrichmentResponse{Result: &letfsv1.PrepareEnrichmentResponse_Input{Input: &letfsv1.EnrichmentInput{SourceId: uuid.NewString()}}}, nil
	}}}
	_, err := client.PrepareEnrichment(t.Context(), Generation{FileID: file, Number: 1})
	require.Equal(t, apperr.Conflict, apperr.KindOf(err))
}

func TestEnrichmentPreservesAbsentMetadataAndEmptyInlinePresence(t *testing.T) {
	file, node := uuid.New(), uuid.New()
	client := IngestClient{API: fakeIngest{
		enrichment: func(context.Context, *letfsv1.PrepareEnrichmentRequest) (*letfsv1.PrepareEnrichmentResponse, error) {
			return &letfsv1.PrepareEnrichmentResponse{Result: &letfsv1.PrepareEnrichmentResponse_Input{Input: &letfsv1.EnrichmentInput{SourceId: file.String(), Nodes: []*letfsv1.InventoryNode{{Id: node.String(), Path: "/", Name: "x", Kind: "file", Content: &letfsv1.InventoryNode_InlineContent{InlineContent: []byte{}}}}}}}, nil
		},
		complete: func(_ context.Context, in *letfsv1.CompleteEnrichmentRequest) (*letfsv1.CompleteEnrichmentResponse, error) {
			require.Nil(t, in.GetNodes()[0].Metadata)
			return &letfsv1.CompleteEnrichmentResponse{SourceId: file.String()}, nil
		},
	}}
	admission, err := client.PrepareEnrichment(t.Context(), Generation{FileID: file, Number: 1})
	require.NoError(t, err)
	require.NotNil(t, admission.Input.Nodes[0].InlineContent)
	require.Empty(t, *admission.Input.Nodes[0].InlineContent)
	require.Nil(t, admission.Input.Nodes[0].SignedURL)
	require.NoError(t, client.CompleteEnrichment(t.Context(), Generation{FileID: file, Number: 1}, []EnrichmentUpdate{{ID: node, Path: "/"}}))
}
