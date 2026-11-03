package filesystem

import (
	"context"
	"encoding/json"
	"strings"
	"unicode/utf8"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/apperr"
)

const maxDepth = 128

type Mount struct {
	Path         string    `json:"path"`
	FilesystemID uuid.UUID `json:"filesystem_id"`
}

type Locator struct {
	NodeID           *uuid.UUID `json:"node_id,omitempty"`
	Path             *string    `json:"path,omitempty"`
	CwdID            *uuid.UUID `json:"cwd_id,omitempty"`
	ExpectedNodeID   *uuid.UUID `json:"expected_node_id,omitempty"`
	ExpectedParentID *uuid.UUID `json:"expected_parent_id,omitempty"`
}

func nodeAlias(name string) (uuid.UUID, bool) {
	if !strings.HasPrefix(name, "@") {
		return uuid.Nil, false
	}
	id, err := uuid.Parse(name[1:])
	return id, err == nil && strings.EqualFold(id.String(), name[1:])
}

func pathParts(fs uuid.UUID, mounts []Mount, locator Locator) ([]string, error) {
	invalid := func() error { return apperr.New(apperr.Invalid, "VALIDATION", "invalid locator or mount") }
	if len(mounts) == 0 || len(mounts) > 32 {
		return nil, invalid()
	}
	found := false
	seen := make(map[string]bool, len(mounts))
	for _, mount := range mounts {
		if mount.FilesystemID == uuid.Nil || !utf8.ValidString(mount.Path) || len(mount.Path) > 4096 || !strings.HasPrefix(mount.Path, "/") ||
			(mount.Path != "/" && strings.HasSuffix(mount.Path, "/")) || strings.ContainsRune(mount.Path, '\x00') || seen[mount.Path] {
			return nil, invalid()
		}
		for _, part := range strings.Split(mount.Path, "/") {
			if part == "." || part == ".." || len(part) > 255 {
				return nil, invalid()
			}
		}
		seen[mount.Path] = true
		found = found || mount.FilesystemID == fs
	}
	if !found {
		return nil, apperr.New(apperr.Missing, "NOT_FOUND", "resource not found")
	}
	for _, id := range []*uuid.UUID{locator.NodeID, locator.CwdID, locator.ExpectedNodeID, locator.ExpectedParentID} {
		if id != nil && *id == uuid.Nil {
			return nil, invalid()
		}
	}
	if locator.NodeID != nil {
		if locator.Path != nil || locator.CwdID != nil {
			return nil, invalid()
		}
		return []string{}, nil
	}
	if locator.Path == nil || *locator.Path == "" || len(*locator.Path) > 4096 || !utf8.ValidString(*locator.Path) || strings.ContainsRune(*locator.Path, '\x00') {
		return nil, invalid()
	}
	path := *locator.Path
	if strings.HasPrefix(path, "/") {
		if locator.CwdID != nil {
			return nil, invalid()
		}
		selected := -1
		for i, mount := range mounts {
			if path == mount.Path || strings.HasPrefix(path, mount.Path+"/") || mount.Path == "/" {
				if selected < 0 || len(mount.Path) > len(mounts[selected].Path) {
					selected = i
				}
			}
		}
		if selected < 0 {
			return nil, apperr.New(apperr.Missing, "NOT_FOUND", "resource not found")
		}
		if mounts[selected].FilesystemID != fs {
			return nil, apperr.New(apperr.Conflict, "CROSS_FILESYSTEM_UNSUPPORTED", "cross-filesystem operation unsupported")
		}
		path = path[len(mounts[selected].Path):]
	}
	parts := []string{}
	for _, part := range strings.Split(path, "/") {
		if part == "" || part == "." {
			continue
		}
		if len(part) > 255 || len(parts) == maxDepth {
			return nil, invalid()
		}
		parts = append(parts, part)
	}
	return parts, nil
}

func guard(locator Locator, id uuid.UUID, parent bool) error {
	if locator.Path == nil {
		return nil
	}
	expected := locator.ExpectedNodeID
	if parent {
		expected = locator.ExpectedParentID
	}
	if expected == nil {
		return apperr.New(apperr.Precondition, "PRECONDITION_REQUIRED", "expected identity required")
	}
	if *expected != id {
		return apperr.New(apperr.Precondition, "TARGET_MISMATCH", "target mismatch")
	}
	return nil
}

