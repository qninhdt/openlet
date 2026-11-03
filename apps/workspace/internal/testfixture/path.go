package testfixture

import (
	"path/filepath"
	"runtime"
)

func Path(parts ...string) string {
	_, file, _, _ := runtime.Caller(0)
	root := filepath.Clean(filepath.Join(filepath.Dir(file), "../../../.."))
	return filepath.Join(append([]string{root}, parts...)...)
}
