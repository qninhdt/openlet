package workspace

import (
	"context"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"time"
)

// applyMembership commits canonical membership and the existing retry receipt together.
func (s *Store) applyMembership(ctx context.Context, in Mutation) error {
	receipt := MutationReceipt{Key: in.Key, Hash: Fingerprint(in)}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	var status string
	if err = tx.QueryRow(ctx, `SELECT status FROM workspaces WHERE id=$1 FOR UPDATE`, in.WorkspaceID).Scan(&status); err != nil {
		return err
	}
	applied, err := mutationApplied(ctx, tx, in.ActorID, in.WorkspaceID, receipt)
	if err != nil || applied {
		return err
	}
	if status != "active" {
		return Fault{"WORKSPACE_DELETING"}
	}
	var role, memberStatus string
	var personal uuid.UUID
	err = tx.QueryRow(ctx, `SELECT role,status,personal_scope_id FROM workspace_members WHERE workspace_id=$1 AND user_id=$2`, in.WorkspaceID, in.TargetID).Scan(&role, &memberStatus, &personal)
	exists := err == nil
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return err
	}
	if role == "owner" {
		return Fault{"FORBIDDEN"}
	}
	if in.Kind == "add" || in.Kind == "join" {
		if in.Role != "admin" && in.Role != "member" {
			return Fault{"VALIDATION"}
		}
		if in.Kind == "join" {
			var invitationStatus, invitationRole string
			var expires time.Time
			var accepted *uuid.UUID
			if err = tx.QueryRow(ctx, `SELECT status,role,expires_at,accepted_user_id FROM workspace_invitations WHERE workspace_id=$1 AND token_hash=$2 FOR UPDATE`, in.WorkspaceID, in.InvitationHash[:]).Scan(&invitationStatus, &invitationRole, &expires, &accepted); err != nil {
				return err
			}
			if invitationStatus == "accepted" {
				if accepted == nil || *accepted != in.ActorID || !exists || memberStatus != "active" {
					return Fault{"INVITATION_ALREADY_USED"}
				}
			} else if invitationStatus != "pending" || !time.Now().Before(expires) || invitationRole != in.Role {
				return Fault{"INVITATION_INVALID"}
			}
		}
		if exists && personal != in.PersonalScopeID {
			return Fault{"SCOPE_CONFLICT"}
		}
		if !exists || memberStatus != "active" {
			var count int
			if err = tx.QueryRow(ctx, `SELECT count(*) FROM workspace_members WHERE workspace_id=$1 AND status='active'`, in.WorkspaceID).Scan(&count); err != nil {
				return err
			}
			if count >= s.MaxMembers {
				return Fault{"RESOURCE_LIMIT"}
			}
			if _, err = tx.Exec(ctx, `INSERT INTO workspace_members(workspace_id,user_id,role,personal_scope_id) VALUES($1,$2,$3,$4) ON CONFLICT(workspace_id,user_id) DO UPDATE SET role=excluded.role,status='active'`, in.WorkspaceID, in.TargetID, in.Role, in.PersonalScopeID); err != nil {
				return err
			}
		}
		if in.Kind == "join" {
			if _, err = tx.Exec(ctx, `UPDATE workspace_invitations SET status='accepted',accepted_user_id=$2 WHERE token_hash=$1`, in.InvitationHash[:], in.ActorID); err != nil {
				return err
			}
		}
	} else {
		if !exists {
			return Fault{"NOT_FOUND"}
		}
		if in.Remove {
			_, err = tx.Exec(ctx, `UPDATE workspace_members SET status='inactive' WHERE workspace_id=$1 AND user_id=$2`, in.WorkspaceID, in.TargetID)
		} else {
			if in.Role != "admin" && in.Role != "member" {
				return Fault{"VALIDATION"}
			}
			_, err = tx.Exec(ctx, `UPDATE workspace_members SET role=$3 WHERE workspace_id=$1 AND user_id=$2 AND status='active'`, in.WorkspaceID, in.TargetID, in.Role)
		}
		if err != nil {
			return err
		}
	}
	if err = saveMutationReceipt(ctx, tx, receipt, in.ActorID, in.WorkspaceID); err != nil {
		return err
	}
	return tx.Commit(ctx)
}
func (s *Service) ApplyMembership(ctx context.Context, in Mutation) (Workspace, error) {
	if err := s.Store.applyMembership(ctx, in); err != nil {
		return Workspace{}, err
	}
	defaults := in.Kind == "add" || in.Kind == "join" || in.Remove
	if err := s.Store.WriteMemberRelationships(ctx, s.Store.Graph, in.WorkspaceID, defaults, in.TargetID); err != nil {
		return Workspace{}, err
	}
	if err := s.Store.CompleteMutation(ctx, in.ActorID, MutationReceipt{Key: in.Key, Hash: Fingerprint(in)}); err != nil {
		return Workspace{}, err
	}
	if in.Remove && in.ActorID == in.TargetID {
		return Workspace{ID: in.WorkspaceID}, nil
	}
	return s.Store.Get(ctx, in.WorkspaceID, in.ActorID)
}
