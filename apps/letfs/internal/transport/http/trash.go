package httpapi

import (
	"net/http"
	"strings"

	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
)

func (s *Server) trashNode(w http.ResponseWriter, r *http.Request) error {
	fs, err := s.requestContext(r)
	if err != nil {
		return err
	}
	locator, err := nodeLocator(r.PathValue("node"))
	if err != nil {
		return err
	}
	rev, err := revision(r)
	if err != nil {
		return err
	}
	entry, err := s.Service.TrashNode(r.Context(), fs, locator, rev, false)
	if err != nil {
		return err
	}
	respond(w, r, http.StatusCreated, trashResponseFrom(entry))
	return nil
}

func (s *Server) listTrash(w http.ResponseWriter, r *http.Request) error {
	fs, err := s.requestContext(r)
	if err != nil {
		return err
	}
	limit, cursor, err := pageInput(r)
	if err != nil {
		return err
	}
	page, err := s.Store.ListTrash(r.Context(), fs, cursor, limit)
	if err != nil {
		return err
	}
	items := make([]trashResponse, len(page.Items))
	for i, entry := range page.Items {
		items[i] = trashResponseFrom(entry)
	}
	respond(w, r, http.StatusOK, struct {
		Items      []trashResponse `json:"items"`
		NextCursor *string         `json:"next_cursor,omitempty"`
	}{items, page.NextCursor})
	return nil
}

func (s *Server) getTrash(w http.ResponseWriter, r *http.Request) error {
	fs, err := s.requestContext(r)
	if err != nil {
		return err
	}
	id, err := parseID(r.PathValue("entry"))
	if err != nil {
		return err
	}
	entry, err := s.Store.GetTrash(r.Context(), fs, id)
	if err != nil {
		return err
	}
	respond(w, r, http.StatusOK, trashResponseFrom(entry))
	return nil
}

func (s *Server) restoreTrash(w http.ResponseWriter, r *http.Request) error {
	raw, ok := strings.CutSuffix(r.PathValue("entry"), ":restore")
	if !ok {
		return invalid()
	}
	fs, err := s.requestContext(r)
	if err != nil {
		return err
	}
	id, err := parseID(raw)
	if err != nil {
		return err
	}
	var input struct {
		DestinationScopeID *string `json:"destination_scope_id,omitempty"`
		ParentID           *string `json:"parent_id,omitempty"`
		Name               *string `json:"name,omitempty"`
	}
	if r.ContentLength != 0 {
		if err = decodeJSON(w, r, &input); err != nil {
			return err
		}
	}
	destination, err := optionalUUID(input.DestinationScopeID)
	if err != nil {
		return err
	}
	restore := filesystem.RestoreTrash{DestinationScopeID: destination, Name: input.Name}
	if input.ParentID != nil {
		parent, err := nodeLocator(*input.ParentID)
		if err != nil {
			return err
		}
		restore.Parent = &parent
	}
	node, err := s.Service.RestoreTrash(r.Context(), fs, id, restore)
	if err != nil {
		return err
	}
	respond(w, r, http.StatusOK, nodeResponseFrom(node))
	return nil
}

func (s *Server) purgeTrash(w http.ResponseWriter, r *http.Request) error {
	fs, err := s.requestContext(r)
	if err != nil {
		return err
	}
	id, err := parseID(r.PathValue("entry"))
	if err != nil {
		return err
	}
	if err = s.Service.PurgeTrash(r.Context(), fs, id); err != nil {
		return err
	}
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(http.StatusNoContent)
	return nil
}
