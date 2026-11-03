package config

import (
	"os"
	"strings"
)

// Secret gives file-backed configuration precedence, including unreadable files.
func Secret(key string) string {
	if path := os.Getenv(key + "_FILE"); path != "" {
		value, err := os.ReadFile(path)
		if err != nil {
			return ""
		}
		return strings.TrimSpace(string(value))
	}
	return os.Getenv(key)
}
