//go:build integration

package workspace

import (
	"context"
	"sync"
	"testing"
	"time"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc"
	"openlet/packages/go/authz"
)

type admissionClient struct {
	v1.PermissionsServiceClient
	check func(context.Context, *v1.CheckPermissionRequest) (*v1.CheckPermissionResponse, error)
}

func (c admissionClient) CheckPermission(ctx context.Context, request *v1.CheckPermissionRequest, _ ...grpc.CallOption) (*v1.CheckPermissionResponse, error) {
	return c.check(ctx, request)
}

func TestIntegrationActionAdmissionUsesGraphAndRechecksCanonicalRevision(t *testing.T) {
	ctx := t.Context()
	store := Store{DB: postgres(t), MaxWorkspaces: 10, MaxMembers: 10, QuotaLimit: 1024, InviteTTL: time.Hour}
	server := setupGraph(t, &store)
	graph := store.Graph
	owner, viewer := uuid.New(), uuid.New()
	created, err := store.EnsureWorkspace(ctx, CreateInput{ActorID: owner, Key: uuid.New(), Name: "Actions"}, "")
	require.NoError(t, err)
	id := created.Workspace.ID
	require.NoError(t, store.Activate(ctx, mapping(id)))
	syncGraph(t, &store, id)
	_, token, err := store.Invite(ctx, id, owner, "viewer@example.test", "viewer")
	require.NoError(t, err)
	_, err = store.AcceptInvite(ctx, viewer, token, []string{"viewer@example.test"})
	require.NoError(t, err)
	syncGraph(t, &store, id)
	current, err := store.Get(ctx, id, owner)
	require.NoError(t, err)
	name := "Graph owns actions"
	_, err = store.Update(ctx, id, viewer, current.Revision, UpdateInput{Name: &name})
	require.EqualError(t, err, "FORBIDDEN")

	// Changing only native action tuples changes admission; the SQL roles stay unchanged.
	_, err = graph.WriteRelationships(ctx, &v1.WriteRelationshipsRequest{Updates: []*v1.RelationshipUpdate{
		graphUpdate(v1.RelationshipUpdate_OPERATION_DELETE, "role", "owner", "workspace_update", "user", "*"),
		graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "role", "viewer", "workspace_update", "user", "*"),
	}})
	require.NoError(t, err)
	_, err = store.Update(ctx, id, owner, current.Revision, UpdateInput{Name: &name})
	require.EqualError(t, err, "FORBIDDEN", "canonical Owner is not a permission fallback")
	updated, err := store.Update(ctx, id, viewer, current.Revision, UpdateInput{Name: &name})
	require.NoError(t, err, "a graph-granted action does not require a local Owner role")
	require.Equal(t, "viewer", updated.Role)
	syncGraph(t, &store, id)
	_, err = store.Update(ctx, id, viewer, updated.Revision, UpdateInput{Name: &name, OwnerID: &owner})
	require.EqualError(t, err, "FORBIDDEN", "combined name/ownership update requires both actions")
	require.EqualError(t, store.ChangeMember(ctx, id, viewer, owner, "editor", false, updated.Revision), "FORBIDDEN")
	require.EqualError(t, store.ChangeMember(ctx, id, owner, owner, "", true, updated.Revision), "OWNER_TRANSFER_REQUIRED")
	_, err = store.Authorize(ctx, id, viewer, authz.MemberRead)
	require.NoError(t, err)
	_, err = store.Authorize(ctx, id, viewer, authz.MemberManage)
	require.EqualError(t, err, "FORBIDDEN")

	_, err = store.Authorize(ctx, id, viewer, authz.ContentRead)
	require.ErrorIs(t, err, authz.ErrInvalidCheck, "filesystem actions belong to letfs")

	store.Graph = admissionClient{PermissionsServiceClient: graph, check: func(ctx context.Context, request *v1.CheckPermissionRequest) (*v1.CheckPermissionResponse, error) {
		response, err := graph.CheckPermission(ctx, request)
		if err != nil {
			return nil, err
		}
		// A separate connection can commit while CheckPermission is in flight: no owner lock is held.
		_, err = store.DB.Exec(ctx, `UPDATE workspaces SET revision=revision+1 WHERE id=$1`, id)
		return response, err
	}}
	name = "Must not commit"
	_, err = store.Update(ctx, id, viewer, updated.Revision, UpdateInput{Name: &name})
	require.EqualError(t, err, "REVISION_MISMATCH")
	actual, err := store.Get(ctx, id, viewer)
	require.NoError(t, err)
	require.Equal(t, updated.Name, actual.Name)
	store.Graph = graph

	// A canceled native check also cannot change the canonical profile or member role.
	canceled, cancel := context.WithCancel(ctx)
	cancel()
	_, err = store.Update(canceled, id, viewer, actual.Revision, UpdateInput{Name: &name})
	require.Error(t, err)
	actual, err = store.Get(ctx, id, viewer)
	require.NoError(t, err)
	require.Equal(t, updated.Name, actual.Name)

	require.NoError(t, server.Stop(ctx, nil))
	_, err = store.Update(ctx, id, viewer, actual.Revision, UpdateInput{Name: &name})
	require.Error(t, err, "graph outage cannot fall back to SQL membership")
	actual, err = store.Get(ctx, id, viewer)
	require.NoError(t, err)
	require.Equal(t, updated.Name, actual.Name)
}

