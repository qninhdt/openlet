package workspace

import (
	"context"
	"errors"
	"time"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/identity"
)

func validateScopeMutation(in Mutation) error {
	if in.Kind != "scope" || in.WorkspaceID == uuid.Nil || in.ActorID == uuid.Nil || in.ScopeID == uuid.Nil || !(identity.Actor{Kind: in.TargetKind, ID: in.TargetID}).Valid() ||
		(in.ScopeRole != "manager" && in.ScopeRole != "editor" && in.ScopeRole != "viewer") || (in.TargetKind == identity.Leta && in.ScopeRole == "manager") ||
		(in.PersonalOwnerID != uuid.Nil && (in.PersonalOwnerID != in.ActorID || in.TargetKind != identity.Leta || in.Revoke)) {
		return Fault{"VALIDATION"}
	}
	return nil
}

func (s *Service) scopeAdmission(ctx context.Context, in Mutation) (Workspace, error) {
	value, err := s.Store.resourceRecord(ctx, in.WorkspaceID)
	if err != nil {
		return value, err
	}
	if err = value.checkActive(); err != nil {
		return value, err
	}
	var owned bool
	if err = s.Store.DB.QueryRow(ctx, `SELECT $2=shared_scope_id OR EXISTS(SELECT 1 FROM workspace_members WHERE workspace_id=$1 AND personal_scope_id=$2) FROM workspaces WHERE id=$1`, in.WorkspaceID, in.ScopeID).Scan(&owned); err != nil {
		return value, err
	}
	if in.TargetKind == identity.Leta {
		if _, err = s.Store.Authorize(ctx, in.WorkspaceID, in.ActorID, authz.WorkspaceRead); err != nil {
			return value, err
		}
		binding, err := s.letaBinding(ctx, in.WorkspaceID, in.TargetID)
		if err != nil {
			return value, err
		}
		if binding.Status != "active" {
			return value, Fault{"STATE_CONFLICT"}
		}
		owned = owned || in.ScopeID == binding.HomeScopeID
		if in.PersonalOwnerID != uuid.Nil {
			member, err := s.Store.Member(ctx, in.WorkspaceID, in.PersonalOwnerID)
			if err != nil {
				return value, err
			}
			if member.Status != "active" || member.PersonalScopeID != in.ScopeID {
				return value, Fault{"FORBIDDEN"}
			}
		}
	} else {
		if _, err = s.Users.Summaries(ctx, []uuid.UUID{in.TargetID}); err != nil {
			return value, err
		}
	}
	if !owned {
		return value, Fault{"NOT_FOUND"}
	}
	allowed, err := authz.Check(ctx, s.Store.Graph, identity.Actor{Kind: identity.User, ID: in.ActorID}, authz.ScopeManageAccess, authz.Resource{Type: "scope", ID: in.ScopeID.String()})
	if err != nil {
		return value, err
	}
	if !allowed {
		return value, Fault{"FORBIDDEN"}
	}
	return value, nil
}

// A retained completion or currently sufficient rights recovers a lost acknowledgement.
func (s *Service) scopeReplay(ctx context.Context, in Mutation) (Workspace, bool, error) {
	var hash string
	var ws uuid.UUID
	var completed bool
	err := s.Store.DB.QueryRow(ctx, `SELECT request_hash,workspace_id,expires_at IS NOT NULL FROM idempotency_keys WHERE actor_id=$1 AND request_key=$2 AND (expires_at IS NULL OR expires_at>now())`, in.ActorID, in.Key).Scan(&hash, &ws, &completed)
	found := err == nil
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return Workspace{}, false, err
	}
	if found && (hash != Fingerprint(in) || ws != in.WorkspaceID) {
		return Workspace{}, false, Fault{"IDEMPOTENCY_CONFLICT"}
	}
	if completed {
		value, err := s.Store.resourceRecord(ctx, in.WorkspaceID)
		return value, true, err
	}
	if in.TargetKind != identity.Leta {
		return Workspace{}, false, nil
	}
	// Canonical IDs are still checked, but current active lifecycle is not required to observe an applied grant.
	binding, err := s.letaBinding(ctx, in.WorkspaceID, in.TargetID)
	if err != nil {
		return Workspace{}, false, err
	}
	var owned bool
	if err = s.Store.DB.QueryRow(ctx, `SELECT ($3::uuid='00000000-0000-0000-0000-000000000000' AND $2=shared_scope_id) OR EXISTS(SELECT 1 FROM workspace_members WHERE workspace_id=$1 AND personal_scope_id=$2 AND ($3::uuid='00000000-0000-0000-0000-000000000000' OR user_id=$3)) FROM workspaces WHERE id=$1`, in.WorkspaceID, in.ScopeID, in.PersonalOwnerID).Scan(&owned); err != nil {
		return Workspace{}, false, err
	}
	if !owned && !(in.PersonalOwnerID == uuid.Nil && in.ScopeID == binding.HomeScopeID) {
		return Workspace{}, false, Fault{"NOT_FOUND"}
	}
	applied := false
	if in.Revoke {
		exists, err := s.Store.hasRelationship(ctx, "scope", in.ScopeID, in.ScopeRole, string(in.TargetKind), in.TargetID)
		if err != nil {
			return Workspace{}, false, err
		}
		applied = !exists && found
	} else {
		action := authz.ScopeReadContent
		if in.ScopeRole == "editor" {
			action = authz.ScopeWrite
		}
		applied, err = authz.Check(ctx, s.Store.Graph, identity.Actor{Kind: in.TargetKind, ID: in.TargetID}, action, authz.Resource{Type: "scope", ID: in.ScopeID.String()})
		if err != nil {
			return Workspace{}, false, err
		}
	}
	if !applied {
		return Workspace{}, false, nil
	}
	if err = s.Store.reserveMutation(ctx, in); err != nil {
		return Workspace{}, false, err
	}
	if err = s.Store.CompleteMutation(ctx, in.ActorID, MutationReceipt{Key: in.Key, Hash: Fingerprint(in)}); err != nil {
		return Workspace{}, false, err
	}
	value, err := s.Store.resourceRecord(ctx, in.WorkspaceID)
	return value, true, err
}

