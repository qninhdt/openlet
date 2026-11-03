package authz

import (
	"context"
	"errors"
	"os"
	"strings"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
)

type Contract struct {
	schema string
	roles  []*v1.Relationship
}

func LoadContract(schemaPath, rolesPath string) (*Contract, error) {
	schema, err := os.ReadFile(schemaPath)
	if err != nil || strings.TrimSpace(string(schema)) == "" {
		return nil, errors.New("expected authorization schema file is unavailable or empty")
	}
	data, err := os.ReadFile(rolesPath)
	if err != nil {
		return nil, errors.New("expected authorization role policy file is unavailable")
	}
	roles, err := ParseRolePolicy(data)
	if err != nil {
		return nil, err
	}
	return &Contract{schema: string(schema), roles: roles}, nil
}

// Verify is read-only: application readiness must never initialize or repair policy.
func (c *Contract) Verify(ctx context.Context, schema v1.SchemaServiceClient, graph v1.PermissionsServiceClient) error {
	if err := VerifySchema(ctx, schema, c.schema); err != nil {
		return err
	}
	return VerifyRolePolicy(ctx, graph, c.roles)
}
