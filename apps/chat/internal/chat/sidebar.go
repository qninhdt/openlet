package chat

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/chat/v1"
)

type sidebarFolderJSON struct {
	ID       string  `json:"id"`
	Name     string  `json:"name"`
	ParentID *string `json:"parent_id,omitempty"`
	Order    int32   `json:"order"`
}

type sidebarLayoutJSON struct {
	Folders     []sidebarFolderJSON `json:"folders"`
	Assignments map[string]string   `json:"assignments"`
	Pins        []string            `json:"pins"`
	Order       []string            `json:"order"`
	Collapsed   []string            `json:"collapsed"`
}

func validateSidebarLayout(layout *pb.SidebarLayout) error {
	if layout == nil {
		return invalid("layout is required")
	}
	if len(layout.Folders) > 200 {
		return invalid("too many sidebar folders")
	}
	byID := make(map[string]*pb.SidebarFolder, len(layout.Folders))
	for _, f := range layout.Folders {
		if f.Id == "" || f.Name == "" {
			return invalid("folder id and name are required")
		}
		if _, dup := byID[f.Id]; dup {
			return invalid("duplicate folder id: " + f.Id)
		}
		byID[f.Id] = f
	}
	for _, f := range layout.Folders {
		depth := 1
		cur := f.ParentId
		visited := map[string]bool{f.Id: true}
		for cur != nil && *cur != "" {
			if visited[*cur] {
				return invalid("folder hierarchy contains a cycle")
			}
			visited[*cur] = true
			parent, ok := byID[*cur]
			if !ok {
				return invalid(fmt.Sprintf("folder %q references missing parent %q", f.Id, *cur))
			}
			depth++
			if depth > 3 {
				return invalid("sidebar folders support a maximum depth of 3")
			}
			cur = parent.ParentId
		}
	}
	for convID, folderID := range layout.Assignments {
		if _, err := uuid.Parse(convID); err != nil {
			return invalid("invalid conversation_id in assignments")
		}
		if _, ok := byID[folderID]; !ok {
			return invalid("assignment references unknown folder: " + folderID)
		}
	}
	return nil
}

func layoutToJSON(l *pb.SidebarLayout) ([]byte, error) {
	j := sidebarLayoutJSON{
		Folders:     make([]sidebarFolderJSON, 0, len(l.Folders)),
		Assignments: l.Assignments,
		Pins:        l.Pins,
		Order:       l.Order,
		Collapsed:   l.Collapsed,
	}
	if j.Assignments == nil {
		j.Assignments = map[string]string{}
	}
	if j.Pins == nil {
		j.Pins = []string{}
	}
	if j.Order == nil {
		j.Order = []string{}
	}
	if j.Collapsed == nil {
		j.Collapsed = []string{}
	}
	for _, f := range l.Folders {
		j.Folders = append(j.Folders, sidebarFolderJSON{
			ID:       f.Id,
			Name:     f.Name,
			ParentID: f.ParentId,
			Order:    f.Order,
		})
	}
	return json.Marshal(j)
}

func layoutFromJSON(raw []byte) *pb.SidebarLayout {
	var j sidebarLayoutJSON
	_ = json.Unmarshal(raw, &j)
	out := &pb.SidebarLayout{
		Folders:     make([]*pb.SidebarFolder, 0, len(j.Folders)),
		Assignments: j.Assignments,
		Pins:        j.Pins,
		Order:       j.Order,
		Collapsed:   j.Collapsed,
	}
	if out.Assignments == nil {
		out.Assignments = map[string]string{}
	}
	for _, f := range j.Folders {
		out.Folders = append(out.Folders, &pb.SidebarFolder{
			Id:       f.ID,
			Name:     f.Name,
			ParentId: f.ParentID,
			Order:    f.Order,
		})
	}
	return out
}

func filterLayoutToAccessible(l *pb.SidebarLayout, allowed map[string]bool) *pb.SidebarLayout {
	if l == nil {
		return &pb.SidebarLayout{Assignments: map[string]string{}}
	}
	filteredAssign := make(map[string]string, len(l.Assignments))
	for cid, fid := range l.Assignments {
		if allowed[cid] {
			filteredAssign[cid] = fid
		}
	}
	filteredPins := make([]string, 0, len(l.Pins))
	for _, cid := range l.Pins {
		if allowed[cid] {
			filteredPins = append(filteredPins, cid)
		}
	}
	filteredOrder := make([]string, 0, len(l.Order))
	for _, cid := range l.Order {
		if allowed[cid] {
			filteredOrder = append(filteredOrder, cid)
		}
	}
	return &pb.SidebarLayout{
		Folders:     l.Folders,
		Assignments: filteredAssign,
		Pins:        filteredPins,
		Order:       filteredOrder,
		Collapsed:   l.Collapsed,
	}
}

