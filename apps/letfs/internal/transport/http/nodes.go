package httpapi

import (
	"errors"
	"io"
	"net/http"
	"strconv"

	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	"github.com/qninhdt/openlet/packages/go/apperr"
)

func (s *Server) createNode(w http.ResponseWriter, r *http.Request) error {
	var input struct {
		Kind      string  `json:"kind"`
		ParentID  string  `json:"parent_id"`
		Name      string  `json:"name"`
		Content   *[]byte `json:"content_base64,omitempty"`
		MediaType *string `json:"media_type,omitempty"`
		SourceID  *string `json:"source_id,omitempty"`
	}
	if err := decodeJSON(w, r, &input); err != nil {
		return err
	}
	fs, mounts, err := requestContext(r)
	if err != nil {
		return err
	}
	key, err := requestKey(r)
	if err != nil {
		return err
	}
	parent, err := parseID(input.ParentID)
	if err != nil {
		return err
	}
	if input.SourceID != nil {
		if input.Kind != "" || input.Content != nil || input.MediaType != nil {
			return invalid()
		}
		source, err := parseID(*input.SourceID)
		if err != nil {
			return err
		}
		rev, err := revision(r)
		if err != nil {
			return err
		}
		result, err := s.Service.CreateCopy(r.Context(), fs, mounts, key, filesystem.CreateCopy{SourceID: source, ParentID: parent, Name: input.Name, Revision: rev})
		if err != nil {
			return err
		}
		respond(w, r, http.StatusAccepted, copyResponseFrom(result))
		return nil
	}
	creation := filesystem.CreateNode{Parent: filesystem.Locator{NodeID: &parent}, Name: input.Name}
	switch input.Kind {
	case "directory":
		if input.Content != nil || input.MediaType != nil {
			return invalid()
		}
	case "file":
		if input.Content == nil {
			return invalid()
		}
		mediaType := "application/octet-stream"
		if input.MediaType != nil {
			mediaType = *input.MediaType
		}
		creation.File = &filesystem.InlineFile{Content: *input.Content, MediaType: mediaType}
	default:
		return invalid()
	}
	node, err := s.Service.CreateNode(r.Context(), fs, mounts, key, creation)
	if err != nil {
		return err
	}
	respond(w, r, http.StatusCreated, nodeResponseFrom(node))
	return nil
}

func (s *Server) getNode(w http.ResponseWriter, r *http.Request) error {
	fs, mounts, err := requestContext(r)
	if err != nil {
		return err
	}
	locator, err := nodeLocator(r.PathValue("node"))
	if err != nil {
		return err
	}
	node, err := s.Store.GetNode(r.Context(), fs, mounts, locator)
	if err != nil {
		return err
	}
	respond(w, r, http.StatusOK, nodeResponseFrom(node))
	return nil
}

func (s *Server) resolveNode(w http.ResponseWriter, r *http.Request) error {
	fs, mounts, err := requestContext(r)
	if err != nil {
		return err
	}
	locator, err := queryLocator(r)
	if err != nil {
		return err
	}
	node, err := s.Store.ResolveNode(r.Context(), fs, mounts, locator)
	if err != nil {
		return err
	}
	respond(w, r, http.StatusOK, nodeResponseFrom(node))
	return nil
}

func (s *Server) listNodes(w http.ResponseWriter, r *http.Request) error {
	fs, mounts, err := requestContext(r)
	if err != nil {
		return err
	}
	var parent filesystem.Locator
	if values, ok := r.URL.Query()["parent_id"]; ok {
		if len(values) != 1 || r.URL.Query().Has("path") || r.URL.Query().Has("node_id") || r.URL.Query().Has("cwd_id") {
			return invalid()
		}
		parent, err = nodeLocator(values[0])
	} else {
		parent, err = queryLocator(r)
	}
	if err != nil {
		return err
	}
	limit, cursor, err := pageInput(r)
	if err != nil {
		return err
	}
	page, err := s.Store.ListNodes(r.Context(), fs, mounts, parent, cursor, limit)
	if err != nil {
		return err
	}
	items := make([]nodeResponse, len(page.Items))
	for i, node := range page.Items {
		items[i] = nodeResponseFrom(node)
	}
	respond(w, r, http.StatusOK, struct {
		Items      []nodeResponse `json:"items"`
		NextCursor *string        `json:"next_cursor,omitempty"`
	}{items, page.NextCursor})
	return nil
}

func (s *Server) batchStat(w http.ResponseWriter, r *http.Request) error {
	var input struct {
		Locators []filesystem.Locator `json:"locators"`
	}
	if err := decodeJSON(w, r, &input); err != nil {
		return err
	}
	if len(input.Locators) < 1 || len(input.Locators) > 100 {
		return apperr.New(apperr.Invalid, "VALIDATION", "locator batch must contain 1..100 items")
	}
	fs, mounts, err := requestContext(r)
	if err != nil {
		return err
	}
	values, err := s.Store.BatchStat(r.Context(), fs, mounts, input.Locators)
	if err != nil {
		return err
	}
	items := make([]nodeResponse, len(values))
	for i, node := range values {
		items[i] = nodeResponseFrom(node)
	}
	respond(w, r, http.StatusOK, struct {
		Items []nodeResponse `json:"items"`
	}{items})
	return nil
}

