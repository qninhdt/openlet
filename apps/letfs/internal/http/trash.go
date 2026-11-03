package httpapi

import (
	"net/http"
	"strings"

	letfsv1 "openlet/packages/go/gen/openlet_api/letfs/v1"
)

func (s *Server) trashNode(w http.ResponseWriter, r *http.Request) error {
	rev, err := revision(r)
	if err != nil {
		return err
	}
	result, err := s.API.TrashNode(r.Context(), &letfsv1.TrashNodeRequest{FilesystemId: fsID(r), Locator: nodeLocator(r.PathValue("node")), PathContext: pathContext(r), Revision: rev})
	if err != nil {
		return err
	}
	respond(w, r, 201, result.Entry)
	return nil
}
func (s *Server) listTrash(w http.ResponseWriter, r *http.Request) error {
	limit, cursor, err := pageInput(r)
	if err != nil {
		return err
	}
	result, err := s.API.ListTrash(r.Context(), &letfsv1.ListTrashRequest{FilesystemId: fsID(r), Limit: limit, Cursor: cursor})
	if err != nil {
		return err
	}
	respond(w, r, 200, result)
	return nil
}
func (s *Server) getTrash(w http.ResponseWriter, r *http.Request) error {
	result, err := s.API.GetTrash(r.Context(), &letfsv1.GetTrashRequest{FilesystemId: fsID(r), EntryId: r.PathValue("entry")})
	if err != nil {
		return err
	}
	respond(w, r, 200, result.Entry)
	return nil
}
func (s *Server) restoreTrash(w http.ResponseWriter, r *http.Request) error {
	entry, ok := strings.CutSuffix(r.PathValue("entry"), ":restore")
	if !ok {
		return invalid()
	}
	result, err := s.API.RestoreTrash(r.Context(), &letfsv1.RestoreTrashRequest{FilesystemId: fsID(r), EntryId: entry})
	if err != nil {
		return err
	}
	respond(w, r, 200, result.Node)
	return nil
}
func (s *Server) purgeTrash(w http.ResponseWriter, r *http.Request) error {
	result, err := s.API.PurgeTrash(r.Context(), &letfsv1.PurgeTrashRequest{FilesystemId: fsID(r), EntryId: r.PathValue("entry")})
	if err != nil {
		return err
	}
	if result.Entry == nil {
		w.Header().Set("Cache-Control", "no-store")
		w.WriteHeader(204)
	} else {
		respond(w, r, 202, result.Entry)
	}
	return nil
}
