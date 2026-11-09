package workspace

import (
	"context"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
	pb "github.com/qninhdt/openlet/packages/go/gen/openlet_api/workspace/v1"
	"github.com/qninhdt/openlet/packages/go/identity"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc"
	"google.golang.org/grpc/metadata"
)

type scopeAPI struct {
	pb.WorkspaceServiceClient
	result *pb.ListAccessibleScopesResponse
	calls  int
	actor  identity.Actor
}

func (a *scopeAPI) ListAccessibleScopes(ctx context.Context, in *pb.ListAccessibleScopesRequest, _ ...grpc.CallOption) (*pb.ListAccessibleScopesResponse, error) {
	a.calls++
	md, _ := metadata.FromOutgoingContext(ctx)
	if value := md.Get("x-openlet-" + string(a.actor.Kind) + "-id"); len(value) != 1 || value[0] != a.actor.ID.String() {
		panic("typed actor not delegated")
	}
	deadline, ok := ctx.Deadline()
	if !ok || time.Until(deadline) > 20*time.Second {
		panic("unbounded scope request")
	}
	return a.result, nil
}

func TestAccessibleScopesValidatesSubjectVisibleItemsAndContinuation(t *testing.T) {
	ws, fs, root, scope, file := uuid.New(), uuid.New(), uuid.New(), uuid.New(), uuid.New()
	actor := identity.Actor{Kind: identity.Leta, ID: root}
	good := func() *pb.ListAccessibleScopesResponse {
		return &pb.ListAccessibleScopesResponse{WorkspaceId: ws.String(), FilesystemId: fs.String(), SubjectKind: "leta", SubjectId: root.String(), Items: []*pb.AccessibleScope{{Id: scope.String(), RootId: file.String(), Kind: "home", Rights: &pb.ScopeRights{ReadMetadata: true, ReadContent: true, Write: true}}}}
	}
	for _, test := range []struct {
		name   string
		mutate func(*pb.ListAccessibleScopesResponse)
	}{
		{"valid", func(*pb.ListAccessibleScopesResponse) {}},
		{"wrong workspace", func(r *pb.ListAccessibleScopesResponse) { r.WorkspaceId = fs.String() }},
		{"equal UUID different actor", func(r *pb.ListAccessibleScopesResponse) { r.SubjectKind = "user" }},
		{"missing metadata rights", func(r *pb.ListAccessibleScopesResponse) { r.Items[0].Rights.ReadMetadata = false }},
		{"missing rights", func(r *pb.ListAccessibleScopesResponse) { r.Items[0].Rights = nil }},
		{"duplicate scope", func(r *pb.ListAccessibleScopesResponse) { r.Items = append(r.Items, r.Items[0]) }},
		{"unknown kind", func(r *pb.ListAccessibleScopesResponse) { r.Items[0].Kind = "unknown" }},
		{"personal without owner", func(r *pb.ListAccessibleScopesResponse) { r.Items[0].Kind = "personal" }},
		{"invalid cursor", func(r *pb.ListAccessibleScopesResponse) { v := ""; r.NextCursor = &v }},
	} {
		t.Run(test.name, func(t *testing.T) {
			result := good()
			test.mutate(result)
			api := &scopeAPI{result: result, actor: actor}
			client := Client{API: api}
			out, err := client.ListAccessibleScopes(t.Context(), ws, actor, nil, 100, nil)
			if test.name == "valid" {
				require.NoError(t, err)
				require.True(t, out.Items[0].Rights.Write)
			} else {
				require.Error(t, err)
			}
		})
	}
	api := &scopeAPI{result: good(), actor: actor}
	client := Client{API: api}
	_, err := client.ListAccessibleScopes(t.Context(), ws, actor, nil, 101, nil)
	require.Error(t, err)
	require.Zero(t, api.calls)
	// Filtering all candidates may produce an empty page with a valid continuation.
	api.result.Items = nil
	next := strings.Repeat("a", 20)
	api.result.NextCursor = &next
	out, err := client.ListAccessibleScopes(t.Context(), ws, actor, nil, 100, nil)
	require.NoError(t, err)
	require.Empty(t, out.Items)
	require.Equal(t, next, *out.NextCursor)
}

func TestChangeScopeAccessRejectsNoncanonicalIDsBeforeRPC(t *testing.T) {
	value := "019a3b66-0000-7000-8000-000000000001"
	actor := identity.Actor{Kind: identity.User, ID: uuid.MustParse(value)}
	input := &pb.ChangeScopeAccessRequest{WorkspaceId: strings.ToUpper(value), ScopeId: value, GranteeKind: "leta", GranteeId: value, Role: "viewer", IdempotencyKey: value}
	_, err := (Client{}).ChangeScopeAccess(t.Context(), actor, input)
	require.Error(t, err, "invalid request must fail before touching an RPC connection")
}
