package httpapi

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	"github.com/qninhdt/openlet/packages/go/apperr"
	sharedhttp "github.com/qninhdt/openlet/packages/go/httpapi"
	"github.com/qninhdt/openlet/packages/go/identity"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
)

type Server struct {
	Store        *filesystem.Store
	Service      *filesystem.Service
	GatewayToken string
	Ready        func(context.Context) error
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	route := func(pattern string, handle func(http.ResponseWriter, *http.Request) error) {
		mux.HandleFunc(pattern, func(w http.ResponseWriter, r *http.Request) {
			if err := handle(w, r); err != nil {
				sharedhttp.WriteError(w, r, err)
			}
		})
	}
	route("GET /v1/filesystems/{filesystem}", s.getFilesystem)
	route("GET /v1/quota-buckets/{bucket}", s.getUsage)
	route("POST /v1/filesystems/{filesystem}/nodes", s.createNode)
	route("GET /v1/filesystems/{filesystem}/nodes", s.listNodes)
	route("GET /v1/filesystems/{filesystem}/nodes:resolve", s.resolveNode)
	route("GET /v1/filesystems/{filesystem}/nodes/{node}", s.getNode)
	route("PATCH /v1/filesystems/{filesystem}/nodes/{node}", s.updateNode)
	route("PUT /v1/filesystems/{filesystem}/nodes/{node}/content", s.replaceContent)
	route("GET /v1/filesystems/{filesystem}/nodes/{node}/content", s.getContent)
	route("GET /v1/filesystems/{filesystem}/nodes/{node}/archive", s.getArchive)
	route("GET /v1/filesystems/{filesystem}/nodes/{node}/processing", s.getProcessing)
	route("POST /v1/filesystems/{filesystem}/nodes/{node}/processing-runs", s.reprocess)
	route("GET /v1/filesystems/{filesystem}/copies/{copy}", s.getCopy)
	route("POST /v1/filesystems/{filesystem}/files/batch-stat", s.batchStat)
	route("DELETE /v1/filesystems/{filesystem}/nodes/{node}", s.trashNode)
	route("GET /v1/filesystems/{filesystem}/trash-entries", s.listTrash)
	route("GET /v1/filesystems/{filesystem}/trash-entries/{entry}", s.getTrash)
	route("POST /v1/filesystems/{filesystem}/trash-entries/{entry}", s.restoreTrash)
	route("DELETE /v1/filesystems/{filesystem}/trash-entries/{entry}", s.purgeTrash)
	route("POST /v1/filesystems/{filesystem}/uploads", s.createUpload)
	route("GET /v1/filesystems/{filesystem}/uploads/{upload}", s.getUpload)
	route("GET /v1/filesystems/{filesystem}/uploads/{upload}/parts", s.getUploadParts)
	route("PUT /v1/filesystems/{filesystem}/uploads/{upload}/completion", s.completeUpload)
	route("DELETE /v1/filesystems/{filesystem}/uploads/{upload}", s.abortUpload)
	route("GET /v1/filesystems/{filesystem}/search", s.searchFiles)
	route("POST /v1/filesystems/{filesystem}/search", s.semanticSearch)
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		sharedhttp.WriteError(w, r, apperr.New(apperr.Missing, "NOT_FOUND", "resource not found"))
	})
	return otelhttp.NewHandler(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id, err := uuid.Parse(r.Header.Get("X-Request-ID"))
		if len(r.Header.Values("X-Request-ID")) != 1 || err != nil || id == uuid.Nil {
			id = uuid.New()
		}
		r.Header.Set("X-Request-ID", id.String())
		w.Header().Set("X-Request-ID", id.String())
		if r.URL.Path == "/live" && r.Method == http.MethodGet {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		if r.URL.Path == "/ready" && r.Method == http.MethodGet {
			ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
			defer cancel()
			if s.Ready == nil || s.Ready(ctx) != nil {
				w.WriteHeader(http.StatusServiceUnavailable)
			} else {
				w.WriteHeader(http.StatusNoContent)
			}
			return
		}
		principal, err := identity.AuthenticateGateway(r.Header, s.GatewayToken, false)
		if err != nil {
			code := "UNAUTHENTICATED"
			if errors.Is(err, identity.ErrOnboardingRequired) {
				code = "ONBOARDING_REQUIRED"
			}
			sharedhttp.WriteError(w, r, apperr.New(apperr.Unauthenticated, code, err.Error()))
			return
		}
		if !strings.HasSuffix(r.URL.Path, "/archive") {
			ctx, cancel := context.WithTimeout(r.Context(), 120*time.Second)
			defer cancel()
			r = r.WithContext(ctx)
		}
		if values, ok := r.URL.Query()["mount_path"]; ok && (len(values) != 1 || values[0] == "") {
			sharedhttp.WriteError(w, r, invalid())
			return
		}
		started := time.Now()
		defer func() {
			slog.InfoContext(r.Context(), "HTTP request", "request_id", id.String(), "method", r.Method, "route", r.Pattern, "elapsed_ms", time.Since(started).Milliseconds())
		}()
		mux.ServeHTTP(w, r.WithContext(identity.WithPrincipal(r.Context(), principal)))
	}), "openlet-letfs")
}

