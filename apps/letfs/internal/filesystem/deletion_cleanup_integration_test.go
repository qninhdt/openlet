//go:build integration

package filesystem

import (
	"context"
	"errors"
	"testing"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/identity"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc"
)

type lostDeletionAcknowledgement struct {
	v1.PermissionsServiceClient
	fail bool
}

func (g *lostDeletionAcknowledgement) DeleteRelationships(ctx context.Context, in *v1.DeleteRelationshipsRequest, opts ...grpc.CallOption) (*v1.DeleteRelationshipsResponse, error) {
	response, err := g.PermissionsServiceClient.DeleteRelationships(ctx, in, opts...)
	if err == nil && g.fail {
		return nil, errors.New("lost graph acknowledgement")
	}
	return response, err
}
func TestIntegrationDeletionRetriesGraphAndPrunesOnlyUnreferencedStorage(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	failing := &lostDeletionAcknowledgement{PermissionsServiceClient: graph, fail: true}
	s := Store{DB: db, Graph: failing, MaxNodes: 100}
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{Service: "workspace"})
	fs, scope, actor := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7()), uuid.New()
	_, err := s.CreateFilesystem(ctx, uuid.New(), CreateFilesystem{ID: fs, LimitBytes: 100})
	require.NoError(t, err)
	_, err = s.CreateScopes(ctx, uuid.New(), fs, []uuid.UUID{scope}, true, true)
	require.NoError(t, err)
	testfixture.Grant(t, graph, "scope", scope, actor, authz.ScopePurge)
	testfixture.Grant(t, graph, "filesystem", fs, actor, authz.FilesystemDelete)
	require.Error(t, s.DeleteScopeData(ctx, fs, scope), "SQL completion is not graph acknowledgement")
	require.Error(t, s.RemoveFilesystem(ctx, fs))
	require.Error(t, s.PruneReceipts(ctx), "failed graph cleanup retains retry identity")
	failing.fail = false
	require.NoError(t, s.DeleteScopeData(ctx, fs, scope))
	require.NoError(t, s.RemoveFilesystem(ctx, fs))
	_, err = db.Exec(ctx, `INSERT INTO uploads(id,scope_id,actor_id,input,transport,expected_size,state) VALUES($1,$2,$3,'{}','inline',0,'aborted')`, uuid.New(), scope, actor)
	require.NoError(t, err)
	_, err = db.Exec(ctx, `INSERT INTO object_deletions(object_key,filesystem_id,state,open_writes) VALUES('ambiguous',$1,'deleted',1),('finished',$1,'deleted',0)`, fs)
	require.NoError(t, err)
	require.NoError(t, s.PruneReceipts(ctx))
	var count int
	require.NoError(t, db.QueryRow(ctx, `SELECT count(*) FROM scopes WHERE id=$1`, scope).Scan(&count))
	require.Zero(t, count)
	require.NoError(t, db.QueryRow(ctx, `SELECT count(*) FROM filesystems WHERE id=$1`, fs).Scan(&count))
	require.Equal(t, 1, count, "unresolved late write retains filesystem attribution")
	require.NoError(t, db.QueryRow(ctx, `SELECT count(*) FROM object_deletions WHERE object_key='finished'`).Scan(&count))
	require.Zero(t, count)
	// A known closed write can release its attribution; no guessed timeout clears it.
	_, err = db.Exec(ctx, `UPDATE object_deletions SET open_writes=0 WHERE object_key='ambiguous'`)
	require.NoError(t, err)
	require.NoError(t, s.PruneReceipts(ctx))
	require.NoError(t, db.QueryRow(ctx, `SELECT count(*) FROM filesystems WHERE id=$1`, fs).Scan(&count))
	require.Zero(t, count)
	require.NoError(t, s.DeleteScopeData(ctx, fs, scope))
	require.NoError(t, s.RemoveFilesystem(ctx, fs))
}

func TestIntegrationScopeDeletionCompletesOnlyAbortedUploadReceipts(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	s := Store{DB: db, MaxNodes: 100}
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	fs := uuid.Must(uuid.NewV7())
	_, err := s.CreateFilesystem(ctx, uuid.New(), CreateFilesystem{ID: fs, LimitBytes: 1000})
	require.NoError(t, err)
	scopes, err := s.CreateScopes(ctx, uuid.New(), fs, []uuid.UUID{uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())}, true, true)
	require.NoError(t, err)
	tests := []struct {
		name, state, operation string
		scope                  uuid.UUID
		wantExpired            bool
	}{
		{"open", "open", "create-upload", scopes[0].ID, true},
		{"aborted", "aborted", "create-upload", scopes[0].ID, true},
		{"finalized", "finalized", "create-upload", scopes[0].ID, false},
		{"foreign", "aborted", "create-upload", scopes[1].ID, false},
		{"other-operation", "aborted", "process-file", scopes[0].ID, false},
	}
	for _, test := range tests {
		id := uuid.New()
		_, err = db.Exec(ctx, `INSERT INTO uploads(id,scope_id,actor_id,input,transport,expected_size,state,result) VALUES($1,$2,$3,'{}','inline',0,$4,'{}')`, id, test.scope, uuid.New(), test.state)
		require.NoError(t, err)
		_, err = db.Exec(ctx, `INSERT INTO idempotency_keys(scope,operation,request_key,request_hash,result) VALUES('test',$1,$2,'hash',jsonb_build_object('id',$3::text))`, test.operation, test.name, id.String())
		require.NoError(t, err)
	}
	require.NoError(t, s.fenceScopeDeletion(ctx, scopes[0].ID))
	for _, test := range tests {
		var expired bool
		require.NoError(t, db.QueryRow(ctx, `SELECT expires_at IS NOT NULL FROM idempotency_keys WHERE scope='test' AND request_key=$1`, test.name).Scan(&expired))
		require.Equal(t, test.wantExpired, expired, test.name)
	}
	require.NoError(t, s.fenceScopeDeletion(ctx, scopes[0].ID), "repeat deletion remains a no-op")
}
