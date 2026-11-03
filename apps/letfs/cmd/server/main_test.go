package main

import (
	"context"
	"strings"
	"testing"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"openlet/apps/letfs/internal/config"
	letfsv1 "openlet/packages/go/gen/openlet_api/letfs/v1"
	"openlet/packages/go/identity"
)

func TestAuthenticationSeparatesPublicStreamsAndOwnerAdministration(t *testing.T) {
	cfg := config.Config{GatewayToken: strings.Repeat("g", 32), WorkspaceToken: strings.Repeat("w", 32), IngestToken: strings.Repeat("i", 32)}
	auth, err := authentication(cfg)
	require.NoError(t, err)
	actor := uuid.New()
	browser := metadata.NewIncomingContext(context.Background(), metadata.Pairs("authorization", "Bearer "+cfg.GatewayToken, "x-openlet-user-id", actor.String()))
	ctx, err := auth.Authenticate(browser, letfsv1.FilesystemService_StreamArchive_FullMethodName)
	require.NoError(t, err)
	principal, ok := identity.FromContext(ctx)
	require.True(t, ok)
	require.Equal(t, actor, principal.ActorID)
	_, err = auth.Authenticate(browser, letfsv1.StorageAdministrationService_CreateBucket_FullMethodName)
	require.Equal(t, codes.PermissionDenied, status.Code(err))
	owner := metadata.NewIncomingContext(context.Background(), metadata.Pairs("authorization", "Bearer "+cfg.WorkspaceToken))
	_, err = auth.Authenticate(owner, letfsv1.FilesystemService_StreamArchive_FullMethodName)
	require.Equal(t, codes.PermissionDenied, status.Code(err))
	_, err = auth.Authenticate(owner, letfsv1.StorageAdministrationService_CreateBucket_FullMethodName)
	require.NoError(t, err)
}

func TestIngestCredentialCannotUsePublicOrOwnerMethods(t *testing.T) {
	cfg := config.Config{GatewayToken: strings.Repeat("g", 32), WorkspaceToken: strings.Repeat("w", 32), IngestToken: strings.Repeat("i", 32)}
	auth, err := authentication(cfg)
	require.NoError(t, err)
	ingest := metadata.NewIncomingContext(t.Context(), metadata.Pairs("authorization", "Bearer "+cfg.IngestToken))
	ctx, err := auth.Authenticate(ingest, letfsv1.IngestService_PrepareParse_FullMethodName)
	require.NoError(t, err)
	principal, ok := identity.FromContext(ctx)
	require.True(t, ok)
	require.Equal(t, "ingest", principal.Service)
	require.False(t, principal.Gateway)
	for _, method := range []string{letfsv1.FilesystemService_GetNode_FullMethodName, letfsv1.StorageAdministrationService_CreateBucket_FullMethodName} {
		_, err = auth.Authenticate(ingest, method)
		require.Equal(t, codes.PermissionDenied, status.Code(err))
	}
	for _, token := range []string{cfg.GatewayToken, cfg.WorkspaceToken} {
		caller := metadata.NewIncomingContext(t.Context(), metadata.Pairs("authorization", "Bearer "+token))
		_, err = auth.Authenticate(caller, letfsv1.IngestService_PrepareParse_FullMethodName)
		require.Equal(t, codes.PermissionDenied, status.Code(err))
	}
}
