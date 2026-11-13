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
		{"artifact name", &pb.EnrichedArtifact{NodeId: id, Name: proto.String("revenue.md")}, true},
		{"artifact path is not a name", &pb.EnrichedArtifact{NodeId: id, Name: proto.String("folder/revenue.md")}, false},
		{"artifact name is not empty", &pb.EnrichedArtifact{NodeId: id, Name: proto.String("")}, false},
		{"artifact name rejects NUL", &pb.EnrichedArtifact{NodeId: id, Name: proto.String("bad\x00.md")}, false},
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
