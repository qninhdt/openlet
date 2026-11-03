package httpapi

import (
	"net/http"
	"strconv"
	"strings"

	letfsv1 "openlet/packages/go/gen/openlet_api/letfs/v1"
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
	key, err := requestKey(r)
	if err != nil {
		return err
	}
	request := &letfsv1.CreateUploadRequest{FilesystemId: fsID(r), PathContext: pathContext(r), IdempotencyKey: key, SizeBytes: &size, MediaType: input.MediaType, ContentMd5: input.ContentMD5}
	if input.NodeID != nil {
		rev, err := revision(r)
		if err != nil {
			return err
		}
		request.Target = &letfsv1.CreateUploadRequest_Replacement{Replacement: &letfsv1.UploadReplacement{Locator: nodeLocator(*input.NodeID), Revision: rev}}
	} else {
		if _, present := r.Header["If-Match"]; present {
			return invalid()
		}
		request.Target = &letfsv1.CreateUploadRequest_Destination{Destination: &letfsv1.UploadDestination{Parent: nodeLocator(*input.ParentID), Name: *input.Name}}
	}
	result, err := s.API.CreateUpload(r.Context(), request)
	if err != nil {
		return err
	}
	respond(w, r, 201, result.Upload)
	return nil
}
func (s *Server) getUpload(w http.ResponseWriter, r *http.Request) error {
	result, err := s.API.GetUpload(r.Context(), &letfsv1.GetUploadRequest{FilesystemId: fsID(r), UploadId: r.PathValue("upload")})
	if err != nil {
		return err
	}
	respond(w, r, 200, result.Upload)
	return nil
}
func (s *Server) getUploadParts(w http.ResponseWriter, r *http.Request) error {
	values := r.URL.Query()["numbers"]
	if len(values) != 1 {
		return invalid()
	}
	request := &letfsv1.GetUploadPartsRequest{FilesystemId: fsID(r), UploadId: r.PathValue("upload")}
	for _, raw := range strings.Split(values[0], ",") {
		number, err := strconv.ParseInt(raw, 10, 32)
		if err != nil || number < 1 {
			return invalid()
		}
		request.Numbers = append(request.Numbers, int32(number))
	}
	result, err := s.API.GetUploadParts(r.Context(), request)
	if err != nil {
		return err
	}
	respond(w, r, 200, result)
	return nil
}
func (s *Server) completeUpload(w http.ResponseWriter, r *http.Request) error {
	var input struct {
		Parts []*letfsv1.PartReceipt `json:"parts,omitempty"`
	}
	if err := decodeJSON(w, r, &input); err != nil {
		return err
	}
	result, err := s.API.CompleteUpload(r.Context(), &letfsv1.CompleteUploadRequest{FilesystemId: fsID(r), UploadId: r.PathValue("upload"), Parts: input.Parts})
	if err != nil {
		return err
	}
	respond(w, r, 200, result.Publication)
	return nil
}
func (s *Server) abortUpload(w http.ResponseWriter, r *http.Request) error {
	_, err := s.API.AbortUpload(r.Context(), &letfsv1.AbortUploadRequest{FilesystemId: fsID(r), UploadId: r.PathValue("upload")})
	if err != nil {
		return err
	}
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(204)
	return nil
}
