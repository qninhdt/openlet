package filesystem

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"github.com/qninhdt/openlet/packages/go/authz"
)

type CreateCopy struct {
	DestinationScopeID uuid.UUID  `json:"destination_scope_id"`
	SourceID           uuid.UUID  `json:"source_id"`
	ParentID           uuid.UUID  `json:"parent_id"`
	Name               string     `json:"name"`
	Revision           *int64     `json:"revision"`
	SourceRootID       *uuid.UUID `json:"source_root_id,omitempty"`
	DestinationRootID  *uuid.UUID `json:"destination_root_id,omitempty"`
}

// copyItem captures identity and payload fingerprints without carrying file bytes.
type copyItem struct {
	Source         uuid.UUID
	SourceParent   *uuid.UUID
	SourceName     string
	Revision       int64
	Kind           string
	Size           int64
	ObjectKey      *string
	InlineSHA256   *string
	Upper          *uuid.UUID
	Destination    uuid.UUID
	Parent         uuid.UUID
	ParentRevision int64
	Name           string
	Derived        bool
	Depth          int64
}

type copyPlan struct {
	DestinationScopeID uuid.UUID
	ID                 uuid.UUID
	ScopeID            uuid.UUID
	SourceRootID       *uuid.UUID
	DestinationRootID  *uuid.UUID

	Root         copyItem
	MaxNodes     int64
	MaxBytes     int64
	Hash         string
	ReceiptScope string
	Key          uuid.UUID
	Result       *Node
}

func copyDestination(copyID, source uuid.UUID) uuid.UUID {
	hash := sha256.New()
	hash.Write([]byte("openlet-copy-node"))
	hash.Write(copyID[:])
	hash.Write(source[:])
	var result uuid.UUID
	copy(result[:], hash.Sum(nil)[:16])
	result[6] = (result[6] & 0x0f) | 0x80
	result[8] = (result[8] & 0x3f) | 0x80
	return result
}

func (s *session) selectCopy(ctx context.Context, copyID uuid.UUID, node, parent Node, name string, derived bool, depth int64) (copyItem, error) {
	item := copyItem{Source: node.ID, SourceParent: node.ParentID, SourceName: node.Name, Revision: node.Revision,
		Kind: node.Kind, Size: node.SizeBytes, Destination: copyDestination(copyID, node.ID), Parent: parent.ID, ParentRevision: parent.Revision,
		Name: name, Derived: derived, Depth: depth}
	var content []byte
	err := s.tx.QueryRow(ctx, `SELECT object_key,COALESCE(inline_bytes,convert_to(text_content,'UTF8')) FROM files WHERE node_id=$1`, node.ID).Scan(&item.ObjectKey, &content)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return copyItem{}, databaseError(err)
	}
	if content != nil {
		digest := sha256.Sum256(content)
		encoded := hex.EncodeToString(digest[:])
		item.InlineSHA256 = &encoded
	}
	err = s.tx.QueryRow(ctx, `SELECT id FROM nodes WHERE scope_id=$1 AND parent_id=$2 ORDER BY id DESC LIMIT 1`, s.scopeID, node.ID).Scan(&item.Upper)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return copyItem{}, databaseError(err)
	}
	return item, nil
}

