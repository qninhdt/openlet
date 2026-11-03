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
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"google.golang.org/grpc/codes"
	"google.golang.org/protobuf/proto"
	"openlet/apps/letfs/internal/filesystem"
	letfsv1 "openlet/packages/go/gen/openlet_api/letfs/v1"
	"openlet/packages/go/identity"
	"openlet/packages/go/rpc"
)

type Server struct {
	API          letfsv1.FilesystemServiceServer
	Store        *filesystem.Store
	GatewayToken string
	Ready        func(context.Context) error
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	route := func(pattern string, handle func(http.ResponseWriter, *http.Request) error) {
		mux.HandleFunc(pattern, func(w http.ResponseWriter, r *http.Request) {
			if err := handle(w, r); err != nil {
				rpc.WriteHTTPError(w, r, err)
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
		rpc.WriteHTTPError(w, r, rpc.Fault(codes.NotFound, "NOT_FOUND", "resource not found"))
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
		// In-process calls do not run the native gRPC authentication interceptor.
		principal, err := identity.AuthenticateGateway(r.Header, s.GatewayToken, false)
		if err != nil {
			code := "UNAUTHENTICATED"
			if errors.Is(err, identity.ErrOnboardingRequired) {
				code = "ONBOARDING_REQUIRED"
			}
			rpc.WriteHTTPError(w, r, rpc.Fault(codes.Unauthenticated, code, err.Error()))
			return
		}
		if !strings.HasSuffix(r.URL.Path, "/archive") {
			ctx, cancel := context.WithTimeout(r.Context(), 120*time.Second)
			defer cancel()
			r = r.WithContext(ctx)
		}
		if values, ok := r.URL.Query()["mount_path"]; ok && (len(values) != 1 || values[0] == "") {
			rpc.WriteHTTPError(w, r, invalid())
			return
		}
		started := time.Now()
		defer func() {
			slog.InfoContext(r.Context(), "HTTP request", "request_id", id.String(), "method", r.Method, "route", r.Pattern, "elapsed_ms", time.Since(started).Milliseconds())
		}()
		mux.ServeHTTP(w, r.WithContext(identity.WithPrincipal(r.Context(), principal)))
	}), "openlet-letfs")
}

func invalid() error              { return rpc.Fault(codes.InvalidArgument, "VALIDATION", "invalid request") }
func fsID(r *http.Request) string { return r.PathValue("filesystem") }
func nodeLocator(id string) *letfsv1.Locator {
	return &letfsv1.Locator{Target: &letfsv1.Locator_NodeId{NodeId: id}}
}
func mountPath(r *http.Request) string {
	path := r.URL.Query().Get("mount_path")
	if path == "" {
		path = "/"
	}
	return path
}
func pathContext(r *http.Request) *letfsv1.PathContext {
	path := mountPath(r)
	return &letfsv1.PathContext{Mounts: []*letfsv1.Mount{{Path: path, FilesystemId: fsID(r)}}}
}
func requestKey(r *http.Request) (string, error) {
	values := r.Header.Values("Idempotency-Key")
	if len(values) != 1 {
		return "", invalid()
	}
	id, err := uuid.Parse(values[0])
	if err != nil || id == uuid.Nil {
		return "", invalid()
	}
	return id.String(), nil
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
func respond(w http.ResponseWriter, r *http.Request, code int, value proto.Message) {
	etag, location := "", ""
	switch item := value.(type) {
	case *letfsv1.Node:
		etag = `"` + strconv.FormatInt(item.Revision, 10) + `"`
		if code == http.StatusCreated {
			location = "/v1/filesystems/" + fsID(r) + "/nodes/" + item.Id
		}
	case *letfsv1.Copy:
		location = "/v1/filesystems/" + fsID(r) + "/copies/" + item.Id
	case *letfsv1.Upload:
		if code == http.StatusCreated {
			location = "/v1/filesystems/" + fsID(r) + "/uploads/" + item.Id
		}
	case *letfsv1.TrashEntry:
		if code == http.StatusCreated || code == http.StatusAccepted {
			location = "/v1/filesystems/" + fsID(r) + "/trash-entries/" + item.Id
		}
	case *letfsv1.UploadPublication:
		etag = `"` + strconv.FormatInt(item.Revision, 10) + `"`
	}
	writeProto(w, r, code, location, etag, value)
}
func (s *Server) getFilesystem(w http.ResponseWriter, r *http.Request) error {
	result, err := s.API.GetFilesystem(r.Context(), &letfsv1.GetFilesystemRequest{FilesystemId: fsID(r)})
	if err != nil {
		return err
	}
	respond(w, r, 200, result.Filesystem)
	return nil
}
func (s *Server) getUsage(w http.ResponseWriter, r *http.Request) error {
	result, err := s.API.GetBucketUsage(r.Context(), &letfsv1.GetBucketUsageRequest{BucketId: r.PathValue("bucket")})
	if err != nil {
		return err
	}
	respond(w, r, 200, result)
	return nil
}
func queryLocator(r *http.Request) (*letfsv1.Locator, error) {
	q := r.URL.Query()
	for _, key := range []string{"node_id", "path", "cwd_id", "expected_node_id", "expected_parent_id"} {
		if len(q[key]) > 1 {
			return nil, invalid()
		}
	}
	result := &letfsv1.Locator{}
	if q.Has("expected_node_id") {
		value := q.Get("expected_node_id")
		result.ExpectedNodeId = &value
	}
	if q.Has("expected_parent_id") {
		value := q.Get("expected_parent_id")
		result.ExpectedParentId = &value
	}
	if q.Has("node_id") {
		if q.Has("path") || q.Has("cwd_id") {
			return nil, invalid()
		}
		result.Target = &letfsv1.Locator_NodeId{NodeId: q.Get("node_id")}
		return result, nil
	}
	if !q.Has("path") {
		return nil, invalid()
	}
	locator := &letfsv1.PathLocator{Path: q.Get("path")}
	if q.Has("cwd_id") {
		value := q.Get("cwd_id")
		locator.CwdId = &value
	}
	result.Target = &letfsv1.Locator_Path{Path: locator}
	return result, nil
}
func locatorMessage(value filesystem.Locator) (*letfsv1.Locator, error) {
	if (value.NodeID == nil) == (value.Path == nil) || value.NodeID != nil && value.CwdID != nil {
		return nil, invalid()
	}
	result := &letfsv1.Locator{}
	if value.NodeID != nil {
		result.Target = &letfsv1.Locator_NodeId{NodeId: value.NodeID.String()}
	} else {
		path := &letfsv1.PathLocator{Path: *value.Path}
		if value.CwdID != nil {
			id := value.CwdID.String()
			path.CwdId = &id
		}
		result.Target = &letfsv1.Locator_Path{Path: path}
	}
	if value.ExpectedNodeID != nil {
		id := value.ExpectedNodeID.String()
		result.ExpectedNodeId = &id
	}
	if value.ExpectedParentID != nil {
		id := value.ExpectedParentID.String()
		result.ExpectedParentId = &id
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
