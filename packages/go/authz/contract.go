package authz

import (
	"context"
	"errors"
	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"os"
	"strings"
)

type Contract struct{ schema string }

func LoadContract(schemaPath string) (*Contract, error) {
	schema, err := os.ReadFile(schemaPath)
	if err != nil || strings.TrimSpace(string(schema)) == "" {
		return nil, errors.New("expected authorization schema file is unavailable or empty")
	}
	return &Contract{schema: string(schema)}, nil
}

// Verify is read-only: readiness must never initialize policy.
func (c *Contract) Verify(ctx context.Context, schema v1.SchemaServiceClient) error {
	return VerifySchema(ctx, schema, c.schema)
}