func (s *Server) userConversationSet(ctx context.Context, q queryer, workspaceID, userID string) (map[string]bool, error) {
	rows, err := q.Query(ctx,
		`SELECT conversation_id::text FROM conversation_members WHERE workspace_id=$1 AND actor_type='user' AND actor_id=$2`,
		workspaceID, userID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	set := map[string]bool{}
	for rows.Next() {
		var cid string
		if err = rows.Scan(&cid); err != nil {
			return nil, err
		}
		set[cid] = true
	}
	return set, rows.Err()
}

func (s *Server) GetSidebar(ctx context.Context, r *pb.GetSidebarRequest) (*pb.SidebarState, error) {
	caller, err := s.check(ctx, "workspace", r.WorkspaceId, "participate")
	if err != nil {
		return nil, err
	}
	if caller.Type != "user" {
		return nil, permissionDenied("sidebar is user-only")
	}
	var rev int32
	var raw []byte
	err = s.DB.QueryRow(ctx,
		`SELECT revision, layout FROM sidebar_layouts WHERE workspace_id=$1 AND user_id=$2`,
		r.WorkspaceId, caller.ID,
	).Scan(&rev, &raw)
	if err == pgx.ErrNoRows {
		return &pb.SidebarState{
			Revision: 0,
			Layout:   &pb.SidebarLayout{Assignments: map[string]string{}},
		}, nil
	}
	if err != nil {
		return nil, err
	}
	allowed, err := s.userConversationSet(ctx, s.DB, r.WorkspaceId, caller.ID)
	if err != nil {
		return nil, err
	}
	return &pb.SidebarState{
		Revision: rev,
		Layout:   filterLayoutToAccessible(layoutFromJSON(raw), allowed),
	}, nil
}

func (s *Server) UpdateSidebar(ctx context.Context, r *pb.UpdateSidebarRequest) (*pb.SidebarState, error) {
	caller, err := s.check(ctx, "workspace", r.WorkspaceId, "participate")
	if err != nil {
		return nil, err
	}
	if caller.Type != "user" {
		return nil, permissionDenied("sidebar is user-only")
	}
	if err = validateSidebarLayout(r.Layout); err != nil {
		return nil, err
	}
	raw, err := layoutToJSON(r.Layout)
	if err != nil {
		return nil, err
	}

	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)

	var newRev int32
	if r.Revision == 0 {
		err = tx.QueryRow(ctx,
			`INSERT INTO sidebar_layouts(workspace_id, user_id, revision, layout, updated_at)
			 VALUES($1, $2, 1, $3::jsonb, now())
			 ON CONFLICT (workspace_id, user_id) DO NOTHING
			 RETURNING revision`,
			r.WorkspaceId, caller.ID, string(raw),
		).Scan(&newRev)
		if err == pgx.ErrNoRows {
			return nil, conflict("sidebar revision conflict")
		}
		if err != nil {
			return nil, err
		}
	} else {
		err = tx.QueryRow(ctx,
			`UPDATE sidebar_layouts
			 SET revision = revision + 1, layout = $4::jsonb, updated_at = now()
			 WHERE workspace_id=$1 AND user_id=$2 AND revision=$3
			 RETURNING revision`,
			r.WorkspaceId, caller.ID, r.Revision, string(raw),
		).Scan(&newRev)
		if err == pgx.ErrNoRows {
			return nil, conflict("sidebar revision conflict")
		}
		if err != nil {
			return nil, err
		}
	}

	if err = insertOutbox(ctx, tx, "centrifugo", r.WorkspaceId, nil, userChannel(caller.ID), "sidebar.updated", map[string]any{
		"workspace_id": r.WorkspaceId,
		"revision":     newRev,
		"layout":       json.RawMessage(raw),
	}); err != nil {
		return nil, err
	}
	if err = notifyOutbox(ctx, tx); err != nil {
		return nil, err
	}
	if err = tx.Commit(ctx); err != nil {
		return nil, err
	}
	return &pb.SidebarState{
		Revision: newRev,
		Layout:   r.Layout,
	}, nil
}
