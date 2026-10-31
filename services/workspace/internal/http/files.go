package http

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"openlet/services/workspace/internal/workspace"
)

type locator struct {
	NodeID           *uuid.UUID `json:"node_id,omitempty"`
	Path             *string    `json:"path,omitempty"`
	CwdID            *uuid.UUID `json:"cwd_id,omitempty"`
	ExpectedNodeID   *uuid.UUID `json:"expected_node_id,omitempty"`
	ExpectedParentID *uuid.UUID `json:"expected_parent_id,omitempty"`
}
type uploadReceipt struct {
	PartNumber uint32 `json:"part_number"`
	ETag       string `json:"etag"`
}
type fileInput struct {
	Stage      string          `json:"stage,omitempty"`
	Locator    *locator        `json:"locator,omitempty"`
	Parent     *locator        `json:"parent,omitempty"`
	Name       *string         `json:"name,omitempty"`
	Text       json.RawMessage `json:"text,omitempty"`
	Locators   []locator       `json:"locators,omitempty"`
	Storage    *string         `json:"storage,omitempty"`
	SizeBytes  *string         `json:"size_bytes,omitempty"`
	ContentMD5 *string         `json:"content_md5,omitempty"`
	Parts      []uploadReceipt `json:"parts,omitempty"`
	Limit      *int            `json:"limit,omitempty"`
	Cursor     *string         `json:"cursor,omitempty"`
	// Preconditions and request identity come from headers or route parameters only.
	Revision   string     `json:"revision,omitempty"`
	RequestKey *uuid.UUID `json:"request_key,omitempty"`
	EntryID    *uuid.UUID `json:"entry_id,omitempty"`
}

