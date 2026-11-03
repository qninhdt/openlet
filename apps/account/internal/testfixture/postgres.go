//go:build integration

package testfixture

import (
	"github.com/jackc/pgx/v5/pgxpool"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"path/filepath"
	"runtime"
	"testing"
)

func Postgres(t *testing.T) *pgxpool.Pool {
	t.Helper()
	_, file, _, _ := runtime.Caller(0)
	return sharedfixture.Postgres(t, filepath.Join(filepath.Dir(file), "../../migrations/0001_initial.sql"))
}
