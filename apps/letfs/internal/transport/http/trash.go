package httpapi

import (
	"net/http"
	"strings"
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
	entry, err := s.Service.TrashNode(r.Context(), fs, locator, rev)
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
	node, err := s.Service.RestoreTrash(r.Context(), fs, id)
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
	entry, err := s.Service.PurgeTrash(r.Context(), fs, id)
	if err != nil {
		return err
	}
	if entry == nil {
		w.Header().Set("Cache-Control", "no-store")
		w.WriteHeader(http.StatusNoContent)
		return nil
	}
	respond(w, r, http.StatusAccepted, trashResponseFrom(*entry))
	return nil
}