func queryLocator(r *http.Request) (*locator, error) {
	l := &locator{}
	q := r.URL.Query()
	if v, ok := q["path"]; ok {
		if len(v) != 1 {
			return nil, workspace.Fault{Code: "VALIDATION"}
		}
		l.Path = &v[0]
	}
	for key, target := range map[string]**uuid.UUID{"node_id": &l.NodeID, "cwd_id": &l.CwdID} {
		if v, ok := q[key]; ok {
			if len(v) != 1 {
				return nil, workspace.Fault{Code: "VALIDATION"}
			}
			id, e := uuid.Parse(v[0])
			if e != nil || id == uuid.Nil {
				return nil, workspace.Fault{Code: "VALIDATION"}
			}
			*target = &id
		}
	}
	return l, nil
}
func (s *Server) fileAction(action string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		ws, e := resourceID(r, "ws")
		if e != nil {
			failure(w, r, e)
			return
		}
		role := "editor"
		if action == "stat" || action == "list" || action == "batch-stat" || action == "content" || action == "processing-status" {
			role = "viewer"
		}
		if action == "purge" {
			role = "owner"
		}
		if _, e = s.Store.Authorize(r.Context(), ws, actorID(r), role); e != nil {
			failure(w, r, e)
			return
		}
		mapping, e := s.Store.Storage(r.Context(), ws)
		if e != nil {
			failure(w, r, e)
			return
		}
		var in fileInput
		if r.Method == "GET" {
			if action != "trash-list" && action != "uploads-status" {
				in.Locator, e = queryLocator(r)
				if e != nil {
					failure(w, r, e)
					return
				}
			}
			if action == "list" || action == "trash-list" {
				// letfs owns cursor scope validation; the facade only bounds the numeric limit.
				limit, err := pageLimit(r)
				if err != nil {
					failure(w, r, err)
					return
				}
				in.Limit = &limit
				if c := r.URL.Query().Get("cursor"); c != "" {
					in.Cursor = &c
				}
			}
		} else if r.Method != "DELETE" && !(action == "uploads-finalize" && r.ContentLength == 0) {
			// Inline JSON is bounded independently of streaming upload routes.
			raw, readError := io.ReadAll(http.MaxBytesReader(w, r.Body, 8*1048576))
			if readError != nil {
				Error(w, r, 413, "REQUEST_LIMIT", "JSON body too large")
				return
			}
			if !utf8.Valid(raw) {
				failure(w, r, workspace.Fault{Code: "VALIDATION"})
				return
			}
			d := json.NewDecoder(bytes.NewReader(raw))
			d.DisallowUnknownFields()
			if d.Decode(&in) != nil {
				failure(w, r, workspace.Fault{Code: "VALIDATION"})
				return
			}
			var extra any
			if d.Decode(&extra) != io.EOF {
				failure(w, r, workspace.Fault{Code: "VALIDATION"})
				return
			}
			if in.Revision != "" || in.RequestKey != nil || in.EntryID != nil {
				failure(w, r, workspace.Fault{Code: "VALIDATION"})
				return
			}
		}
		if action == "content" {
			if values, exists := r.URL.Query()["revision"]; exists {
				if len(values) != 1 {
					failure(w, r, workspace.Fault{Code: "VALIDATION"})
					return
				}
				revision, err := strconv.ParseUint(values[0], 10, 63)
				if err != nil || revision == 0 || strconv.FormatUint(revision, 10) != values[0] {
					failure(w, r, workspace.Fault{Code: "VALIDATION"})
					return
				}
				in.Revision = values[0]
			}
			// A logical node revision is not the provider object's ETag.
			if r.Header.Get("If-Match") != "" {
				failure(w, r, workspace.Fault{Code: "VALIDATION"})
				return
			}
		}
		if action == "rename" || action == "move" || action == "replace-text" || action == "trash" || action == "restore" || action == "purge" || action == "copy" {
			in.Revision, e = precondition(r)
			if e != nil {
				failure(w, r, e)
				return
			}
		}
		if action == "uploads-create" && in.Locator != nil {
			in.Revision, e = precondition(r)
			if e != nil {
				failure(w, r, e)
				return
			}
		}
		if action == "copy" || action == "uploads-create" || (action == "purge" && r.Header.Get("Idempotency-Key") != "") {
			key, err := uuid.Parse(r.Header.Get("Idempotency-Key"))
			if err != nil || key == uuid.Nil {
				failure(w, r, workspace.Fault{Code: "VALIDATION"})
				return
			}
			in.RequestKey = &key
		}
		if action == "uploads-finalize" || action == "uploads-abort" || action == "uploads-status" {
			id, err := resourceID(r, "upload")
			if err != nil {
				failure(w, r, err)
				return
			}
			in.EntryID = &id
		}
		if action == "restore" || action == "purge" {
			id, err := resourceID(r, "entry")
			if err != nil {
				failure(w, r, err)
				return
			}
			in.EntryID = &id
		}
		body, e := json.Marshal(map[string]any{"scope": map[string]any{"actor_id": actorID(r), "mounts": []any{map[string]any{"path": "/drive", "filesystem_id": mapping.FilesystemID}}}, "input": in})
		if e != nil {
			failure(w, r, e)
			return
		}
		s.proxyLetfs(w, r, "POST", "/internal/v1/filesystems/"+mapping.FilesystemID.String()+"/files/"+action, bytes.NewReader(body))
	}
}
func (s *Server) usage(w http.ResponseWriter, r *http.Request) {
	ws, e := resourceID(r, "ws")
	if e != nil {
		failure(w, r, e)
		return
	}
	if _, e = s.Store.Authorize(r.Context(), ws, actorID(r), "viewer"); e != nil {
		failure(w, r, e)
		return
	}
	mapping, e := s.Store.Storage(r.Context(), ws)
	if e != nil {
		failure(w, r, e)
		return
	}
	req, e := http.NewRequestWithContext(r.Context(), "GET", s.Config.LetfsURL+"/internal/v1/quota-buckets/"+mapping.BucketID.String(), nil)
	if e != nil {
		failure(w, r, e)
		return
	}
	req.Header.Set("Authorization", "Bearer "+s.Config.WorkspaceToken)
	res, e := (&http.Client{Timeout: 10 * time.Second}).Do(req)
	if e != nil {
		failure(w, r, e)
		return
	}
	defer res.Body.Close()
	if res.StatusCode != 200 {
		failure(w, r, workspace.Fault{Code: "STORAGE_UNAVAILABLE"})
		return
	}
	var v struct {
		ID           uuid.UUID         `json:"id"`
		Used         string            `json:"used_bytes"`
		Limit        string            `json:"limit_bytes"`
		UploadLimits map[string]string `json:"upload_limits"`
	}
	if json.NewDecoder(io.LimitReader(res.Body, 65536)).Decode(&v) != nil || v.ID != mapping.BucketID {
		Error(w, r, 503, "DEPENDENCY_UNAVAILABLE", "invalid storage response")
		return
	}
	respond(w, 200, map[string]any{"used_bytes": v.Used, "limit_bytes": v.Limit, "upload_limits": v.UploadLimits})
}
func registerFiles(r chi.Router, s *Server) {
	base := "/workspaces/{ws}/files"
	r.Get(base+"/search", s.searchFiles)
	r.Post(base+"/semantic-search", s.searchFiles)
	for path, action := range map[string]string{"/stat": "stat", "/list": "list", "/content": "content", "/processing-status": "processing-status", "/trash": "trash-list"} {
		r.Get(base+path, s.fileAction(action))
	}
	for path, action := range map[string]string{"/processing-retry": "processing-retry", "/batch-stat": "batch-stat", "/directories": "directories", "/text": "text", "/rename": "rename", "/move": "move", "/copy": "copy", "/trash": "trash", "/trash/{entry}/restore": "restore"} {
		r.Post(base+path, s.fileAction(action))
	}
	r.Post(base+"/exports", s.exportFiles)
	r.Get(base+"/exports/{export}", s.exportFiles)
	r.Get(base+"/exports/{export}/{action:download}", s.exportFiles)
	r.Post(base+"/uploads", s.fileAction("uploads-create"))
	r.Put(base+"/uploads/{upload}/bytes", s.uploadBytes)
	r.Post(base+"/uploads/{upload}/parts", s.uploadParts)
	r.Get(base+"/uploads/{upload}", s.fileAction("uploads-status"))
	r.Post(base+"/uploads/{upload}/finalize", s.fileAction("uploads-finalize"))
	r.Delete(base+"/uploads/{upload}", s.fileAction("uploads-abort"))
	r.Put(base+"/text", s.fileAction("replace-text"))
	r.Delete(base+"/trash/{entry}", s.fileAction("purge"))
	r.Get("/workspaces/{ws}/usage", s.usage)
}

