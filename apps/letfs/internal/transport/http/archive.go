package httpapi

import (
	"errors"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	"github.com/qninhdt/openlet/packages/go/apperr"
)

func writeArchive(w http.ResponseWriter, deadline time.Time, name string, source io.Reader) error {
	if name == "" || strings.ContainsAny(name, "\r\n\x00") {
		return apperr.New(apperr.Internal, "INTERNAL", "invalid archive descriptor")
	}
	controller := http.NewResponseController(w)
	if err := controller.SetWriteDeadline(deadline); err != nil && !errors.Is(err, http.ErrNotSupported) {
		return apperr.New(apperr.Unavailable, "DEPENDENCY_UNAVAILABLE", "archive response unavailable")
	}
	defer controller.SetWriteDeadline(time.Time{})
	filename := strings.ReplaceAll(url.QueryEscape(name), "+", "%20")
	w.Header().Set("Content-Type", "application/zip")
	w.Header().Set("Content-Disposition", `attachment; filename="download.zip"; filename*=UTF-8''`+filename)
	w.Header().Set("Cache-Control", "private, no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	buffer := make([]byte, 65536)
	written := false
	for {
		n, err := source.Read(buffer)
		if n > 0 {
			if _, writeErr := w.Write(buffer[:n]); writeErr != nil {
				panic(http.ErrAbortHandler)
			}
			written = true
			if flushErr := controller.Flush(); flushErr != nil {
				panic(http.ErrAbortHandler)
			}
		}
		if errors.Is(err, io.EOF) && written {
			return nil
		}
		if err != nil || n == 0 {
			panic(http.ErrAbortHandler)
		}
	}
}

func (s *Server) getArchive(w http.ResponseWriter, r *http.Request) error {
	fs, err := uuid.Parse(fsID(r))
	if err != nil {
		return invalid()
	}
	node, err := uuid.Parse(r.PathValue("node"))
	if err != nil {
		return invalid()
	}
	archive, err := s.Store.OpenArchive(r.Context(), fs, []filesystem.Mount{{Path: mountPath(r), FilesystemID: fs}}, node)
	if err != nil {
		return err
	}
	defer archive.Close()
	deadline, _ := archive.Context.Deadline()
	return writeArchive(w, deadline, archive.Name, archive)
}
