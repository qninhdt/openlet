package httpapi

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strconv"
	"strings"

	"google.golang.org/grpc/codes"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
	"openlet/packages/go/rpc"
)

const maxJSONBody = 8 * 1024 * 1024

func decodeJSON(w http.ResponseWriter, r *http.Request, destination any) error {
	tooLarge := rpc.Fault(codes.ResourceExhausted, "REQUEST_LIMIT", "request body too large")
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
	return rpc.Fault(codes.InvalidArgument, "VALIDATION", "invalid JSON request")
}

func validRevision(value string) bool {
	revision, err := strconv.ParseInt(value, 10, 64)
	return err == nil && revision > 0 && strconv.FormatInt(revision, 10) == value
}

func requiredRevision(r *http.Request) (string, error) {
	values := r.Header.Values("If-Match")
	if len(values) == 0 {
		return "", rpc.Fault(codes.FailedPrecondition, "PRECONDITION_REQUIRED", "If-Match required")
	}
	if len(values) == 1 && len(values[0]) >= 3 {
		value := values[0]
		if value[0] == '"' && value[len(value)-1] == '"' && validRevision(value[1:len(value)-1]) {
			return value[1 : len(value)-1], nil
		}
	}
	return "", rpc.Fault(codes.InvalidArgument, "VALIDATION", "invalid If-Match")
}

func writeProto(w http.ResponseWriter, r *http.Request, code int, location, etag string, message proto.Message) {
	if location != "" && (!strings.HasPrefix(location, "/") || strings.HasPrefix(location, "//") || strings.ContainsAny(location, "\r\n\x00\\")) {
		rpc.WriteHTTPError(w, r, rpc.Fault(codes.Internal, "INTERNAL", "invalid resource location"))
		return
	}
	body, err := (protojson.MarshalOptions{UseProtoNames: true, EmitDefaultValues: true}).Marshal(message)
	if err != nil {
		rpc.WriteHTTPError(w, r, err)
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