func (s *Server) updateNode(w http.ResponseWriter, r *http.Request) error {
	rev, err := revision(r)
	if err != nil {
		return err
	}
	var input struct {
		Name     *string `json:"name,omitempty"`
		ParentID *string `json:"parent_id,omitempty"`
	}
	if err = decodeJSON(w, r, &input); err != nil {
		return err
	}
	fs, mounts, err := requestContext(r)
	if err != nil {
		return err
	}
	locator, err := nodeLocator(r.PathValue("node"))
	if err != nil {
		return err
	}
	patch := filesystem.UpdateNode{Locator: locator, Revision: rev, Name: input.Name}
	if input.ParentID != nil {
		parent, err := nodeLocator(*input.ParentID)
		if err != nil {
			return err
		}
		patch.Parent = &parent
	}
	node, err := s.Service.UpdateNode(r.Context(), fs, mounts, patch)
	if err != nil {
		return err
	}
	respond(w, r, http.StatusOK, nodeResponseFrom(node))
	return nil
}

func (s *Server) replaceContent(w http.ResponseWriter, r *http.Request) error {
	rev, err := revision(r)
	if err != nil {
		return err
	}
	content, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 1048576))
	if err != nil {
		var large *http.MaxBytesError
		if errors.As(err, &large) {
			return apperr.New(apperr.Limit, "REQUEST_LIMIT", "inline content exceeds limit")
		}
		return invalid()
	}
	fs, mounts, err := requestContext(r)
	if err != nil {
		return err
	}
	locator, err := nodeLocator(r.PathValue("node"))
	if err != nil {
		return err
	}
	node, err := s.Service.ReplaceContent(r.Context(), fs, mounts, locator, rev, content, contentType(r))
	if err != nil {
		return err
	}
	respond(w, r, http.StatusOK, nodeResponseFrom(node))
	return nil
}

func (s *Server) getContent(w http.ResponseWriter, r *http.Request) error {
	fs, mounts, err := requestContext(r)
	if err != nil {
		return err
	}
	id, err := parseID(r.PathValue("node"))
	if err != nil {
		return err
	}
	var rev *int64
	if values, ok := r.URL.Query()["revision"]; ok {
		if len(values) != 1 || !validRevision(values[0]) {
			return invalid()
		}
		value, _ := strconv.ParseInt(values[0], 10, 64)
		rev = &value
	}
	download, err := s.Store.GetDownload(r.Context(), fs, mounts, id, rev)
	if err != nil {
		return err
	}
	return writeDownload(w, r, download)
}

func (s *Server) getCopy(w http.ResponseWriter, r *http.Request) error {
	fs, err := parseID(fsID(r))
	if err != nil {
		return err
	}
	id, err := parseID(r.PathValue("copy"))
	if err != nil {
		return err
	}
	state, err := s.Service.GetCopy(r.Context(), fs, id)
	if err != nil {
		return err
	}
	respond(w, r, http.StatusOK, copyResponseFrom(state))
	return nil
}

func (s *Server) getProcessing(w http.ResponseWriter, r *http.Request) error {
	fs, mounts, err := requestContext(r)
	if err != nil {
		return err
	}
	id, err := parseID(r.PathValue("node"))
	if err != nil {
		return err
	}
	value, err := s.Store.GetProcessing(r.Context(), fs, mounts, id)
	if err != nil {
		return err
	}
	respond(w, r, http.StatusOK, struct {
		DesiredGeneration int64   `json:"desired_generation,string"`
		PublicationStatus string  `json:"publication_status"`
		ErrorCode         *string `json:"error_code,omitempty"`
		FileID            string  `json:"file_id"`
	}{value.DesiredGeneration, value.PublicationStatus, value.ErrorCode, value.FileID.String()})
	return nil
}

func (s *Server) reprocess(w http.ResponseWriter, r *http.Request) error {
	var input struct{}
	if err := decodeJSON(w, r, &input); err != nil {
		return err
	}
	fs, mounts, err := requestContext(r)
	if err != nil {
		return err
	}
	id, err := parseID(r.PathValue("node"))
	if err != nil {
		return err
	}
	key, err := requestKey(r)
	if err != nil {
		return err
	}
	result, err := s.Service.Reprocess(r.Context(), fs, mounts, id, key)
	if err != nil {
		return err
	}
	respond(w, r, http.StatusAccepted, struct {
		FileID     string `json:"file_id"`
		Generation int64  `json:"generation,string"`
		WorkflowID string `json:"workflow_id"`
	}{result.FileID.String(), result.Generation, result.WorkflowID})
	return nil
}
