//go:build integration

package testfixture

import (
	"github.com/jackc/pgx/v5/pgxpool"
	sharedfixture "openlet/packages/go/testfixture"
	"testing"
)

func Postgres(t *testing.T) *pgxpool.Pool {
	t.Helper()
	return sharedfixture.Postgres(t, "../../migrations/0001_initial.sql")
}
