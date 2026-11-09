package filesystem

import (
	"bytes"
	"context"
	"encoding/json"
	"strings"
	"unicode/utf8"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"github.com/qninhdt/openlet/packages/go/authz"
)

type TextSearchInput struct {
	Locator                      Locator
	Mode, Text                   string
	IgnoreCase                   bool
	MaxFiles, MaxLines, MaxBytes *int32
}

type TextSearchResult struct {
	Items    []TreeEntry
	Content  []byte
	Stat     *FileStat
	Complete bool
}

func literalPattern(text string) string {
	return "%" + strings.NewReplacer(`\`, `\\`, `%`, `\%`, `_`, `\_`).Replace(text) + "%"
}

func candidateLines(body []byte, text string, ignoreCase bool, maxLines, maxBytes int) ([]byte, bool) {
	if strings.ContainsRune(text, 0) {
		return []byte{}, true
	}
	all := ignoreCase || strings.ContainsAny(text, "\r\n")
	var result []byte
	count := 0
	for len(body) > 0 {
		n := bytes.IndexByte(body, '\n') + 1
		if n == 0 {
			n = len(body)
		}
		line := body[:n]
		if all || bytes.Contains(line, []byte(text)) {
			count++
			if count > maxLines || n > maxBytes-len(result) {
				return nil, false
			}
			result = append(result, line...)
		}
		body = body[n:]
	}
	return result, true
}

// Separate literal candidates keep GIN usable; joining files already excludes directories.
var textCandidatesSQL = `WITH RECURSIVE tree AS (
 SELECT n.*,''::text COLLATE "C" AS path,0 AS depth,$5::boolean AS readonly FROM nodes n WHERE n.scope_id=$1 AND n.id=$2
 UNION ALL SELECT n.*,CASE WHEN t.path='' THEN n.name ELSE t.path||'/'||n.name END,t.depth+1,t.readonly OR t.kind='file'
 FROM tree t JOIN nodes n ON n.parent_id=t.id AND n.scope_id=$1 WHERE t.depth<128
), candidates AS (
 SELECT node_id FROM files WHERE storage_kind='text' AND text_content LIKE $3 ESCAPE '\'
 UNION ALL SELECT node_id FROM files WHERE storage_kind IN ('inline','object')
)
 SELECT ` + strings.Replace(nodeColumns, "f.context", "NULL::text", 1) + `,n.readonly` + strings.Replace(metadataColumns, "EXISTS(", "f.storage_kind<>'text' AND EXISTS(", 1) + `,n.path
 FROM tree n JOIN files f ON f.node_id=n.id
 WHERE n.depth>0 AND n.id IN (SELECT node_id FROM candidates)
 ORDER BY n.path,n.id LIMIT $4`

func (s *Store) TextSearch(ctx context.Context, scope uuid.UUID, input TextSearchInput) (TextSearchResult, error) {
	maxFiles, maxLines, maxBytes := int32(MaxTreeEntries), int32(MaxReadBytes), int32(MaxReadBytes)
	if input.MaxFiles != nil {
		maxFiles = *input.MaxFiles
	}
	if input.MaxLines != nil {
		maxLines = *input.MaxLines
	}
	if input.MaxBytes != nil {
		maxBytes = *input.MaxBytes
	}
	if input.Mode != "files" && input.Mode != "lines" || len(input.Text) > 4096 || !utf8.ValidString(input.Text) || maxFiles < 1 || maxFiles > MaxTreeEntries || maxLines < 1 || maxLines > MaxReadBytes || maxBytes < 1 || maxBytes > MaxReadBytes {
		return TextSearchResult{}, apperr.New(apperr.Invalid, "VALIDATION", "invalid text search")
	}
	if _, err := s.authorize(ctx, scope, "scope", authz.ScopeReadContent); err != nil {
		return TextSearchResult{}, err
	}
	session, err := s.openSession(ctx, scope, false)
	if err != nil {
		return TextSearchResult{}, err
	}
	defer session.tx.Rollback(ctx)
	node, err := session.resolveOne(ctx, input.Locator)
	if err != nil {
		return TextSearchResult{}, err
	}
	if input.Locator.ExpectedNodeID != nil && *input.Locator.ExpectedNodeID != node.ID {
		return TextSearchResult{}, apperr.New(apperr.Precondition, "TARGET_MISMATCH", "target mismatch")
	}
	result := TextSearchResult{Items: []TreeEntry{}, Complete: true}
	if input.Mode == "lines" {
		if node.Kind != "file" {
			return TextSearchResult{}, apperr.New(apperr.Conflict, "NOT_FILE", "file required")
		}
		stat, body, err := session.fileRepresentation(ctx, node)
		if err != nil {
			if errorReason(err) != "RESOURCE_LIMIT" {
				return TextSearchResult{}, err
			}
			result.Complete = false
		} else {
			if stat.StorageKind == "text" {
				if err = session.tx.QueryRow(ctx, `SELECT convert_to(text_content,'UTF8') FROM files WHERE node_id=$1`, node.ID).Scan(&body); err != nil {
					return TextSearchResult{}, databaseError(err)
				}
			}
			if len(body) > MaxReadBytes || int64(len(body)) != stat.ReadableSize {
				return TextSearchResult{}, readLimit()
			}
			result.Content, result.Complete = candidateLines(body, input.Text, input.IgnoreCase, int(maxLines), int(maxBytes))
			if result.Complete {
				result.Stat = &stat
			}
		}
	} else if !strings.ContainsRune(input.Text, 0) {
		result, err = session.textCandidates(ctx, scope, node, input, int(maxFiles), int(maxBytes))
		if err != nil {
			return TextSearchResult{}, err
		}
	}
	// Permission changes must not release buffered paths or excerpts after long snapshot work.
	if _, err = s.authorize(ctx, scope, "scope", authz.ScopeReadContent); err != nil {
		return TextSearchResult{}, err
	}
	return result, nil
}

func (s *session) textCandidates(ctx context.Context, scope uuid.UUID, node Node, input TextSearchInput, maxFiles, maxBytes int) (TextSearchResult, error) {
	pattern := literalPattern(input.Text)
	// Unicode folding is delegated to Mirage; all eligible files are a safe candidate superset.
	if input.IgnoreCase {
		pattern = "%"
	}
	rows, err := s.tx.Query(ctx, textCandidatesSQL, scope, node.ID, pattern, maxFiles+1, node.readonly)
	if err != nil {
		return TextSearchResult{}, databaseError(err)
	}
	files := []fileMetadata{}
	for rows.Next() {
		var m fileMetadata
		if err = rows.Scan(append(m.fields(), &m.Path)...); err != nil {
			rows.Close()
			return TextSearchResult{}, databaseError(err)
		}
		if len(m.Path) > 4096 {
			rows.Close()
			return TextSearchResult{Items: []TreeEntry{}, Complete: false}, nil
		}
		files = append(files, m)
	}
	rows.Close()
	if err = rows.Err(); err != nil {
		return TextSearchResult{}, databaseError(err)
	}
	if len(files) > maxFiles {
		return TextSearchResult{Items: []TreeEntry{}, Complete: false}, nil
	}
	trees, err := s.artifactTrees(ctx, files)
	if err != nil {
		if errorReason(err) == "RESOURCE_LIMIT" {
			return TextSearchResult{Items: []TreeEntry{}, Complete: false}, nil
		}
		return TextSearchResult{}, err
	}
	result := TextSearchResult{Items: []TreeEntry{}, Complete: true}
	total := 0
	for _, m := range files {
		stat, _, err := representation(m, trees[m.Node.ID])
		if err != nil {
			if errorReason(err) == "RESOURCE_LIMIT" {
				return TextSearchResult{Items: []TreeEntry{}, Complete: false}, nil
			}
			return TextSearchResult{}, err
		}
		item := TreeEntry{Path: m.Path, Stat: stat}
		encoded, err := json.Marshal(item)
		if err != nil {
			return TextSearchResult{}, err
		}
		if len(encoded) > maxBytes-total {
			return TextSearchResult{Items: []TreeEntry{}, Complete: false}, nil
		}
		total += len(encoded)
		result.Items = append(result.Items, item)
	}
	return result, nil
}
