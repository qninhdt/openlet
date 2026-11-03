package httpapi

import (
	"net/http"
	"strconv"
	"strings"

	"github.com/qninhdt/openlet/apps/letfs/internal/clients/storage"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	"github.com/qninhdt/openlet/packages/go/apperr"
)

func (s *Server) createUpload(w http.ResponseWriter, r *http.Request) error {
	var input struct {
		ParentID   *string `json:"parent_id,omitempty"`
		NodeID     *string `json:"node_id,omitempty"`
		Name       *string `json:"name,omitempty"`
		MediaType  string  `json:"media_type"`
		SizeBytes  string  `json:"size_bytes"`
		ContentMD5 *string `json:"content_md5,omitempty"`
	}
	if err := decodeJSON(w, r, &input); err != nil {
		return err
	}
	if (input.NodeID == nil) == (input.ParentID == nil) || input.NodeID != nil && input.Name != nil || input.ParentID != nil && input.Name == nil {
		return invalid()
	}
	size, err := strconv.ParseInt(input.SizeBytes, 10, 64)
	if err != nil || size < 0 || strconv.FormatInt(size, 10) != input.SizeBytes {
		return invalid()
	}
	fs, mounts, err := requestContext(r)
	if err != nil {
		return err
	}
	key, err := requestKey(r)
	if err != nil {
		return err
	}
	creation := filesystem.UploadCreation{SizeBytes: &size, MediaType: input.MediaType, ContentMD5: input.ContentMD5}
	if input.NodeID != nil {
		locator, err := nodeLocator(*input.NodeID)
		if err != nil {
			return err
		}
		rev, err := revision(r)
		if err != nil {
			return err
		}
		creation.Replacement = &filesystem.UploadReplacement{Locator: locator, Revision: rev}
	} else {
		if _, present := r.Header["If-Match"]; present {
			return invalid()
		}
		parent, err := nodeLocator(*input.ParentID)
		if err != nil {
			return err
		}
		creation.Destination = &filesystem.UploadDestination{Parent: parent, Name: *input.Name}
	}
	upload, err := s.Service.CreateUpload(r.Context(), fs, mounts, key, creation)
	if err != nil {
		return err
	}
	respond(w, r, http.StatusCreated, uploadResponseFrom(upload))
	return nil
}

func (s *Server) getUpload(w http.ResponseWriter, r *http.Request) error {
	fs, err := parseID(fsID(r))
	if err != nil {
		return err
	}
	id, err := parseID(r.PathValue("upload"))
	if err != nil {
		return err
	}
	upload, err := s.Store.GetUpload(r.Context(), fs, id)
	if err != nil {
		return err
	}
	respond(w, r, http.StatusOK, uploadResponseFrom(upload))
	return nil
}

func (s *Server) getUploadParts(w http.ResponseWriter, r *http.Request) error {
	values := r.URL.Query()["numbers"]
	if len(values) != 1 {
		return invalid()
	}
	numbers := make([]int32, 0, strings.Count(values[0], ",")+1)
	for _, raw := range strings.Split(values[0], ",") {
		number, err := strconv.ParseInt(raw, 10, 32)
		if err != nil || number < 1 {
			return invalid()
		}
		numbers = append(numbers, int32(number))
	}
	fs, err := parseID(fsID(r))
	if err != nil {
		return err
	}
	id, err := parseID(r.PathValue("upload"))
	if err != nil {
		return err
	}
	parts, err := s.Store.GetUploadParts(r.Context(), fs, id, numbers)
	if err != nil {
		return err
	}
	items := make([]uploadPartResponse, len(parts))
	for i, part := range parts {
		items[i] = uploadPartResponse{part.Number, signedUploadResponseFrom(part.Transfer)}
	}
	respond(w, r, http.StatusOK, struct {
		Items []uploadPartResponse `json:"items"`
	}{items})
	return nil
}

func (s *Server) completeUpload(w http.ResponseWriter, r *http.Request) error {
	var input struct {
		Parts []storage.PartReceipt `json:"parts,omitempty"`
	}
	if err := decodeJSON(w, r, &input); err != nil {
		return err
	}
	if len(input.Parts) > 10000 {
		return apperr.New(apperr.Invalid, "VALIDATION", "at most 10000 part receipts allowed")
	}
	fs, err := parseID(fsID(r))
	if err != nil {
		return err
	}
	id, err := parseID(r.PathValue("upload"))
	if err != nil {
		return err
	}
	publication, err := s.Service.CompleteUpload(r.Context(), fs, id, input.Parts)
	if err != nil {
		return err
	}
	respond(w, r, http.StatusOK, publicationResponseFrom(publication))
	return nil
}

func (s *Server) abortUpload(w http.ResponseWriter, r *http.Request) error {
	fs, err := parseID(fsID(r))
	if err != nil {
		return err
	}
	id, err := parseID(r.PathValue("upload"))
	if err != nil {
		return err
	}
	if err = s.Service.AbortUpload(r.Context(), fs, id); err != nil {
		return err
	}
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(http.StatusNoContent)
	return nil
}
