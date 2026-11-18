//go:build integration

package storage

import (
	"archive/zip"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	az "github.com/authzed/authzed-go/proto/authzed/api/v1"
	authzed "github.com/authzed/authzed-go/v1"
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/google/uuid"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"google.golang.org/genproto/googleapis/api/httpbody"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

type permissionStub struct {
	az.UnimplementedPermissionsServiceServer
	denied bool
	full   bool
}

func (p *permissionStub) CheckPermission(_ context.Context, r *az.CheckPermissionRequest) (*az.CheckPermissionResponse, error) {
	p.full = p.full || r.Consistency.GetFullyConsistent()
	allowed := az.CheckPermissionResponse_PERMISSIONSHIP_HAS_PERMISSION
	if p.denied {
		allowed = az.CheckPermissionResponse_PERMISSIONSHIP_NO_PERMISSION
	}
	return &az.CheckPermissionResponse{Permissionship: allowed}, nil
}

type archiveOutput struct {
	ctx context.Context
	bytes.Buffer
}

func (o *archiveOutput) Context() context.Context { return o.ctx }
func (o *archiveOutput) Send(value *httpbody.HttpBody) error {
	_, err := o.Write(value.Data)
	return err
}
func (*archiveOutput) SendHeader(metadata.MD) error { return nil }
func (*archiveOutput) SetHeader(metadata.MD) error  { return nil }
func (*archiveOutput) SetTrailer(metadata.MD)       {}
func (*archiveOutput) SendMsg(any) error            { return nil }
func (*archiveOutput) RecvMsg(any) error            { return io.EOF }

func testTransfers(t *testing.T, s *Server, workspace, storage, folder string) {
	t.Helper()
	ctx := context.Background()
	actor := uuid.NewString()
	ctx = metadata.NewIncomingContext(ctx, metadata.Pairs("x-openlet-user-id", actor))
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	graph := grpc.NewServer()
	permissions := new(permissionStub)
	az.RegisterPermissionsServiceServer(graph, permissions)
	go graph.Serve(listener)
	defer graph.Stop()
	client, err := authzed.NewClient(listener.Addr().String(), grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	s.Graph = client
	current, err := oneResolved(ctx, s.DB, workspace, storage, &pb.NodeLocator{Locator: &pb.NodeLocator_Path{Path: "/docs/note.txt"}}, true, false)
	if err != nil {
		t.Fatal(err)
	}
	previous := current.Node.File.Version
	edit := &pb.MutateTextRequest{WorkspaceId: workspace, StorageId: storage, Target: &pb.NodeLocator{Locator: &pb.NodeLocator_NodeId{NodeId: current.Node.Id}}, ExpectedVersion: &previous, RequestId: uuid.NewString(), Mutation: &pb.MutateTextRequest_Replace{Replace: "latest notes"}}
	saved, err := s.MutateText(ctx, edit)
	if err != nil || saved.File.Version != previous+1 {
		t.Fatalf("replace current text: %v %v", saved, err)
	}
	if replayed, err := s.MutateText(ctx, edit); err != nil || replayed.File.Version != saved.File.Version {
		t.Fatalf("edit replay: %v %v", replayed, err)
	}
	edit.RequestId = uuid.NewString()
	if _, err = s.MutateText(ctx, edit); status.Code(err) != codes.Aborted {
		t.Fatalf("stale edit overwrote current text: %v", err)
	}
	var used, logical int64
	if err = s.DB.QueryRow(ctx, `SELECT (SELECT used_bytes FROM workspace_storage WHERE workspace_id=$1),(SELECT coalesce(sum(f.size_bytes),0) FROM files f JOIN nodes n ON n.id=f.node_id JOIN storages s ON s.id=n.storage_id WHERE s.workspace_id=$1)`, workspace).Scan(&used, &logical); err != nil || used != logical {
		t.Fatalf("edits retained extra quota: %d != %d: %v", used, logical, err)
	}
	archive := &pb.DownloadArchiveRequest{WorkspaceId: workspace, StorageId: storage, Targets: []*pb.NodeLocator{{Locator: &pb.NodeLocator_NodeId{NodeId: folder}}}}
	ticket, err := s.CreateArchiveDownload(ctx, archive)
	if err != nil {
		t.Fatal(err)
	}
	output := &archiveOutput{ctx: context.Background()}
	if err = s.DownloadArchiveTicket(&pb.ArchiveDownloadTicketRequest{Ticket: ticket.Ticket}, output); err != nil {
		t.Fatal(err)
	}
	if !permissions.full {
		t.Fatal("ticket download did not recheck current permission")
	}
	zipped, err := zip.NewReader(bytes.NewReader(output.Bytes()), int64(output.Len()))
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, file := range zipped.File {
		if strings.HasSuffix(file.Name, "note.txt") {
			reader, err := file.Open()
			if err != nil {
				t.Fatal(err)
			}
			content, err := io.ReadAll(reader)
			_ = reader.Close()
			if err != nil || string(content) != "latest notes" {
				t.Fatalf("archive text %q: %v", content, err)
			}
			found = true
		}
	}
	if !found {
		t.Fatal("archive omitted nested text")
	}
	if err = s.DownloadArchiveTicket(&pb.ArchiveDownloadTicketRequest{Ticket: ticket.Ticket}, &archiveOutput{ctx: ctx}); status.Code(err) != codes.NotFound {
		t.Fatalf("ticket replay admitted: %v", err)
	}
	ticket, err = s.CreateArchiveDownload(ctx, archive)
	if err != nil {
		t.Fatal(err)
	}
	permissions.denied = true
	if err = s.DownloadArchiveTicket(&pb.ArchiveDownloadTicketRequest{Ticket: ticket.Ticket}, &archiveOutput{ctx: ctx}); status.Code(err) != codes.PermissionDenied {
		t.Fatalf("revoked download admitted: %v", err)
	}
	permissions.denied = false
	if image := os.Getenv("OPENLET_TEST_ENVOY_IMAGE"); image != "" {
		t.Run("gateway archive", func(t *testing.T) { testGatewayArchive(t, s, ctx, archive, image) })
	}
	ticket, err = s.CreateArchiveDownload(ctx, archive)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = s.DB.Exec(ctx, `UPDATE archive_downloads SET expires_at=now()-interval '1 second'`); err != nil {
		t.Fatal(err)
	}
	if _, _, err = s.consumeArchiveDownload(ctx, ticket.Ticket); status.Code(err) != codes.NotFound {
		t.Fatalf("expired download admitted: %v", err)
	}

	objectStore := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "HEAD" {
			w.WriteHeader(404)
			return
		}
		w.Header().Set("Content-Type", "application/xml")
		_, _ = io.WriteString(w, `<ListPartsResult><IsTruncated>false</IsTruncated><Part><PartNumber>1</PartNumber><ETag>first</ETag><Size>4</Size><ChecksumCRC32C>AAAAAA==</ChecksumCRC32C></Part></ListPartsResult>`)
	}))
	defer objectStore.Close()
	s.S3 = s3.New(s3.Options{BaseEndpoint: aws.String(objectStore.URL), Region: "test", UsePathStyle: true, Credentials: credentials.NewStaticCredentialsProvider("test", "test", "")})
	s.Presign = s3.NewPresignClient(s.S3)
	s.Bucket = "test"
	upload := uuid.NewString()
	if _, err = s.DB.Exec(ctx, `INSERT INTO uploads(id,storage_id,actor,root_id,parent_id,name,object_key,size_bytes,media_type,checksum,multipart_id,expires_at) VALUES($1,$2,$3,$4,$4,'file.pdf','objects/test',8,'application/pdf','AAAAAA==','multipart',$5)`, upload, storage, "user:"+actor, folder, time.Now().Add(time.Hour)); err != nil {
		t.Fatal(err)
	}
	resumed, err := s.GetUpload(ctx, &pb.UploadRequest{WorkspaceId: workspace, StorageId: storage, UploadId: upload})
	if err != nil || len(resumed.GetCompletedParts()) != 1 || resumed.CompletedParts[0].PartNumber != 1 || resumed.CompletedParts[0].Checksum != "AAAAAA==" {
		t.Fatalf("resume parts: %+v %v", resumed, err)
	}
	other := metadata.NewIncomingContext(context.Background(), metadata.Pairs("x-openlet-user-id", uuid.NewString()))
	if _, err = s.GetUpload(other, &pb.UploadRequest{WorkspaceId: workspace, StorageId: storage, UploadId: upload}); status.Code(err) != codes.NotFound {
		t.Fatalf("another actor read upload session: %v", err)
	}
}