func invalid() error              { return apperr.New(apperr.Invalid, "VALIDATION", "invalid request") }
func fsID(r *http.Request) string { return r.PathValue("filesystem") }
func parseID(value string) (uuid.UUID, error) {
	id, err := uuid.Parse(value)
	if err != nil || id == uuid.Nil {
		return uuid.Nil, invalid()
	}
	return id, nil
}
func nodeLocator(id string) (filesystem.Locator, error) {
	value, err := parseID(id)
	return filesystem.Locator{NodeID: &value}, err
}
func mountPath(r *http.Request) string {
	path := r.URL.Query().Get("mount_path")
	if path == "" {
		path = "/"
	}
	return path
}
func requestContext(r *http.Request) (uuid.UUID, []filesystem.Mount, error) {
	fs, err := parseID(fsID(r))
	if err != nil {
		return uuid.Nil, nil, err
	}
	return fs, []filesystem.Mount{{Path: mountPath(r), FilesystemID: fs}}, nil
}
func requestKey(r *http.Request) (uuid.UUID, error) {
	values := r.Header.Values("Idempotency-Key")
	if len(values) != 1 {
		return uuid.Nil, invalid()
	}
	id, err := uuid.Parse(values[0])
	if err != nil || id == uuid.Nil {
		return uuid.Nil, invalid()
	}
	return id, nil
}
func revision(r *http.Request) (*int64, error) {
	value, err := requiredRevision(r)
	if err != nil {
		return nil, err
	}
	parsed, err := strconv.ParseInt(value, 10, 64)
	return &parsed, err
}
func pageInput(r *http.Request) (*int32, *string, error) {
	var limit *int32
	var cursor *string
	q := r.URL.Query()
	if values, ok := q["limit"]; ok {
		if len(values) != 1 {
			return nil, nil, invalid()
		}
		value, err := strconv.ParseInt(values[0], 10, 32)
		if err != nil || value < 1 || value > 100 {
			return nil, nil, invalid()
		}
		parsed := int32(value)
		limit = &parsed
	}
	if values, ok := q["cursor"]; ok {
		if len(values) != 1 {
			return nil, nil, invalid()
		}
		cursor = &values[0]
	}
	return limit, cursor, nil
}
func respond(w http.ResponseWriter, r *http.Request, code int, value any) {
	etag, location := "", ""
	switch item := value.(type) {
	case nodeResponse:
		etag = `"` + strconv.FormatInt(item.Revision, 10) + `"`
		if code == http.StatusCreated {
			location = "/v1/filesystems/" + fsID(r) + "/nodes/" + item.ID
		}
	case copyResponse:
		location = "/v1/filesystems/" + fsID(r) + "/copies/" + item.ID
	case uploadResponse:
		if code == http.StatusCreated {
			location = "/v1/filesystems/" + fsID(r) + "/uploads/" + item.ID
		}
	case trashResponse:
		if code == http.StatusCreated || code == http.StatusAccepted {
			location = "/v1/filesystems/" + fsID(r) + "/trash-entries/" + item.ID
		}
	case publicationResponse:
		etag = `"` + strconv.FormatInt(item.Revision, 10) + `"`
	}
	writeJSON(w, r, code, location, etag, value)
}
func (s *Server) getFilesystem(w http.ResponseWriter, r *http.Request) error {
	id, err := parseID(fsID(r))
	if err != nil {
		return err
	}
	result, err := s.Store.GetFilesystem(r.Context(), id)
	if err != nil {
		return err
	}
	respond(w, r, 200, filesystemResponse{result.ID.String(), result.BucketID.String(), result.RootID.String(), result.State})
	return nil
}
func (s *Server) getUsage(w http.ResponseWriter, r *http.Request) error {
	id, err := parseID(r.PathValue("bucket"))
	if err != nil {
		return err
	}
	bucket, err := s.Store.GetBucketUsage(r.Context(), id)
	if err != nil {
		return err
	}
	respond(w, r, 200, struct {
		Bucket       bucketResponse       `json:"bucket"`
		UploadLimits uploadLimitsResponse `json:"upload_limits"`
	}{
		Bucket:       bucketResponse{bucket.ID.String(), bucket.LimitBytes, bucket.UsedBytes, bucket.State},
		UploadLimits: uploadLimitsResponse{s.Store.InlineLimit, s.Store.MaxFileBytes, s.Store.MultipartThreshold, s.Store.MultipartPartBytes},
	})
	return nil
}
func queryLocator(r *http.Request) (filesystem.Locator, error) {
	q := r.URL.Query()
	for _, key := range []string{"node_id", "path", "cwd_id", "expected_node_id", "expected_parent_id"} {
		if len(q[key]) > 1 {
			return filesystem.Locator{}, invalid()
		}
	}
	result := filesystem.Locator{}
	if q.Has("expected_node_id") {
		value, err := parseID(q.Get("expected_node_id"))
		if err != nil {
			return result, err
		}
		result.ExpectedNodeID = &value
	}
	if q.Has("expected_parent_id") {
		value, err := parseID(q.Get("expected_parent_id"))
		if err != nil {
			return result, err
		}
		result.ExpectedParentID = &value
	}
	if q.Has("node_id") {
		if q.Has("path") || q.Has("cwd_id") {
			return result, invalid()
		}
		value, err := parseID(q.Get("node_id"))
		if err != nil {
			return result, err
		}
		result.NodeID = &value
		return result, nil
	}
	if !q.Has("path") {
		return result, invalid()
	}
	path := q.Get("path")
	result.Path = &path
	if q.Has("cwd_id") {
		value, err := parseID(q.Get("cwd_id"))
		if err != nil {
			return result, err
		}
		result.CwdID = &value
	}
	return result, nil
}
func contentType(r *http.Request) string {
	value := r.Header.Get("Content-Type")
	if strings.TrimSpace(value) == "" {
		return "application/octet-stream"
	}
	return value
}
