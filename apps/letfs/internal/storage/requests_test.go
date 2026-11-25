package storage

import (
	"testing"

	"buf.build/go/protovalidate"
	"github.com/google/uuid"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"google.golang.org/protobuf/proto"
)

func TestStorageMutationRequests(t *testing.T) {
	id := uuid.NewString()
	name := "Renamed"
	for _, tc := range []struct {
		name    string
		request proto.Message
		valid   bool
	}{
		{"parsed artifact text", &pb.SaveParsedArtifactsRequest{BlobId: id, Artifacts: []*pb.ParsedArtifactInput{{Path: "01-intro.md", Kind: pb.NodeKind_NODE_KIND_FILE, MediaType: "text/markdown", TextContent: proto.String("# Intro"), Indexable: true}}}, true},
		{"parsed artifact empty path", &pb.SaveParsedArtifactsRequest{BlobId: id, Artifacts: []*pb.ParsedArtifactInput{{Path: "", Kind: pb.NodeKind_NODE_KIND_FILE}}}, false},
		{"enriched artifact path", &pb.EnrichedArtifactInput{ArtifactId: id, Path: proto.String("images/01-revenue.jpg")}, true},
		{"enriched artifact empty path", &pb.EnrichedArtifactInput{ArtifactId: id, Path: proto.String("")}, false},
		{"node locator artifact path", &pb.NodeLocator{Locator: &pb.NodeLocator_NodeId{NodeId: id}, ArtifactPath: proto.String("01-intro.md")}, true},
		{"rename without receipt", &pb.UpdateStorageRequest{WorkspaceId: id, StorageId: id, Name: name}, true},
		{"empty update", &pb.UpdateStorageRequest{WorkspaceId: id, StorageId: id}, false},
		{"multipart checksums", &pb.SignPartsRequest{WorkspaceId: id, StorageId: id, UploadId: id, Parts: []*pb.UploadPart{{PartNumber: 1, Checksum: "AAAAAA=="}}}, true},
		{"duplicate part", &pb.SignPartsRequest{WorkspaceId: id, StorageId: id, UploadId: id, Parts: []*pb.UploadPart{{PartNumber: 1, Checksum: "AAAAAA=="}, {PartNumber: 1, Checksum: "AAAAAA=="}}}, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			err := protovalidate.Validate(tc.request)
			if (err == nil) != tc.valid {
				t.Fatalf("valid=%v: %v", tc.valid, err)
			}
		})
	}
}
