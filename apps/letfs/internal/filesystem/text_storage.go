package filesystem

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"path"
	"strings"
	"unicode/utf8"
)

type inlinePayload struct {
	Kind         string
	Bytes        []byte
	Text         *string
	NewlineCount *int64
	SHA256       *string
}

func textCandidate(name, mediaType string, allowBlobFiles bool) bool {
	if !allowBlobFiles {
		return true
	}
	format, _ := processingFormat(name)
	if format != "" && format != "text" && format != "csv" {
		return false
	}
	switch strings.ToLower(path.Ext(name)) {
	case ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar":
		return false
	}
	mediaType, _, _ = strings.Cut(strings.ToLower(mediaType), ";")
	mediaType = strings.TrimSpace(mediaType)
	if strings.HasPrefix(mediaType, "image/") || strings.HasPrefix(mediaType, "audio/") || strings.HasPrefix(mediaType, "video/") || strings.HasPrefix(mediaType, "font/") {
		return false
	}
	switch mediaType {
	case "application/pdf", "application/zip", "application/gzip", "application/x-tar":
		return false
	case "application/json", "application/jsonl", "application/xml", "application/yaml", "application/x-yaml", "application/javascript", "application/sql", "application/toml":
		return true
	}
	return format == "text" || format == "csv" || strings.HasPrefix(mediaType, "text/") || strings.HasSuffix(mediaType, "+json") || strings.HasSuffix(mediaType, "+xml")
}

// Classification preserves exact bytes; textual MIME alone cannot turn invalid UTF-8 into TEXT.
func (s *Store) classifyInline(name, mediaType string, content []byte, allowBlobFiles bool) inlinePayload {
	if content == nil {
		content = []byte{}
	}
	if int64(len(content)) > min(s.InlineLimit, s.MaxFileBytes) || !textCandidate(name, mediaType, allowBlobFiles) || !utf8.Valid(content) || bytes.IndexByte(content, 0) >= 0 {
		return inlinePayload{Kind: "inline", Bytes: content}
	}
	return textPayload(content)
}

func textPayload(content []byte) inlinePayload {
	text := string(content)
	lines := int64(bytes.Count(content, []byte{'\n'}))
	digest := sha256.Sum256(content)
	hash := hex.EncodeToString(digest[:])
	return inlinePayload{Kind: "text", Text: &text, NewlineCount: &lines, SHA256: &hash}
}