func (s *Server) proxyLetfs(w http.ResponseWriter, r *http.Request, method, path string, body io.Reader) {
	req, e := http.NewRequestWithContext(r.Context(), method, s.Config.LetfsURL+path, body)
	if e != nil {
		failure(w, r, e)
		return
	}
	req.Header.Set("Authorization", "Bearer "+s.Config.WorkspaceToken)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Actor-ID", actorID(r).String())
	if method == "PUT" {
		req.Header.Set("Content-Type", "application/octet-stream")
	}
	if v := r.Header.Get("Range"); v != "" {
		req.Header.Set("Range", v)
	}
	res, e := (&http.Client{Timeout: 2 * time.Minute, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}).Do(req)
	if e != nil {
		failure(w, r, e)
		return
	}
	defer res.Body.Close()
	for _, k := range []string{"Content-Type", "Content-Length", "ETag", "Content-Range", "Accept-Ranges", "Content-Disposition", "X-Content-Type-Options", "Retry-After", "Location"} {
		if v := res.Header.Get(k); v != "" {
			w.Header().Set(k, v)
		}
	}
	if (strings.HasSuffix(path, "/copy") || strings.HasSuffix(path, "/purge")) && res.StatusCode >= 200 && res.StatusCode < 300 && res.StatusCode != http.StatusNoContent {
		var value map[string]any
		if json.NewDecoder(io.LimitReader(res.Body, 65536)).Decode(&value) != nil {
			Error(w, r, 503, "DEPENDENCY_UNAVAILABLE", "invalid operation response")
			return
		}
		if op, ok := value["operation_id"].(string); ok {
			value["status_url"] = "/v1/workspaces/" + chi.URLParam(r, "ws") + "/operations/" + op
		}
		w.Header().Del("Content-Length")
		respond(w, res.StatusCode, value)
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(res.StatusCode)
	_, _ = io.Copy(w, res.Body)
}
func (s *Server) uploadBytes(w http.ResponseWriter, r *http.Request) {
	s.proxyUpload(w, r, "bytes", 1048576)
}
func (s *Server) uploadParts(w http.ResponseWriter, r *http.Request) {
	s.proxyUpload(w, r, "parts", 65536)
}
func (s *Server) proxyUpload(w http.ResponseWriter, r *http.Request, suffix string, limit int64) {
	ws, e := resourceID(r, "ws")
	if e != nil {
		failure(w, r, e)
		return
	}
	if _, e = s.Store.Authorize(r.Context(), ws, actorID(r), "editor"); e != nil {
		failure(w, r, e)
		return
	}
	id, e := resourceID(r, "upload")
	if e != nil {
		failure(w, r, e)
		return
	}
	mapping, e := s.Store.Storage(r.Context(), ws)
	if e != nil {
		failure(w, r, e)
		return
	}
	body, err := io.ReadAll(http.MaxBytesReader(w, r.Body, limit))
	if err != nil {
		var oversized *http.MaxBytesError
		if errors.As(err, &oversized) {
			Error(w, r, 413, "REQUEST_LIMIT", "upload request body exceeds limit")
		} else {
			Error(w, r, 400, "VALIDATION", "incomplete upload request body")
		}
		return
	}
	s.proxyLetfs(w, r, r.Method, "/internal/v1/filesystems/"+mapping.FilesystemID.String()+"/uploads/"+id.String()+"/"+suffix, bytes.NewReader(body))
}

func (s *Server) fileOperation(w http.ResponseWriter, r *http.Request, ws, op uuid.UUID) {
	actor, e := s.Store.Authorize(r.Context(), ws, actorID(r), "viewer")
	if e != nil {
		failure(w, r, e)
		return
	}
	storage, e := s.Store.Storage(r.Context(), ws)
	if e != nil {
		failure(w, r, e)
		return
	}
	req, e := http.NewRequestWithContext(r.Context(), "GET", s.Config.LetfsURL+"/internal/v1/filesystems/"+storage.FilesystemID.String()+"/operations/"+op.String(), nil)
	if e != nil {
		failure(w, r, e)
		return
	}
	req.Header.Set("Authorization", "Bearer "+s.Config.WorkspaceToken)
	res, e := (&http.Client{Timeout: 10 * time.Second}).Do(req)
	if e != nil {
		failure(w, r, e)
		return
	}
	defer res.Body.Close()
	if res.StatusCode == 404 {
		failure(w, r, workspace.Fault{Code: "NOT_FOUND"})
		return
	}
	if res.StatusCode != 200 {
		Error(w, r, 503, "DEPENDENCY_UNAVAILABLE", "storage unavailable")
		return
	}
	var value map[string]any
	if json.NewDecoder(io.LimitReader(res.Body, 65536)).Decode(&value) != nil {
		Error(w, r, 503, "DEPENDENCY_UNAVAILABLE", "invalid operation response")
		return
	}
	if value["actor_id"] != actorID(r).String() && actor.Role != "owner" {
		failure(w, r, workspace.Fault{Code: "NOT_FOUND"})
		return
	}
	delete(value, "actor_id")
	value["status_url"] = "/v1/workspaces/" + ws.String() + "/operations/" + op.String()
	respond(w, 200, value)
}
