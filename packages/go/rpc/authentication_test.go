package rpc

import (
	"context"
	"testing"

	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/identity"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

func TestCallerAuthenticationAndMethodScope(t *testing.T) {
	const token = "isolated-public-gateway-credential-12345"
	const actor = "019a3b66-0000-7000-8000-000000000001"
	authentication, err := NewAuthenticator([]Credential{{Service: "gateway", Token: token, Gateway: true,
		Methods: []string{letfsv1.FilesystemService_GetNode_FullMethodName}}})
	require.NoError(t, err)
	for _, test := range []struct {
		name   string
		method string
		md     metadata.MD
		code   codes.Code
	}{
		{"missing", letfsv1.FilesystemService_GetNode_FullMethodName, nil, codes.Unauthenticated},
		{"bad token", letfsv1.FilesystemService_GetNode_FullMethodName, metadata.Pairs("authorization", "Bearer other"), codes.Unauthenticated},
		{"missing actor", letfsv1.FilesystemService_GetNode_FullMethodName, metadata.Pairs("authorization", "Bearer "+token), codes.Unauthenticated},
		{"duplicate actor", letfsv1.FilesystemService_GetNode_FullMethodName, metadata.Pairs("authorization", "Bearer "+token, "x-openlet-user-id", actor, "x-openlet-user-id", actor), codes.Unauthenticated},
		{"duplicate credential", letfsv1.FilesystemService_GetNode_FullMethodName, metadata.Pairs("authorization", "Bearer "+token, "authorization", "Bearer "+token, "x-openlet-user-id", actor), codes.Unauthenticated},
		{"spoofed service", letfsv1.FilesystemService_GetNode_FullMethodName, metadata.Pairs("authorization", "Bearer "+token, "x-openlet-user-id", actor, "x-openlet-service", "workspace"), codes.Unauthenticated},
		{"private method", letfsv1.StorageAdministrationService_CreateBucket_FullMethodName, metadata.Pairs("authorization", "Bearer "+token, "x-openlet-user-id", actor), codes.PermissionDenied},
		{"valid", letfsv1.FilesystemService_GetNode_FullMethodName, metadata.Pairs("authorization", "Bearer "+token, "x-openlet-user-id", actor), codes.OK},
	} {
		t.Run(test.name, func(t *testing.T) {
			ctx, err := authentication.Authenticate(metadata.NewIncomingContext(context.Background(), test.md), test.method)
			require.Equal(t, test.code, status.Code(err))
			if err == nil {
				principal, ok := identity.FromContext(ctx)
				require.True(t, ok)
				require.True(t, principal.Gateway)
				require.Equal(t, actor, principal.ActorID.String())
			}
		})
	}
}

func TestCredentialConfigurationCannotAliasGatewayAndService(t *testing.T) {
	credential := Credential{Service: "gateway", Token: "isolated-public-gateway-credential-12345",
		Methods: []string{letfsv1.FilesystemService_GetNode_FullMethodName}, Gateway: true}
	_, err := NewAuthenticator([]Credential{credential, credential})
	require.Error(t, err)
	credential.Token = ""
	_, err = NewAuthenticator([]Credential{credential})
	require.Error(t, err)
	_, err = NewAuthenticator(nil)
	require.Error(t, err)
}

func TestServiceCredentialsCannotImpersonateUsers(t *testing.T) {
	const ingest = "isolated-ingest-method-credential-12345"
	const workspace = "isolated-workspace-method-credential-12345"
	const actor = "019a3b66-0000-7000-8000-000000000001"
	authentication, err := NewAuthenticator([]Credential{
		{Service: "ingest", Token: ingest, Methods: []string{letfsv1.IngestService_PrepareParse_FullMethodName}},
		{Service: "workspace", Token: workspace, Methods: []string{letfsv1.StorageAdministrationService_CreateBucket_FullMethodName}},
	})
	require.NoError(t, err)
	for _, test := range []struct {
		name, token, method, actor, service string
		code                                codes.Code
	}{
		{"scoped ingest", ingest, letfsv1.IngestService_PrepareParse_FullMethodName, "", "ingest", codes.OK},
		{"ingest cannot impersonate", ingest, letfsv1.IngestService_PrepareParse_FullMethodName, actor, "", codes.PermissionDenied},
		{"ingest cannot use public methods", ingest, letfsv1.FilesystemService_GetNode_FullMethodName, "", "", codes.PermissionDenied},
		{"scoped administration", workspace, letfsv1.StorageAdministrationService_CreateBucket_FullMethodName, "", "workspace", codes.OK},
		{"workspace cannot impersonate", workspace, letfsv1.StorageAdministrationService_CreateBucket_FullMethodName, actor, "", codes.PermissionDenied},
		{"workspace cannot use ingest", workspace, letfsv1.IngestService_PrepareParse_FullMethodName, "", "", codes.PermissionDenied},
		{"workspace cannot use public methods", workspace, letfsv1.FilesystemService_GetNode_FullMethodName, actor, "", codes.PermissionDenied},
	} {
		t.Run(test.name, func(t *testing.T) {
			md := metadata.Pairs("authorization", "Bearer "+test.token)
			if test.actor != "" {
				md.Set("x-openlet-user-id", test.actor)
			}
			ctx, err := authentication.Authenticate(metadata.NewIncomingContext(t.Context(), md), test.method)
			require.Equal(t, test.code, status.Code(err))
			if err == nil {
				principal, ok := identity.FromContext(ctx)
				require.True(t, ok)
				require.False(t, principal.Gateway)
				require.Equal(t, test.service, principal.Service)
				require.Zero(t, principal.ActorID)
			}
		})
	}
}
