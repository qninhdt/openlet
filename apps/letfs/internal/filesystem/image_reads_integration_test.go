//go:build integration

package filesystem

import (
	"bytes"
	"image"
	"image/png"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/clients/storage"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/identity"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
	"golang.org/x/sync/semaphore"
)

func TestIntegrationImageReadRechecksSourceAndPermission(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	s := Store{DB: db, Graph: graph, MaxNodes: 100, InlineLimit: 1048576, MaxFileBytes: 104857600, ImageSlots: semaphore.NewWeighted(2)}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "workspace"})
	user, fs, scope := uuid.New(), uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{ActorKind: identity.User, ActorID: user, Service: "gateway", Gateway: true})
	_, err := s.CreateFilesystem(owner, uuid.New(), CreateFilesystem{ID: fs, LimitBytes: 1 << 24})
	require.NoError(t, err)
	scopes, err := s.CreateScopes(owner, uuid.New(), fs, []uuid.UUID{scope}, true, true)
	require.NoError(t, err)
	testfixture.Grant(t, graph, "scope", scope, user, authz.ScopeWrite)
	var source bytes.Buffer
	require.NoError(t, png.Encode(&source, image.NewNRGBA(image.Rect(0, 0, 2, 3))))
	node, err := s.CreateNode(ctx, scope, uuid.New(), CreateNode{Parent: Locator{NodeID: scopes[0].RootID}, Name: "photo.png", File: &InlineFile{Content: source.Bytes(), MediaType: "image/png"}})
	require.NoError(t, err)
	loc := Locator{NodeID: &node.ID}
	metadata, err := s.ReadText(ctx, scope, loc, TextSelection{Kind: "whole"}, nil)
	require.NoError(t, err)
	require.Equal(t, "blob_metadata", metadata.Stat.RepresentationKind)
	require.NotEqual(t, source.Bytes(), metadata.Content)
	preview, err := s.ReadImage(ctx, scope, loc, &metadata.Stat.Fingerprint)
	require.NoError(t, err)
	require.Equal(t, 2, preview.Width)
	require.Equal(t, 3, preview.Height)
	require.NoError(t, s.ImageSlots.Acquire(ctx, 2))
	_, err = s.ReadImage(ctx, scope, loc, nil)
	require.Equal(t, "RESOURCE_LIMIT", reason(err))
	s.ImageSlots.Release(2)
	_, err = s.ReadImage(ctx, scope, loc, ptr("stale"))
	require.Equal(t, "CONTENT_CHANGED", reason(err))
	require.True(t, s.ImageSlots.TryAcquire(2))
	s.ImageSlots.Release(2)
	var mode atomic.Int32
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch mode.Load() {
		case 1:
			_, e := db.Exec(r.Context(), `UPDATE nodes SET revision=revision+1 WHERE id=$1`, node.ID)
			if e != nil {
				http.Error(w, "update failed", 500)
				return
			}
		case 2:
			_, e := graph.WriteRelationships(r.Context(), &v1.WriteRelationshipsRequest{Updates: []*v1.RelationshipUpdate{{Operation: v1.RelationshipUpdate_OPERATION_DELETE, Relationship: &v1.Relationship{Resource: &v1.ObjectReference{ObjectType: "scope", ObjectId: scope.String()}, Relation: "editor", Subject: &v1.SubjectReference{Object: &v1.ObjectReference{ObjectType: "user", ObjectId: user.String()}}}}}})
			if e != nil {
				http.Error(w, "revoke failed", 500)
				return
			}
		}
		_, _ = w.Write(source.Bytes())
	}))
	defer remote.Close()
	s.Storage, err = storage.New(storage.Config{Endpoint: remote.URL, Region: "test", Bucket: "isolated", AccessKey: "test", SecretKey: "isolated-secret", AllowHTTP: true})
	require.NoError(t, err)
	_, err = db.Exec(ctx, `UPDATE files SET storage_kind='object',inline_bytes=NULL,object_key='private-image' WHERE node_id=$1`, node.ID)
	require.NoError(t, err)
	preview, err = s.ReadImage(ctx, scope, loc, nil)
	require.NoError(t, err)
	require.Equal(t, 3, preview.Height)
	mode.Store(1)
	_, err = s.ReadImage(ctx, scope, loc, nil)
	require.Equal(t, "CONTENT_CHANGED", reason(err))
	mode.Store(2)
	_, err = s.ReadImage(ctx, scope, loc, nil)
	require.Equal(t, "FORBIDDEN", reason(err))
	require.True(t, s.ImageSlots.TryAcquire(2))
	s.ImageSlots.Release(2)
}