func TestIntegrationConcurrentOwnershipAndMemberChangesPreserveOneOwner(t *testing.T) {
	ctx := t.Context()
	store := Store{DB: postgres(t), MaxWorkspaces: 10, MaxMembers: 10, QuotaLimit: 1024}
	setupGraph(t, &store)
	for _, competing := range []string{"transfer", "leave", "remove"} {
		t.Run(competing, func(t *testing.T) {
			owner, first, second := uuid.New(), uuid.New(), uuid.New()
			admitted, err := store.EnsureWorkspace(ctx, CreateInput{ActorID: owner, Key: uuid.New(), Name: competing}, "")
			require.NoError(t, err)
			id := admitted.Workspace.ID
			storage := mapping(id)
			require.NoError(t, store.Activate(ctx, storage))
			_, err = store.DB.Exec(ctx, `INSERT INTO workspace_members(workspace_id,user_id,role) VALUES($1,$2,'editor'),($1,$3,'editor')`, id, first, second)
			require.NoError(t, err)
			syncGraph(t, &store, id)
			current, err := store.Get(ctx, id, owner)
			require.NoError(t, err)
			start := make(chan struct{})
			results := make(chan error, 2)
			var workers sync.WaitGroup
			workers.Go(func() {
				<-start
				_, err := store.Update(ctx, id, owner, current.Revision, UpdateInput{OwnerID: &first})
				results <- err
			})
			workers.Go(func() {
				<-start
				var err error
				switch competing {
				case "transfer":
					_, err = store.Update(ctx, id, owner, current.Revision, UpdateInput{OwnerID: &second})
				case "leave":
					err = store.ChangeMember(ctx, id, first, first, "", true, current.Revision)
				case "remove":
					err = store.ChangeMember(ctx, id, owner, first, "", true, current.Revision)
				}
				results <- err
			})
			close(start)
			workers.Wait()
			close(results)
			committed := 0
			for err := range results {
				if err == nil {
					committed++
				} else {
					require.EqualError(t, err, "REVISION_MISMATCH")
				}
			}
			require.Equal(t, 1, committed)
			var count int
			require.NoError(t, store.DB.QueryRow(ctx, `SELECT count(*) FROM workspace_members WHERE workspace_id=$1 AND role='owner'`, id).Scan(&count))
			require.Equal(t, 1, count)
			syncGraph(t, &store, id)
			members, err := store.Members(ctx, id, uuid.Nil, 10)
			require.NoError(t, err)
			for _, member := range members {
				allowed, err := authz.Check(ctx, store.Graph, member.UserID.String(), authz.WorkspaceTransfer, authz.Resource{Type: "workspace", ID: id.String()})
				require.NoError(t, err)
				require.Equal(t, member.Role == "owner", allowed)
			}
		})
	}
}
