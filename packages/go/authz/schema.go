package authz

import (
	"context"
	"errors"
	"strings"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

var ErrSchemaMismatch = errors.New("authorization schema differs from the expected contract")

// VerifySchema is read-only and belongs in dependency readiness checks.
func VerifySchema(ctx context.Context, client v1.SchemaServiceClient, expected string) error {
	if strings.TrimSpace(expected) == "" {
		return ErrSchemaMismatch
	}
	response, err := client.ReadSchema(ctx, &v1.ReadSchemaRequest{})
	if err != nil {
		return err
	}
	if strings.TrimSpace(response.SchemaText) != strings.TrimSpace(expected) {
		return ErrSchemaMismatch
	}
	return nil
}

// InitializeSchema runs under exclusive deployment/operator ownership, before writers start.
// Existing schemas require an explicit migration; startup cannot overwrite unknown policy.
func InitializeSchema(ctx context.Context, client v1.SchemaServiceClient, expected string) error {
	err := VerifySchema(ctx, client, expected)
	if status.Code(err) != codes.NotFound {
		return err
	}
	if _, err := client.WriteSchema(ctx, &v1.WriteSchemaRequest{Schema: expected}); err != nil {
		return err
	}
	return VerifySchema(ctx, client, expected)
}
