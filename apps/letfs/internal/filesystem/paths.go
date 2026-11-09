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

type Locator struct {
	NodeID           *uuid.UUID `json:"node_id,omitempty"`
	Path             *string    `json:"path,omitempty"`
	CwdID            *uuid.UUID `json:"cwd_id,omitempty"`
	ExpectedNodeID   *uuid.UUID `json:"expected_node_id,omitempty"`
	ExpectedParentID *uuid.UUID `json:"expected_parent_id,omitempty"`
	RootID           *uuid.UUID `json:"root_id,omitempty"`
}

func nodeAlias(name string) (uuid.UUID, bool) {
	if !strings.HasPrefix(name, "@") {
		return uuid.Nil, false
	}
	id, err := uuid.Parse(name[1:])
	return id, err == nil && strings.EqualFold(id.String(), name[1:])
}

func pathParts(locator Locator) ([]string, error) {
	invalid := func() error { return apperr.New(apperr.Invalid, "VALIDATION", "invalid locator") }
	for _, id := range []*uuid.UUID{locator.NodeID, locator.CwdID, locator.ExpectedNodeID, locator.ExpectedParentID, locator.RootID} {
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

func (s *session) resolve(ctx context.Context, locators []Locator) ([]Node, error) {
	if len(locators) == 0 || len(locators) > 100 {
		return nil, apperr.New(apperr.Invalid, "VALIDATION", "locator batch must contain 1..100 items")
	}
	type request struct {
		Index int       `json:"idx"`
		Start uuid.UUID `json:"start_id"`
		Parts []string  `json:"parts"`
		Root  uuid.UUID `json:"root_id"`
	}
	requests := make([]request, len(locators))
	for i, locator := range locators {
		parts, err := pathParts(locator)
		if err != nil {
			return nil, err
		}
		root := s.root
		if locator.RootID != nil {
			root = *locator.RootID
		}
		start := root
		if locator.NodeID != nil {
			start = *locator.NodeID
		} else if locator.CwdID != nil {
			start = *locator.CwdID
		}
		if locator.Path != nil && start == root && len(parts) > 0 {
			if alias, ok := nodeAlias(parts[0]); ok {
				start, parts = alias, parts[1:]
			}
		}
		requests[i] = request{i, start, parts, root}
	}
	encoded, err := json.Marshal(requests)
	if err != nil {
		return nil, err
	}
	// One bounded statement shares liveness and provenance with every locator's walk.
	rows, err := s.tx.Query(ctx, `WITH RECURSIVE req AS (
 SELECT * FROM jsonb_to_recordset($3) AS x(idx int,start_id uuid,parts text[],root_id uuid)
), roots(idx,id,parent_id,kind,depth) AS (
 SELECT r.idx,n.id,n.parent_id,n.kind,0 FROM req r JOIN nodes n ON n.id=r.root_id AND n.scope_id=$1 AND n.kind='directory'
 UNION ALL SELECT a.idx,n.id,n.parent_id,n.kind,a.depth+1 FROM roots a JOIN nodes n ON n.id=a.parent_id AND n.scope_id=$1 WHERE a.id<>$2 AND a.depth<128
), valid_roots AS (
 SELECT idx FROM roots GROUP BY idx HAVING bool_or(id=$2) AND NOT bool_or(depth>0 AND kind='file')
), ancestors(idx,id,parent_id,depth) AS (
 SELECT r.idx,n.id,n.parent_id,0 FROM req r JOIN nodes n ON n.id=r.start_id AND n.scope_id=$1
 UNION ALL SELECT a.idx,n.id,n.parent_id,a.depth+1 FROM ancestors a JOIN nodes n ON n.id=a.parent_id AND n.scope_id=$1 WHERE a.id<>$2 AND a.depth<128
), live AS (
 SELECT a.idx FROM ancestors a JOIN req r USING(idx) GROUP BY a.idx HAVING bool_or(a.id=$2) AND bool_or(a.id=r.root_id)
), walk(idx,pos,id,parent_id,kind) AS (
 SELECT r.idx,0,n.id,n.parent_id,n.kind FROM req r JOIN live l USING(idx) JOIN valid_roots v USING(idx) JOIN nodes n ON n.id=r.start_id AND n.scope_id=$1
 UNION ALL SELECT w.idx,w.pos+1,n.id,n.parent_id,n.kind FROM walk w JOIN req r USING(idx)
 JOIN nodes n ON n.scope_id=$1 AND ((r.parts[w.pos+1]='..' AND n.id=w.parent_id AND w.id<>r.root_id)
 OR (r.parts[w.pos+1]<>'..' AND n.parent_id=w.id AND n.name=r.parts[w.pos+1]))
 WHERE w.pos<cardinality(r.parts)
), resolved AS (
 SELECT r.idx,n.* FROM walk w JOIN req r USING(idx) JOIN nodes n ON n.id=w.id AND n.scope_id=$1 WHERE w.pos=cardinality(r.parts)
), provenance(idx,id,parent_id,kind,depth) AS (
 SELECT idx,id,parent_id,kind,0 FROM resolved
 UNION ALL SELECT a.idx,n.id,n.parent_id,n.kind,a.depth+1 FROM provenance a
 JOIN nodes n ON n.id=a.parent_id AND n.scope_id=$1 WHERE a.id<>$2 AND a.depth<128
)
SELECT n.idx,`+nodeColumns+`,p.artifact_readonly FROM resolved n JOIN (
 SELECT idx,bool_or(depth>0 AND kind='file') AS artifact_readonly FROM provenance GROUP BY idx
) p USING(idx) LEFT JOIN files f ON f.node_id=n.id ORDER BY n.idx`, s.scopeID, s.root, encoded)
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

func (s *session) resolveOne(ctx context.Context, locator Locator) (Node, error) {
	nodes, err := s.resolve(ctx, []Locator{locator})
	if err != nil {
		return Node{}, err
	}
	return nodes[0], nil
}
