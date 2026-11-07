package filesystem

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"github.com/qninhdt/openlet/packages/go/authz"
)

type CreateCopy struct {
	DestinationScopeID uuid.UUID `json:"destination_scope_id"`
	SourceID           uuid.UUID `json:"source_id"`
	ParentID           uuid.UUID `json:"parent_id"`
	Name               string    `json:"name"`
	Revision           *int64    `json:"revision"`
}

// CopyItem captures identity and payload fingerprints without carrying file bytes.
type CopyItem struct {
	Source         uuid.UUID  `json:"source"`
	SourceParent   *uuid.UUID `json:"source_parent"`
	SourceName     string     `json:"source_name"`
	Revision       int64      `json:"revision,string"`
	Kind           string     `json:"kind"`
	Size           int64      `json:"size"`
	ObjectKey      *string    `json:"object_key"`
	InlineSHA256   *string    `json:"inline_sha256"`
	Upper          *uuid.UUID `json:"upper"`
	Destination    uuid.UUID  `json:"destination"`
	Parent         uuid.UUID  `json:"parent"`
	ParentRevision int64      `json:"parent_revision,string"`
	Name           string     `json:"name"`
	Derived        bool       `json:"derived"`
	Depth          int64      `json:"depth"`
}

type CopyAdmission struct {
	FilesystemID       uuid.UUID `json:"filesystem_id"`
	DestinationScopeID uuid.UUID `json:"destination_scope_id"`
	ID                 uuid.UUID `json:"id"`
	ScopeID            uuid.UUID `json:"scope_id"`
	ActorID            uuid.UUID `json:"actor_id"`
	Root               CopyItem  `json:"root"`
	MaxNodes           int64     `json:"max_nodes"`
	MaxBytes           int64     `json:"max_bytes"`
	Deadline           time.Time `json:"deadline"`
}

type CopyResult struct {
	ID                uuid.UUID `json:"id"`
	DestinationRootID uuid.UUID `json:"destination_root_id"`
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

func (s *session) selectCopy(ctx context.Context, copyID uuid.UUID, node, parent Node, name string, derived bool, depth int64) (CopyItem, error) {
	item := CopyItem{Source: node.ID, SourceParent: node.ParentID, SourceName: node.Name, Revision: node.Revision,
		Kind: node.Kind, Size: node.SizeBytes, Destination: copyDestination(copyID, node.ID), Parent: parent.ID, ParentRevision: parent.Revision,
		Name: name, Derived: derived, Depth: depth}
	var content []byte
	err := s.tx.QueryRow(ctx, `SELECT object_key,inline_bytes FROM files WHERE node_id=$1`, node.ID).Scan(&item.ObjectKey, &content)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return CopyItem{}, databaseError(err)
	}
	if content != nil {
		digest := sha256.Sum256(content)
		encoded := hex.EncodeToString(digest[:])
		item.InlineSHA256 = &encoded
	}
	err = s.tx.QueryRow(ctx, `SELECT id FROM nodes WHERE scope_id=$1 AND parent_id=$2 ORDER BY id DESC LIMIT 1`, s.scopeID, node.ID).Scan(&item.Upper)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return CopyItem{}, databaseError(err)
	}
	return item, nil
}

