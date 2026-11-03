package shared_test

import (
	"go/parser"
	"go/token"
	"io/fs"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

// Enforce dependency direction so a transport type cannot spread back into operations.
func TestServiceDependencyBoundaries(t *testing.T) {
	root := "../.."
	for _, directory := range []string{"apps/account/internal", "apps/workspace/internal", "apps/letfs/internal", "packages/go"} {
		err := filepath.WalkDir(filepath.Join(root, directory), func(path string, entry fs.DirEntry, err error) error {
			if err != nil {
				return err
			}
			if entry.IsDir() {
				return nil
			}
			if !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") {
				return nil
			}
			source, err := parser.ParseFile(token.NewFileSet(), path, nil, parser.ImportsOnly)
			if err != nil {
				return err
			}
			relative, err := filepath.Rel(root, path)
			if err != nil {
				return err
			}
			relative = filepath.ToSlash(relative)
			business := strings.HasPrefix(relative, "apps/account/internal/user/") || strings.HasPrefix(relative, "apps/workspace/internal/workspace/") || strings.HasPrefix(relative, "apps/letfs/internal/filesystem/")
			adapter := strings.Contains(relative, "/transport/http/") || strings.Contains(relative, "/temporal/")
			for _, dependency := range source.Imports {
				name, err := strconv.Unquote(dependency.Path.Value)
				if err != nil {
					return err
				}
				forbidden := strings.Contains(name, "/internal/app") || strings.Contains(name, "/internal/jobs")
				if strings.HasPrefix(relative, "packages/go/") {
					forbidden = forbidden || strings.Contains(name, "openlet/apps/")
				}
				if business {
					forbidden = forbidden || name == "net/http" || strings.HasPrefix(name, "github.com/gin-gonic/") || strings.HasPrefix(name, "go.temporal.io/")
				}
				if business || adapter {
					forbidden = forbidden || strings.Contains(name, "/gen/openlet_api/") || strings.HasPrefix(name, "google.golang.org/grpc")
				}
				if forbidden {
					t.Errorf("%s imports forbidden dependency %s", relative, name)
				}
			}
			return nil
		})
		if err != nil {
			t.Fatal(err)
		}
	}
}
