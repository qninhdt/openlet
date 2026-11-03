package httpapi

import (
	"errors"
	"io"
	"net/http"
	"strconv"

	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/rpc"
	"google.golang.org/grpc/codes"
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
	key, err := requestKey(r)
	if err != nil {
		return err
	}
	if input.SourceID != nil {
		if input.Kind != "" || input.Content != nil || input.MediaType != nil {
			return invalid()
		}
		rev, err := revision(r)
		if err != nil {
			return err
		}
		result, err := s.API.CreateCopy(r.Context(), &letfsv1.CreateCopyRequest{FilesystemId: fsID(r), SourceId: *input.SourceID, ParentId: input.ParentID, Name: input.Name, Revision: rev, IdempotencyKey: key, PathContext: pathContext(r)})
		if err != nil {
			return err
		}
		respond(w, r, 202, result.Copy)
		return nil
	}
	request := &letfsv1.CreateNodeRequest{FilesystemId: fsID(r), IdempotencyKey: key, PathContext: pathContext(r)}
	switch input.Kind {
	case "directory":
		if input.Content != nil || input.MediaType != nil {
			return invalid()
		}
		request.Input = &letfsv1.CreateNodeRequest_Directory{Directory: &letfsv1.DirectoryCreation{Parent: nodeLocator(input.ParentID), Name: input.Name}}
	case "file":
		if input.Content == nil {
			return invalid()
		}
		media := "application/octet-stream"
		if input.MediaType != nil {
			media = *input.MediaType
		}
		request.Input = &letfsv1.CreateNodeRequest_File{File: &letfsv1.InlineFileCreation{Parent: nodeLocator(input.ParentID), Name: input.Name, Content: *input.Content, MediaType: media}}
	default:
		return invalid()
	}
	result, err := s.API.CreateNode(r.Context(), request)
	if err != nil {
		return err
	}
	respond(w, r, 201, result.Node)
	return nil
}
func (s *Server) getNode(w http.ResponseWriter, r *http.Request) error {
	result, err := s.API.GetNode(r.Context(), &letfsv1.GetNodeRequest{FilesystemId: fsID(r), NodeId: r.PathValue("node"), PathContext: pathContext(r)})
	if err != nil {
		return err
	}
	respond(w, r, 200, result.Node)
	return nil
}
func (s *Server) resolveNode(w http.ResponseWriter, r *http.Request) error {
	locator, err := queryLocator(r)
	if err != nil {
		return err
	}
	result, err := s.API.ResolveNode(r.Context(), &letfsv1.ResolveNodeRequest{FilesystemId: fsID(r), Locator: locator, PathContext: pathContext(r)})
	if err != nil {
		return err
	}
	respond(w, r, 200, result.Node)
	return nil
}
func (s *Server) listNodes(w http.ResponseWriter, r *http.Request) error {
	var parent *letfsv1.Locator
	var err error
	if values, ok := r.URL.Query()["parent_id"]; ok {
		if len(values) != 1 || r.URL.Query().Has("path") || r.URL.Query().Has("node_id") || r.URL.Query().Has("cwd_id") {
			return invalid()
		}
		parent = nodeLocator(values[0])
	} else {
		parent, err = queryLocator(r)
		if err != nil {
			return err
		}
	}
	limit, cursor, err := pageInput(r)
	if err != nil {
		return err
	}
	result, err := s.API.ListNodes(r.Context(), &letfsv1.ListNodesRequest{FilesystemId: fsID(r), Parent: parent, PathContext: pathContext(r), Limit: limit, Cursor: cursor})
	if err != nil {
		return err
	}
	respond(w, r, 200, result)
	return nil
}
func (s *Server) batchStat(w http.ResponseWriter, r *http.Request) error {
	var input struct {
		Locators []filesystem.Locator `json:"locators"`
	}
	if err := decodeJSON(w, r, &input); err != nil {
		return err
	}
	request := &letfsv1.BatchStatRequest{FilesystemId: fsID(r), PathContext: pathContext(r)}
	for _, value := range input.Locators {
		locator, err := locatorMessage(value)
		if err != nil {
			return err
		}
		request.Locators = append(request.Locators, locator)
	}
	result, err := s.API.BatchStat(r.Context(), request)
	if err != nil {
		return err
	}
	respond(w, r, 200, result)
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
	if err := decodeJSON(w, r, &input); err != nil {
		return err
	}
	request := &letfsv1.UpdateNodeRequest{FilesystemId: fsID(r), Locator: nodeLocator(r.PathValue("node")), PathContext: pathContext(r), Revision: rev, Name: input.Name}
	if input.ParentID != nil {
		request.Parent = nodeLocator(*input.ParentID)
	}
	result, err := s.API.UpdateNode(r.Context(), request)
	if err != nil {
		return err
	}
	respond(w, r, 200, result.Node)
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
			return rpc.Fault(codes.ResourceExhausted, "REQUEST_LIMIT", "inline content exceeds limit")
		}
		return invalid()
	}
	result, err := s.API.ReplaceContent(r.Context(), &letfsv1.ReplaceContentRequest{FilesystemId: fsID(r), Locator: nodeLocator(r.PathValue("node")), PathContext: pathContext(r), Revision: rev, Content: content, MediaType: contentType(r)})
	if err != nil {
		return err
	}
	respond(w, r, 200, result.Node)
	return nil
}
func (s *Server) getContent(w http.ResponseWriter, r *http.Request) error {
	request := &letfsv1.GetDownloadRequest{FilesystemId: fsID(r), NodeId: r.PathValue("node"), PathContext: pathContext(r)}
	if values, ok := r.URL.Query()["revision"]; ok {
		if len(values) != 1 || !validRevision(values[0]) {
			return invalid()
		}
		rev, _ := strconv.ParseInt(values[0], 10, 64)
		request.Revision = &rev
	}
	result, err := s.API.GetDownload(r.Context(), request)
	if err != nil {
		return err
	}
	return writeDownload(w, r, result.Download)
}
func (s *Server) getCopy(w http.ResponseWriter, r *http.Request) error {
	result, err := s.API.GetCopy(r.Context(), &letfsv1.GetCopyRequest{FilesystemId: fsID(r), CopyId: r.PathValue("copy")})
	if err != nil {
		return err
	}
	respond(w, r, 200, result.Copy)
	return nil
}
func (s *Server) getProcessing(w http.ResponseWriter, r *http.Request) error {
	result, err := s.API.GetProcessing(r.Context(), &letfsv1.GetProcessingRequest{FilesystemId: fsID(r), NodeId: r.PathValue("node"), PathContext: pathContext(r)})
	if err != nil {
		return err
	}
	respond(w, r, 200, result.Processing)
	return nil
}
func (s *Server) reprocess(w http.ResponseWriter, r *http.Request) error {
	var input struct{}
	if err := decodeJSON(w, r, &input); err != nil {
		return err
	}
	key, err := requestKey(r)
	if err != nil {
		return err
	}
	result, err := s.API.ReprocessNode(r.Context(), &letfsv1.ReprocessNodeRequest{FilesystemId: fsID(r), NodeId: r.PathValue("node"), PathContext: pathContext(r), IdempotencyKey: key})
	if err != nil {
		return err
	}
	respond(w, r, 202, result)
	return nil
}
