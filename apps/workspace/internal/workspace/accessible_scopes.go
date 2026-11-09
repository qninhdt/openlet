package workspace

import (
	"context"
	"encoding/base64"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/identity"
)

type AccessibleScope struct {
	ID           uuid.UUID    `json:"id"`
	RootID       uuid.UUID    `json:"root_id"`
	Kind         string       `json:"kind"`
	Owner        *UserSummary `json:"owner,omitempty"`
	ReadMetadata bool         `json:"read_metadata"`
	ReadContent  bool         `json:"read_content"`
	Write        bool         `json:"write"`
}

type AccessibleScopePage struct {
	WorkspaceID  uuid.UUID         `json:"workspace_id"`
	FilesystemID uuid.UUID         `json:"filesystem_id"`
	Subject      identity.Actor    `json:"subject"`
	Items        []AccessibleScope `json:"items"`
	NextCursor   *string           `json:"next_cursor"`
}

// Inspector is the current human viewing a Leta; native runtime discovery has none.
func (s *Service) AccessibleScopes(ctx context.Context, ws uuid.UUID, subject identity.Actor, inspector uuid.UUID, cursor *string, limit int32) (AccessibleScopePage, error) {
	if !subject.Valid() || ws == uuid.Nil || limit < 1 || limit > 100 ||
		(subject.Kind == identity.User && inspector != uuid.Nil && inspector != subject.ID) {
		return AccessibleScopePage{}, Fault{"VALIDATION"}
	}
	ctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	if inspector != uuid.Nil && subject.Kind == identity.Leta {
		if _, err := s.Store.Authorize(ctx, ws, inspector, authz.WorkspaceRead); err != nil {
			return AccessibleScopePage{}, err
		}
		if err := s.inspectLeta(ctx, subject.ID, inspector); err != nil {
			return AccessibleScopePage{}, err
		}
	}
	value, binding, err := s.resourceWorkspace(ctx, ws, subject)
	if err != nil {
		return AccessibleScopePage{}, err
	}
	prefix := "scopes/" + ws.String() + "/" + subject.String() + "/" + inspector.String() + "|"
	var storageCursor *string
	if cursor != nil {
		if len(*cursor) == 0 || len(*cursor) > 2048 {
			return AccessibleScopePage{}, Fault{"VALIDATION"}
		}
		decoded, err := base64.RawURLEncoding.DecodeString(*cursor)
		if err != nil {
			return AccessibleScopePage{}, Fault{"VALIDATION"}
		}
		token, ok := strings.CutPrefix(string(decoded), prefix)
		if !ok || token == "" || len(token) > 512 {
			return AccessibleScopePage{}, Fault{"VALIDATION"}
		}
		storageCursor = &token
	}
	if s.Storage == nil || s.Store.Graph == nil {
		return AccessibleScopePage{}, unavailable()
	}
	candidates, err := s.Storage.ListScopes(ctx, value.FilesystemID, limit, storageCursor)
	if err != nil {
		return AccessibleScopePage{}, err
	}
	result := AccessibleScopePage{WorkspaceID: ws, FilesystemID: value.FilesystemID, Subject: subject, Items: []AccessibleScope{}}
	if candidates.NextCursor != nil {
		next := base64.RawURLEncoding.EncodeToString([]byte(prefix + *candidates.NextCursor))
		result.NextCursor = &next
	}
	if len(candidates.Items) == 0 {
		return result, nil
	}
	resources := make([]authz.Resource, len(candidates.Items))
	for i, item := range candidates.Items {
		resources[i] = authz.Resource{Type: "scope", ID: item.ID.String()}
	}
	decisions := make([][]bool, 3)
	for i, action := range []authz.Action{authz.ScopeReadMetadata, authz.ScopeReadContent, authz.ScopeWrite} {
		check, stop := context.WithTimeout(ctx, 2*time.Second)
		decisions[i], err = authz.BulkCheck(check, s.Store.Graph, subject, action, resources)
		stop()
		if err != nil {
			return AccessibleScopePage{}, err
		}
	}
	ids := make([]uuid.UUID, 0, len(candidates.Items))
	for i, item := range candidates.Items {
		if !decisions[0][i] {
			continue
		}
		kind := "scope"
		if item.ID == value.SharedScopeID {
			kind = "shared"
		} else if binding != nil && item.ID == binding.HomeScopeID {
			kind = "home"
		}
		result.Items = append(result.Items, AccessibleScope{ID: item.ID, RootID: item.RootID, Kind: kind, ReadMetadata: true, ReadContent: decisions[1][i], Write: decisions[2][i]})
		ids = append(ids, item.ID)
	}
	if len(ids) == 0 {
		return result, nil
	}
	rows, err := s.Store.DB.Query(ctx, `SELECT personal_scope_id,user_id FROM workspace_members WHERE workspace_id=$1 AND personal_scope_id=ANY($2)`, ws, ids)
	if err != nil {
		return AccessibleScopePage{}, err
	}
	type owner struct{ Scope, User uuid.UUID }
	owners, err := pgx.CollectRows(rows, pgx.RowToStructByPos[owner])
	if err != nil {
		return AccessibleScopePage{}, err
	}
	if len(owners) == 0 {
		return result, nil
	}
	if s.Users == nil {
		return AccessibleScopePage{}, unavailable()
	}
	users := make([]uuid.UUID, len(owners))
	byScope := make(map[uuid.UUID]uuid.UUID, len(owners))
	for i, owner := range owners {
		users[i], byScope[owner.Scope] = owner.User, owner.User
	}
	profiles, err := s.Users.Summaries(ctx, users)
	if err != nil {
		return AccessibleScopePage{}, err
	}
	for i := range result.Items {
		item := &result.Items[i]
		if user, ok := byScope[item.ID]; ok {
			profile, ok := profiles[user]
			if !ok || profile.ID != user {
				return AccessibleScopePage{}, unavailable()
			}
			item.Kind, item.Owner = "personal", &profile
		}
	}
	return result, nil
}
