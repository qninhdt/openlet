package httpapi

import (
	"net/http"
	"strings"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
)

func optionalUUID(raw *string) (*uuid.UUID, error) {
	if raw == nil {
		return nil, nil
	}
	id, err := parseID(*raw)
	return &id, err
}

func (s *Server) copyNode(w http.ResponseWriter, r *http.Request) error {
	raw, ok := strings.CutSuffix(r.PathValue("node"), ":copy")
	if !ok {
		return invalid()
	}
	source, err := parseID(raw)
	if err != nil {
		return err
	}
	scope, err := s.requestContext(r)
	if err != nil {
		return err
	}
	key, err := requestKey(r)
	if err != nil {
		return err
	}
	rev, err := revision(r)
	if err != nil {
		return err
	}
	var input struct {
		DestinationScopeID *string `json:"destination_scope_id,omitempty"`
		ParentID           string  `json:"parent_id"`
		Name               string  `json:"name,omitempty"`
	}
	if err = decodeJSON(w, r, &input); err != nil {
		return err
	}
	parent, err := parseID(input.ParentID)
	if err != nil {
		return err
	}
	destination, err := optionalUUID(input.DestinationScopeID)
	if err != nil {
		return err
	}
	destinationID := scope
	if destination != nil {
		destinationID = *destination
	}
	node, err := s.Service.CreateCopy(r.Context(), scope, key, filesystem.CreateCopy{DestinationScopeID: destinationID, SourceID: source, ParentID: parent, Name: input.Name, Revision: rev})
	if err != nil {
		return err
	}
	respond(w, r, http.StatusCreated, nodeResponseFrom(node))
	return nil
}
