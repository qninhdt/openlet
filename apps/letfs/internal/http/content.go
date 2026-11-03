package httpapi

import (
	"fmt"
	"net/http"
	"net/url"
	"strconv"
	"strings"

	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/rpc"
	"google.golang.org/grpc/codes"
)

func singleRange(values []string, size int64) (start, end int64, partial bool, err error) {
	invalid := func() (int64, int64, bool, error) {
		return 0, 0, false, rpc.Fault(codes.OutOfRange, "INVALID_RANGE", "one satisfiable byte range required")
	}
	if len(values) == 0 {
		return 0, size - 1, false, nil
	}
	if len(values) != 1 || size <= 0 || !strings.HasPrefix(values[0], "bytes=") {
		return invalid()
	}
	a, b, ok := strings.Cut(strings.TrimPrefix(values[0], "bytes="), "-")
	if !ok {
		return invalid()
	}
	number := func(value string) (uint64, error) {
		for _, digit := range value {
			if digit < '0' || digit > '9' {
				return 0, strconv.ErrSyntax
			}
		}
		return strconv.ParseUint(value, 10, 64)
	}
	if a == "" {
		suffix, parseErr := number(b)
		if parseErr != nil || suffix == 0 {
			return invalid()
		}
		if suffix < uint64(size) {
			start = size - int64(suffix)
		}
		return start, size - 1, true, nil
	}
	first, parseErr := number(a)
	if parseErr != nil || first >= uint64(size) {
		return invalid()
	}
	last := uint64(size - 1)
	if b != "" {
		last, parseErr = number(b)
		if parseErr != nil || last < first {
			return invalid()
		}
		last = min(last, uint64(size-1))
	}
	return int64(first), int64(last), true, nil
}

// writeDownload receives an already-authorized descriptor; errors precede response headers.
func writeDownload(w http.ResponseWriter, r *http.Request, download *letfsv1.Download) error {
	if download == nil || download.SizeBytes < 0 || strings.ContainsAny(download.Mime, "\r\n\x00") {
		return rpc.Fault(codes.Internal, "INTERNAL", "invalid download descriptor")
	}
	if _, present := r.Header["If-Match"]; present {
		return rpc.Fault(codes.InvalidArgument, "VALIDATION", "use revision query for content reads")
	}
	if revisions, present := r.URL.Query()["revision"]; present {
		if len(revisions) != 1 || !validRevision(revisions[0]) {
			return rpc.Fault(codes.InvalidArgument, "VALIDATION", "invalid revision")
		}
		if `"`+revisions[0]+`"` != download.Etag {
			return rpc.Fault(codes.FailedPrecondition, "REVISION_MISMATCH", "revision mismatch")
		}
	}
	start, end, partial, err := singleRange(r.Header.Values("Range"), download.SizeBytes)
	if err != nil {
		return err
	}
	switch source := download.Source.(type) {
	case *letfsv1.Download_SignedUrl:
		target, err := url.Parse(source.SignedUrl)
		if err != nil || (target.Scheme != "https" && target.Scheme != "http") || target.Host == "" || target.User != nil || target.Fragment != "" || strings.ContainsAny(source.SignedUrl, "\r\n\x00") {
			return rpc.Fault(codes.Internal, "INTERNAL", "invalid download descriptor")
		}
		w.Header().Set("Location", source.SignedUrl)
		w.Header().Set("ETag", download.Etag)
		w.Header().Set("Cache-Control", "private, no-store")
		w.WriteHeader(http.StatusTemporaryRedirect)
		return nil
	case *letfsv1.Download_InlineContent:
		if int64(len(source.InlineContent)) != download.SizeBytes {
			return rpc.Fault(codes.Internal, "INTERNAL", "invalid download descriptor")
		}
		content := source.InlineContent
		if partial {
			content = content[start : end+1]
		}
		mime := download.Mime
		if mime == "" {
			mime = "application/octet-stream"
		}
		w.Header().Set("ETag", download.Etag)
		w.Header().Set("Cache-Control", "private, no-store")
		w.Header().Set("Content-Type", mime)
		w.Header().Set("Content-Disposition", "attachment")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Accept-Ranges", "bytes")
		w.Header().Set("Content-Length", strconv.Itoa(len(content)))
		if partial {
			w.Header().Set("Content-Range", fmt.Sprintf("bytes %d-%d/%d", start, end, download.SizeBytes))
			w.WriteHeader(http.StatusPartialContent)
		}
		if _, err := w.Write(content); err != nil {
			panic(http.ErrAbortHandler)
		}
		return nil
	default:
		return rpc.Fault(codes.Internal, "INTERNAL", "invalid download descriptor")
	}
}