// AdmitCopy persists admission; callers must dispatch its workflow before acknowledging a job.
func (s *Store) AdmitCopy(ctx context.Context, scopeID uuid.UUID, key uuid.UUID, input CreateCopy) (CopyAdmission, error) {
	actor, err := s.authorize(ctx, input.DestinationScopeID, "scope", authz.ScopeWrite)
	if err != nil {
		return CopyAdmission{}, err
	}
	if _, err = s.authorize(ctx, scopeID, "scope", authz.ScopeReadContent); err != nil {
		return CopyAdmission{}, err
	}
	if key == uuid.Nil || input.SourceID == uuid.Nil || input.ParentID == uuid.Nil {
		return CopyAdmission{}, apperr.New(apperr.Invalid, "VALIDATION", "copy identities required")
	}
	if err = ValidateName(input.Name); err != nil {
		return CopyAdmission{}, err
	}
	if _, err = pathParts(Locator{NodeID: &input.SourceID}); err != nil {
		return CopyAdmission{}, err
	}
	hash, err := fingerprint(input)
	if err != nil {
		return CopyAdmission{}, err
	}
	session, err := s.openSession(ctx, input.DestinationScopeID, true)
	if err != nil {
		return CopyAdmission{}, err
	}
	defer session.tx.Rollback(ctx)
	sourceSession, err := session.inScope(ctx, scopeID)
	if err != nil {
		return CopyAdmission{}, err
	}

	scope := "scope/" + scopeID.String() + "/actor/" + actor.String()
	var savedHash string
	var saved []byte
	err = session.tx.QueryRow(ctx, `SELECT request_hash,result FROM idempotency_keys
 WHERE scope=$1 AND operation='copy-node' AND request_key=$2 AND (expires_at IS NULL OR expires_at>now())`, scope, key.String()).Scan(&savedHash, &saved)
	if err == nil {
		if savedHash != hash {
			return CopyAdmission{}, apperr.New(apperr.Conflict, "IDEMPOTENCY_CONFLICT", "request key was used for different input")
		}
		var admission CopyAdmission
		if err = json.Unmarshal(saved, &admission); err != nil {
			return CopyAdmission{}, apperr.New(apperr.Conflict, "INVALID_RECEIPT", "invalid saved receipt")
		}
		return admission, nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return CopyAdmission{}, databaseError(err)
	}
	if err = session.uploadCapacity(ctx, s.MaxOutstanding, s.MaxCleanupBacklog); err != nil {
		return CopyAdmission{}, err
	}
	source, err := sourceSession.resolveOne(ctx, Locator{NodeID: &input.SourceID})
	if err != nil {
		return CopyAdmission{}, err
	}
	if err = source.revision(input.Revision); err != nil {
		return CopyAdmission{}, err
	}
	parent, err := session.resolveOne(ctx, Locator{NodeID: &input.ParentID})
	if err != nil {
		return CopyAdmission{}, err
	}
	if err = parent.writable(); err != nil {
		return CopyAdmission{}, err
	}
	if err = parent.directory(); err != nil {
		return CopyAdmission{}, err
	}
	if err = session.name(parent.ID, input.Name); err != nil {
		return CopyAdmission{}, err
	}
	if scopeID == input.DestinationScopeID {
		if err = session.cycle(ctx, source.ID, parent.ID); err != nil {
			return CopyAdmission{}, err
		}
	}
	var occupied bool
	err = session.tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM nodes WHERE scope_id=$1 AND parent_id=$2 AND name=$3)`, input.DestinationScopeID, parent.ID, input.Name).Scan(&occupied)
	if err != nil {
		return CopyAdmission{}, databaseError(err)
	}
	if occupied {
		return CopyAdmission{}, apperr.New(apperr.Exists, "NAME_CONFLICT", "name already exists")
	}
	depth, err := session.depth(ctx, parent.ID)
	if err != nil {
		return CopyAdmission{}, err
	}
	if depth >= maxDepth {
		return CopyAdmission{}, apperr.New(apperr.Conflict, "RESOURCE_LIMIT", "tree depth limit exceeded")
	}
	id := uuid.Must(uuid.NewV7())
	root, err := sourceSession.selectCopy(ctx, id, source, parent, input.Name, false, depth+1)
	if err != nil {
		return CopyAdmission{}, err
	}
	if root.ObjectKey != nil && !session.allowBlobFiles {
		return CopyAdmission{}, apperr.New(apperr.Invalid, "BLOB_FILES_DISABLED", "destination scope does not allow blob files")
	}
	var maxBytes int64
	if err = session.tx.QueryRow(ctx, `SELECT limit_bytes FROM filesystems WHERE id=$1`, session.filesystemID).Scan(&maxBytes); err != nil {
		return CopyAdmission{}, databaseError(err)
	}
	if s.MaxCopyNodes <= 0 {
		return CopyAdmission{}, apperr.New(apperr.Conflict, "RESOURCE_LIMIT", "invalid copy node limit")
	}
	admission := CopyAdmission{ID: id, FilesystemID: session.filesystemID, ScopeID: scopeID, DestinationScopeID: input.DestinationScopeID, ActorID: actor, Root: root, MaxNodes: s.MaxCopyNodes, MaxBytes: maxBytes, Deadline: time.Now().UTC().Add(time.Hour)}
	saved, err = json.Marshal(admission)
	if err != nil {
		return CopyAdmission{}, err
	}
	_, err = session.tx.Exec(ctx, `INSERT INTO idempotency_keys(scope,operation,request_key,request_hash,result)
 VALUES($1,'copy-node',$2,$3,$4) ON CONFLICT(scope,operation,request_key) DO UPDATE SET request_hash=excluded.request_hash,
 result=excluded.result,expires_at=NULL WHERE idempotency_keys.expires_at<=now()`, scope, key.String(), hash, saved)
	if err != nil {
		return CopyAdmission{}, databaseError(err)
	}
	return admission, databaseError(session.tx.Commit(ctx))
}
