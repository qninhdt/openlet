//go:build integration

package grpc

import (
	"bytes"
	"encoding/json"
	"image"
	"image/png"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"testing"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/identity"
	"github.com/qninhdt/openlet/packages/go/rpc"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
	"golang.org/x/sync/semaphore"
	grpcgo "google.golang.org/grpc"
)

// Opt in: runs the actual pinned Python adapter against this native service fixture.
func TestIntegrationMirageLetFS(t *testing.T) {
	if os.Getenv("OPENLET_MIRAGE_INTEGRATION") != "1" {
		t.Skip("set OPENLET_MIRAGE_INTEGRATION=1 for cross-language Mirage integration")
	}
	db := testfixture.Postgres(t, "../../../migrations/0001_initial.sql")
	graph, graphAddress, _ := sharedfixture.SpiceDB(t, "../../../../../packages/contracts/authz/schema.zed")
	store := &filesystem.Store{DB: db, Graph: graph, MaxNodes: 1000, MaxCopyNodes: 1000, MaxOutstanding: 100, MaxCleanupBacklog: 100, InlineLimit: 1048576, MaxFileBytes: 104857600, ImageSlots: semaphore.NewWeighted(2)}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "workspace"})
	fs, scope, leta := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7()), uuid.New()
	_, err := store.CreateFilesystem(owner, uuid.New(), filesystem.CreateFilesystem{ID: fs, LimitBytes: 1 << 24})
	require.NoError(t, err)
	scopes, err := store.CreateScopes(owner, uuid.New(), fs, []uuid.UUID{scope}, true, false)
	require.NoError(t, err)
	_, err = graph.WriteRelationships(t.Context(), &v1.WriteRelationshipsRequest{Updates: []*v1.RelationshipUpdate{{Operation: v1.RelationshipUpdate_OPERATION_TOUCH, Relationship: &v1.Relationship{Resource: &v1.ObjectReference{ObjectType: "scope", ObjectId: scope.String()}, Relation: "editor", Subject: &v1.SubjectReference{Object: &v1.ObjectReference{ObjectType: "leta", ObjectId: leta.String()}}}}}})
	require.NoError(t, err)
	actor := identity.WithPrincipal(t.Context(), identity.Principal{ActorKind: identity.Leta, ActorID: leta, Service: "leta"})
	box, err := store.CreateDirectories(actor, scope, filesystem.Locator{NodeID: scopes[0].RootID}, []string{"box"}, false)
	require.NoError(t, err)
	source, err := store.CreateNode(actor, scope, uuid.New(), filesystem.CreateNode{Parent: filesystem.Locator{NodeID: &box.ID}, Name: "report.pdf", File: &filesystem.InlineFile{Content: []byte("private original blob"), MediaType: "application/pdf"}})
	require.NoError(t, err)
	artifact := uuid.Must(uuid.NewV7())
	var picture bytes.Buffer
	require.NoError(t, png.Encode(&picture, image.NewRGBA(image.Rect(0, 0, 2, 2))))
	_, err = store.CreateNode(actor, scope, uuid.New(), filesystem.CreateNode{Parent: filesystem.Locator{NodeID: &box.ID}, Name: "picture.png", File: &filesystem.InlineFile{Content: picture.Bytes(), MediaType: "image/png"}})
	require.NoError(t, err)
	body := "artifact needle\r\nlast line"
	_, err = db.Exec(t.Context(), `INSERT INTO nodes(id,scope_id,parent_id,name,kind,size_bytes) VALUES($1,$2,$3,'report.md','file',$4)`, artifact, scope, source.ID, len(body))
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `INSERT INTO files(node_id,storage_kind,media_type,text_content,newline_count,text_sha256) VALUES($1,'text','text/markdown',$2,1,encode(sha256(convert_to($2,'UTF8')),'hex'))`, artifact, body)
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `UPDATE filesystems SET used_bytes=used_bytes+$2,node_count=node_count+1 WHERE id=$1`, fs, len(body))
	require.NoError(t, err)
	const token = "isolated-mirage-native-fixture-token-123456"
	authentication, err := rpc.NewAuthenticator([]rpc.Credential{LetaCredential(token)})
	require.NoError(t, err)
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	server := grpcgo.NewServer(grpcgo.UnaryInterceptor(authentication.Unary()))
	letfsv1.RegisterFilesystemServiceServer(server, &Filesystem{Store: store, Service: &filesystem.Service{Store: store}})
	done := make(chan error, 1)
	go func() { done <- server.Serve(listener) }()
	t.Cleanup(func() { server.Stop(); require.NoError(t, <-done) })
	fixture, err := json.Marshal(map[string]string{"address": listener.Addr().String(), "token": token, "filesystem_id": fs.String(), "scope_id": scope.String(), "root_id": box.ID.String(), "scope_root_id": scopes[0].RootID.String(), "leta_id": leta.String(), "source_id": source.ID.String(), "graph_address": graphAddress, "graph_key": sharedfixture.SpiceDBKey, "database_url": db.Config().ConnString()})
	require.NoError(t, err)
	root, err := filepath.Abs("../../../../..")
	require.NoError(t, err)
	command := exec.CommandContext(t.Context(), "uv", "run", "--locked", "--package", "leta", "pytest", "apps/leta/tests/integration/test_mirage_letfs.py", "apps/leta/tests/integration/test_mirage_cache_permissions.py", "apps/leta/tests/test_filesystem_tools.py", "-q")
	command.Dir = root
	command.Env = append(os.Environ(), "OPENLET_TEST_LETFS_FIXTURE="+string(fixture))
	output, err := command.CombinedOutput()
	t.Log(string(output))
	require.NoError(t, err)
}
