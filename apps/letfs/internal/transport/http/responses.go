package httpapi

import (
	"encoding/json"
	"time"

	"github.com/qninhdt/openlet/apps/letfs/internal/clients/storage"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
)

type timestamp struct{ time.Time }

func (value timestamp) MarshalJSON() ([]byte, error) {
	if value.Year() < 1 || value.Year() > 9999 {
		return nil, &time.ParseError{Layout: time.RFC3339Nano, Value: value.String()}
	}
	format := "2006-01-02T15:04:05Z07:00"
	switch nanos := value.Nanosecond(); {
	case nanos == 0:
	case nanos%1_000_000 == 0:
		format = "2006-01-02T15:04:05.000Z07:00"
	case nanos%1_000 == 0:
		format = "2006-01-02T15:04:05.000000Z07:00"
	default:
		format = "2006-01-02T15:04:05.000000000Z07:00"
	}
	return json.Marshal(value.UTC().Format(format))
}

type filesystemResponse struct {
	ID         string `json:"id"`
	LimitBytes int64  `json:"limit_bytes,string"`
	UsedBytes  int64  `json:"used_bytes,string"`
	NodeCount  int64  `json:"node_count,string"`
	State      string `json:"state"`
}

type nodeResponse struct {
	ID           string    `json:"id"`
	ScopeID      string    `json:"scope_id"`
	ParentID     *string   `json:"parent_id,omitempty"`
	Name         string    `json:"name"`
	Kind         string    `json:"kind"`
	Revision     int64     `json:"revision,string"`
	SizeBytes    int64     `json:"size_bytes,string"`
	MediaType    *string   `json:"media_type,omitempty"`
	CreatedAt    timestamp `json:"created_at"`
	UpdatedAt    timestamp `json:"updated_at"`
	Title        *string   `json:"title,omitempty"`
	Description  *string   `json:"description,omitempty"`
	SemanticType *string   `json:"semantic_type,omitempty"`
	Context      *string   `json:"context,omitempty"`
}

func nodeResponseFrom(value filesystem.Node) nodeResponse {
	var parent *string
	if value.ParentID != nil {
		id := value.ParentID.String()
		parent = &id
	}
	return nodeResponse{
		ID: value.ID.String(), ScopeID: value.ScopeID.String(), ParentID: parent,
		Name: value.Name, Kind: value.Kind, Revision: value.Revision, SizeBytes: value.SizeBytes,
		MediaType: value.MediaType, CreatedAt: timestamp{value.CreatedAt}, UpdatedAt: timestamp{value.UpdatedAt},
		Title: value.Title, Description: value.Description, SemanticType: value.SemanticType, Context: value.Context,
	}
}

type trashResponse struct {
	ID        string    `json:"id"`
	NodeID    string    `json:"node_id"`
	ParentID  *string   `json:"parent_id,omitempty"`
	Name      string    `json:"name"`
	ActorID   string    `json:"actor_id"`
	Status    string    `json:"status"`
	CreatedAt timestamp `json:"created_at"`
}

func trashResponseFrom(value filesystem.TrashEntry) trashResponse {
	var parent *string
	if value.ParentID != nil {
		id := value.ParentID.String()
		parent = &id
	}
	return trashResponse{value.ID.String(), value.NodeID.String(), parent, value.Name, value.ActorID.String(), value.Status, timestamp{value.CreatedAt}}
}

type signedUploadResponse struct {
	URL           string            `json:"url"`
	Headers       map[string]string `json:"headers"`
	ContentLength int64             `json:"content_length,string"`
	ExpiresAt     timestamp         `json:"expires_at"`
}

func signedUploadResponseFrom(value storage.SignedUpload) signedUploadResponse {
	headers := value.Headers
	if headers == nil {
		headers = map[string]string{}
	}
	return signedUploadResponse{value.URL, headers, value.ContentLength, timestamp{value.ExpiresAt}}
}

type publicationResponse struct {
	NodeID   string `json:"node_id"`
	Status   string `json:"status"`
	Revision int64  `json:"revision,string"`
}

func publicationResponseFrom(value filesystem.UploadPublication) publicationResponse {
	return publicationResponse{value.NodeID.String(), value.Status, value.Revision}
}

type uploadResponse struct {
	ID            string                `json:"id"`
	Status        string                `json:"status"`
	Transport     string                `json:"transport"`
	ExpiresAt     timestamp             `json:"expires_at"`
	SizeBytes     *int64                `json:"size_bytes,omitempty,string"`
	PartSizeBytes *int64                `json:"part_size_bytes,omitempty,string"`
	PartCount     *int32                `json:"part_count,omitempty"`
	Transfer      *signedUploadResponse `json:"transfer,omitempty"`
	Publication   *publicationResponse  `json:"publication,omitempty"`
}

func uploadResponseFrom(value filesystem.Upload) uploadResponse {
	result := uploadResponse{ID: value.ID.String(), Status: value.State, Transport: value.Transport, ExpiresAt: timestamp{value.ExpiresAt}, SizeBytes: &value.SizeBytes, PartSizeBytes: value.PartSize}
	if value.PartSize != nil {
		count := value.PartCount()
		result.PartCount = &count
	}
	if value.Transfer != nil {
		transfer := signedUploadResponseFrom(*value.Transfer)
		result.Transfer = &transfer
	}
	if value.Publication != nil {
		publication := publicationResponseFrom(*value.Publication)
		result.Publication = &publication
	}
	return result
}

type uploadPartResponse struct {
	PartNumber int32                `json:"part_number"`
	Transfer   signedUploadResponse `json:"transfer"`
}
