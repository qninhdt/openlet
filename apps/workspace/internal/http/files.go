package http

import (
	"bytes"
	"encoding/json"
	"errors"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"openlet/apps/workspace/internal/workspace"
)

type locator struct {
	NodeID           *uuid.UUID `json:"node_id,omitempty"`
	Path             *string    `json:"path,omitempty"`
	CwdID            *uuid.UUID `json:"cwd_id,omitempty"`
	ExpectedNodeID   *uuid.UUID `json:"expected_node_id,omitempty"`
	ExpectedParentID *uuid.UUID `json:"expected_parent_id,omitempty"`
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
func (s *Server) batchStat(c *gin.Context) {
	fs, ok := s.nodeFilesystem(c, "viewer")
	if !ok {
		return
	}
	w, r := c.Writer, c.Request
	var input struct {
		Locators []locator `json:"locators"`
	}
	if err := decodeLimited(w, r, &input, 8*1048576); err != nil {
		failure(w, r, err)
		return
	}
	if len(input.Locators) == 0 || len(input.Locators) > 100 {
		failure(w, r, workspace.Fault{Code: "VALIDATION"})
		return
	}
	body, err := json.Marshal(map[string]any{"scope": map[string]any{"actor_id": actorID(r), "mounts": []any{map[string]any{"path": "/drive", "filesystem_id": fs}}}, "input": input})
	if err != nil {
		failure(w, r, err)
		return
	}
	s.proxyLetfs(c, http.MethodPost, "/internal/v1/filesystems/"+fs.String()+"/files/batch-stat", bytes.NewReader(body))
}
func (s *Server) usage(c *gin.Context) {
	w, r := c.Writer, c.Request
	ws, e := resourceID(c, "ws")
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
	res, e := (&http.Client{Transport: otelhttp.NewTransport(http.DefaultTransport), Timeout: 10 * time.Second}).Do(req)
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
func registerFiles(r *gin.RouterGroup, s *Server) {
	r.POST("/workspaces/:ws/nodes", s.createNode)
	r.GET("/workspaces/:ws/copies/:copy", s.copyStatus)
	r.GET("/workspaces/:ws/nodes", s.readNode("list"))
	r.GET("/workspaces/:ws/nodes\\:resolve", s.readNode("resolve"))
	r.GET("/workspaces/:ws/nodes/:node", s.readNode("stat"))
	r.GET("/workspaces/:ws/nodes/:node/content", s.readNode("content"))
	r.GET("/workspaces/:ws/nodes/:node/processing", s.readNode("processing"))
	r.POST("/workspaces/:ws/nodes/:node/processing-runs", s.reprocessNode)
	r.PATCH("/workspaces/:ws/nodes/:node", s.updateNode)
	r.PUT("/workspaces/:ws/nodes/:node/content", s.updateNode)
	r.DELETE("/workspaces/:ws/nodes/:node", s.trashNode)
	r.GET("/workspaces/:ws/trash-entries", s.trashResource)
	r.GET("/workspaces/:ws/trash-entries/:entry", s.trashResource)
	r.POST("/workspaces/:ws/trash-entries/:entry", s.trashResource)
	r.DELETE("/workspaces/:ws/trash-entries/:entry", s.trashResource)
	base := "/workspaces/:ws/files"
	r.GET("/workspaces/:ws/search", s.searchFiles)
	r.POST("/workspaces/:ws/search", s.searchFiles)
	r.POST(base+"/batch-stat", s.batchStat)
	r.GET("/workspaces/:ws/nodes/:node/archive", s.archive)
	r.POST("/workspaces/:ws/uploads", s.createUpload)
	r.GET("/workspaces/:ws/uploads/:upload", s.uploadResource("status"))
	r.GET("/workspaces/:ws/uploads/:upload/parts", s.uploadResource("parts"))
	r.PUT("/workspaces/:ws/uploads/:upload/completion", s.uploadResource("complete"))
	r.DELETE("/workspaces/:ws/uploads/:upload", s.uploadResource("abort"))
	r.GET("/workspaces/:ws/storage", s.usage)
}

func (s *Server) proxyLetfs(c *gin.Context, method, path string, body io.Reader) {
	w, r := c.Writer, c.Request
	req, e := http.NewRequestWithContext(r.Context(), method, s.Config.LetfsURL+path, body)
	if e != nil {
		failure(w, r, e)
		return
	}
	req.Header.Set("Authorization", "Bearer "+s.Config.WorkspaceToken)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Actor-ID", actorID(r).String())
	if role, ok := c.Get("workspace-role"); ok {
		req.Header.Set("X-Workspace-Role", role.(string))
	}
	if method == "PUT" {
		contentType := r.Header.Get("Content-Type")
		if contentType == "" {
			contentType = "application/octet-stream"
		}
		req.Header.Set("Content-Type", contentType)
	}
	for _, key := range []string{"Range", "If-Match", "Idempotency-Key"} {
		for _, v := range r.Header.Values(key) {
			req.Header.Add(key, v)
		}
	}
	timeout := 2 * time.Minute
	if strings.HasSuffix(path, "/archive") {
		timeout = 1810 * time.Second
		if err := http.NewResponseController(w).SetWriteDeadline(time.Now().Add(timeout)); err != nil && !errors.Is(err, http.ErrNotSupported) {
			failure(w, r, err)
			return
		}
	}
	res, e := (&http.Client{Transport: otelhttp.NewTransport(http.DefaultTransport), Timeout: timeout, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}).Do(req)
	if e != nil {
		failure(w, r, e)
		return
	}
	defer res.Body.Close()
	for _, k := range []string{"Content-Type", "Content-Length", "ETag", "Content-Range", "Accept-Ranges", "Content-Disposition", "X-Content-Type-Options", "Retry-After", "Location"} {
		if v := res.Header.Get(k); v != "" {
			if k == "Location" && strings.HasPrefix(v, "/internal/v1/filesystems/") {
				parts := strings.SplitN(strings.TrimPrefix(v, "/internal/v1/filesystems/"), "/", 2)
				if len(parts) == 2 {
					v = "/v1/workspaces/" + c.Param("ws") + "/" + parts[1]
				}
			}
			w.Header().Set(k, v)
		}
	}
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(res.StatusCode)
	if _, err := io.Copy(w, res.Body); err != nil {
		panic(http.ErrAbortHandler)
	}
}