func (s *session) resolve(ctx context.Context, mounts []Mount, locators []Locator) ([]Node, error) {
	if len(locators) == 0 || len(locators) > 100 {
		return nil, apperr.New(apperr.Invalid, "VALIDATION", "locator batch must contain 1..100 items")
	}
	type request struct {
		Index int       `json:"idx"`
		Start uuid.UUID `json:"start_id"`
		Parts []string  `json:"parts"`
	}
	requests := make([]request, len(locators))
	for i, locator := range locators {
		parts, err := pathParts(s.fs, mounts, locator)
		if err != nil {
			return nil, err
		}
		start := s.root
		if locator.NodeID != nil {
			start = *locator.NodeID
		} else if locator.CwdID != nil {
			start = *locator.CwdID
		}
		if locator.Path != nil && start == s.root && len(parts) > 0 {
			if alias, ok := nodeAlias(parts[0]); ok {
				start, parts = alias, parts[1:]
			}
		}
		requests[i] = request{i, start, parts}
	}
	encoded, err := json.Marshal(requests)
	if err != nil {
		return nil, err
	}
	// One bounded statement shares liveness and provenance with every locator's walk.
	rows, err := s.tx.Query(ctx, `WITH RECURSIVE req AS (
 SELECT * FROM jsonb_to_recordset($3) AS x(idx int,start_id uuid,parts text[])
), ancestors(idx,id,parent_id,depth) AS (
 SELECT r.idx,n.id,n.parent_id,0 FROM req r JOIN nodes n ON n.id=r.start_id AND n.filesystem_id=$1
 UNION ALL SELECT a.idx,n.id,n.parent_id,a.depth+1 FROM ancestors a JOIN nodes n ON n.id=a.parent_id AND n.filesystem_id=$1 WHERE a.id<>$2 AND a.depth<128
), live AS (SELECT DISTINCT idx FROM ancestors WHERE id=$2), walk(idx,pos,id,parent_id,kind) AS (
 SELECT r.idx,0,n.id,n.parent_id,n.kind FROM req r JOIN live l USING(idx) JOIN nodes n ON n.id=r.start_id AND n.filesystem_id=$1
 UNION ALL SELECT w.idx,w.pos+1,n.id,n.parent_id,n.kind FROM walk w JOIN req r USING(idx)
 JOIN nodes n ON n.filesystem_id=$1 AND CASE WHEN r.parts[w.pos+1]='..' THEN n.id=w.parent_id AND w.id<>$2 ELSE n.parent_id=w.id AND n.name=r.parts[w.pos+1] END
 WHERE w.pos<cardinality(r.parts)
), resolved AS (
 SELECT r.idx,n.* FROM walk w JOIN req r USING(idx) JOIN nodes n ON n.id=w.id AND n.filesystem_id=$1 WHERE w.pos=cardinality(r.parts)
), provenance(idx,id,parent_id,kind,depth) AS (
 SELECT idx,id,parent_id,kind,0 FROM resolved
 UNION ALL SELECT a.idx,n.id,n.parent_id,n.kind,a.depth+1 FROM provenance a
 JOIN nodes n ON n.id=a.parent_id AND n.filesystem_id=$1 WHERE a.id<>$2 AND a.depth<128
)
SELECT n.idx,`+nodeColumns+`,p.artifact_readonly FROM resolved n JOIN (
 SELECT idx,bool_or(depth>0 AND kind='file') AS artifact_readonly FROM provenance GROUP BY idx
) p USING(idx) LEFT JOIN files f ON f.node_id=n.id ORDER BY n.idx`, s.fs, s.root, encoded)
	if err != nil {
		return nil, databaseError(err)
	}
	defer rows.Close()
	result := make([]Node, 0, len(locators))
	for rows.Next() {
		var index int
		var node Node
		if err = rows.Scan(append([]any{&index}, node.fields()...)...); err != nil {
			return nil, databaseError(err)
		}
		if index != len(result) {
			return nil, apperr.New(apperr.Missing, "NOT_FOUND", "resource not found")
		}
		result = append(result, node)
	}
	if err = rows.Err(); err != nil {
		return nil, databaseError(err)
	}
	if len(result) != len(locators) {
		return nil, apperr.New(apperr.Missing, "NOT_FOUND", "resource not found")
	}
	return result, nil
}

func (s *session) resolveOne(ctx context.Context, mounts []Mount, locator Locator) (Node, error) {
	nodes, err := s.resolve(ctx, mounts, []Locator{locator})
	if err != nil {
		return Node{}, err
	}
	return nodes[0], nil
}
