package storage

import (
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"testing"
)

func TestTextExactBytesAndPatch(t *testing.T) {
	original := "\ufeffa\r\n猫\n"
	part, err := selectText(original, &pb.ReadTextRequest{Selection: &pb.ReadTextRequest_Lines{Lines: &pb.LineRange{First: 2, Count: 1}}})
	if err != nil || part != "猫\n" {
		t.Fatalf("%q %v", part, err)
	}
	got, err := applyText(original, &pb.MutateTextRequest{Mutation: &pb.MutateTextRequest_Patch{Patch: &pb.TextPatch{Edits: []*pb.TextEdit{{StartByte: 3, EndByte: 4, Replacement: "A"}}}}})
	if err != nil || got != "\ufeffA\r\n猫\n" {
		t.Fatalf("%q %v", got, err)
	}
	if _, err = applyText(original, &pb.MutateTextRequest{Mutation: &pb.MutateTextRequest_TruncateBytes{TruncateBytes: 1}}); err == nil {
		t.Fatal("accepted split UTF-8")
	}
	s := Server{Settings: Settings{MaxTextBytes: 100}}
	if err = s.validateText("a\x00b"); err == nil {
		t.Fatal("accepted PostgreSQL NUL")
	}
}

func TestTextReadAndEditModes(t *testing.T) {
	part, err := selectText("abc", &pb.ReadTextRequest{Selection: &pb.ReadTextRequest_Bytes{Bytes: &pb.ByteRange{Offset: 1}}})
	if err != nil || part != "bc" {
		t.Fatalf("read to EOF: %q %v", part, err)
	}
	part, err = selectText("abc", &pb.ReadTextRequest{Selection: &pb.ReadTextRequest_Bytes{Bytes: &pb.ByteRange{Offset: 20}}})
	if err != nil || part != "" {
		t.Fatalf("read beyond EOF: %q %v", part, err)
	}
	got, err := applyText("abc", &pb.MutateTextRequest{Mutation: &pb.MutateTextRequest_Overwrite{Overwrite: &pb.TextOverwrite{Offset: 2, Content: "XYZ"}}})
	if err != nil || got != "abXYZ" {
		t.Fatalf("overwrite extending at EOF: %q %v", got, err)
	}
	r := &pb.MutateTextRequest{Mutation: &pb.MutateTextRequest_LiteralReplace{LiteralReplace: &pb.TextReplace{OldText: "a", NewText: "b"}}}
	if _, err := applyText("aa", r); err == nil {
		t.Fatal("ambiguous replacement accepted")
	}
	r.GetLiteralReplace().ReplaceAll = true
	got, err = applyText("aa", r)
	if err != nil || got != "bb" {
		t.Fatalf("replace all: %q %v", got, err)
	}
}

func TestBlobTransfersRejectDeclaredText(t *testing.T) {
	for _, media := range []string{"text/plain; charset=utf-8", "application/json", "application/ld+json", "application/xml", "application/xhtml+xml", "application/yaml"} {
		if _, err := blobMediaType(media); err == nil {
			t.Errorf("accepted text on S3: %s", media)
		}
	}
	for _, media := range []string{"application/octet-stream", "application/pdf", "image/svg+xml", documentMedia[3]} {
		if got, err := blobMediaType(media); err != nil || got != media {
			t.Errorf("rejected blob %s: %s %v", media, got, err)
		}
	}
}