// prepareCopy validates both scopes before any destination writes.
func (s *Store) prepareCopy(ctx context.Context, scopeID uuid.UUID, key uuid.UUID, input CreateCopy) (copyPlan, error) {
	if input.DestinationScopeID == uuid.Nil {
		input.DestinationScopeID = scopeID
	}
	if input.DestinationRootID == nil && input.DestinationScopeID == scopeID {
		input.DestinationRootID = input.SourceRootID
	}
	actor, err := s.authorize(ctx, input.DestinationScopeID, "scope", authz.ScopeWrite)
	if err != nil {
		return copyPlan{}, err
	}
	if _, err = s.authorize(ctx, scopeID, "scope", authz.ScopeReadContent); err != nil {
		return copyPlan{}, err
	}
	if key == uuid.Nil || input.SourceID == uuid.Nil || input.ParentID == uuid.Nil {
		return copyPlan{}, apperr.New(apperr.Invalid, "VALIDATION", "copy identities required")
	}

	if _, err = pathParts(Locator{NodeID: &input.SourceID, RootID: input.SourceRootID}); err != nil {
		return copyPlan{}, err
	}
	if _, err = pathParts(Locator{NodeID: &input.ParentID, RootID: input.DestinationRootID}); err != nil {
		return copyPlan{}, err
	}
	hash, err := fingerprint(input)
	if err != nil {
		return copyPlan{}, err
	}
	session, err := s.openSession(ctx, input.DestinationScopeID, true)
	if err != nil {
		return copyPlan{}, err
	}
	defer session.tx.Rollback(ctx)
	sourceSession, err := session.inScope(ctx, scopeID)
	if err != nil {
		return copyPlan{}, err
	}

	scope := "scope/" + scopeID.String() + "/actor/" + actor.String()
	var savedHash string
	var saved []byte
	err = session.tx.QueryRow(ctx, `SELECT request_hash,result FROM idempotency_keys
 WHERE scope=$1 AND operation='copy-node' AND request_key=$2 AND expires_at>now()`, scope, key.String()).Scan(&savedHash, &saved)
	if err == nil {
		if savedHash != hash {
			return copyPlan{}, apperr.New(apperr.Conflict, "IDEMPOTENCY_CONFLICT", "request key was used for different input")
		}
		var node Node
		if err = json.Unmarshal(saved, &node); err != nil {
			return copyPlan{}, err
		}
		return copyPlan{Result: &node}, nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return copyPlan{}, databaseError(err)
	}
	if err = session.uploadCapacity(ctx, s.MaxOutstanding, s.MaxCleanupBacklog); err != nil {
		return copyPlan{}, err
	}
	source, err := sourceSession.resolveOne(ctx, Locator{NodeID: &input.SourceID, RootID: input.SourceRootID})
	if err != nil {
		return copyPlan{}, err
	}
	if err = source.revision(input.Revision); err != nil {
		return copyPlan{}, err
	}
	parent, err := session.resolveOne(ctx, Locator{NodeID: &input.ParentID, RootID: input.DestinationRootID})
	if err != nil {
		return copyPlan{}, err
	}
	if err = parent.writable(); err != nil {
		return copyPlan{}, err
	}
	if err = parent.directory(); err != nil {
		return copyPlan{}, err
	}
	if input.Name == "" {
		input.Name = source.Name
	}
	if err = session.name(parent.ID, input.Name, input.DestinationRootID); err != nil {
		return copyPlan{}, err
	}
	if scopeID == input.DestinationScopeID {
		if err = session.cycle(ctx, source.ID, parent.ID); err != nil {
			return copyPlan{}, err
		}
	}
	var occupied bool
	err = session.tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM nodes WHERE scope_id=$1 AND parent_id=$2 AND name=$3)`, input.DestinationScopeID, parent.ID, input.Name).Scan(&occupied)
	if err != nil {
		return copyPlan{}, databaseError(err)
	}
	if occupied {
		return copyPlan{}, apperr.New(apperr.Exists, "NAME_CONFLICT", "name already exists")
	}
	depth, err := session.depth(ctx, parent.ID)
	if err != nil {
		return copyPlan{}, err
	}
	if depth >= maxDepth {
		return copyPlan{}, apperr.New(apperr.Conflict, "RESOURCE_LIMIT", "tree depth limit exceeded")
	}
	id := uuid.Must(uuid.NewV7())
	root, err := sourceSession.selectCopy(ctx, id, source, parent, input.Name, false, depth+1)
	if err != nil {
		return copyPlan{}, err
	}
	if root.ObjectKey != nil && !session.allowBlobFiles {
		return copyPlan{}, apperr.New(apperr.Invalid, "BLOB_FILES_DISABLED", "destination scope does not allow blob files")
	}
	var maxBytes int64
	if err = session.tx.QueryRow(ctx, `SELECT limit_bytes FROM filesystems WHERE id=$1`, session.filesystemID).Scan(&maxBytes); err != nil {
		return copyPlan{}, databaseError(err)
	}
	if s.MaxCopyNodes <= 0 {
		return copyPlan{}, apperr.New(apperr.Conflict, "RESOURCE_LIMIT", "invalid copy node limit")
	}
	plan := copyPlan{ID: id, ScopeID: scopeID, DestinationScopeID: input.DestinationScopeID, SourceRootID: input.SourceRootID, DestinationRootID: input.DestinationRootID, Root: root, MaxNodes: s.MaxCopyNodes, MaxBytes: maxBytes, Hash: hash, ReceiptScope: scope, Key: key}
	return plan, databaseError(session.tx.Commit(ctx))
}

func (s *Store) CopyNode(ctx context.Context, scopeID, key uuid.UUID, input CreateCopy) (Node, error) {
	plan, err := s.prepareCopy(ctx, scopeID, key, input)
	if err != nil {
		return Node{}, err
	}
	if plan.Result != nil {
		return *plan.Result, nil
	}
	if err = s.copyTreeData(ctx, plan); err != nil {
		return Node{}, err
	}
	session, err := s.openSession(ctx, plan.DestinationScopeID, true)
	if err != nil {
		return Node{}, err
	}
	defer session.tx.Rollback(ctx)
	node, err := session.resolveOne(ctx, Locator{NodeID: &plan.Root.Destination, RootID: plan.DestinationRootID})
	if err != nil {
		return Node{}, err
	}
	data, err := json.Marshal(node)
	if err != nil {
		return Node{}, err
	}
	changed, err := session.tx.Exec(ctx, `INSERT INTO idempotency_keys(scope,operation,request_key,request_hash,result,expires_at)
 VALUES($1,'copy-node',$2,$3,$4,now()+interval '24 hours') ON CONFLICT(scope,operation,request_key) DO UPDATE
 SET request_hash=excluded.request_hash,result=excluded.result,expires_at=excluded.expires_at WHERE idempotency_keys.expires_at<=now()`, plan.ReceiptScope, plan.Key.String(), plan.Hash, data)
	if err != nil {
		return Node{}, databaseError(err)
	}
	if changed.RowsAffected() != 1 {
		return Node{}, apperr.New(apperr.Conflict, "IDEMPOTENCY_CONFLICT", "request key was used for another completed copy")
	}
	return node, databaseError(session.tx.Commit(ctx))
}