func testGatewayArchive(t *testing.T, s *Server, actor context.Context, archive *pb.DownloadArchiveRequest, image string) {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	service := grpc.NewServer()
	pb.RegisterLetFSServiceServer(service, s)
	go service.Serve(listener)
	defer service.Stop()
	portListener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := portListener.Addr().(*net.TCPAddr).Port
	portListener.Close()
	raw, err := os.ReadFile("../../../../infra/config/envoy.template.yaml")
	if err != nil {
		t.Fatal(err)
	}
	values := map[string]any{"LISTEN_HOST": "127.0.0.1", "LISTEN_PORT": port, "ISSUER": "https://test.invalid", "AUDIENCE": "test", "JWKS_URL": "http://127.0.0.1:1/jwks", "JWKS_HOST": "127.0.0.1", "JWKS_PORT": 1, "PLATFORM_HOST": "127.0.0.1", "PLATFORM_PORT": 1, "LETFS_HOST": "127.0.0.1", "LETFS_PORT": listener.Addr().(*net.TCPAddr).Port}
	config := string(raw)
	values["USER_ID_CLAIM"] = "public_metadata.openlet_user_id"
	for key, value := range values {
		encoded, err := json.Marshal(value)
		if err != nil {
			t.Fatal(err)
		}
		config = strings.ReplaceAll(config, "@"+key+"@", string(encoded))
	}
	dir := t.TempDir()
	configPath := filepath.Join(dir, "envoy.yaml")
	if err = os.WriteFile(configPath, []byte(config), 0644); err != nil {
		t.Fatal(err)
	}
	descriptor, err := filepath.Abs("../../../../packages/contracts/generated/public.pb")
	if err != nil {
		t.Fatal(err)
	}
	name := "openlet-archive-check-" + uuid.NewString()
	log, err := os.Create(filepath.Join(dir, "envoy.log"))
	if err != nil {
		t.Fatal(err)
	}
	defer log.Close()
	command := exec.Command("docker", "run", "--rm", "--name", name, "--network", "host", "--user", "0:0", "-v", configPath+":/etc/envoy/envoy.yaml:ro", "-v", descriptor+":/etc/openlet/public.pb:ro", image, "-c", "/etc/envoy/envoy.yaml", "--concurrency", "1", "--disable-hot-restart", "--log-level", "error")
	command.Stdout, command.Stderr = log, log
	if err = command.Start(); err != nil {
		t.Fatal(err)
	}
	defer func() { _ = exec.Command("docker", "rm", "-f", name).Run(); _ = command.Wait() }()
	address := "127.0.0.1:" + strconv.Itoa(port)
	ready := false
	for deadline := time.Now().Add(10 * time.Second); time.Now().Before(deadline); {
		conn, err := net.DialTimeout("tcp", address, 100*time.Millisecond)
		if err == nil {
			conn.Close()
			ready = true
			break
		}
		time.Sleep(100 * time.Millisecond)
	}
	if !ready {
		output, _ := os.ReadFile(log.Name())
		t.Fatalf("gateway did not start: %s", output)
	}
	ticket, err := s.CreateArchiveDownload(actor, archive)
	if err != nil {
		t.Fatal(err)
	}
	client := &http.Client{Timeout: 10 * time.Second}
	url := "http://" + address + "/v1/archive-downloads/" + ticket.Ticket
	response, err := client.Get(url)
	if err != nil {
		t.Fatal(err)
	}
	data, err := io.ReadAll(response.Body)
	response.Body.Close()
	if err != nil || response.StatusCode != 200 || !strings.HasPrefix(response.Header.Get("Content-Disposition"), "attachment;") {
		t.Fatalf("archive response %d %q: %s %v", response.StatusCode, response.Header.Get("Content-Disposition"), data, err)
	}
	zipped, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil || len(zipped.File) == 0 {
		t.Fatalf("gateway did not return raw ZIP bytes: %v", err)
	}
	response, err = client.Get(url)
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if response.StatusCode != 404 {
		t.Fatalf("gateway admitted replay: %d", response.StatusCode)
	}
	for _, path := range []string{url, fmt.Sprintf("http://%s/v1/workspaces/%s/storages/%s/nodes:downloadArchive", address, archive.WorkspaceId, archive.StorageId)} {
		response, err = client.Post(path, "application/json", strings.NewReader("{}"))
		if err != nil {
			t.Fatal(err)
		}
		response.Body.Close()
		if response.StatusCode != 401 {
			t.Fatalf("unauthenticated POST admitted: %d", response.StatusCode)
		}
	}
}