func (s *Store) reserveMutation(ctx context.Context, in Mutation) error {
	_, err := s.DB.Exec(ctx, `DELETE FROM idempotency_keys WHERE actor_id=$1 AND request_key=$2 AND expires_at<=now()`, in.ActorID, in.Key)
	if err != nil {
		return err
	}
	_, err = s.DB.Exec(ctx, `INSERT INTO idempotency_keys(actor_id,request_key,request_hash,workspace_id) VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING`, in.ActorID, in.Key, Fingerprint(in), in.WorkspaceID)
	if err != nil {
		return err
	}
	var hash string
	var ws uuid.UUID
	if err = s.DB.QueryRow(ctx, `SELECT request_hash,workspace_id FROM idempotency_keys WHERE actor_id=$1 AND request_key=$2`, in.ActorID, in.Key).Scan(&hash, &ws); err != nil {
		return err
	}
	if hash != Fingerprint(in) || ws != in.WorkspaceID {
		return Fault{"IDEMPOTENCY_CONFLICT"}
	}
	return nil
}

func (s *Service) ChangeTypedScopeAccess(ctx context.Context, in Mutation) (Workspace, error) {
	if err := validateScopeMutation(in); err != nil {
		return Workspace{}, err
	}
	if in.Key == uuid.Nil {
		in.Key = uuid.Must(uuid.NewV7())
	}
	ctx, cancel := context.WithTimeout(ctx, 60*time.Second)
	defer cancel()
	if value, done, err := s.scopeReplay(ctx, in); err != nil || done {
		return value, err
	}
	if _, err := s.scopeAdmission(ctx, in); err != nil {
		return Workspace{}, err
	}
	if err := s.Store.reserveMutation(ctx, in); err != nil {
		return Workspace{}, err
	}
	return s.Mutate(ctx, in)
}

func (s *Service) UpdateScopeAccess(ctx context.Context, in Mutation) (Workspace, error) {
	ctx, cancel := context.WithTimeout(ctx, 25*time.Second)
	defer cancel()

	if in.TargetKind == identity.Leta {
		if err := validateScopeMutation(in); err != nil {
			return Workspace{}, err
		}
		if value, done, err := s.scopeReplay(ctx, in); err != nil || done {
			return value, err
		}
		if _, err := s.scopeAdmission(ctx, in); err != nil {
			return Workspace{}, err
		}
		if err := s.Store.reserveMutation(ctx, in); err != nil {
			return Workspace{}, err
		}
	} else {
		var state string
		if err := s.Store.DB.QueryRow(ctx, `SELECT status FROM workspaces WHERE id=$1`, in.WorkspaceID).Scan(&state); err != nil {
			return Workspace{}, err
		}
		if state != "active" {
			return Workspace{}, Fault{"WORKSPACE_DELETING"}
		}
	}
	op := v1.RelationshipUpdate_OPERATION_TOUCH
	if in.Revoke {
		op = v1.RelationshipUpdate_OPERATION_DELETE
	}
	if _, err := s.Store.Graph.WriteRelationships(ctx, &v1.WriteRelationshipsRequest{Updates: []*v1.RelationshipUpdate{graphUpdate(op, "scope", in.ScopeID.String(), in.ScopeRole, string(in.TargetKind), in.TargetID.String())}}); err != nil {
		return Workspace{}, err
	}
	if in.Key != uuid.Nil {
		if err := s.Store.CompleteMutation(ctx, in.ActorID, MutationReceipt{Key: in.Key, Hash: Fingerprint(in)}); err != nil {
			return Workspace{}, err
		}
	}
	return Workspace{ID: in.WorkspaceID}, nil
}
