package httpapi

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strconv"
	"strings"

	"github.com/qninhdt/openlet/packages/go/apperr"
	sharedhttp "github.com/qninhdt/openlet/packages/go/httpapi"
)

const maxJSONBody = 8 * 1024 * 1024

func decodeJSON(w http.ResponseWriter, r *http.Request, destination any) error {
	tooLarge := apperr.New(apperr.Limit, "REQUEST_LIMIT", "request body too large")
	if r.ContentLength > maxJSONBody {
		return tooLarge
	}
	r.Body = http.MaxBytesReader(w, r.Body, maxJSONBody)
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	err := decoder.Decode(destination)
	if err == nil {
		var extra any
		err = decoder.Decode(&extra)
		if errors.Is(err, io.EOF) {
			return nil
		}
	}
	var limit *http.MaxBytesError
	if errors.As(err, &limit) {
		return tooLarge
	}
	return apperr.New(apperr.Invalid, "VALIDATION", "invalid JSON request")
}

func validRevision(value string) bool {
	revision, err := strconv.ParseInt(value, 10, 64)
	return err == nil && revision > 0 && strconv.FormatInt(revision, 10) == value
}

func requiredRevision(r *http.Request) (string, error) {
	values := r.Header.Values("If-Match")
	if len(values) == 0 {
		return "", apperr.New(apperr.Precondition, "PRECONDITION_REQUIRED", "If-Match required")
	}
	if len(values) == 1 && len(values[0]) >= 3 {
		value := values[0]
		if value[0] == '"' && value[len(value)-1] == '"' && validRevision(value[1:len(value)-1]) {
			return value[1 : len(value)-1], nil
		}
	}
	return "", apperr.New(apperr.Invalid, "VALIDATION", "invalid If-Match")
}

func writeJSON(w http.ResponseWriter, r *http.Request, code int, location, etag string, value any) {
	if location != "" && (!strings.HasPrefix(location, "/") || strings.HasPrefix(location, "//") || strings.ContainsAny(location, "\r\n\x00\\")) {
		sharedhttp.WriteError(w, r, apperr.New(apperr.Internal, "INTERNAL", "invalid resource location"))
		return
	}
	body, err := json.Marshal(value)
	if err != nil {
		sharedhttp.WriteError(w, r, err)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	if etag != "" {
		w.Header().Set("ETag", etag)
	}
	if location != "" {
		w.Header().Set("Location", location)
	}
	w.WriteHeader(code)
	if _, err := w.Write(body); err != nil {
		panic(http.ErrAbortHandler)
	}
}
